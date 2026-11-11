"""A `ModelClient` that plays a script instead of calling a model.

Every deterministic test uses it, and so does `make dev` without an API key (the model client
selector set to `scripted`). It never touches the network and reports zero token usage unless a
script step says otherwise, so nothing is charged to the spend ledger.

A script is either a list of steps, played one per call, or a single policy function asked on
every call. A step is a list of events, a function of the request that returns one (so it can
read a `quote_id` or a figure from an earlier tool result), or a `FailAfter`, which yields its
events and then raises `ModelUnavailable`.

`happy_path()` is the built-in policy: SPEC section 2 over four user turns (locate, load
history and backtest; price; term sheet; request submission). It reads nothing from the user's
words. It decides from the tool results already in the request, and every figure it writes is
copied from one of them.
"""

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass

from veranico.modules.access.contracts import ModelUsage
from veranico.modules.assistant.application.ports import (
    ModelCompleted,
    ModelEvent,
    ModelRequest,
    ModelStop,
    ModelTextDelta,
    ModelToolCall,
    ModelUnavailable,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)


@dataclass(frozen=True, slots=True)
class FailAfter:
    """Yield `events`, then raise `ModelUnavailable` carrying `usage`."""

    events: tuple[ModelEvent, ...] = ()
    usage: ModelUsage | None = None


Played = Sequence[ModelEvent] | FailAfter
Policy = Callable[[ModelRequest], Played]
Step = Played | Policy


class ScriptExhaustedError(RuntimeError):
    """The loop asked for more model calls than the script has steps."""


class ScriptedModelClient:
    def __init__(self, script: Sequence[Step] | Policy) -> None:
        self._policy: Policy | None = script if callable(script) else None
        self._steps: list[Step] = [] if callable(script) else list(script)
        self._played = 0
        self.requests: list[ModelRequest] = []

    @classmethod
    def happy_path(cls) -> "ScriptedModelClient":
        return cls(happy_path_policy)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        self.requests.append(request)
        played = self._next(request)
        if isinstance(played, FailAfter):
            for event in played.events:
                yield event
            raise ModelUnavailable("scripted failure", usage=played.usage)
        for event in played:
            yield event

    def _next(self, request: ModelRequest) -> Played:
        if self._policy is not None:
            return self._policy(request)
        if self._played >= len(self._steps):
            raise ScriptExhaustedError(
                f"the script has {len(self._steps)} steps and call {self._played + 1} was made"
            )
        step = self._steps[self._played]
        self._played += 1
        return step(request) if callable(step) else step


# Helpers for writing scripts


def no_usage(model: str = "scripted") -> ModelUsage:
    return ModelUsage(model=model, input_tokens=0, output_tokens=0)


def say(text: str, *, stop: ModelStop = "end_turn", usage: ModelUsage | None = None) -> Played:
    """A text answer, streamed sentence by sentence."""
    return (*_deltas(text), ModelCompleted(stop=stop, usage=usage or no_usage()))


def call_tool(
    name: str,
    arguments: Mapping[str, object],
    *,
    call_id: str = "call-1",
    text: str = "",
    usage: ModelUsage | None = None,
) -> Played:
    """One tool call, with optional text before it."""
    return (
        *_deltas(text),
        ModelToolCall(call_id=call_id, name=name, arguments=arguments),
        ModelCompleted(stop="tool_use", usage=usage or no_usage()),
    )


def tool_results(request: ModelRequest) -> list[tuple[str, ToolResultBlock]]:
    """Every tool result of the request with its tool name, oldest first."""
    names = {
        block.call_id: block.name
        for message in request.messages
        for block in message.blocks
        if isinstance(block, ToolCallBlock)
    }
    return [
        (names.get(block.call_id, ""), block)
        for message in request.messages
        for block in message.blocks
        if isinstance(block, ToolResultBlock)
    ]


def _deltas(text: str) -> tuple[ModelTextDelta, ...]:
    if not text:
        return ()
    pieces = text.split(". ")
    return tuple(
        ModelTextDelta(text=piece if at == len(pieces) - 1 else f"{piece}. ")
        for at, piece in enumerate(pieces)
    )


# The built-in scenario

