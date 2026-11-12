"""`term_sheet(locale)`: the stored bytes, rendered on the first download (contracts 7)."""

from pathlib import Path

import pytest

from tests.fakes.quoting import FakeQuotingFacade
from tests.unit.documents import fixtures
from tests.unit.documents.doubles import CountingRenderer, api_key, browser, documents_facade
from veranico.modules.documents.application.content import build_content
from veranico.modules.documents.contracts import DocumentsFacade
from veranico.modules.documents.infrastructure.pdf_renderer import ReportlabTermSheetRenderer
from veranico.shared.infrastructure.blobs import LocalBlobStore
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.errors import NotFoundError
from veranico.shared.kernel.ids import QuoteId, WorkspaceId
from veranico.shared.kernel.principal import Principal

QUOTE_ID = QuoteId("Q-3F8H2D")  # the dry spell fixture, workspace `ws-dry`
PT_PATH = "documents/ws-dry/Q-3F8H2D/term-sheet.pt-BR.pdf"


@pytest.fixture
def quoting() -> FakeQuotingFacade:
    facade = FakeQuotingFacade()
    facade.seed_quote(fixtures.dry_spell_quote())
    return facade


@pytest.fixture
def blobs(tmp_path: Path) -> LocalBlobStore:
    return LocalBlobStore(tmp_path)


@pytest.fixture
def renderer() -> CountingRenderer:
    return CountingRenderer()


@pytest.fixture
def facade(
    quoting: FakeQuotingFacade, blobs: LocalBlobStore, renderer: CountingRenderer
) -> DocumentsFacade:
    return documents_facade(quoting=quoting, blobs=blobs, renderer=renderer)


def rendered_entries(quoting: FakeQuotingFacade) -> list[tuple[str, Coded]]:
    return [
        (entry.actor, entry.action)
        for entry in quoting.audit_actions(QUOTE_ID)
        if entry.action.code == "audit.term_sheet_rendered"
    ]


@pytest.mark.req("R-8-5", "R-11.1-3")
async def test_a_first_download_renders_only_that_language_and_stores_it(
    facade: DocumentsFacade, blobs: LocalBlobStore, renderer: CountingRenderer
) -> None:
    data = await facade.term_sheet(browser("ws-dry"), QUOTE_ID, "pt-BR")

    assert data == b"%PDF-counting Q-3F8H2D pt-BR"
    assert renderer.renders == [("Q-3F8H2D", "pt-BR")]
    assert await blobs.list("") == [PT_PATH]
    assert (await blobs.get(PT_PATH)).data == data


@pytest.mark.parametrize(
    ("principal", "actor"),
    [
        (browser("ws-dry"), "human"),
        (api_key("ws-dry"), "api_client"),
        (Principal(workspace_id=WorkspaceId("ws-dry"), kind="system"), "system"),
    ],
)
async def test_the_actor_of_a_download_that_renders_follows_the_principal(
    facade: DocumentsFacade, quoting: FakeQuotingFacade, principal: Principal, actor: str
) -> None:
    await facade.term_sheet(principal, QUOTE_ID, "en")

    assert rendered_entries(quoting) == [
        (actor, Coded(code="audit.term_sheet_rendered", params={"locale": "en"}))
    ]


@pytest.mark.req("R-8-3")
async def test_later_downloads_return_the_stored_bytes_without_rendering(
    facade: DocumentsFacade,
    quoting: FakeQuotingFacade,
    blobs: LocalBlobStore,
    renderer: CountingRenderer,
) -> None:
    first = await facade.term_sheet(browser("ws-dry"), QUOTE_ID, "en")

    second = await facade.term_sheet(api_key("ws-dry"), QUOTE_ID, "en")

    assert second == first
    assert renderer.renders == [("Q-3F8H2D", "en")]
    assert len(rendered_entries(quoting)) == 1
    assert (await blobs.get("documents/ws-dry/Q-3F8H2D/term-sheet.en.pdf")).generation == 1


@pytest.mark.req("R-8-3")
async def test_a_download_after_render_term_sheets_serves_what_was_stored(
    facade: DocumentsFacade, quoting: FakeQuotingFacade, renderer: CountingRenderer
) -> None:
    principal = browser("ws-dry")
    await facade.render_term_sheets(principal, QUOTE_ID, "agent")

    data = await facade.term_sheet(principal, QUOTE_ID, "pt-BR")

    assert data == b"%PDF-counting Q-3F8H2D pt-BR"
    assert len(renderer.renders) == 2
    assert [actor for actor, _ in rendered_entries(quoting)] == ["agent", "agent"]


@pytest.mark.req("R-8-3")
async def test_the_stored_term_sheet_outlives_a_change_of_status(
    facade: DocumentsFacade, quoting: FakeQuotingFacade, renderer: CountingRenderer
) -> None:
    principal = browser("ws-dry")
    first = await facade.term_sheet(principal, QUOTE_ID, "en")
    quoting.seed_quote(fixtures.dry_spell_quote().model_copy(update={"status": "submitted"}))

    assert await facade.term_sheet(principal, QUOTE_ID, "en") == first
    assert len(renderer.renders) == 1


@pytest.mark.req("R-10.1-2")
async def test_a_quote_of_another_workspace_is_not_found_and_nothing_is_touched(
    facade: DocumentsFacade,
    quoting: FakeQuotingFacade,
    blobs: LocalBlobStore,
    renderer: CountingRenderer,
) -> None:
    await facade.term_sheet(browser("ws-dry"), QUOTE_ID, "en")  # stored for its own workspace

    for principal in (browser("ws-other"), api_key("ws-other")):
        with pytest.raises(NotFoundError):
            await facade.term_sheet(principal, QUOTE_ID, "en")

    assert await blobs.list("") == ["documents/ws-dry/Q-3F8H2D/term-sheet.en.pdf"]
    assert len(renderer.renders) == 1
    assert len(rendered_entries(quoting)) == 1


@pytest.mark.req("R-8-1", "R-8-2")
async def test_with_the_real_renderer_the_download_is_the_term_sheet_of_the_quote(
    quoting: FakeQuotingFacade, blobs: LocalBlobStore
) -> None:
    real = documents_facade(quoting=quoting, blobs=blobs, renderer=ReportlabTermSheetRenderer())

    data = await real.term_sheet(browser("ws-dry"), QUOTE_ID, "pt-BR")

    assert data.startswith(b"%PDF-")
    # The stored file is the deterministic render of the stored quote.
    content = build_content(fixtures.dry_spell_quote())
    assert data == ReportlabTermSheetRenderer().render(content, "pt-BR")
    assert (await blobs.get(PT_PATH)).data == data
