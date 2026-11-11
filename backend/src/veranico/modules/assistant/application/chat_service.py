"""Opening a turn and reading a conversation: what the routes and the facade call.

`open_turn` does everything that can refuse a message, before any event exists, so the route
can answer a refusal as a problem document: the length of the message, the conversation, the
visitor's allowance and the spend ceilings, and the claim of the conversation. The order
matters: a message that is too long or names an unknown conversation consumes no allowance,
and `admit_message` checks the ceilings before it consumes, so a reached ceiling consumes
none either. A new conversation is created only after its message was admitted.
"""

import uuid
from collections.abc import AsyncGenerator
from contextlib import aclosing

from veranico.modules.access.contracts import VisitorRef
from veranico.modules.assistant.application.turn import Turn, TurnDeps
from veranico.modules.assistant.application.views import conversation_view
from veranico.modules.assistant.contracts import AgentEvent, ChatRequest, ConversationView
from veranico.modules.assistant.domain.conversation import UserEntry
from veranico.shared.kernel.errors import (
    AllowanceExhaustedError,
    MessageTooLongError,
    SpendCeilingReachedError,
)
from veranico.shared.kernel.ids import ConversationId
from veranico.shared.kernel.principal import Principal


class ChatService:
    def __init__(self, deps: TurnDeps) -> None:
        self._deps = deps

    async def open_turn(
        self, principal: Principal, visitor: VisitorRef, request: ChatRequest
    ) -> Turn:
        """Admit the message, claim the conversation and store the user message.

        Raises `message_too_long`, `not_found`, `allowance_exhausted`, `spend_ceiling_reached`
        or `conflict` (another turn is running on the conversation).
        """
        deps = self._deps
        workspace_id = principal.workspace_id
        if len(request.message) > deps.settings.access.max_message_chars:
            raise MessageTooLongError
        conversation_id = request.conversation_id
        if conversation_id is not None:
            await deps.store.load(workspace_id, conversation_id)

        admission = await deps.access.admit_message(visitor, conversation_id is None)
        if not admission.allowed:
            if admission.reason == "visitor_allowance":
                raise AllowanceExhaustedError
            raise SpendCeilingReachedError

        if conversation_id is None:
            conversation_id = await deps.store.create(workspace_id, request.locale)
        message_id = uuid.uuid4().hex
        turn = await deps.store.claim_turn(workspace_id, conversation_id, message_id)
        try:
            # Read under the claim: no other turn can add entries now.
            state = await deps.store.load(workspace_id, conversation_id)
            point = request.map_point
            user = UserEntry(
                seq=state.entries[-1].seq + 1 if state.entries else 1,
                turn=turn,
                text=request.message,
                locale=request.locale,
                map_point=None if point is None else (point.lat, point.lon),
            )
            await deps.store.append(conversation_id, [user])
        except BaseException:
            await deps.store.finish_turn(conversation_id, message_id, (), 0, deps.prompt.version)
            raise
        return Turn(
            deps,
            principal=principal,
            conversation_id=conversation_id,
            message_id=message_id,
            turn=turn,
            locale=request.locale,
            entries=[*state.entries, user],
            conversation_tokens=state.total_tokens,
        )

    async def chat(
        self, principal: Principal, visitor: VisitorRef, request: ChatRequest
    ) -> AsyncGenerator[AgentEvent]:
        """`AssistantFacade.chat`: a refusal is raised when the first event is asked for."""
        turn = await self.open_turn(principal, visitor, request)
        # Closing this stream closes the turn at once, which settles and releases it.
        async with aclosing(turn.events()) as events:
            async for event in events:
                yield event

    async def conversation(
        self, principal: Principal, conversation_id: ConversationId
    ) -> ConversationView:
        state = await self._deps.store.load(principal.workspace_id, conversation_id)
        return conversation_view(state)
