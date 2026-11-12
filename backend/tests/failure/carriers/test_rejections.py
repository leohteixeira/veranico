"""Rejections by the carrier, seen from the API role: a 4xx cannot succeed on a retry, so
the round is abandoned at once and the queue is told to stop."""

from datetime import timedelta

import pytest

from tests.failure.carriers.conftest import Stack

pytestmark = [pytest.mark.failure, pytest.mark.integration, pytest.mark.req("R-7-6")]


@pytest.mark.req("R-7-7")
async def test_wrong_secret_gets_401_and_the_delivery_is_abandoned(stack: Stack) -> None:
    api = stack.api(secret="a-secret-the-carrier-does-not-share")
    event_id = stack.approved_event()

    response = await api.deliver(event_id, retry_count=0)

    assert response.status_code == 200  # the queue must not retry what cannot succeed
    assert response.json()["delivered"] is False
    assert response.json()["retryable"] is False
    (attempt,) = stack.quoting.delivery_attempts(event_id)
    assert (attempt.status_code, attempt.error_code) == (401, "http_error")
    assert stack.quoting.abandoned(event_id) is True
    quote = await stack.quote(event_id)
    assert quote.status == "approved"
    assert quote.submission is not None
    assert quote.submission.delivery.status == "abandoned"
    assert await stack.receipt_document(event_id) is None


@pytest.mark.req("R-7-8")
async def test_clock_301_seconds_behind_gets_400_and_the_delivery_is_abandoned(
    stack: Stack,
) -> None:
    api = stack.api(clock_behind=timedelta(seconds=301))
    event_id = stack.approved_event()

    response = await api.deliver(event_id, retry_count=0)

    assert response.status_code == 200
    assert response.json()["retryable"] is False
    (attempt,) = stack.quoting.delivery_attempts(event_id)
    assert (attempt.status_code, attempt.error_code) == (400, "http_error")
    assert stack.quoting.abandoned(event_id) is True
    assert await stack.receipt_document(event_id) is None


async def test_clock_300_seconds_behind_is_still_delivered(stack: Stack) -> None:
    api = stack.api(clock_behind=timedelta(seconds=300))
    event_id = stack.approved_event()

    response = await api.deliver(event_id, retry_count=0)

    assert response.status_code == 200
    assert response.json()["delivered"] is True


async def test_redelivery_round_after_abandonment_delivers(stack: Stack) -> None:
    event_id = stack.approved_event()
    misconfigured = stack.api(secret="a-secret-the-carrier-does-not-share")
    await misconfigured.deliver(event_id, retry_count=0)
    assert stack.quoting.abandoned(event_id) is True
    recorded = len(stack.quoting.delivery_attempts(event_id))

    # The secret is fixed and the delivery is enqueued again: a new round, whose base is
    # the highest attempt number already recorded.
    response = await stack.api().deliver(event_id, retry_count=0, base=recorded)

    assert response.status_code == 200
    assert response.json()["delivered"] is True
    assert response.json()["attempt"]["attempt"] == 2
    receipt_id = response.json()["attempt"]["receipt_id"]
    assert [a.attempt for a in stack.quoting.delivery_attempts(event_id)] == [1, 2]
    quote = await stack.quote(event_id)
    assert quote.status == "submitted"
    assert quote.submission is not None
    assert quote.submission.delivery.receipt_id == receipt_id
    document = await stack.receipt_document(event_id)
    assert document is not None
    assert document["receipt_id"] == receipt_id
