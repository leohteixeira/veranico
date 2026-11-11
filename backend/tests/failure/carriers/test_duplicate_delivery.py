import pytest

from tests.failure.carriers.conftest import Stack

pytestmark = [
    pytest.mark.failure,
    pytest.mark.integration,
    pytest.mark.req("R-16.3-4"),
    pytest.mark.req("R-7-9"),
]


async def test_duplicate_delivery_returns_the_original_receipt(stack: Stack) -> None:
    api = stack.api()
    event_id = stack.approved_event()
    delivered = await api.deliver(event_id, retry_count=0)
    receipt_id = delivered.json()["attempt"]["receipt_id"]
    assert delivered.status_code == 200
    assert receipt_id is not None
    stored = await stack.receipt_document(event_id)
    quote_after_delivery = await stack.quote(event_id)

    # A queue that dispatches again after success: a new attempt number each time.
    second = await api.deliver(event_id, retry_count=1)
    third = await api.deliver(event_id, retry_count=2)

    for duplicate in (second, third):
        assert duplicate.status_code == 200
        assert duplicate.json()["delivered"] is True
        assert duplicate.json()["attempt"]["receipt_id"] == receipt_id
    assert [a.attempt for a in stack.quoting.delivery_attempts(event_id)] == [1, 2, 3]
    assert {a.receipt_id for a in stack.quoting.delivery_attempts(event_id)} == {receipt_id}
    # The carrier kept the original receipt, and the quote is where the first delivery left it.
    assert await stack.receipt_document(event_id) == stored
    quote = await stack.quote(event_id)
    assert quote.status == quote_after_delivery.status == "submitted"
    assert quote.submission is not None
    assert quote.submission.delivery.status == "delivered"
    assert quote.submission.delivery.receipt_id == receipt_id
    assert stack.quoting.abandoned(event_id) is False


async def test_same_attempt_number_sent_twice_is_recorded_once(stack: Stack) -> None:
    api = stack.api()
    event_id = stack.approved_event()
    first = await api.deliver(event_id, retry_count=0)
    audit_after_first = len((await stack.quote(event_id)).audit)

    # The same dispatch arriving twice (at-least-once execution): same retry count.
    again = await api.deliver(event_id, retry_count=0)

    assert again.status_code == 200
    assert again.json()["attempt"]["receipt_id"] == first.json()["attempt"]["receipt_id"]
    assert [a.attempt for a in stack.quoting.delivery_attempts(event_id)] == [1]
    assert len((await stack.quote(event_id)).audit) == audit_after_first
    assert (await stack.quote(event_id)).status == "submitted"
