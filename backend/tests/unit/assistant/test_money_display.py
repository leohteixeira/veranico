"""Money reaches the model with its text for the turn's locale (SPEC 9.3 rule 7, 13).

The model copies `display` instead of formatting centavos itself. Only the model-facing copy
of a tool result carries it: the stored result and the `tool_finished` event stay as they were,
and the text is grounded against the stored centavos (SPEC 9.5).
"""

from collections.abc import Iterator, Mapping

import pytest

from tests.fakes.builders import cover, priced_cover
from tests.fakes.settings import settings_for_tests
from tests.unit.assistant.tools.kit import BROWSER, LIMIT_CENTS
from tests.unit.assistant.turn_kit import build_turn_kit, finished_tools, run, started
from veranico.modules.assistant.application.ports import ModelRequest, ToolResultBlock, ToolSpec
from veranico.modules.assistant.application.prompt import build_request, load_system_prompt
from veranico.modules.assistant.application.tools.models import PriceCoverOutput
from veranico.modules.assistant.contracts import GroundingFlagged
from veranico.modules.assistant.domain.compaction import estimate_tokens
from veranico.modules.assistant.domain.conversation import (
    AssistantStep,
    Entry,
    ToolCall,
    ToolResultEntry,
    UserEntry,
)
from veranico.modules.assistant.domain.grounding import check_grounding
from veranico.modules.assistant.domain.money_display import with_money_display
from veranico.modules.assistant.infrastructure.scripted_model import (
    Played,
    call_tool,
    say,
    tool_results,
)
from veranico.shared.kernel.ids import Locale, QuoteId
from veranico.shared.kernel.money import format_money

PROMPT = load_system_prompt()
TOOLS = (ToolSpec(name="price_cover", description="Price a cover.", input_schema={}),)
PRICED: dict[str, object] = PriceCoverOutput(
    quote_id=QuoteId("Q-7K3M9P"), priced=priced_cover(cover(limit_cents=LIMIT_CENTS))
).model_dump(mode="json")


def money_nodes(node: object) -> Iterator[Mapping[str, object]]:
    """Every `Money` mapping in a serialised result."""
    if isinstance(node, Mapping):
        if "amount_cents" in node and node.get("currency") == "BRL":
            yield node
        for value in node.values():
            yield from money_nodes(value)
    elif isinstance(node, list | tuple):
        for item in node:
            yield from money_nodes(item)


def price_history(turn_of_result: int, *, then: int | None = None) -> list[Entry]:
    entries: list[Entry] = [
        UserEntry(seq=1, turn=turn_of_result, text="Price it"),
        AssistantStep(
            seq=2,
            turn=turn_of_result,
            text="",
            tool_calls=(ToolCall(call_id="c1", tool="price_cover", arguments={}),),
        ),
        ToolResultEntry(
            seq=3,
            turn=turn_of_result,
            call_id="c1",
            tool="price_cover",
            status="ok",
            result=PRICED,
        ),
    ]
    if then is not None:
        entries.append(UserEntry(seq=4, turn=then, text="And now?"))
    return entries


def result_content(request: ModelRequest) -> Mapping[str, object]:
    [block] = [b for m in request.messages for b in m.blocks if isinstance(b, ToolResultBlock)]
    return block.content


@pytest.mark.parametrize(
    ("amount_cents", "locale", "display"),
    [
        (4_063_788, "en", "R$ 40,637.88"),
        (4_063_788, "pt-BR", "R$ 40.637,88"),
        (30_000_000, "en", "R$ 300,000.00"),
        (30_000_000, "pt-BR", "R$ 300.000,00"),
        (5, "en", "R$ 0.05"),
        (-123_456, "pt-BR", "-R$ 1.234,56"),
    ],
)
def test_a_money_value_gets_the_text_of_the_locale(
    amount_cents: int, locale: Locale, display: str
) -> None:
    money = {"amount_cents": amount_cents, "currency": "BRL"}

    assert with_money_display({"premium": money}, locale) == {
        "premium": {**money, "display": display}
    }