# The first example request of the interface: a coffee farm near Três Pontas, in the Sul de
# Minas showcase region; rainfall below 150 mm from 1 September to 31 October pays linearly
# down to 75 mm, with a limit of R$ 300,000.
HAPPY_PATH_QUERY = "Três Pontas"
HAPPY_PATH_COVER: Mapping[str, object] = {
    "index_type": "rainfall_below",
    "window_start": "09-01",
    "window_end": "10-31",
    "trigger": 150.0,
    "exit": 75.0,
    "limit_cents": 30_000_000,
}
HAPPY_PATH_SIMULATION: Mapping[str, object] = {"n": 100_000, "seed": 42}
_FALLBACK_CARRIER = "carrier-1"


def happy_path_policy(request: ModelRequest) -> Played:
    """The next step of SPEC section 2, from the tool results the request already holds."""
    usage = no_usage(request.model)
    results = tool_results(request)
    latest = {name: block.content for name, block in results if not block.is_error}
    this_turn = _results_of_current_turn(request)
    call_id = f"scripted-{len(results) + 1}"

    def call(name: str, arguments: Mapping[str, object]) -> Played:
        return call_tool(name, arguments, call_id=call_id, usage=usage)

    if request.tool_use == "none":
        return say("I stopped here; ask again to continue from the last step.", usage=usage)
    if this_turn:
        name, block = this_turn[-1]
        if block.is_error:
            code = block.content.get("error_code", "unknown")
            return say(f"The step {name} failed with the code {code}, so I stopped.", usage=usage)
        if name == "resolve_location":
            point = _point(block.content)
            return call("get_weather_history", {"lat": point["lat"], "lon": point["lon"]})
        if name == "get_weather_history":
            arguments = {"dataset_id": block.content["dataset_id"], **HAPPY_PATH_COVER}
            return call("backtest_index", arguments)
        if name == "backtest_index":
            return say(_backtest_answer(block.content, latest), usage=usage)
        if name == "price_cover":
            return say(_price_answer(block.content, latest), usage=usage)
        if name == "draft_term_sheet":
            return say(_term_sheet_answer(block.content, latest), usage=usage)
        if name == "request_submission":
            return say(_submission_answer(block.content, latest), usage=usage)

    if "backtest_index" not in latest:
        return call("resolve_location", {"query": HAPPY_PATH_QUERY})
    if "price_cover" not in latest:
        point = _point(latest.get("resolve_location", {}))
        arguments = {**point, **HAPPY_PATH_COVER, **HAPPY_PATH_SIMULATION}
        return call("price_cover", arguments)
    quote_id = latest["price_cover"].get("quote_id")
    if "draft_term_sheet" not in latest:
        return call("draft_term_sheet", {"quote_id": quote_id})
    if "request_submission" not in latest:
        arguments = {"quote_id": quote_id, "carrier_id": _first_carrier(request)}
        return call("request_submission", arguments)
    return say(
        f"The flow for quote {quote_id} is complete. A person decides the submission in the "
        "Approvals tab; I cannot approve it.",
        usage=usage,
    )


def _results_of_current_turn(request: ModelRequest) -> list[tuple[str, ToolResultBlock]]:
    """The tool results that came after the last message the user typed."""
    last_typed = max(
        (
            at
            for at, message in enumerate(request.messages)
            if message.role == "user" and any(isinstance(b, TextBlock) for b in message.blocks)
        ),
        default=-1,
    )
    names = {
        block.call_id: block.name
        for message in request.messages
        for block in message.blocks
        if isinstance(block, ToolCallBlock)
    }
    current: list[tuple[str, ToolResultBlock]] = []
    for at, message in enumerate(request.messages):
        for block in message.blocks:
            if isinstance(block, ToolResultBlock) and (
                at > last_typed or (at == last_typed and _follows_text(message.blocks, block))
            ):
                current.append((names.get(block.call_id, ""), block))
    return current


def _follows_text(blocks: Sequence[object], result: ToolResultBlock) -> bool:
    """True when `result` sits after the typed text inside one merged user message."""
    seen_text = False
    for block in blocks:
        if isinstance(block, TextBlock):
            seen_text = True
        elif block is result:
            return seen_text
    return False


def _point(location: Mapping[str, object]) -> dict[str, object]:
    """Coordinates and labels of a resolved location; the first candidate of an ambiguous one."""
    candidates = location.get("candidates")
    if isinstance(candidates, list) and candidates and isinstance(candidates[0], Mapping):
        location = candidates[0]
    return {
        "lat": location.get("lat"),
        "lon": location.get("lon"),
        "label": location.get("label"),
        "admin_region": location.get("admin_region"),
    }


