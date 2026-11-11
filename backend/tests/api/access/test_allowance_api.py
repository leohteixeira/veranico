from datetime import datetime, timedelta

import pytest

from tests.api.access.conftest import ADDRESS, AccessApi

pytestmark = pytest.mark.integration

URL = "/api/v1/allowance"
CODE_HEADER = "Veranico-Allowance-Code"


def _next_midnight(api: AccessApi) -> datetime:
    return (api.clock.now() + timedelta(days=1)).replace(hour=0, minute=0, second=0)


@pytest.mark.req("R-10-1", "R-10.3-1", "R-11.2-12")
async def test_a_new_visitor_gets_the_default_allowance(api: AccessApi) -> None:
    browser = api.browser()

    response = await browser.get(URL)

    assert response.status_code == 200, response.text
    assert response.headers["set-cookie"].startswith("vr_ws=v1.")  # no gate: a workspace opens
    body = response.json()
    assert set(body) == {"conversations_left", "messages_left", "resets_at", "boosted"}
    assert (body["conversations_left"], body["messages_left"], body["boosted"]) == (2, 15, False)
    assert datetime.fromisoformat(body["resets_at"]) == _next_midnight(api)


@pytest.mark.req("R-10.3-1", "R-11.2-12")
async def test_the_allowance_is_reduced_after_admitted_messages(api: AccessApi) -> None:
    browser = api.browser()
    visitor = api.facade.visitor(ADDRESS, None)
    await api.facade.admit_message(visitor, new_conversation=True)
    await api.facade.admit_message(visitor, new_conversation=False)

    body = (await browser.get(URL)).json()
    again = (await browser.get(URL)).json()

    assert (body["conversations_left"], body["messages_left"]) == (1, 13)
    assert again == body  # reading it consumes nothing


@pytest.mark.req("R-10.3-1")
async def test_the_allowance_belongs_to_the_visitor_and_not_to_the_browser(api: AccessApi) -> None:
    visitor = api.facade.visitor(ADDRESS, None)
    await api.facade.admit_message(visitor, new_conversation=True)

    same_address = (await api.browser().get(URL)).json()  # a fresh browser, a new workspace
    other_address = (
        await api.browser().get(URL, headers={"X-Forwarded-For": "203.0.113.58"})
    ).json()
    spoofed = (
        await api.browser().get(URL, headers={"X-Forwarded-For": f"198.51.100.9, {ADDRESS}"})
    ).json()

    assert (same_address["conversations_left"], same_address["messages_left"]) == (1, 14)
    assert (other_address["conversations_left"], other_address["messages_left"]) == (2, 15)
    # An entry the client wrote before the platform's own does not make a new visitor.
    assert (spoofed["conversations_left"], spoofed["messages_left"]) == (1, 14)


@pytest.mark.req("R-10.3-2", "R-11.2-12")
async def test_the_boost_code_in_the_header_gives_the_larger_limits(api: AccessApi) -> None:
    browser = api.browser()

    body = (await browser.get(URL, headers={CODE_HEADER: api.allowance_code})).json()

    assert (body["conversations_left"], body["messages_left"], body["boosted"]) == (6, 60, True)


@pytest.mark.req("R-10.3-2")
@pytest.mark.parametrize("wrong", ["not-the-code", "x", None])
async def test_a_wrong_code_or_no_header_gives_the_default_limits(
    api: AccessApi, wrong: str | None
) -> None:
    browser = api.browser()
    headers = {CODE_HEADER: wrong} if wrong is not None else {}

    response = await browser.get(URL, headers=headers)

    assert response.status_code == 200  # the code is required for nothing
    body = response.json()
    assert (body["conversations_left"], body["messages_left"], body["boosted"]) == (2, 15, False)
