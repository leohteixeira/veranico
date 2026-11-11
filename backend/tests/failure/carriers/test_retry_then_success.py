import pytest

from tests.failure.carriers.conftest import StackFactory

pytestmark = [
    pytest.mark.failure,
    pytest.mark.integration,
    pytest.mark.req("R-16.3-3"),
    pytest.mark.req("R-7-10"),
]


async def test_carrier_answers_503_then_succeeds(stack_factory: StackFactory) -> None:
    stack = stack_factory(fail_first_attempt=True)
    api = stack.api()
    event_id = stack.approved_event()

    first = await api.deliver(event_id, retry_count=0)

    assert first.status_code == 503  # the queue will call again
    assert first.json()["delivered"] is False
    assert first.json()["retryable"] is True
    (attempt,) = stack.quoting.delivery_attempts(event_id)
    assert (attempt.attempt, attempt.error_code, attempt.status_code) == (1, "http_error", 503)
    assert attempt.receipt_id is None
    assert (await stack.quote(event_id)).status == "approved"
    assert stack.quoting.abandoned(event_id) is False

    second = await api.deliver(event_id, retry_count=1)

    assert second.status_code == 200
    assert second.json()["delivered"] is True
    receipt_id = second.json()["attempt"]["receipt_id"]
    assert receipt_id is not None
    attempts = stack.quoting.delivery_attempts(event_id)
    assert [a.attempt for a in attempts] == [1, 2]
    assert attempts[1].status_code == 200
    assert attempts[1].error_code is None
    assert attempts[1].receipt_id == receipt_id
    quote = await stack.quote(event_id)
    assert quote.status == "submitted"
    assert quote.submission is not None
    assert quote.submission.delivery.status == "delivered"
    assert quote.submission.delivery.attempts == 2
    assert quote.submission.delivery.receipt_id == receipt_id
    assert stack.quoting.abandoned(event_id) is False
    document = await stack.receipt_document(event_id)
    assert document is not None
    assert document["status"] == "received"
    assert document["receipt_id"] == receipt_id