def _first_carrier(request: ModelRequest) -> str:
    """The first carrier the `request_submission` tool definition allows."""
    for tool in request.tools:
        if tool.name != "request_submission":
            continue
        properties = tool.input_schema.get("properties")
        carrier = properties.get("carrier_id") if isinstance(properties, Mapping) else None
        allowed = carrier.get("enum") if isinstance(carrier, Mapping) else None
        if isinstance(allowed, list) and allowed and isinstance(allowed[0], str):
            return allowed[0]
    return _FALLBACK_CARRIER


def _backtest_answer(backtest: Mapping[str, object], latest: Mapping[str, object]) -> str:
    place = _get(latest.get("resolve_location"), "label") or "this point"
    season = backtest.get("max_payout_season")
    sentences = [
        f"Over {backtest.get('seasons_used')} seasons at {place}, the index paid in "
        f"{_percent(backtest.get('trigger_frequency'))} of them",
        f"The average historical payout is {_money(backtest.get('burn_cost'))} and the largest "
        f"is {_money(backtest.get('max_payout'))}" + (f", in {season}" if season else ""),
    ]
    if _has_trend_warning(backtest):
        sentences.append("The index has a significant trend, so history may misstate current risk")
    sentences.append(_source_sentence(latest))
    sentences.append("Shall I price this structure?")
    return ". ".join(sentences)


def _price_answer(result: Mapping[str, object], latest: Mapping[str, object]) -> str:
    priced = result.get("priced")
    simulation = _get(priced, "simulation")
    premium = _get(priced, "premium")
    backtest = _get(priced, "backtest")
    sentences = [
        f"Quote {result.get('quote_id')} is a draft",
        f"Expected loss {_money(_get(simulation, 'expected_loss'))}; one-in-ten payout "
        f"{_money(_get(simulation, 'payout_1_in_10'))}; one-in-a-hundred payout "
        f"{_money(_get(simulation, 'payout_1_in_100'))}",
        f"The indicative premium is {_money(_get(premium, 'premium'))}, a rate on line of "
        f"{_percent(_get(premium, 'rate_on_line'))}",
        f"Assumptions: rainfall total from 09-01 to 10-31, {_get(backtest, 'seasons_used')} "
        f"seasons used, simulation method {_get(simulation, 'method')}",
    ]
    if _has_trend_warning(backtest):
        sentences.append("The index has a significant trend, so history may misstate current risk")
    sentences.append(_source_sentence(latest))
    sentences.append("Pricing is illustrative.")
    return ". ".join(sentences)


def _term_sheet_answer(result: Mapping[str, object], latest: Mapping[str, object]) -> str:
    quote_id = _get(latest.get("price_cover"), "quote_id")
    documents = result.get("documents")
    count = len(documents) if isinstance(documents, list) else 0
    return (
        f"The term sheet for quote {quote_id} is rendered in English and Portuguese "
        f"({count} documents). It is in the Quote tab."
    )


def _submission_answer(result: Mapping[str, object], latest: Mapping[str, object]) -> str:
    quote_id = _get(latest.get("price_cover"), "quote_id")
    return (
        f"Submission {result.get('submission_id')} for quote {quote_id} is waiting for approval. "
        "I can request it but I cannot approve it: a person decides in the Approvals tab."
    )


def _source_sentence(latest: Mapping[str, object]) -> str:
    source = _get(latest.get("get_weather_history"), "source")
    if source == "synthetic":
        return "The weather data for this region is synthetic, not real weather history"
    return f"The weather data source is {source}"


def _has_trend_warning(backtest: object) -> bool:
    warnings = _get(backtest, "warnings")
    return isinstance(warnings, list) and any(
        _get(warning, "code") == "warning.trend_significant" for warning in warnings
    )


def _get(node: object, key: str) -> object:
    return node.get(key) if isinstance(node, Mapping) else None


def _money(money: object) -> str:
    """`{"amount_cents": 1234567}` as `R$ 12,345.67`: digits moved, nothing computed."""
    centavos = _get(money, "amount_cents")
    if not isinstance(centavos, int):
        return "an unknown amount"
    digits = str(abs(centavos)).rjust(3, "0")
    sign = "-" if centavos < 0 else ""
    return f"{sign}R$ {int(digits[:-2]):,}.{digits[-2:]}"


def _percent(rate: object) -> str:
    """`"0.123456"` as `12.3456%`: the decimal point moved two places, nothing rounded."""
    if not isinstance(rate, str) or "." not in rate:
        return "an unknown share"
    sign = "-" if rate.startswith("-") else ""
    whole, fraction = rate.lstrip("-").split(".")
    digits = whole + fraction[:2]
    return f"{sign}{int(digits)}.{fraction[2:]}%"
