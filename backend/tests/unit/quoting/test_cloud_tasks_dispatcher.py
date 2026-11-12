import re
from datetime import timedelta

import pytest
from google.api_core.exceptions import AlreadyExists, ServiceUnavailable
from google.cloud import tasks_v2

from tests.unit.quoting.world import BROWSER, World
from veranico.modules.quoting.contracts import DeliveryAttempt
from veranico.modules.quoting.infrastructure.cloud_tasks_dispatcher import CloudTasksDispatcher
from veranico.shared.kernel.errors import NotFoundError
from veranico.shared.kernel.ids import EventId, new_event_id

pytestmark = pytest.mark.req("R-7-2")

QUEUE = "projects/veranico-test/locations/us-central1/queues/veranico-deliveries"
BASE_URL = "https://api.veranico.test"
INVOKER = "tasks-invoker@veranico-test.iam.gserviceaccount.com"
AUDIENCE = "https://api.veranico.test"


class MemoryTasks:
    """An in-memory queue: it keeps every request and refuses a name it already holds."""

    def __init__(self) -> None:
        self.requests: list[tasks_v2.CreateTaskRequest] = []
        self.failure: Exception | None = None

    async def create_task(self, request: tasks_v2.CreateTaskRequest) -> object:
        if self.failure is not None:
            raise self.failure
        if any(earlier.task.name == request.task.name for earlier in self.requests):
            raise AlreadyExists("task exists")
        self.requests.append(request)
        return request.task

    @property
    def names(self) -> list[str]:
        return [request.task.name.removeprefix(f"{QUEUE}/tasks/") for request in self.requests]


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def tasks() -> MemoryTasks:
    return MemoryTasks()


@pytest.fixture
def dispatcher(world: World, tasks: MemoryTasks) -> CloudTasksDispatcher:
    return CloudTasksDispatcher(
        client=tasks,
        outbox=world.outbox,
        project="veranico-test",
        location="us-central1",
        queue="veranico-deliveries",
        base_url=BASE_URL + "/",
        service_account_email=INVOKER,
        audience=AUDIENCE,
        dispatch_deadline_seconds=30.0,
    )


async def _approved_event(world: World) -> EventId:
    approval = await world.approved()
    return world.record_of(approval.quote_id).event_id


async def test_the_task_is_named_after_the_event_and_calls_the_deliver_route(
    world: World, tasks: MemoryTasks, dispatcher: CloudTasksDispatcher
) -> None:
    event_id = await _approved_event(world)

    await dispatcher.enqueue(event_id)

    (request,) = tasks.requests
    assert request.parent == QUEUE
    task = request.task
    assert task.name == f"{QUEUE}/tasks/{event_id}"
    call = task.http_request
    assert call.url == f"{BASE_URL}/api/v1/internal/outbox/{event_id}/deliver"
    assert call.http_method == tasks_v2.HttpMethod.POST
    assert call.body == b""
    assert dict(call.headers) == {"Veranico-Attempt-Base": "0"}
    assert call.oidc_token.service_account_email == INVOKER
    assert call.oidc_token.audience == AUDIENCE
    assert task.dispatch_deadline == timedelta(seconds=30)


async def test_enqueueing_the_same_round_again_is_a_success_and_creates_no_second_task(
    world: World, tasks: MemoryTasks, dispatcher: CloudTasksDispatcher
) -> None:
    event_id = await _approved_event(world)

    await dispatcher.enqueue(event_id)
    await dispatcher.enqueue(event_id)  # the queue answers ALREADY_EXISTS

    assert tasks.names == [event_id]


async def test_any_other_client_error_propagates(
    world: World, tasks: MemoryTasks, dispatcher: CloudTasksDispatcher
) -> None:
    event_id = await _approved_event(world)
    tasks.failure = ServiceUnavailable("queue unavailable")

    with pytest.raises(ServiceUnavailable):
        await dispatcher.enqueue(event_id)

    assert tasks.requests == []


async def test_an_unknown_event_is_not_found_and_creates_no_task(
    tasks: MemoryTasks, dispatcher: CloudTasksDispatcher
) -> None:
    with pytest.raises(NotFoundError):
        await dispatcher.enqueue(EventId("0190a8e0-0000-7000-8000-00000000dead"))

    assert tasks.requests == []


@pytest.mark.req("R-7-6")
async def test_each_redelivered_round_gets_its_own_task_name_and_the_attempt_base(
    world: World, tasks: MemoryTasks, dispatcher: CloudTasksDispatcher
) -> None:
    """A finished task's name stays reserved: a round named as the last would be refused."""
    approval = await world.approved()
    event_id = world.record_of(approval.quote_id).event_id
    await dispatcher.enqueue(event_id)

    # Round one fails twice and is abandoned; round two is never reached and is abandoned
    # with no attempt, so both redeliveries start from the same attempt base.
    for number in (1, 2):
        await world.service.record_delivery_attempt(
            DeliveryAttempt(
                event_id=event_id,
                attempt=number,
                status_code=503,
                error_code="delivery_failed",
                duration_ms=10,
                receipt_id=None,
            )
        )
    for _ in range(2):
        await world.service.record_delivery_abandoned(event_id)
        await world.service.redeliver(BROWSER, approval.approval_id)
        await dispatcher.enqueue(event_id)

    assert tasks.names == [event_id, f"{event_id}-r1", f"{event_id}-r2"]
    assert [dict(request.task.http_request.headers) for request in tasks.requests] == [
        {"Veranico-Attempt-Base": "0"},
        {"Veranico-Attempt-Base": "2"},
        {"Veranico-Attempt-Base": "2"},
    ]
    assert len({request.task.http_request.url for request in tasks.requests}) == 1


async def test_a_task_id_holds_only_the_characters_the_queue_allows(
    world: World, tasks: MemoryTasks, dispatcher: CloudTasksDispatcher
) -> None:
    approval = await world.approved()
    record = world.record_of(approval.quote_id)
    real_id = new_event_id()
    world.outbox.records[real_id] = type(record)(
        event=record.event.model_copy(update={"event_id": real_id}),
        quote_id=record.quote_id,
        status="pending",
        created_at=record.created_at,
        round=3,
    )

    await dispatcher.enqueue(real_id)

    assert re.fullmatch(r"[A-Za-z0-9_-]{1,500}", tasks.names[0])
    assert tasks.names[0] == f"{real_id}-r3"
