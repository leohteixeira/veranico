import pytest

from tests.unit.assistant.tools.kit import BROWSER, OTHER, build_kit
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.ids import QuoteId

pytestmark = [pytest.mark.req("R-9.4-6"), pytest.mark.req("R-9.4-8")]


async def test_maps_arguments_to_the_facade_call() -> None:
    kit = build_kit()
    quote_id = await kit.priced_quote_id()

    await kit.registry.execute(BROWSER, "draft_term_sheet", {"quote_id": quote_id})

    assert kit.documents.calls == [("render_term_sheets", (BROWSER, quote_id, "agent"))]


async def test_draft_term_sheet_passes_the_agent_actor() -> None:
    kit = build_kit()
    quote_id = await kit.priced_quote_id()

    await kit.registry.execute(BROWSER, "draft_term_sheet", {"quote_id": quote_id})

    audit = kit.quoting.audit_actions(QuoteId(quote_id))
    assert [(entry.actor, entry.action.code) for entry in audit] == [
        ("agent", "audit.quote_created"),
        ("agent", "audit.term_sheet_rendered"),
    ]


async def test_returns_the_output_model_serialised() -> None:
    kit = build_kit()
    quote_id = await kit.priced_quote_id()

    outcome = await kit.registry.execute(BROWSER, "draft_term_sheet", {"quote_id": quote_id})

    expected = await kit.documents.render_term_sheets(BROWSER, QuoteId(quote_id), "agent")
    assert outcome.ok
    assert outcome.result == {"documents": [ref.model_dump(mode="json") for ref in expected]}
    assert [ref.locale for ref in expected] == ["en", "pt-BR"]
    assert outcome.summary == Coded(code="tool.draft_term_sheet")
    assert outcome.approval is None


async def test_quote_of_another_workspace_is_not_found() -> None:
    kit = build_kit()
    quote_id = await kit.priced_quote_id()

    outcome = await kit.registry.execute(OTHER, "draft_term_sheet", {"quote_id": quote_id})

    assert outcome.error is not None
    assert outcome.error.error_code == "not_found"
