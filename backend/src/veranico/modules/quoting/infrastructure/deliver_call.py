"""The call both dispatchers end in: `POST /api/v1/internal/outbox/{event_id}/deliver`.

No body. The deliver route (owned by `carriers`) numbers the attempt from two headers:
`attempt = base + retry count + 1`.
"""

from veranico.shared.kernel.ids import EventId

# Set by the dispatcher: the highest attempt number recorded before this delivery round.
ATTEMPT_BASE_HEADER = "Veranico-Attempt-Base"
# Set by Cloud Tasks on every dispatch (0 for the first); the relay sets it itself.
RETRY_COUNT_HEADER = "X-CloudTasks-TaskRetryCount"


def deliver_url(base_url: str, event_id: EventId) -> str:
    return f"{base_url.rstrip('/')}/api/v1/internal/outbox/{event_id}/deliver"
