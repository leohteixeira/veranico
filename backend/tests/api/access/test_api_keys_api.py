from datetime import datetime, timedelta

import pytest

from tests.api.access.conftest import AccessApi

pytestmark = pytest.mark.integration

URL = "/api/v1/workspace/api-keys"


@pytest.mark.req("R-10-1", "R-10.1-1", "R-10.2-1", "R-11.2-8")
async def test_a_first_request_without_a_cookie_creates_a_workspace_and_returns_a_key(
    api: AccessApi,
) -> None:
    browser = api.browser()

    response = await browser.post(URL)

    assert response.status_code == 200, response.text
    set_cookie = response.headers["set-cookie"]
    assert set_cookie.startswith("vr_ws=v1.")
    assert "HttpOnly" in set_cookie
    body = response.json()
    assert set(body) == {"key_id", "secret", "expires_at"}
    assert body["secret"].startswith(f"vrk_{body['key_id']}_")
    assert datetime.fromisoformat(body["expires_at"]) == api.clock.now() + timedelta(days=14)


@pytest.mark.req("R-10.2-2", "R-11.2-8")
async def test_the_returned_secret_authenticates_into_the_browsers_workspace(
    api: AccessApi,
) -> None:
    browser = api.browser()

    body = (await browser.post(URL)).json()

    workspace, new_cookie = await api.facade.open_workspace(browser.cookies["vr_ws"])
    principal = await api.facade.authenticate_api_key(body["secret"])
    assert new_cookie is None
    assert principal.kind == "api_key"
    assert principal.key_id == body["key_id"]
    assert principal.workspace_id == workspace.workspace_id


@pytest.mark.req("R-10.2-1", "R-10.1-1")
async def test_a_second_key_of_the_same_browser_belongs_to_the_same_workspace(
    api: AccessApi,
) -> None:
    browser = api.browser()

    first = await browser.post(URL)
    second = await browser.post(URL)

    assert second.status_code == 200
    assert "set-cookie" not in second.headers  # the cookie it sent is still its workspace
    first_key, second_key = first.json(), second.json()
    assert first_key["key_id"] != second_key["key_id"]
    assert first_key["secret"] != second_key["secret"]
    first_principal = await api.facade.authenticate_api_key(first_key["secret"])
    second_principal = await api.facade.authenticate_api_key(second_key["secret"])
    assert first_principal.workspace_id == second_principal.workspace_id


@pytest.mark.req("R-10.2-1")
async def test_the_secret_is_shown_once_and_no_route_returns_it_again(api: AccessApi) -> None:
    browser = api.browser()
    await browser.post(URL)

    # The module has two routes, and neither lists keys.
    paths = {(method, path) for path, item in api.app.openapi()["paths"].items() for method in item}

    assert paths == {("post", URL), ("get", "/api/v1/allowance")}
