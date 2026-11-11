"""Term sheets in Cloud Storage (SPEC 8, 14), on the emulator with the real renderer."""

import asyncio

import pytest

from tests.fakes.quoting import FakeQuotingFacade
from tests.unit.documents import fixtures
from tests.unit.documents.doubles import browser
from veranico.modules.documents.application.facade import DocumentsService
from veranico.modules.documents.application.term_sheets import TermSheets
from veranico.modules.documents.contracts import DocumentsFacade
from veranico.modules.documents.infrastructure.pdf_renderer import ReportlabTermSheetRenderer
from veranico.modules.quoting.contracts import QuoteView
from veranico.shared.infrastructure.blobs import GcsBlobStore
from veranico.shared.kernel.ids import WorkspaceId

pytestmark = pytest.mark.integration


class Scene:
    def __init__(self, blobs: GcsBlobStore, workspace_id: str) -> None:
        self.quote: QuoteView = fixtures.rainfall_quote().model_copy(
            update={"workspace_id": WorkspaceId(workspace_id)}
        )
        self.prefix = f"documents/{workspace_id}/{self.quote.quote_id}/"
        self.principal = browser(workspace_id)
        self.quoting = FakeQuotingFacade()
        self.quoting.seed_quote(self.quote)
        self.blobs = blobs
        self.facade: DocumentsFacade = DocumentsService(
            term_sheets=TermSheets(
                quoting=self.quoting, blobs=blobs, renderer=ReportlabTermSheetRenderer()
            )
        )

    def rendered_locales(self) -> list[str | int | float]:
        return sorted(
            entry.action.params["locale"]
            for entry in self.quoting.audit_actions(self.quote.quote_id)
            if entry.action.code == "audit.term_sheet_rendered"
        )


@pytest.fixture
def scene(blobs: GcsBlobStore, workspace_id: str) -> Scene:
    return Scene(blobs, workspace_id)


@pytest.mark.req("R-8-5", "R-14-2")
async def test_both_term_sheets_are_stored_under_the_workspace_prefix_and_nowhere_else(
    scene: Scene, workspace_id: str
) -> None:
    references = await scene.facade.render_term_sheets(
        scene.principal, scene.quote.quote_id, "agent"
    )

    stored = await scene.blobs.list(f"documents/{workspace_id}/")
    assert stored == [f"{scene.prefix}term-sheet.en.pdf", f"{scene.prefix}term-sheet.pt-BR.pdf"]
    # Nothing of this workspace outside its own prefix (the bucket is shared with other tests).
    everything = await scene.blobs.list("")
    assert [path for path in everything if workspace_id in path] == stored
    sizes = [len((await scene.blobs.get(path)).data) for path in stored]
    assert [reference.size_bytes for reference in references] == sizes


@pytest.mark.req("R-8-5", "R-8-3")
async def test_the_bytes_read_back_equal_the_bytes_returned(scene: Scene) -> None:
    for locale in ("en", "pt-BR"):
        returned = await scene.facade.term_sheet(scene.principal, scene.quote.quote_id, locale)
        stored = await scene.blobs.get(f"{scene.prefix}term-sheet.{locale}.pdf")
        again = await scene.facade.term_sheet(scene.principal, scene.quote.quote_id, locale)

        assert returned.startswith(b"%PDF-")
        assert stored.data == returned
        assert again == returned

    assert scene.rendered_locales() == ["en", "pt-BR"]  # one entry per language, not per call


@pytest.mark.req("R-8-3", "R-8-5")
async def test_two_renders_started_together_end_with_two_objects_and_identical_bytes(
    scene: Scene,
) -> None:
    first, second = await asyncio.gather(
        scene.facade.render_term_sheets(scene.principal, scene.quote.quote_id, "agent"),
        scene.facade.render_term_sheets(scene.principal, scene.quote.quote_id, "agent"),
    )

    assert first == second
    stored = await scene.blobs.list(scene.prefix)
    assert stored == [f"{scene.prefix}term-sheet.en.pdf", f"{scene.prefix}term-sheet.pt-BR.pdf"]
    for reference, path in zip(first, stored, strict=True):
        data = (await scene.blobs.get(path)).data
        assert len(data) == reference.size_bytes
        assert data == await scene.facade.term_sheet(
            scene.principal, scene.quote.quote_id, reference.locale or "en"
        )
    # The create-only write lets exactly one of the two renders record each entry.
    assert scene.rendered_locales() == ["en", "pt-BR"]