@pytest.mark.req("R-9.3-7")
@pytest.mark.parametrize("locale", ["en", "pt-BR"])
def test_the_price_cover_result_the_model_reads_carries_the_locale_text(locale: Locale) -> None:
    request = build_request(PROMPT, price_history(1), TOOLS, settings_for_tests(), locale=locale)

    content = result_content(request)
    seen = list(money_nodes(content))
    assert len(seen) == len(list(money_nodes(PRICED))) > 0
    for money in seen:
        assert money["display"] == format_money(money["amount_cents"], locale)  # type: ignore[arg-type]
    priced = content["priced"]
    assert isinstance(priced, Mapping)
    limit = priced["backtest"]["cover"]["limit"]  # type: ignore[index]
    expected = {"en": "R$ 300,000.00", "pt-BR": "R$ 300.000,00"}[locale]
    assert limit == {"amount_cents": LIMIT_CENTS, "currency": "BRL", "display": expected}
    # Everything else is the stored result, unchanged.
    assert with_money_display(PRICED, locale) == content
    assert "display" not in str(PRICED)


@pytest.mark.req("R-9.2-3")
@pytest.mark.parametrize("locale", ["en", "pt-BR"])
def test_the_compaction_summary_keeps_the_locale_text(locale: Locale) -> None:
    entries = price_history(1, then=2)
    tool_definitions = [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in TOOLS
    ]
    full = estimate_tokens(PROMPT.text, tool_definitions, entries, 4)
    tight = settings_for_tests(
        assistant={"compaction_threshold_tokens": full - 1, "chars_per_token": 4}
    )

    content = result_content(build_request(PROMPT, entries, TOOLS, tight, locale=locale))

    assert content["compacted"] is True
    priced = content["priced"]
    assert isinstance(priced, Mapping)
    assert "seasons" not in priced["backtest"]  # the per-season list was dropped
    premium = priced["premium"]["premium"]  # type: ignore[index]
    assert premium["display"] == format_money(premium["amount_cents"], locale)
    seen = list(money_nodes(content))
    assert seen
    assert all(money["display"] == format_money(money["amount_cents"], locale) for money in seen)  # type: ignore[arg-type]


@pytest.mark.req("R-9.5-2")
@pytest.mark.parametrize("locale", ["en", "pt-BR"])
def test_every_display_text_is_grounded_in_the_stored_result(locale: Locale) -> None:
    content = with_money_display(PRICED, locale)
    answer = " ".join(str(money["display"]) for money in money_nodes(content))

    report = check_grounding(answer, [PRICED], [], locale)

    assert answer
    assert report.ungrounded == ()


def premium_copied(request: ModelRequest) -> Played:
    """Answers with the premium text exactly as the model read it in the price_cover result."""
    _, block = tool_results(request)[-1]
    premium = block.content["priced"]["premium"]["premium"]  # type: ignore[index]
    return say(f"The premium is {premium['display']}.")


@pytest.mark.req("R-9.5-2")
@pytest.mark.parametrize("locale", ["en", "pt-BR"])
async def test_a_turn_shows_the_model_its_locale_and_keeps_the_stream_result(
    locale: Locale,
) -> None:
    kit = build_turn_kit()
    service, model = kit.scripted(
        call_tool("price_cover", kit.tools.price_arguments(), call_id="c1"), premium_copied
    )

    events = await run(service, "Price it", locale=locale)

    _, block = tool_results(model.requests[-1])[-1]
    premium = block.content["priced"]["premium"]["premium"]  # type: ignore[index]
    assert premium["display"] == format_money(premium["amount_cents"], locale)
    # The model copied it, and the copy is grounded.
    assert not [event for event in events if isinstance(event, GroundingFlagged)]
    # The frontend receives the result as before: centavos only.
    [finished] = finished_tools(events)
    assert finished.result is not None
    assert "display" not in str(finished.result)
    state = await kit.store.load(BROWSER.workspace_id, started(events).conversation_id)
    stored = [entry for entry in state.entries if isinstance(entry, ToolResultEntry)]
    assert "display" not in str(stored[0].result)
