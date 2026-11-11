"""`render_term_sheets`: both locales, stored once, audited once per locale (contracts 7)."""

import logging
from pathlib import Path

import pytest

from tests.fakes.quoting import FakeQuotingFacade
from tests.unit.documents import fixtures
from tests.unit.documents.doubles import AuditFailsQuoting, CountingRenderer, api_key, browser
from veranico.modules.documents.application.facade import DocumentsService
from veranico.modules.documents.application.term_sheets import TermSheets
from veranico.modules.documents.contracts import DocumentRef, DocumentsFacade
from veranico.modules.quoting.contracts import Actor, QuoteView
from veranico.shared.infrastructure.blobs import LocalBlobStore
from veranico.shared.kernel.coded import Coded
from veranico.shared.kernel.errors import NotFoundError
from veranico.shared.kernel.ids import QuoteId

EN_PATH = "documents/ws-rain/Q-7K2M9P/term-sheet.en.pdf"
PT_PATH = "documents/ws-rain/Q-7K2M9P/term-sheet.pt-BR.pdf"


class Scene:
    def __init__(self, root: Path, quoting: FakeQuotingFacade | None = None) -> None:
        self.quote: QuoteView = fixtures.rainfall_quote()  # workspace `ws-rain`
        self.quoting = quoting or FakeQuotingFacade()
        self.quoting.seed_quote(self.quote)
        self.blobs = LocalBlobStore(root)
        self.renderer = CountingRenderer()
        self.facade: DocumentsFacade = DocumentsService(
            term_sheets=TermSheets(quoting=self.quoting, blobs=self.blobs, renderer=self.renderer)
        )

    def rendered_entries(self) -> list[tuple[str, Coded]]:
        return [
            (entry.actor, entry.action)
            for entry in self.quoting.audit_actions(self.quote.quote_id)
            if entry.action.code == "audit.term_sheet_rendered"
        ]

    def calls(self, name: str) -> int:
        return sum(1 for call, _ in self.quoting.calls if call == name)


@pytest.fixture
def scene(tmp_path: Path) -> Scene:
    return Scene(tmp_path)


@pytest.mark.req("R-8-1", "R-8-6", "R-13-3")
async def test_it_returns_one_reference_per_language(scene: Scene) -> None:
    references = await scene.facade.render_term_sheets(
        browser("ws-rain"), scene.quote.quote_id, "agent"
    )

    assert references == [
        DocumentRef(
            quote_id=QuoteId("Q-7K2M9P"),
            kind="term_sheet",
            locale="en",
            content_type="application/pdf",
            size_bytes=len(b"%PDF-counting Q-7K2M9P en"),
            path="/api/v1/quotes/Q-7K2M9P/term-sheet.pdf?lang=en",
        ),
        DocumentRef(
            quote_id=QuoteId("Q-7K2M9P"),
            kind="term_sheet",
            locale="pt-BR",
            content_type="application/pdf",
            size_bytes=len(b"%PDF-counting Q-7K2M9P pt-BR"),
            path="/api/v1/quotes/Q-7K2M9P/term-sheet.pdf?lang=pt-BR",
        ),
    ]


@pytest.mark.req("R-8-5", "R-14-2")
async def test_it_stores_both_files_under_the_prefix_of_the_quotes_workspace(scene: Scene) -> None:
    await scene.facade.render_term_sheets(browser("ws-rain"), scene.quote.quote_id, "agent")

    assert await scene.blobs.list("") == [EN_PATH, PT_PATH]
    assert (await scene.blobs.get(EN_PATH)).data == b"%PDF-counting Q-7K2M9P en"
    assert (await scene.blobs.get(PT_PATH)).data == b"%PDF-counting Q-7K2M9P pt-BR"


@pytest.mark.parametrize("actor", ["agent", "api_client"])
async def test_it_records_one_audit_entry_per_language_with_the_actor_it_was_given(
    scene: Scene, actor: Actor
) -> None:
    await scene.facade.render_term_sheets(browser("ws-rain"), scene.quote.quote_id, actor)

    assert scene.rendered_entries() == [
        (actor, Coded(code="audit.term_sheet_rendered", params={"locale": "en"})),
        (actor, Coded(code="audit.term_sheet_rendered", params={"locale": "pt-BR"})),
    ]


