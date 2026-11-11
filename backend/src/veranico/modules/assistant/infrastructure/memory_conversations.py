"""`ConversationStore` in memory, for unit tests. Same behaviour as the Firestore store."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from veranico.modules.assistant.application.ports import ConversationState, TurnRecord
from veranico.modules.assistant.domain.conversation import Entry
from veranico.shared.kernel.clock import Clock
from veranico.shared.kernel.errors import ConflictError, NotFoundError
from veranico.shared.kernel.ids import ConversationId, Locale, WorkspaceId

DEFAULT_LEASE = timedelta(minutes=3)


@dataclass
class _Conversation:
    workspace_id: WorkspaceId
    locale: Locale
    expires_at: datetime
    entries: dict[int, Entry] = field(default_factory=dict)
    turns: dict[int, TurnRecord] = field(default_factory=dict)
    total_tokens: int = 0
    claim: tuple[str, datetime] | None = None  # message id, end of the lease


class MemoryConversationStore:
    def __init__(self, clock: Clock, *, ttl: timedelta, lease: timedelta = DEFAULT_LEASE) -> None:
        self._clock = clock
        self._ttl = ttl
        self._lease = lease
        self._conversations: dict[ConversationId, _Conversation] = {}

    async def create(self, workspace_id: WorkspaceId, locale: Locale) -> ConversationId:
        conversation_id = ConversationId(uuid.uuid4().hex)
        self._conversations[conversation_id] = _Conversation(
            workspace_id=workspace_id, locale=locale, expires_at=self._clock.now() + self._ttl
        )
        return conversation_id

    async def claim_turn(
        self, workspace_id: WorkspaceId, conversation_id: ConversationId, message_id: str
    ) -> int:
        conversation = self._owned(workspace_id, conversation_id)
        now = self._clock.now()
        if conversation.claim is not None and conversation.claim[1] > now:
            raise ConflictError("a turn is already running on this conversation")
        turn = max(conversation.turns, default=0) + 1
        conversation.claim = (message_id, now + self._lease)
        conversation.turns[turn] = TurnRecord(turn=turn, message_id=message_id, started_at=now)
        return turn

    async def append(self, conversation_id: ConversationId, entries: Sequence[Entry]) -> None:
        conversation = self._conversations.get(conversation_id)
        if conversation is None:
            raise NotFoundError
        seqs = [entry.seq for entry in entries]
        if len(set(seqs)) != len(seqs) or any(seq in conversation.entries for seq in seqs):
            raise ConflictError("an entry with this seq is already stored")
        conversation.entries.update({entry.seq: entry for entry in entries})
        if conversation.claim is not None:
            conversation.claim = (conversation.claim[0], self._clock.now() + self._lease)

    async def finish_turn(
        self,
        conversation_id: ConversationId,
        message_id: str,
        flagged: Sequence[str],
        tokens: int,
        prompt_version: str,
    ) -> None:
        conversation = self._conversations.get(conversation_id)
        if conversation is None:
            raise NotFoundError
        for turn, record in conversation.turns.items():
            if record.message_id == message_id:
                conversation.turns[turn] = replace(
                    record,
                    finished_at=self._clock.now(),
                    flagged=tuple(flagged),
                    prompt_version=prompt_version,
                )
        conversation.total_tokens += tokens
        if conversation.claim is not None and conversation.claim[0] == message_id:
            conversation.claim = None

    async def load(
        self, workspace_id: WorkspaceId, conversation_id: ConversationId
    ) -> ConversationState:
        conversation = self._owned(workspace_id, conversation_id)
        return ConversationState(
            conversation_id=conversation_id,
            workspace_id=conversation.workspace_id,
            locale=conversation.locale,
            entries=tuple(conversation.entries[seq] for seq in sorted(conversation.entries)),
            turns=tuple(conversation.turns[turn] for turn in sorted(conversation.turns)),
            total_tokens=conversation.total_tokens,
        )

    def _owned(self, workspace_id: WorkspaceId, conversation_id: ConversationId) -> _Conversation:
        conversation = self._conversations.get(conversation_id)
        if (
            conversation is None
            or conversation.workspace_id != workspace_id
            or conversation.expires_at <= self._clock.now()
        ):
            raise NotFoundError
        return conversation
