import pytest

from tests.api.carriers.conftest import (
    ATTEMPT_LIMIT,
    REJECTED,
    UNAVAILABLE,
    ApiFactory,
    DeliverApi,
)
from veranico.modules.carriers.http.router import ATTEMPT_BASE_HEADER, RETRY_COUNT_HEADER

pytestmark = [pytest.mark.req("R-7-3"), pytest.mark.req("R-11.3-1")]

INTERNAL_TOKEN = "route-test-internal-token"


def _headers(*, retry_count: int | None = None, base: int | None = None) -> dict[str, str]:
    headers = {}
    if retry_count is not None:
        headers[RETRY_COUNT_HEADER] = str(retry_count)
    if base is not None:
        headers[ATTEMPT_BASE_HEADER] = str(base)
    return headers


def test_header_names_are_the_ones_the_queue_and_the_relay_send() -> None:
    # Cloud Tasks sets the first on every dispatch; plan 03's dispatchers set the second.
    assert RETRY_COUNT_HEADER == "X-CloudTasks-TaskRetryCount"
    assert ATTEMPT_BASE_HEADER == "Veranico-Attempt-Base"


async def test_without_a_service_identity_the_route_is_forbidden_and_sends_nothing(
    api_factory: ApiFactory,
) -> None:
    api = api_factory(internal_auth="token", internal_token=INTERNAL_TOKEN)

    missing = await api.deliver()
    wrong = await api.deliver(headers={"Authorization": "Bearer another-token"})

    for response in (missing, wrong):
        assert response.status_code == 403
        assert response.json()["code"] == "forbidden"
    assert api.sender.requests == []
    assert api.quoting.delivery_attempts(api.event_id) == []


async def test_with_the_service_identity_the_route_delivers(api_factory: ApiFactory) -> None:
    api = api_factory(internal_auth="token", internal_token=INTERNAL_TOKEN)

    response = await api.deliver(headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"})

    assert response.status_code == 200
    assert len(api.sender.requests) == 1


async def test_delivered_attempt_answers_200_with_the_outcome(api: DeliverApi) -> None:
    response = await api.deliver(headers=_headers(retry_count=0))

    assert response.status_code == 200
    outcome = response.json()
    assert outcome["delivered"] is True
    assert outcome["retryable"] is False
    assert outcome["attempt"]["event_id"] == api.event_id
    assert outcome["attempt"]["attempt"] == 1
    assert outcome["attempt"]["status_code"] == 200
    assert outcome["attempt"]["receipt_id"] == "R-7K2M9X"
    assert api.abandon_calls() == 0


async def test_first_dispatch_without_a_base_header_is_attempt_1(api: DeliverApi) -> None:
    await api.deliver(headers=_headers(retry_count=0))

    assert [a.attempt for a in api.quoting.delivery_attempts(api.event_id)] == [1]


async def test_a_call_without_either_header_is_attempt_1(api: DeliverApi) -> None:
    await api.deliver()

    assert [a.attempt for a in api.quoting.delivery_attempts(api.event_id)] == [1]


async def test_attempt_number_is_base_plus_retry_count_plus_one(api: DeliverApi) -> None:
    await api.deliver(headers=_headers(base=4, retry_count=2))

    assert [a.attempt for a in api.quoting.delivery_attempts(api.event_id)] == [7]


async def test_retryable_failure_below_the_limit_answers_503_and_does_not_abandon(
    api: DeliverApi,
) -> None:
    api.sender.script(UNAVAILABLE)

    response = await api.deliver(headers=_headers(retry_count=ATTEMPT_LIMIT - 2))

    assert response.status_code == 503
    outcome = response.json()
    assert outcome["delivered"] is False
    assert outcome["retryable"] is True
    assert outcome["attempt"]["error_code"] == "http_error"
    assert outcome["attempt"]["status_code"] == 503
    assert api.abandon_calls() == 0
    assert api.quoting.abandoned(api.event_id) is False


@pytest.mark.req("R-7-6")
async def test_retryable_failure_on_the_last_attempt_of_the_round_abandons_once(
    api: DeliverApi,
) -> None:
    api.sender.script(UNAVAILABLE)

    response = await api.deliver(headers=_headers(retry_count=ATTEMPT_LIMIT - 1))

    assert response.status_code == 200
    assert response.json()["delivered"] is False
    assert response.json()["retryable"] is True
    assert api.abandon_calls() == 1
    assert api.quoting.abandoned(api.event_id) is True


@pytest.mark.req("R-7-6")
@pytest.mark.parametrize("retry_count", [0, 1, ATTEMPT_LIMIT - 1, ATTEMPT_LIMIT + 5])
async def test_non_retryable_failure_abandons_once_at_any_retry_count(
    api: DeliverApi, retry_count: int
) -> None:
    api.sender.script(REJECTED)

    response = await api.deliver(headers=_headers(retry_count=retry_count))

    assert response.status_code == 200
    assert response.json()["delivered"] is False
    assert response.json()["retryable"] is False
    assert api.abandon_calls() == 1
    assert api.quoting.abandoned(api.event_id) is True


@pytest.mark.req("R-7-6")
async def test_first_attempt_of_a_redelivery_round_is_not_abandoned(api: DeliverApi) -> None:
    # The absolute attempt number (5) is past the limit; the position in the round is not.
    api.sender.script(UNAVAILABLE)

    response = await api.deliver(headers=_headers(base=4, retry_count=0))

    assert response.status_code == 503
    assert [a.attempt for a in api.quoting.delivery_attempts(api.event_id)] == [5]
    assert api.abandon_calls() == 0


@pytest.mark.req("R-7-6")
async def test_a_failing_call_past_the_limit_still_answers_200(api: DeliverApi) -> None:
    # The queue counts dispatches that never reached this route and may keep calling after
    # the round was abandoned: the application stops at its own limit.
    api.sender.script(UNAVAILABLE, UNAVAILABLE)
    await api.deliver(headers=_headers(retry_count=ATTEMPT_LIMIT - 1))

    response = await api.deliver(headers=_headers(retry_count=ATTEMPT_LIMIT + 4))

    assert response.status_code == 200
    assert response.json()["delivered"] is False
    assert api.quoting.abandoned(api.event_id) is True


@pytest.mark.req("R-7-6")
async def test_a_call_past_the_limit_that_succeeds_delivers(api: DeliverApi) -> None:
    api.sender.script(UNAVAILABLE)
    await api.deliver(headers=_headers(retry_count=ATTEMPT_LIMIT - 1))

    response = await api.deliver(headers=_headers(retry_count=ATTEMPT_LIMIT))

    assert response.status_code == 200
    assert response.json()["delivered"] is True
    assert response.json()["attempt"]["attempt"] == ATTEMPT_LIMIT + 1


@pytest.mark.parametrize(
    "headers",
    [
        {RETRY_COUNT_HEADER: "soon"},
        {RETRY_COUNT_HEADER: "-1"},
        {RETRY_COUNT_HEADER: "1.5"},
        {ATTEMPT_BASE_HEADER: "many"},
        {ATTEMPT_BASE_HEADER: "-2"},
        {ATTEMPT_BASE_HEADER: ""},
    ],
)
async def test_malformed_header_is_invalid_arguments_and_sends_nothing(
    api: DeliverApi, headers: dict[str, str]
) -> None:
    response = await api.deliver(headers=headers)

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_arguments"
    assert api.sender.requests == []
    assert api.quoting.delivery_attempts(api.event_id) == []


async def test_unknown_event_id_is_not_found(api: DeliverApi) -> None:
    response = await api.deliver(event_id="no-such-event")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
    assert api.sender.requests == []