@pytest.mark.req("R-8-3")
async def test_a_second_call_renders_stores_and_audits_nothing(scene: Scene) -> None:
    principal = browser("ws-rain")
    first = await scene.facade.render_term_sheets(principal, scene.quote.quote_id, "agent")
    generations = [(await scene.blobs.get(path)).generation for path in (EN_PATH, PT_PATH)]

    second = await scene.facade.render_term_sheets(principal, scene.quote.quote_id, "human")

    assert second == first
    assert scene.renderer.renders == [("Q-7K2M9P", "en"), ("Q-7K2M9P", "pt-BR")]
    assert [(await scene.blobs.get(path)).generation for path in (EN_PATH, PT_PATH)] == generations
    assert len(scene.rendered_entries()) == 2
    assert scene.calls("append_audit") == 2


async def test_only_the_missing_language_is_rendered(scene: Scene) -> None:
    principal = browser("ws-rain")
    await scene.facade.term_sheet(principal, scene.quote.quote_id, "pt-BR")

    references = await scene.facade.render_term_sheets(principal, scene.quote.quote_id, "agent")

    assert [reference.locale for reference in references] == ["en", "pt-BR"]
    assert scene.renderer.renders == [("Q-7K2M9P", "pt-BR"), ("Q-7K2M9P", "en")]
    assert scene.rendered_entries() == [
        ("human", Coded(code="audit.term_sheet_rendered", params={"locale": "pt-BR"})),
        ("agent", Coded(code="audit.term_sheet_rendered", params={"locale": "en"})),
    ]


@pytest.mark.req("R-10.1-2")
async def test_a_quote_of_another_workspace_is_not_found_and_nothing_is_touched(
    scene: Scene,
) -> None:
    with pytest.raises(NotFoundError):
        await scene.facade.render_term_sheets(browser("ws-other"), scene.quote.quote_id, "agent")
    with pytest.raises(NotFoundError):
        await scene.facade.render_term_sheets(browser("ws-rain"), QuoteId("Q-000000"), "agent")

    assert await scene.blobs.list("") == []
    assert scene.renderer.renders == []
    assert scene.rendered_entries() == []


@pytest.mark.req("R-10.1-2")
async def test_an_api_key_of_the_workspace_is_served(scene: Scene) -> None:
    references = await scene.facade.render_term_sheets(
        api_key("ws-rain"), scene.quote.quote_id, "api_client"
    )

    assert len(references) == 2
    assert await scene.blobs.list("") == [EN_PATH, PT_PATH]


@pytest.mark.req("R-8-6")
async def test_no_reference_exposes_a_bucket_or_a_storage_url(scene: Scene) -> None:
    references = await scene.facade.render_term_sheets(
        browser("ws-rain"), scene.quote.quote_id, "agent"
    )

    for reference in references:
        serialised = reference.model_dump_json()
        assert reference.path.startswith("/api/v1/quotes/Q-7K2M9P/")
        for forbidden in ("documents/", "ws-rain", "storage", "gs://", "http", "bucket"):
            assert forbidden not in serialised, forbidden


async def test_a_failed_audit_entry_does_not_fail_the_call_and_the_next_call_finds_the_file(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    scene = Scene(tmp_path, AuditFailsQuoting())
    principal = browser("ws-rain")

    with caplog.at_level(logging.ERROR):
        first = await scene.facade.render_term_sheets(principal, scene.quote.quote_id, "agent")
    second = await scene.facade.render_term_sheets(principal, scene.quote.quote_id, "agent")

    assert second == first
    assert len(first) == 2
    assert await scene.blobs.list("") == [EN_PATH, PT_PATH]
    assert len(scene.renderer.renders) == 2  # the second call rendered nothing
    assert scene.calls("append_audit") == 2  # ... and did not try the entries again
    assert len(caplog.records) == 2
    assert all("audit entry was not recorded" in record.getMessage() for record in caplog.records)
