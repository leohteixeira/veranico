import pytest

from tests.fakes import builders
from tests.fakes.documents import FakeDocumentsFacade, evidence_bytes, term_sheet_bytes
from tests.fakes.quoting import FakeQuotingFacade
from veranico.shared.kernel.errors import NotFoundError
from veranico.shared.kernel.ids import QuoteId, WorkspaceId
from veranico.shared.kernel.principal import Principal

BROWSER = Principal(workspace_id=WorkspaceId("ws-1"), kind="browser")
OTHER = Principal(workspace_id=WorkspaceId("ws-2"), kind="browser")
QUOTE_ID = QuoteId("Q-000001")


def documents() -> tuple[FakeDocumentsFacade, FakeQuotingFacade]:
    quoting = FakeQuotingFacade()
    quoting.seed_quote(builders.quote_view(quote_id=QUOTE_ID, workspace_id="ws-1"))
    return FakeDocumentsFacade(quoting), quoting


async def test_render_term_sheets_returns_two_references_and_is_idempotent() -> None:
    fake, quoting = documents()

    first = await fake.render_term_sheets(BROWSER, QUOTE_ID, "agent")
    second = await fake.render_term_sheets(BROWSER, QUOTE_ID, "human")

    assert first == second
    assert [(ref.kind, ref.locale, ref.content_type) for ref in first] == [
        ("term_sheet", "en", "application/pdf"),
        ("term_sheet", "pt-BR", "application/pdf"),
    ]
    assert [ref.path for ref in first] == [
        "/api/v1/quotes/Q-000001/term-sheet.pdf?lang=en",
        "/api/v1/quotes/Q-000001/term-sheet.pdf?lang=pt-BR",
    ]
    assert first[0].size_bytes == len(await fake.term_sheet(BROWSER, QUOTE_ID, "en"))
    rendered = [
        (entry.actor, entry.action.code)
        for entry in quoting.audit_actions(QUOTE_ID)
        if entry.action.code == "audit.term_sheet_rendered"
    ]
    assert rendered == [("agent", "audit.term_sheet_rendered")]  # audited once


async def test_downloads_differ_by_locale_and_kind() -> None:
    fake, _ = documents()

    english = await fake.term_sheet(BROWSER, QUOTE_ID, "en")
    portuguese = await fake.term_sheet(BROWSER, QUOTE_ID, "pt-BR")
    evidence = await fake.evidence(BROWSER, QUOTE_ID)

    assert english == term_sheet_bytes(QUOTE_ID, "en")
    assert english != portuguese
    assert evidence == evidence_bytes(QUOTE_ID)


async def test_a_quote_of_another_workspace_is_not_found() -> None:
    fake, quoting = documents()

    with pytest.raises(NotFoundError):
        await fake.render_term_sheets(OTHER, QUOTE_ID, "agent")
    with pytest.raises(NotFoundError):
        await fake.term_sheet(OTHER, QUOTE_ID, "en")
    with pytest.raises(NotFoundError):
        await fake.evidence(OTHER, QUOTE_ID)
    with pytest.raises(NotFoundError):
        await fake.render_term_sheets(BROWSER, QuoteId("Q-ZZZZZZ"), "agent")
    assert len(quoting.audit_actions(QUOTE_ID)) == 1
    assert [name for name, _ in fake.calls] == [
        "render_term_sheets",
        "term_sheet",
        "evidence",
        "render_term_sheets",
    ]
