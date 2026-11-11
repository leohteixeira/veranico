"""Nothing sensitive leaves the service in a span or a log line (SPEC 15).

Unique sentinel strings travel in every place a secret, an address or a visitor's text can
enter the API role: the chat message, a place name inside a request body, the API key, the
workspace cookie, the allowance code, the forwarded client address, a query string and a
path. After the requests, no sentinel may appear in any exported span (attributes, events,
status, resource) or in any log line as the service formats it.

The requests go through the real application. While a route is still a stub the sentinel
stops at the HTTP edge, so today this proves the edge (the request span, authentication,
the problem mapper, validation) and the modules that are real. It keeps running unchanged
as modules land, and then covers them: the chat turn with its tool arguments (plan 06) is
the part that waits.
"""

import httpx
import pytest

from tests.integration.delivery.conftest import CLIENT_ADDRESS, Observed

pytestmark = [pytest.mark.integration, pytest.mark.req("R-15-5")]

MESSAGE = "sentinel-message-4c1d9e"
PLACE = "sentinel-place-8a2f07"
API_KEY = "sentinel-apikey-e55b31"
COOKIE = "sentinel-cookie-0d7c64"
CODE = "sentinel-code-b93a12"
QUERY = "sentinel-query-61fe40"
PATH = "sentinel-path-2e8d5b"
FORWARDED = "198.51.100.23"  # TEST-NET-2: the address the proxy would report

SENTINELS = (MESSAGE, PLACE, API_KEY, COOKIE, CODE, QUERY, PATH, FORWARDED, CLIENT_ADDRESS)

COVER = {
    "index": {
        "index_type": "rainfall_below",
        "window": {"start": "09-01", "end": "10-31"},
        "trigger": 100.0,
        "exit": 20.0,
    },
    "limit": {"amount_cents": 30_000_000, "currency": "BRL"},
}


async def _send_everything(client: httpx.AsyncClient) -> list[httpx.Response]:
    edge = {"X-Forwarded-For": f"10.0.0.1, {FORWARDED}"}
    browser = {**edge, "Cookie": f"vr_ws={COOKIE}", "Veranico-Allowance-Code": CODE}
    key = {**edge, "Authorization": f"Bearer {API_KEY}"}
    return [
        # The chat message, with and without a valid body.
        await client.post(
            "/api/v1/chat",
            headers=browser,
            json={"conversation_id": None, "message": f"quote for {MESSAGE}", "locale": "en"},
        ),
        await client.post(
            "/api/v1/chat",
            headers=browser,
            json={"conversation_id": None, "message": MESSAGE, "locale": PLACE},
        ),
        await client.get("/api/v1/allowance", headers=browser),
        await client.get(f"/api/v1/conversations/{PATH}", headers=browser),
        # The public API: a key that does not exist, a label typed by a person.
        await client.post(
            "/api/v1/quotes",
            headers={**key, "Idempotency-Key": QUERY},
            json={"location": {"lat": -21.5, "lon": -45.4, "label": PLACE}, "cover": COVER},
        ),
        await client.get(f"/api/v1/quotes/{PATH}", headers=key),
        # Public reference data: a path value, a query value and an invalid query.
        await client.get(f"/api/v1/regions/{PATH}/cells", params={"metric": QUERY}, headers=edge),
        await client.get("/api/v1/regions", params={"q": QUERY}, headers=edge),
        # No route at all.
        await client.get(f"/{PATH}/missing", params={"q": QUERY}, headers=browser),
    ]


async def test_no_sentinel_reaches_a_span(observed: Observed) -> None:
    responses = await _send_everything(observed.client)

    assert len(observed.spans) >= len(responses)
    for span in observed.spans:
        exported = span.to_json()
        for sentinel in SENTINELS:
            assert sentinel not in exported, f"{sentinel} in span {span.name}"


async def test_no_sentinel_reaches_a_log_line(observed: Observed) -> None:
    await _send_everything(observed.client)

    for line in observed.log_lines:
        for sentinel in SENTINELS:
            assert sentinel not in line, f"{sentinel} in a log line of the service"


async def test_no_secret_of_the_settings_reaches_a_span_or_a_log_line(observed: Observed) -> None:
    settings = observed.settings
    secrets = [
        secret.get_secret_value()
        for secret in (
            settings.cookie_signing_secret,
            settings.access.ip_hash_salt,
            settings.access.allowance_code,
            settings.delivery.webhook_signing_secret,
        )
        if secret is not None
    ]

    await _send_everything(observed.client)

    everything = [span.to_json() for span in observed.spans] + observed.log_lines
    assert len(secrets) == 4
    for text in everything:
        for secret in secrets:
            assert secret not in text


async def test_a_problem_document_does_not_echo_what_was_sent(observed: Observed) -> None:
    """The answer is not a span or a log, but it is stored by clients and proxies alike."""
    responses = await _send_everything(observed.client)

    for response in responses:
        if response.headers.get("content-type") != "application/problem+json":
            continue
        for sentinel in (MESSAGE, API_KEY, COOKIE, CODE, FORWARDED, CLIENT_ADDRESS):
            assert sentinel not in response.text, f"{sentinel} in {response.request.url.path}"
