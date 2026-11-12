"""`ConversationStore` on Firestore: `assistant_conversations/{conversation_id}` and its
subcollection `messages`. The module touches no other collection.

Conversation document:

    workspace_id, locale, created_at, expires_at (the TTL field), total_tokens,
    last_turn, last_seq,
    claim: {message_id, expires_at} or null         the running turn and the end of its lease
    turns: {"t<N>": {turn, message_id, started_at, finished_at, flagged, prompt_version}}

Message document `messages/{seq, six digits}`: one entry of the conversation model, with
`kind` (`user`, `assistant`, `tool_result`), `seq`, `turn` and its own `expires_at`. Tool
arguments, full tool results and summaries are stored as JSON text: they come back byte for
byte, whatever keys and number types they hold.

Verified in the Firestore documentation on 2026-11-11 (client `google-cloud-firestore` 2.34.1):

* A TTL policy names one timestamp field per collection group, deletes "typically within 24
  hours" after expiry, and "does not delete subcollections under that document". So every
  message carries its own `expires_at` (the `messages` collection group needs its own TTL
  policy), and `load` treats an expired conversation as not found, because expired documents
  "continue to appear in queries and lookup requests" until they are deleted.
* A document is at most 1 MiB and a request at most 10 MiB. One entry per document keeps a
  conversation of any length inside both; a single tool result is a few tens of kilobytes.
* Unquoted field path segments may not start with a digit, hence the `t<N>` keys of `turns`.
* The emulator does not mimic production transaction behaviour: contended transactions wait
  for a lock and time out. No transaction is used here. The claim is a write with an
  update-time precondition, an append is one batch of creates (it fails as a whole when an
  entry exists), and the token total uses the server-side increment.
"""

import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Literal, cast

from google.api_core.exceptions import Conflict, FailedPrecondition, NotFound
from google.cloud.firestore import AsyncClient, Increment

from veranico.modules.assistant.application.ports import ConversationState, TurnRecord
from veranico.modules.assistant.domain.conversation import (
    AssistantStep,
    Entry,
    ToolCall,
    ToolResultEntry,
    UserEntry,
)
from veranico.shared.kernel.clock import Clock
from veranico.shared.kernel.errors import ConflictError, NotFoundError
from veranico.shared.kernel.ids import ConversationId, Locale, WorkspaceId

COLLECTION = "assistant_conversations"
MESSAGES = "messages"
DEFAULT_LEASE = timedelta(minutes=3)


