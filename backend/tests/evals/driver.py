"""Drives one case through the running application and counts what the model calls cost.

`converse` feeds a case's user turns, in order, into one conversation through
`AssistantFacade.chat` and returns the transcript. `MeteredModel` wraps the model client the
application calls: it adds the usage of every call to the run's `Spend`, priced by
`AccessFacade.cost_of` (the configured prices), and refuses further calls once the run's cost
limit is reached, so a run cannot spend past its limit by more than one model call.
"""

from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from decimal import Decimal

from tests.evals.cases import Case
from tests.evals.checks import ToolCall, Transcript, TurnRecord, Usage
from tests.evals.harness import Application
from veranico.modules.access.contracts import ModelUsage
from veranico.modules.assistant.application.ports import (
    ModelClient,
    ModelCompleted,
    ModelEvent,
    ModelRequest,
    ModelUnavailable,
)
from veranico.modules.assistant.application.replay import EVENT_NAMES
from veranico.modules.assistant.contracts import (
    ChatRequest,
    Done,
    TextDelta,
    ToolFinished,
    ToolStarted,
)
from veranico.shared.kernel.ids import ConversationId, QuoteId

VISITOR_ADDRESS = "203.0.113.62"  # TEST-NET-3; hashed by `access` before anything keeps it
MICROS_PER_DOLLAR = 1_000_000

CostOf = Callable[[ModelUsage], int]


class RunBudgetReachedError(RuntimeError):
    """The run's cost limit leaves no room for this case."""


def usd(micros: int) -> str:
    """Millionths of a dollar as dollars, exactly."""
    return f"{micros // MICROS_PER_DOLLAR}.{micros % MICROS_PER_DOLLAR:06d}"


def usd_micros(dollars: str) -> int:
    """`"1.50"` as millionths of a dollar. Raises `ValueError` on anything else."""
    try:
        micros = Decimal(dollars) * MICROS_PER_DOLLAR
    except ArithmeticError as error:
        raise ValueError(f"not an amount in dollars: {dollars!r}") from error
    if not micros.is_finite() or micros <= 0 or micros != micros.to_integral_value():
        raise ValueError(f"not a positive amount in dollars: {dollars!r}")
    return int(micros)


def priced(usage: ModelUsage, cost_of: CostOf) -> Usage:
    return Usage(
        model_calls=1,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        cost_usd_micros=cost_of(usage),
    )


@dataclass
class Spend:
    """What one run has spent so far, and the limit it may not pass."""

    limit_usd_micros: int | None = None
    agent: Usage = field(default_factory=Usage)  # the calls of the loop under test
    grader: Usage = field(default_factory=Usage)  # the calls of the `refuses` grader
    largest_case_usd_micros: int = 0
    stopped: bool = False  # true once the limit refused a call or a case

    @property
    def spent_usd_micros(self) -> int:
        return self.agent.cost_usd_micros + self.grader.cost_usd_micros

    def add(self, usage: Usage, *, grader: bool = False) -> None:
        if grader:
            self.grader = self.grader.plus(usage)
        else:
            self.agent = self.agent.plus(usage)

    def reached(self) -> bool:
        return self.limit_usd_micros is not None and self.spent_usd_micros >= self.limit_usd_micros

    def admit_case(self) -> None:
        """Raise when the next case could pass the limit: what is spent plus the most
        expensive case so far must fit under it."""
        if self.limit_usd_micros is None:
            return
        if self.stopped or (
            self.spent_usd_micros + self.largest_case_usd_micros > self.limit_usd_micros
        ):
            self.stopped = True
            raise RunBudgetReachedError(
                f"spent US$ {usd(self.spent_usd_micros)} of US$ {usd(self.limit_usd_micros)}; "
                f"the most expensive case so far cost US$ {usd(self.largest_case_usd_micros)}"
            )

    def close_case(self, cost_usd_micros: int) -> None:
        self.largest_case_usd_micros = max(self.largest_case_usd_micros, cost_usd_micros)


class MeteredModel:
    """A `ModelClient` that counts the usage of the client it wraps into the run's spend."""

    def __init__(self, inner: ModelClient, spend: Spend) -> None:
        self._inner = inner
        self._spend = spend
        self._turn = Usage()
        self.cost_of: CostOf | None = None  # `AccessFacade.cost_of` of the application

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelEvent]:
        if self._spend.reached():
            self._spend.stopped = True
            raise ModelUnavailable("the cost limit of the evaluation run is reached")
        try:
            async with aclosing(self._inner.stream(request)) as events:
                async for event in events:
                    if isinstance(event, ModelCompleted):
                        self._count(event.usage)
                    yield event
        except ModelUnavailable as error:
            if error.usage is not None:
                self._count(error.usage)
            raise

    def take_turn_usage(self) -> Usage:
        """What the calls since the last take used."""
        taken, self._turn = self._turn, Usage()
        return taken

    def _count(self, usage: ModelUsage) -> None:
        if self.cost_of is None:
            raise RuntimeError("MeteredModel.cost_of was not set before the first model call")
        counted = priced(usage, self.cost_of)
        self._turn = self._turn.plus(counted)
        self._spend.add(counted)


async def converse(app: Application, case: Case, metered: MeteredModel | None = None) -> Transcript:
    """One conversation: the case's turns through `AssistantFacade.chat`, as a new visitor."""
    container = app.container
    if container.access is None or container.assistant is None or container.quoting is None:
        raise RuntimeError("the application is not the API role")
    access, assistant = container.access.facade, container.assistant.facade
    principal, _ = await access.open_workspace(None)
    visitor = access.visitor(VISITOR_ADDRESS, None)

    conversation_id: ConversationId | None = None
    turns: list[TurnRecord] = []
    for message in case.turns:
        request = ChatRequest(conversation_id=conversation_id, message=message, locale=case.locale)
        text: list[str] = []
        names: list[str] = []
        arguments: dict[str, dict[str, object]] = {}
        calls: list[ToolCall] = []
        stop_reason = "error"
        async for event in assistant.chat(principal, visitor, request):
            names.append(EVENT_NAMES[type(event)])
            if isinstance(event, TextDelta):
                text.append(event.text)
            elif isinstance(event, ToolStarted):
                arguments[event.call_id] = event.arguments
            elif isinstance(event, ToolFinished):
                calls.append(
                    ToolCall(
                        tool=event.tool,
                        arguments=arguments.get(event.call_id, {}),
                        status=event.status,
                        result=event.result,
                        error_code=event.error.error_code if event.error else None,
                    )
                )
            elif isinstance(event, Done):
                conversation_id = event.conversation_id
                stop_reason = event.stop_reason
        turns.append(
            TurnRecord(
                user=message,
                answer="".join(text),
                calls=tuple(calls),
                events=tuple(names),
                stop_reason=stop_reason,
                usage=metered.take_turn_usage() if metered else Usage(),
            )
        )

    quotes = {}
    for turn in turns:
        for call in turn.calls:
            if call.tool == "price_cover" and call.result is not None:
                quote_id = str(call.result["quote_id"])
                view = await container.quoting.facade.get_quote(principal, QuoteId(quote_id))
                quotes[quote_id] = view.status
    return Transcript(locale=case.locale, turns=tuple(turns), quotes=quotes)
