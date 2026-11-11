"""One user turn: the loop of model calls and tool calls, as a stream of events (SPEC 9.1).

`ChatService.open_turn` admitted the message, claimed the conversation and stored the user
message; `Turn.events` does the rest. The rules of the stream:

* `started` is the first event and `done` the last; there is exactly one of each.
* An `error` event is directly followed by `done`.
* Before every model call the loop checks, in this order: the shutdown signal (`error` with
  `shutting_down`, `done` with `error`), the conversation's token budget (`done` with `budget`
  and no `error`) and the spend ceiling (`error` with `spend_ceiling_reached`, `done` with
  `budget`). After every model call, however it ended, its usage is charged.
* Tools run one after another. A tool error is a result the model reads, never an exception.
  When the tool-call limit is reached, or one tool failed twice in a row, the loop makes one
  last model call that cannot use tools, so the model says what is done and what is pending.
* A step (one model call and the results of its tool calls) is stored in one write when it is
  complete. A step cut by a failure, a disconnect or a shutdown is not stored.
* The grounding check runs on the text of the whole turn after the last text was sent. It
  never holds text back.

Spans: `agent.turn` with one `llm.call` per model call and one `tool.<name>` per executed
tool. They carry identifiers, counts and codes, and never message text or tool payloads.
"""

import asyncio
import time
from collections.abc import AsyncGenerator, Coroutine, Mapping, Sequence
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Final, Literal

from opentelemetry import trace

from veranico.modules.access.contracts import AccessFacade, ModelUsage
from veranico.modules.assistant.application.ports import (
    ConversationStore,
    ModelClient,
    ModelStop,
    ModelTextDelta,
    ModelToolCall,
    ModelUnavailable,
    ModelUsageSoFar,
)
from veranico.modules.assistant.application.prompt import SystemPrompt, build_request
from veranico.modules.assistant.application.tools.models import ToolOutcome
from veranico.modules.assistant.application.tools.registry import ToolRegistry
from veranico.modules.assistant.application.views import STEP_SEPARATOR, tool_finished
from veranico.modules.assistant.contracts import (
    AgentEvent,
    Done,
    GroundingFlagged,
    Started,
    StreamError,
    TextDelta,
    ToolError,
    ToolStarted,
)
from veranico.modules.assistant.domain.conversation import (
    AssistantStep,
    Entry,
    ToolCall,
    ToolResultEntry,
    UserEntry,
)
from veranico.modules.assistant.domain.grounding import check_grounding
from veranico.shared.infrastructure import telemetry
from veranico.shared.infrastructure.settings import Settings
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.errors import (
    ModelUnavailableError,
    ShuttingDownError,
    SpendCeilingReachedError,
)
from veranico.shared.kernel.ids import ConversationId, Locale
from veranico.shared.kernel.principal import Principal

StopReason = Literal["end_turn", "tool_limit", "budget", "error"]

# The error code of a tool call the loop did not run: it came after the tool-call limit of the
# turn, or after the failure that ended the tool use of the turn.
TOOL_NOT_EXECUTED: Final = "tool_not_executed"

# Span name of a call to a tool the registry does not have: the name came from the model.
_UNKNOWN_TOOL: Final = "unknown"

# Work that must finish although its turn was cancelled. The loop keeps only weak references
# to tasks, so they are held here until they end.
_settling: set[asyncio.Task[None]] = set()


async def _settled(work: Coroutine[object, object, None]) -> None:
    """Run `work` to its end even when the caller is being cancelled.

    A disconnect cancels the turn at whatever it was awaiting. The charge of a model call and
    the release of the conversation's claim still have to happen, so they run as a task of
    their own, which the cancellation of the turn does not reach.
    """
    task = asyncio.ensure_future(work)
    _settling.add(task)
    task.add_done_callback(_settling.discard)
    await asyncio.shield(task)


@dataclass(frozen=True, slots=True, kw_only=True)
class TurnDeps:
    """What every turn of the process shares."""

    settings: Settings
    access: AccessFacade
    store: ConversationStore
    model: ModelClient
    registry: ToolRegistry
    prompt: SystemPrompt
    shutdown: asyncio.Event


@dataclass(slots=True)
class _ModelCall:
    """What one model call produced, filled while its stream is read."""

    text: list[str] = field(default_factory=list)
    tool_calls: list[ModelToolCall] = field(default_factory=list)
    usage: ModelUsage | None = None
    stop: ModelStop | None = None
    failed: bool = False


@dataclass(frozen=True, slots=True)
class _Ending:
    stop_reason: StopReason
    error_code: str | None = None


