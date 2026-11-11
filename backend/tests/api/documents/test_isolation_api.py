"""Workspace isolation of the two downloads (SPEC 10.1): another workspace sees `not_found`."""

import httpx
import pytest

from tests.api.documents.conftest import DocumentsApi
from tests.unit.documents import fixtures

pytestmark = pytest.mark.integration

ROUTES = ("/api/v1/quotes/Q-7K2M9P/term-sheet.pdf", "/api/v1/quotes/Q-7K2M9P/evidence.nc")


def assert_not_found(response: httpx.Response) -> None:
    assert response.status_code == 404, response.text
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "not_found"
    assert body["status"] == 404
    assert body["type"] == "https://veranico.dev/problems/not_found"
    assert "content-disposition" not in response.headers


@pytest.mark.req("R-10.1-2", "R-11.2-4")
@pytest.mark.parametrize("route", ROUTES)
async def test_a_second_workspace_gets_not_found_by_cookie_and_by_api_key(
    api: DocumentsApi, route: str
) -> None:
    owner = await api.visitor()
    other = await api.visitor()
    api.seed(fixtures.rainfall_quote(), owner.workspace_id)
    assert other.workspace_id != owner.workspace_id

    assert_not_found(await other.browser.get(route))
    assert_not_found(await other.api_key.get(route))

    # Nothing was rendered, exported or stored for the caller that does not own the quote.
    assert await api.blobs.list("") == []
    assert api.climate.evidence_requests == []


@pytest.mark.req("R-10.1-2")
@pytest.mark.parametrize("route", ROUTES)
async def test_a_stored_document_stays_invisible_to_another_workspace(
    api: DocumentsApi, route: str
) -> None:
    owner = await api.visitor()
    other = await api.visitor()
    api.seed(fixtures.rainfall_quote(), owner.workspace_id)
    owned = await owner.browser.get(route)
    assert owned.status_code == 200

    assert_not_found(await other.browser.get(route))
    assert_not_found(await other.api_key.get(route))

    stored = await api.blobs.list("")
    assert len(stored) == 1
    assert stored[0].startswith(f"documents/{owner.workspace_id}/Q-7K2M9P/")


@pytest.mark.req("R-10.1-2")
@pytest.mark.parametrize("route", ROUTES)
async def test_a_request_without_a_session_owns_nothing(api: DocumentsApi, route: str) -> None:
    owner = await api.visitor()
    api.seed(fixtures.rainfall_quote(), owner.workspace_id)

    async with api.client() as anonymous:  # no cookie: a new, empty workspace is opened
        assert_not_found(await anonymous.get(route))


@pytest.mark.parametrize(
    "route", ["/api/v1/quotes/Q-000000/term-sheet.pdf", "/api/v1/quotes/Q-000000/evidence.nc"]
)
async def test_an_unknown_quote_is_not_found(api: DocumentsApi, route: str) -> None:
    visitor = await api.visitor()
    api.seed(fixtures.rainfall_quote(), visitor.workspace_id)

    assert_not_found(await visitor.browser.get(route))
    assert_not_found(await visitor.api_key.get(route))


async def test_an_invalid_api_key_is_refused(api: DocumentsApi) -> None:
    owner = await api.visitor()
    api.seed(fixtures.rainfall_quote(), owner.workspace_id)

    async with api.client(headers={"Authorization": "Bearer not-a-key"}) as stranger:
        response = await stranger.get(ROUTES[0])

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
