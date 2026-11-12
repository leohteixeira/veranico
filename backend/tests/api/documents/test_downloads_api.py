"""`GET /quotes/{id}/term-sheet.pdf` and `GET /quotes/{id}/evidence.nc` (SPEC 8, 11.1, 11.2)."""

import pytest

from tests.api.documents.conftest import NETCDF, DocumentsApi, pdf_text
from tests.unit.documents import fixtures

pytestmark = pytest.mark.integration

TERM_SHEET = "/api/v1/quotes/Q-7K2M9P/term-sheet.pdf"
EVIDENCE = "/api/v1/quotes/Q-7K2M9P/evidence.nc"
PREMIUM = {"en": "Premium R$ 29,178.96", "pt-BR": "Prêmio R$ 29.178,96"}


@pytest.mark.req("R-11.1-3", "R-11.2-4", "R-8-1", "R-8-6")
async def test_the_term_sheet_route_answers_with_the_pdf_of_the_quote(api: DocumentsApi) -> None:
    visitor = await api.visitor()
    api.seed(fixtures.rainfall_quote(), visitor.workspace_id)

    response = await visitor.browser.get(TERM_SHEET, params={"lang": "en"})

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        'attachment; filename="veranico-Q-7K2M9P-term-sheet-en.pdf"'
    )
    assert response.content.startswith(b"%PDF-")
    assert PREMIUM["en"] in pdf_text(response.content)
    # Served by the API: the response points at no bucket and no storage address.
    assert api.bucket not in str(response.headers)
    assert "location" not in response.headers
    stored = await api.blobs.list("")
    assert stored == [f"documents/{visitor.workspace_id}/Q-7K2M9P/term-sheet.en.pdf"]


@pytest.mark.req("R-11.1-3", "R-13-3")
async def test_each_language_is_a_different_file(api: DocumentsApi) -> None:
    visitor = await api.visitor()
    api.seed(fixtures.rainfall_quote(), visitor.workspace_id)

    english = await visitor.browser.get(TERM_SHEET, params={"lang": "en"})
    portuguese = await visitor.browser.get(TERM_SHEET, params={"lang": "pt-BR"})

    assert english.status_code == portuguese.status_code == 200
    assert english.content != portuguese.content
    assert PREMIUM["pt-BR"] in pdf_text(portuguese.content)
    assert PREMIUM["pt-BR"] not in pdf_text(english.content)
    assert "term-sheet-pt-BR.pdf" in portuguese.headers["content-disposition"]


@pytest.mark.req("R-11.1-3", "R-13-3")
@pytest.mark.parametrize(
    ("accept_language", "locale"),
    [
        ("pt-BR,pt;q=0.9", "pt-BR"),
        ("pt-PT", "pt-BR"),
        ("en-GB,en;q=0.8", "en"),
        ("es-AR,es;q=0.9,pt;q=0.5", "pt-BR"),  # the first language the term sheet exists in
        ("es-ES,fr;q=0.8", "en"),  # none is supported
        (None, "en"),
    ],
)
async def test_without_lang_the_accept_language_header_selects_the_language(
    api: DocumentsApi, accept_language: str | None, locale: str
) -> None:
    visitor = await api.visitor()
    api.seed(fixtures.rainfall_quote(), visitor.workspace_id)
    headers = {"Accept-Language": accept_language} if accept_language is not None else {}

    response = await visitor.browser.get(TERM_SHEET, headers=headers)

    assert response.status_code == 200, response.text
    assert f"term-sheet-{locale}.pdf" in response.headers["content-disposition"]
    assert PREMIUM[locale] in pdf_text(response.content)


@pytest.mark.req("R-11.1-3")
async def test_lang_wins_over_the_accept_language_header(api: DocumentsApi) -> None:
    visitor = await api.visitor()
    api.seed(fixtures.rainfall_quote(), visitor.workspace_id)

    response = await visitor.browser.get(
        TERM_SHEET, params={"lang": "en"}, headers={"Accept-Language": "pt-BR"}
    )

    assert PREMIUM["en"] in pdf_text(response.content)


@pytest.mark.req("R-11.1-3")
@pytest.mark.parametrize("lang", ["es", "pt", "EN", ""])
async def test_an_unsupported_lang_is_invalid_arguments(api: DocumentsApi, lang: str) -> None:
    visitor = await api.visitor()
    api.seed(fixtures.rainfall_quote(), visitor.workspace_id)

    response = await visitor.browser.get(TERM_SHEET, params={"lang": lang})

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "invalid_arguments"
    assert await api.blobs.list("") == []


@pytest.mark.req("R-11.1-4", "R-11.2-4", "R-8-4", "R-8-6")
async def test_the_evidence_route_answers_with_the_netcdf_bytes(api: DocumentsApi) -> None:
    visitor = await api.visitor()
    api.seed(fixtures.rainfall_quote(), visitor.workspace_id)

    response = await visitor.browser.get(EVIDENCE)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/x-netcdf"
    assert response.headers["content-disposition"] == (
        'attachment; filename="veranico-Q-7K2M9P-evidence.nc"'
    )
    assert response.content == NETCDF
    assert api.bucket not in str(response.headers)
    (request,) = api.climate.evidence_requests
    assert (request.first_season, request.last_season) == (1950, 2024)
    assert request.attributes["quote_id"] == "Q-7K2M9P"


@pytest.mark.req("R-11.1-3", "R-11.1-4", "R-11.2-4")
async def test_both_routes_serve_the_cookie_session_and_an_api_key_of_the_workspace(
    api: DocumentsApi,
) -> None:
    visitor = await api.visitor()
    api.seed(fixtures.rainfall_quote(), visitor.workspace_id)

    by_cookie = await visitor.browser.get(TERM_SHEET, params={"lang": "pt-BR"})
    by_key = await visitor.api_key.get(TERM_SHEET, params={"lang": "pt-BR"})
    evidence_by_key = await visitor.api_key.get(EVIDENCE)
    evidence_by_cookie = await visitor.browser.get(EVIDENCE)

    assert by_cookie.status_code == by_key.status_code == 200
    assert by_key.content == by_cookie.content  # the stored file, not a second render
    assert evidence_by_key.status_code == evidence_by_cookie.status_code == 200
    assert evidence_by_key.content == evidence_by_cookie.content == NETCDF
    assert len(api.climate.evidence_requests) == 1


async def test_the_audit_actor_of_a_download_that_renders_follows_the_caller(
    api: DocumentsApi,
) -> None:
    visitor = await api.visitor()
    quote = api.seed(fixtures.rainfall_quote(), visitor.workspace_id)

    await visitor.browser.get(TERM_SHEET, params={"lang": "en"})
    await visitor.api_key.get(TERM_SHEET, params={"lang": "pt-BR"})
    await visitor.api_key.get(TERM_SHEET, params={"lang": "en"})  # stored already: no entry

    rendered = [
        (entry.actor, entry.action.params)
        for entry in api.quoting.audit_actions(quote.quote_id)
        if entry.action.code == "audit.term_sheet_rendered"
    ]
    assert rendered == [("human", {"locale": "en"}), ("api_client", {"locale": "pt-BR"})]