class Turn:
    """An admitted, claimed turn whose user message is stored. `events` runs it once."""

    def __init__(
        self,
        deps: TurnDeps,
        *,
        principal: Principal,
        conversation_id: ConversationId,
        message_id: str,
        turn: int,
        locale: Locale,
        entries: Sequence[Entry],
        conversation_tokens: int,
    ) -> None:
        self._deps = deps
        self._principal = principal
        self.conversation_id = conversation_id
        self.message_id = message_id
        self._turn = turn
        self._locale = locale
        self._entries = list(entries)  # the stored history, the user message of this turn last
        self._conversation_tokens = conversation_tokens  # before this turn
        self._tokens = 0  # of this turn
        self._texts: list[str] = []  # text of each model call of this turn, as streamed
        self._completed: list[str] = []  # tools that finished without error, in order
        self._executed = 0
        self._flagged: tuple[str, ...] = ()
        self._finished = False

    async def events(self) -> AsyncGenerator[AgentEvent]:
        deps = self._deps
        span = telemetry.tracer().start_span(
            telemetry.SPAN_AGENT_TURN,
            attributes={
                telemetry.ATTR_AGENT_CONVERSATION_ID: self.conversation_id,
                telemetry.ATTR_AGENT_PROMPT_VERSION: deps.prompt.version,
            },
        )
        # The spans of the turn are parented explicitly. Making `agent.turn` the current span
        # across the `yield`s below would leave it current in the consumer between events.
        parent = trace.set_span_in_context(span)
        tools = tuple(deps.registry.definitions())
        known_tools = {tool.name for tool in tools}
        limit = deps.settings.assistant.tool_call_limit
        budget = deps.settings.access.conversation_token_budget
        wrap_up: Literal["tool_limit", "failures"] | None = None
        last_failed: str | None = None
        ending: _Ending
        try:
            yield Started(conversation_id=self.conversation_id, message_id=self.message_id)
            while True:
                if deps.shutdown.is_set():
                    ending = _Ending("error", ShuttingDownError.code)
                    break
                if self._conversation_tokens + self._tokens >= budget:
                    ending = _Ending("budget")
                    break
                if not (await deps.access.may_spend()).allowed:
                    ending = _Ending("budget", SpendCeilingReachedError.code)
                    break

                request = build_request(
                    deps.prompt,
                    self._entries,
                    tools,
                    deps.settings,
                    tool_use="none" if wrap_up is not None else "auto",
                )
                call = _ModelCall()
                interrupted = False
                llm_span = telemetry.tracer().start_span(
                    telemetry.SPAN_LLM_CALL,
                    context=parent,
                    attributes={telemetry.ATTR_LLM_MODEL: request.model},
                )
                started_ns = time.perf_counter_ns()
                try:
                    async with aclosing(deps.model.stream(request)) as stream:
                        async for item in stream:
                            if isinstance(item, ModelTextDelta):
                                if item.text:
                                    if not call.text and self._texts:
                                        yield TextDelta(text=STEP_SEPARATOR)
                                    call.text.append(item.text)
                                    yield TextDelta(text=item.text)
                            elif isinstance(item, ModelToolCall):
                                call.tool_calls.append(item)
                            elif isinstance(item, ModelUsageSoFar):
                                call.usage = item.usage
                            else:
                                call.usage, call.stop = item.usage, item.stop
                            if call.stop is None and deps.shutdown.is_set():
                                interrupted = True
                                break
                except ModelUnavailable as error:
                    call.failed = True
                    call.usage = error.usage or call.usage
                finally:
                    text = "".join(call.text)
                    if text:
                        self._texts.append(text)
                    await _settled(self._charge(llm_span, call, started_ns))

                if interrupted:
                    ending = _Ending("error", ShuttingDownError.code)
                    break
                if call.failed:
                    ending = _Ending("error", ModelUnavailableError.code)
                    break

                requested = [] if wrap_up is not None else call.tool_calls
                step = AssistantStep(
                    seq=self._next_seq(),
                    turn=self._turn,
                    text=text,
                    tool_calls=tuple(
                        ToolCall(call_id=item.call_id, tool=item.name, arguments=item.arguments)
                        for item in requested
                    ),
                )
                if not requested:
                    if text:
                        await self._store([step])
                    ending = _Ending("tool_limit" if wrap_up == "tool_limit" else "end_turn")
                    break

                results: list[ToolResultEntry] = []
                for item in requested:
                    yield ToolStarted(
                        call_id=item.call_id, tool=item.name, arguments=dict(item.arguments)
                    )
                    duration_ms = 0
                    if wrap_up == "failures":
                        outcome = _not_executed(f"{last_failed} failed twice in a row")
                    elif self._executed >= limit:
                        outcome = _not_executed(f"the limit of {limit} tool calls was reached")
                    else:
                        name = item.name if item.name in known_tools else _UNKNOWN_TOOL
                        # Current while the tool runs, so spans its facade opens nest under it.
                        with telemetry.tracer().start_as_current_span(
                            telemetry.tool_span_name(name), context=parent
                        ) as tool_span:
                            tool_started_ns = time.perf_counter_ns()
                            outcome = await deps.registry.execute(
                                self._principal, item.name, item.arguments
                            )
                            duration_ms = _elapsed_ms(tool_started_ns)
                            _describe_tool(tool_span, outcome, duration_ms)
                        self._executed += 1
                        if outcome.ok:
                            last_failed = None
                            self._completed.append(item.name)
                        elif last_failed == item.name:
                            wrap_up = "failures"
                        else:
                            last_failed = item.name
                    result = self._result(step.seq + 1 + len(results), item, outcome, duration_ms)
                    results.append(result)
                    yield tool_finished(result)
                    if outcome.approval is not None:
                        yield outcome.approval
                await self._store([step, *results])
                if wrap_up is None and self._executed >= limit:
                    wrap_up = "tool_limit"

            self._flagged = self._ungrounded()
            if self._flagged:
                yield GroundingFlagged(message_id=self.message_id, values=list(self._flagged))
            if ending.error_code is not None:
                yield StreamError(code=ending.error_code, completed=list(self._completed))
            span.set_attribute(telemetry.ATTR_AGENT_STOP_REASON, ending.stop_reason)
            # Before `done`: the client may send its next message as soon as it reads `done`,
            # and the claim must be free by then.
            await self._finish()
            yield Done(
                conversation_id=self.conversation_id,
                message_id=self.message_id,
                stop_reason=ending.stop_reason,
                prompt_version=deps.prompt.version,
            )
        except BaseException as error:
            # A disconnect closes or cancels the generator; anything else is a defect.
            span.set_attribute(telemetry.ATTR_ERROR_TYPE, type(error).__name__)
            raise
        finally:
            span.set_attribute(telemetry.ATTR_AGENT_TOOL_CALLS, self._executed)
            # A count: the figures themselves are message text and stay out of the span.
            span.set_attribute(telemetry.ATTR_AGENT_UNGROUNDED_FIGURES, len(self._flagged))
            try:
                if not self._finished:
                    await _settled(self._finish())
            finally:
                span.end()

    async def _charge(self, span: trace.Span, call: _ModelCall, started_ns: int) -> None:
        """Close the `llm.call` span and charge what the call used (SPEC 10.3)."""
        access = self._deps.access
        try:
            span.set_attribute(telemetry.ATTR_LLM_LATENCY_MS, _elapsed_ms(started_ns))
            if call.stop is not None:
                span.set_attribute(telemetry.ATTR_LLM_STOP_REASON, call.stop)
            elif call.failed:
                span.set_attribute(telemetry.ATTR_LLM_STOP_REASON, "error")
            usage = call.usage
            if usage is None:
                return
            span.set_attribute(telemetry.ATTR_LLM_INPUT_TOKENS, usage.input_tokens)
            span.set_attribute(telemetry.ATTR_LLM_OUTPUT_TOKENS, usage.output_tokens)
            span.set_attribute(telemetry.ATTR_LLM_COST_USD_MICROS, access.cost_of(usage))
            self._tokens += (
                usage.input_tokens
                + usage.output_tokens
                + usage.cache_read_tokens
                + usage.cache_write_tokens
            )
            await access.record_spend(usage)
        finally:
            span.end()

    async def _finish(self) -> None:
        self._finished = True
        await self._deps.store.finish_turn(
            self.conversation_id,
            self.message_id,
            self._flagged,
            self._tokens,
            self._deps.prompt.version,
        )

    async def _store(self, entries: Sequence[Entry]) -> None:
        await self._deps.store.append(self.conversation_id, entries)
        self._entries.extend(entries)

    def _next_seq(self) -> int:
        return self._entries[-1].seq + 1

    def _result(
        self, seq: int, call: ModelToolCall, outcome: ToolOutcome, duration_ms: int
    ) -> ToolResultEntry:
        result: Mapping[str, object]
        if outcome.error is not None:
            result = outcome.error.model_dump(mode="json")
        else:
            result = outcome.result or {}
        return ToolResultEntry(
            seq=seq,
            turn=self._turn,
            call_id=call.call_id,
            tool=call.name,
            status="ok" if outcome.ok else "error",
            result=result,
            summary=outcome.summary.model_dump(mode="json"),
            duration_ms=duration_ms,
        )

    def _ungrounded(self) -> tuple[str, ...]:
        """Figures of this turn's answer found in no tool result and no user message."""
        answer = STEP_SEPARATOR.join(self._texts)
        if not answer:
            return ()
        report = check_grounding(
            answer,
            [entry.result for entry in self._entries if isinstance(entry, ToolResultEntry)],
            [entry.text for entry in self._entries if isinstance(entry, UserEntry)],
            self._locale,
        )
        return report.ungrounded


def _not_executed(reason: str) -> ToolOutcome:
    return ToolOutcome(
        summary=Coded(code="tool.error", params={"error_code": TOOL_NOT_EXECUTED}),
        error=ToolError(
            error_code=TOOL_NOT_EXECUTED,
            message=f"not executed: {reason}; no more tools run in this turn",
            retryable=False,
        ),
    )


def _describe_tool(span: trace.Span, outcome: ToolOutcome, duration_ms: int) -> None:
    span.set_attribute(telemetry.ATTR_TOOL_STATUS, "ok" if outcome.ok else "error")
    span.set_attribute(telemetry.ATTR_TOOL_DURATION_MS, duration_ms)
    if outcome.error is not None:
        span.set_attribute(telemetry.ATTR_TOOL_ERROR_CODE, outcome.error.error_code)


def _elapsed_ms(started_ns: int) -> int:
    return (time.perf_counter_ns() - started_ns) // 1_000_000
