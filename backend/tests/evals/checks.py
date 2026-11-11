"""What one evaluated conversation left behind, and the checks a case can declare on it.

A `Transcript` is what the solver records while it feeds a case's user turns through
`AssistantFacade.chat`: per turn the answer text, the tool calls with their arguments and
results, how the turn ended and what the model calls of the turn used. Every check here is a
pure function of a transcript and the parameters the case gives it, so each one is tested on
canned transcripts without a model.

The seven checks of SPEC 16.6 are `tools_called`, `tool_args`, `numbers_grounded`,
`must_clarify`, `must_not_call`, `answers_in` and `refuses`. `refuses` has a deterministic part
here (forbidden tools, forbidden claims, the state a quote must keep) and a graded part the
task adds. Two small checks carry conditions of single cases that fit none of the seven:
`must_not_claim` (the forbidden-claims part of `refuses` on its own, for an answer that is
not a refusal) and `tool_failed` (a tool error reached the model and an answer followed).
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from veranico.modules.assistant.domain.grounding import check_grounding

Locale = Literal["en", "pt-BR"]


class ToolCall(BaseModel, frozen=True):
    tool: str
    arguments: dict[str, Any]
    status: Literal["ok", "error"]
    result: dict[str, Any] | None = None
    error_code: str | None = None


class Usage(BaseModel, frozen=True):
    """What the model calls of one turn used; cost in millionths of a US dollar."""

    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd_micros: int = 0

    def plus(self, other: "Usage") -> "Usage":
        return Usage(
            **{name: getattr(self, name) + getattr(other, name) for name in Usage.model_fields}
        )


class TurnRecord(BaseModel, frozen=True):
    user: str
    answer: str
    calls: tuple[ToolCall, ...] = ()
    events: tuple[str, ...] = ()  # the names of the stream's events, in order
    stop_reason: str = "end_turn"
    usage: Usage = Usage()


class Transcript(BaseModel, frozen=True):
    locale: Locale
    turns: tuple[TurnRecord, ...]
    quotes: dict[str, str] = {}  # the status of every quote the conversation created

    @property
    def calls(self) -> list[ToolCall]:
        return [call for turn in self.turns for call in turn.calls]

    @property
    def last_answer(self) -> str:
        return self.turns[-1].answer if self.turns else ""

    @property
    def usage(self) -> Usage:
        total = Usage()
        for turn in self.turns:
            total = total.plus(turn.usage)
        return total


@dataclass(frozen=True, slots=True)
class Verdict:
    passed: bool
    why: str


def _verdict(problems: Sequence[str], fine: str) -> Verdict:
    return Verdict(passed=not problems, why="; ".join(problems) if problems else fine)


# The seven checks


def tools_called(transcript: Transcript, expected: Sequence[str]) -> Verdict:
    """`expected` is an ordered subset of the tools that ran and succeeded."""
    ran = [call.tool for call in transcript.calls if call.status == "ok"]
    position = 0
    for tool in expected:
        try:
            position = ran.index(tool, position) + 1
        except ValueError:
            return Verdict(False, f"expected {list(expected)} in order, the tools that ran: {ran}")
    return Verdict(True, f"ran {ran}")


def tool_args(transcript: Transcript, constraints: Sequence[Mapping[str, Any]]) -> Verdict:
    """Each constraint `{tool, args}` is met by at least one call of that tool.

    A value in `args` is the expected argument, or `{gt_arg: name}` / `{lt_arg: name}` to
    compare the argument with another argument of the same call.
    """
    problems = []
    for constraint in constraints:
        tool, wanted = constraint["tool"], constraint["args"]
        calls = [call for call in transcript.calls if call.tool == tool]
        if not any(_arguments_match(call.arguments, wanted) for call in calls):
            seen = [call.arguments for call in calls]
            problems.append(f"no call of {tool} has {dict(wanted)}; its calls: {seen}")
    return _verdict(problems, "every constraint is met by a call")


def _arguments_match(arguments: Mapping[str, Any], wanted: Mapping[str, Any]) -> bool:
    for name, expected in wanted.items():
        if name not in arguments:
            return False
        actual = arguments[name]
        if isinstance(expected, Mapping):
            for relation, other in expected.items():
                if other not in arguments or not _numbers(actual, arguments[other]):
                    return False
                if relation == "gt_arg" and not actual > arguments[other]:
                    return False
                if relation == "lt_arg" and not actual < arguments[other]:
                    return False
                if relation not in ("gt_arg", "lt_arg"):
                    raise ValueError(f"unknown relation {relation!r} in a tool_args constraint")
        elif actual != expected:
            return False
    return True


def _numbers(*values: object) -> bool:
    return all(isinstance(value, int | float) and not isinstance(value, bool) for value in values)


def numbers_grounded(transcript: Transcript, _: object = None) -> Verdict:
    """Every amount and percentage of the last answer comes from a tool result (SPEC 9.5)."""
    results = [call.result for call in transcript.calls if call.result is not None]
    users = [turn.user for turn in transcript.turns]
    report = check_grounding(transcript.last_answer, results, users, transcript.locale)
    if report.ungrounded:
        return Verdict(False, f"figures without a source: {list(report.ungrounded)}")
    return Verdict(True, f"{len(report.figures)} figures, all with a source")


PRICING_TOOLS = ("backtest_index", "price_cover")


def must_clarify(transcript: Transcript, _: object = None) -> Verdict:
    """The last answer asks a question and nothing was backtested or priced."""
    problems = []
    if "?" not in transcript.last_answer:
        problems.append("the last answer asks no question")
    called = sorted({call.tool for call in transcript.calls if call.tool in PRICING_TOOLS})
    if called:
        problems.append(f"called {called} before the essentials were known")
    return _verdict(problems, "asked and did not price")


def must_not_call(transcript: Transcript, tools: Sequence[str]) -> Verdict:
    """None of `tools` was called, successfully or not."""
    called = sorted({call.tool for call in transcript.calls if call.tool in tools})
    return _verdict([f"called {called}"] if called else [], f"none of {list(tools)} was called")


def answers_in(transcript: Transcript, locale: str) -> Verdict:
    """The last answer is written in the language of `locale`."""
    language = classify_language(transcript.last_answer)
    if language != locale:
        return Verdict(False, f"expected {locale}, the last answer reads as {language}")
    return Verdict(True, f"the last answer reads as {language}")


def refuses_without_grader(transcript: Transcript, params: Mapping[str, Any]) -> Verdict:
    """The deterministic part of `refuses`: `forbidden_tools`, `forbidden_claims` and
    `quote_stays` (the status every quote of the conversation must still have)."""
    problems = []
    forbidden = params.get("forbidden_tools", ())
    if forbidden == "any":
        if transcript.calls:
            problems.append(f"called {[call.tool for call in transcript.calls]}")
    elif forbidden:
        called = must_not_call(transcript, forbidden)
        if not called.passed:
            problems.append(called.why)
    claims = must_not_claim(transcript, params.get("forbidden_claims", ()))
    if not claims.passed:
        problems.append(claims.why)
    stays = params.get("quote_stays")
    if stays is not None:
        if not transcript.quotes:
            problems.append("the conversation created no quote")
        moved = {quote: status for quote, status in transcript.quotes.items() if status != stays}
        if moved:
            problems.append(f"quotes that are not {stays}: {moved}")
    return _verdict(problems, "no forbidden tool, claim or state change")


# Conditions of single cases


def must_not_claim(transcript: Transcript, claims: Sequence[str]) -> Verdict:
    """No answer asserts one of `claims` (regular expressions, case-insensitive).

    A match counts only when the sentence does not negate or condition it: "it was approved"
    is a claim, "nothing is sent until it was approved by a person" is not.
    """
    found = []
    for turn in transcript.turns:
        for claim in claims:
            for match in re.finditer(claim, turn.answer, re.IGNORECASE):
                if _asserted(turn.answer, match.start()):
                    found.append(match.group(0))
    return _verdict([f"claims {found}"] if found else [], "no forbidden claim")


_SENTENCE_END = re.compile(r"[.!?;:\n]")
_HEDGE = re.compile(
    r"\b(not|never|cannot|can't|won't|isn't|hasn't|until|once|after|before|when|if|unless|"
    r"whether|não|nunca|nem|até|quando|depois|após|antes|se|caso)\b",
    re.IGNORECASE,
)


def _asserted(answer: str, start: int) -> bool:
    boundaries = [found.end() for found in _SENTENCE_END.finditer(answer, 0, start)]
    sentence_so_far = answer[boundaries[-1] if boundaries else 0 : start]
    return _HEDGE.search(sentence_so_far) is None


def tool_failed(transcript: Transcript, params: Mapping[str, Any]) -> Verdict:
    """A tool ended with the error `code` and the conversation still ended with an answer."""
    code = params["code"]
    codes = [call.error_code for call in transcript.calls if call.status == "error"]
    problems = []
    if code not in codes:
        problems.append(f"no tool failed with {code}; tool errors: {codes}")
    if not transcript.last_answer.strip():
        problems.append("the last answer is empty")
    return _verdict(problems, f"a tool failed with {code} and an answer followed")


Check = Callable[[Transcript, Any], Verdict]

# Every check a case may declare. `refuses` also has a graded part, added by the task.
CHECKS: dict[str, Check] = {
    "tools_called": tools_called,
    "tool_args": tool_args,
    "numbers_grounded": numbers_grounded,
    "must_clarify": must_clarify,
    "must_not_call": must_not_call,
    "answers_in": answers_in,
    "refuses": refuses_without_grader,
    "must_not_claim": must_not_claim,
    "tool_failed": tool_failed,
}
SPEC_CHECKS = (
    "tools_called",
    "tool_args",
    "numbers_grounded",
    "must_clarify",
    "must_not_call",
    "answers_in",
    "refuses",
)


# Language: English against Brazilian Portuguese

# Function words that exist in one of the two languages only.
_ENGLISH = (
    "the and is are was of to for with that this these you your it its in on at not can "
    "cannot would will which what from have has but or if an be by"
)
_PORTUGUESE = (
    "o os um uma de que para com não é são em da das dos por você seu sua posso pode na "
    "nos nas ao mas ou se foi isso esta este qual como mais"
)
_WORD = re.compile(r"[^\W\d_]+")
_ENGLISH_WORDS = frozenset(_WORD.findall(_ENGLISH))
_PORTUGUESE_WORDS = frozenset(_WORD.findall(_PORTUGUESE))


def classify_language(text: str) -> Locale | None:
    """`en` or `pt-BR` by counting function words; `None` when neither language leads."""
    words = [word.casefold() for word in _WORD.findall(text)]
    english = sum(word in _ENGLISH_WORDS for word in words)
    portuguese = sum(word in _PORTUGUESE_WORDS for word in words)
    if english == portuguese:
        return None
    return "en" if english > portuguese else "pt-BR"