class FirestoreConversationStore:
    def __init__(
        self, client: AsyncClient, clock: Clock, *, ttl: timedelta, lease: timedelta = DEFAULT_LEASE
    ) -> None:
        self._client = client
        self._collection = client.collection(COLLECTION)
        self._clock = clock
        self._ttl = ttl
        self._lease = lease

    async def create(self, workspace_id: WorkspaceId, locale: Locale) -> ConversationId:
        conversation_id = ConversationId(uuid.uuid4().hex)
        now = self._clock.now()
        await self._collection.document(conversation_id).create(
            {
                "workspace_id": workspace_id,
                "locale": locale,
                "created_at": now,
                "expires_at": now + self._ttl,
                "total_tokens": 0,
                "last_turn": 0,
                "last_seq": 0,
                "claim": None,
                "turns": {},
            }
        )
        return conversation_id

    async def claim_turn(
        self, workspace_id: WorkspaceId, conversation_id: ConversationId, message_id: str
    ) -> int:
        reference = self._collection.document(conversation_id)
        snapshot = await reference.get()
        data = self._owned(snapshot.to_dict(), workspace_id)
        now = self._clock.now()
        claim = data.get("claim")
        if claim is not None and claim["expires_at"] > now:
            raise ConflictError("a turn is already running on this conversation")
        turn = int(data["last_turn"]) + 1
        try:
            # Only if the document is still the version that was read: of two turns that both
            # saw no claim, one write lands and the other fails here.
            await reference.update(
                {
                    "claim": {"message_id": message_id, "expires_at": now + self._lease},
                    "last_turn": turn,
                    f"turns.t{turn}": {
                        "turn": turn,
                        "message_id": message_id,
                        "started_at": now,
                        "finished_at": None,
                        "flagged": [],
                        "prompt_version": None,
                    },
                },
                option=self._client.write_option(last_update_time=snapshot.update_time),
            )
        except (FailedPrecondition, NotFound) as error:
            raise ConflictError("a turn is already running on this conversation") from error
        return turn

    async def append(self, conversation_id: ConversationId, entries: Sequence[Entry]) -> None:
        if not entries:
            return
        reference = self._collection.document(conversation_id)
        expires_at = self._clock.now() + self._ttl
        batch = self._client.batch()
        for entry in entries:
            document = reference.collection(MESSAGES).document(f"{entry.seq:06d}")
            batch.create(document, {**_entry_to_document(entry), "expires_at": expires_at})
        batch.update(
            reference,
            {
                "last_seq": max(entry.seq for entry in entries),
                "claim.expires_at": self._clock.now() + self._lease,
            },
        )
        try:
            await batch.commit()
        except Conflict as error:  # a message with one of these seq values exists
            raise ConflictError("an entry with this seq is already stored") from error
        except NotFound as error:  # the conversation document is gone
            raise NotFoundError from error

    async def finish_turn(
        self,
        conversation_id: ConversationId,
        message_id: str,
        flagged: Sequence[str],
        tokens: int,
        prompt_version: str,
    ) -> None:
        reference = self._collection.document(conversation_id)
        data = (await reference.get()).to_dict()
        if data is None:
            raise NotFoundError
        changes: dict[str, Any] = {"total_tokens": Increment(tokens)}
        for key, turn in data.get("turns", {}).items():
            if turn["message_id"] == message_id:
                changes[f"turns.{key}.finished_at"] = self._clock.now()
                changes[f"turns.{key}.flagged"] = list(flagged)
                changes[f"turns.{key}.prompt_version"] = prompt_version
        claim = data.get("claim")
        if claim is not None and claim.get("message_id") == message_id:
            changes["claim"] = None
        await reference.update(changes)

    async def load(
        self, workspace_id: WorkspaceId, conversation_id: ConversationId
    ) -> ConversationState:
        reference = self._collection.document(conversation_id)
        data = self._owned((await reference.get()).to_dict(), workspace_id)
        messages = reference.collection(MESSAGES).order_by("seq").stream()
        entries = [_entry_from_document(message.to_dict() or {}) async for message in messages]
        turns = sorted(
            (_turn_from_document(turn) for turn in data.get("turns", {}).values()),
            key=lambda record: record.turn,
        )
        return ConversationState(
            conversation_id=conversation_id,
            workspace_id=WorkspaceId(data["workspace_id"]),
            locale=cast(Locale, data["locale"]),
            entries=tuple(entries),
            turns=tuple(turns),
            total_tokens=int(data["total_tokens"]),
        )

    def _owned(self, data: dict[str, Any] | None, workspace_id: WorkspaceId) -> dict[str, Any]:
        """The conversation document, or `not_found` when it is absent, another's or expired."""
        if (
            data is None
            or data["workspace_id"] != workspace_id
            or data["expires_at"] <= self._clock.now()
        ):
            raise NotFoundError
        return data


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _entry_to_document(entry: Entry) -> dict[str, Any]:
    common: dict[str, Any] = {"seq": entry.seq, "turn": entry.turn}
    if isinstance(entry, UserEntry):
        return {
            **common,
            "kind": "user",
            "text": entry.text,
            "locale": entry.locale,
            "map_point": list(entry.map_point) if entry.map_point is not None else None,
        }
    if isinstance(entry, AssistantStep):
        return {
            **common,
            "kind": "assistant",
            "text": entry.text,
            "tool_calls": [
                {
                    "call_id": call.call_id,
                    "tool": call.tool,
                    "arguments_json": _json(call.arguments),
                }
                for call in entry.tool_calls
            ],
        }
    return {
        **common,
        "kind": "tool_result",
        "call_id": entry.call_id,
        "tool": entry.tool,
        "status": entry.status,
        "result_json": _json(entry.result),
        "summary_json": _json(entry.summary) if entry.summary is not None else None,
        "duration_ms": entry.duration_ms,
    }


def _entry_from_document(data: Mapping[str, Any]) -> Entry:
    seq, turn, kind = int(data["seq"]), int(data["turn"]), data["kind"]
    if kind == "user":
        point = data.get("map_point")
        return UserEntry(
            seq=seq,
            turn=turn,
            text=data["text"],
            locale=data.get("locale"),
            map_point=(float(point[0]), float(point[1])) if point is not None else None,
        )
    if kind == "assistant":
        return AssistantStep(
            seq=seq,
            turn=turn,
            text=data["text"],
            tool_calls=tuple(
                ToolCall(
                    call_id=call["call_id"],
                    tool=call["tool"],
                    arguments=json.loads(call["arguments_json"]),
                )
                for call in data.get("tool_calls", [])
            ),
        )
    if kind != "tool_result":
        raise ValueError(f"unknown message kind: {kind}")
    summary = data.get("summary_json")
    return ToolResultEntry(
        seq=seq,
        turn=turn,
        call_id=data["call_id"],
        tool=data["tool"],
        status=cast(Literal["ok", "error"], data["status"]),
        result=json.loads(data["result_json"]),
        summary=json.loads(summary) if summary is not None else None,
        duration_ms=int(data.get("duration_ms", 0)),
    )


def _turn_from_document(data: Mapping[str, Any]) -> TurnRecord:
    started_at: datetime = data["started_at"]
    return TurnRecord(
        turn=int(data["turn"]),
        message_id=data["message_id"],
        started_at=started_at,
        finished_at=data.get("finished_at"),
        flagged=tuple(data.get("flagged", [])),
        prompt_version=data.get("prompt_version"),
    )
