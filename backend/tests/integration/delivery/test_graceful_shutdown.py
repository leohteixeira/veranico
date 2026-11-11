"""Graceful shutdown, in process (SPEC 17, contracts sections 1 and 8).

On SIGTERM `main.py` sets the shutdown event of the container before the server waits for
open connections. Two things must follow: readiness turns non-200, and an open chat stream
ends with `error` (code `shutting_down`) then `done`, instead of a dropped connection.

The signal itself is covered where it is installed (`tests/api/test_lifecycle.py`), and the
container side by `infra/smoke/container_smoke.sh` (SIGTERM ends the process before the
grace period). Here the event is set directly, which is all the signal handler does.

The stream side is open until the assistant module (plan 06) lands: the test below is
expected to fail today and turns into a failure the day `POST /chat` streams, which is when
it is finished with a scripted model step that holds the turn open while the event is set.
"""

import json

import pytest

from tests.integration.delivery.conftest import Observed

pytestmark = pytest.mark.integration

CHAT = {"conversation_id": None, "message": "Coffee farm near Varginha", "locale": "en"}


def sse_events(body: str) -> list[tuple[str, dict[str, object]]]:
    """Parse `event: <name>\\ndata: <json>\\n\\n` blocks (contracts section 8)."""
    events = []
    for block in body.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in fields:
            events.append((fields["event"], json.loads(fields.get("data", "{}"))))
    return events


async def test_readiness_turns_503_once_the_shutdown_event_is_set(observed: Observed) -> None:
    ready = await observed.client.get("/readyz")

    observed.container.shutdown.set()
    after = await observed.client.get("/readyz")
    alive = await observed.client.get("/healthz")

    assert (ready.status_code, ready.json()) == (200, {"status": "ready"})
    assert (after.status_code, after.json()) == (503, {"status": "shutting_down"})
    assert alive.status_code == 200  # liveness is not readiness: the process still answers


# The identifier is only here: readiness alone does not prove the requirement.
@pytest.mark.req("R-17-6")
@pytest.mark.xfail(
    strict=True,
    reason=(
        "open: POST /chat does not stream yet (plan 06). When it does, this marker fails "
        "and is finished with a scripted step that holds the turn open during shutdown."
    ),
)
async def test_an_open_chat_stream_ends_with_shutting_down_then_done(observed: Observed) -> None:
    observed.container.shutdown.set()

    response = await observed.client.post("/api/v1/chat", json=CHAT)

    assert response.status_code == 200
    events = sse_events(response.text)
    assert [name for name, _ in events][-2:] == ["error", "done"]
    assert events[-2][1]["code"] == "shutting_down"
    assert events[-1][1]["stop_reason"] == "error"
