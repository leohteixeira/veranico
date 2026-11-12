"""The Firestore conversation store against the emulator.

    docker compose -p veranico up -d --wait firestore storage
    uv run pytest tests/integration/assistant -q

The emulator is shared: every test creates conversations under random ids and clears nothing.
"""

import os
import socket
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from google.cloud.firestore import AsyncClient

from tests.fakes.settings import settings_for_tests
from tests.unit.assistant.store_contract import (
    LEASE,
    NOW,
    TTL,
    WS,
    ConversationStoreContract,
    turn_entries,
)
from veranico.modules.assistant.application.ports import ConversationStore
from veranico.modules.assistant.infrastructure.firestore_conversations import (
    COLLECTION,
    MESSAGES,
    FirestoreConversationStore,
)
from veranico.shared.infrastructure.firestore import close_firestore, firestore_client
from veranico.shared.kernel.clock import FixedClock

pytestmark = pytest.mark.integration

FIRESTORE_HOST = os.environ.get("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8580")


async def _client() -> AsyncClient:
    host, _, port = FIRESTORE_HOST.partition(":")
    try:
        socket.create_connection((host, int(port)), timeout=2).close()
    except OSError:
        pytest.fail(
            f"the Firestore emulator is not listening on {FIRESTORE_HOST}: "
            "run `docker compose -p veranico up -d --wait firestore storage`"
        )
    return firestore_client(settings_for_tests(firestore_emulator_host=FIRESTORE_HOST))


@pytest.fixture
async def clients() -> AsyncIterator[tuple[AsyncClient, AsyncClient]]:
    """Two clients, as two instances of the service would hold."""
    first, second = await _client(), await _client()
    yield first, second
    await close_firestore(first)
    await close_firestore(second)


class TestFirestoreConversationStore(ConversationStoreContract):
    @pytest.fixture
    def clock(self) -> FixedClock:
        return FixedClock(NOW)

    @pytest.fixture
    def stores(
        self, clients: tuple[AsyncClient, AsyncClient], clock: FixedClock
    ) -> tuple[ConversationStore, ConversationStore]:
        first, second = clients
        return (
            FirestoreConversationStore(first, clock, ttl=TTL, lease=LEASE),
            FirestoreConversationStore(second, clock, ttl=TTL, lease=LEASE),
        )

    @pytest.mark.req("R-14-1")
    @pytest.mark.req("R-9.2-1")
    async def test_documents_carry_expires_at(
        self,
        stores: tuple[ConversationStore, ConversationStore],
        clients: tuple[AsyncClient, AsyncClient],
        clock: FixedClock,
    ) -> None:
        store, _ = stores
        conversation_id = await store.create(WS, "en")
        await store.claim_turn(WS, conversation_id, "m-1")
        clock.advance(timedelta(hours=1))
        await store.append(conversation_id, turn_entries(1, 1))

        reference = clients[1].collection(COLLECTION).document(conversation_id)
        conversation = (await reference.get()).to_dict()
        messages = [m async for m in reference.collection(MESSAGES).order_by("seq").stream()]

        # TTL does not delete subcollections, so each message has its own timestamp.
        assert conversation is not None
        assert conversation["workspace_id"] == WS
        assert conversation["expires_at"] == NOW + TTL
        assert [message.id for message in messages] == [f"{seq:06d}" for seq in range(1, 6)]
        for message in messages:
            data = message.to_dict()
            assert data is not None
            assert data["expires_at"] == NOW + timedelta(hours=1) + TTL

    @pytest.mark.req("R-9.2-2")
    async def test_tool_payloads_are_stored_as_json_text(
        self,
        stores: tuple[ConversationStore, ConversationStore],
        clients: tuple[AsyncClient, AsyncClient],
    ) -> None:
        store, _ = stores
        conversation_id = await store.create(WS, "en")
        await store.claim_turn(WS, conversation_id, "m-1")
        await store.append(conversation_id, turn_entries(1, 1))

        reference = clients[0].collection(COLLECTION).document(conversation_id)
        result = (await reference.collection(MESSAGES).document("000003").get()).to_dict()

        assert result is not None
        assert result["kind"] == "tool_result"
        assert isinstance(result["result_json"], str)
        assert '"quote_id":"Q-7K3M9P"' in result["result_json"]
