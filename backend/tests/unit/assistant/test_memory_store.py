"""The in-memory conversation store behaves as the contract says (it backs the unit tests)."""

import pytest

from tests.unit.assistant.store_contract import LEASE, NOW, TTL, ConversationStoreContract
from veranico.modules.assistant.application.ports import ConversationStore
from veranico.modules.assistant.infrastructure.memory_conversations import MemoryConversationStore
from veranico.shared.kernel.clock import FixedClock


class TestMemoryConversationStore(ConversationStoreContract):
    @pytest.fixture
    def clock(self) -> FixedClock:
        return FixedClock(NOW)

    @pytest.fixture
    def stores(self, clock: FixedClock) -> tuple[ConversationStore, ConversationStore]:
        store = MemoryConversationStore(clock, ttl=TTL, lease=LEASE)
        return store, store
