"""`OutboxDispatcher` over Cloud Tasks: one HTTP target task per delivery round.

Checked in the Cloud Tasks v2 reference and "Create HTTP target tasks" on 2026-11-11
(`google-cloud-tasks` 2.26.0):

* A task id may hold letters, digits, hyphens and underscores, up to 500 characters; an
  event id (UUID) fits. Creating a task under the name of an existing or recently finished
  task fails with `ALREADY_EXISTS`, and a finished task's name stays reserved for a time.
  The first round is therefore named after the event id, which makes `enqueue` idempotent,
  and a later round `<event_id>-r<round>`: a redelivery would otherwise be refused as a
  duplicate of the round it replaces.
* The queue calls the URL with an OIDC token of the given service account and audience,
  keeps custom headers, and sets `X-CloudTasks-TaskRetryCount` itself. Any answer outside
  2xx, or none before the dispatch deadline, is retried by the queue's retry policy.
* The dispatch deadline is a field of the task (15 seconds to 30 minutes).

There is no retry here: when the call fails the outbox record stays `pending` and the sweep
hands the event over again.
"""

from datetime import timedelta
from typing import Protocol

from google.api_core.exceptions import AlreadyExists
from google.cloud import tasks_v2

from veranico.modules.quoting.application.ports import OutboxStore
from veranico.modules.quoting.domain.outbox import OutboxRecord
from veranico.modules.quoting.infrastructure.deliver_call import ATTEMPT_BASE_HEADER, deliver_url
from veranico.shared.kernel.errors import NotFoundError
from veranico.shared.kernel.ids import EventId


class TaskCreator(Protocol):
    """The one call this adapter makes; `tasks_v2.CloudTasksAsyncClient` satisfies it."""

    async def create_task(self, request: tasks_v2.CreateTaskRequest) -> object: ...


def task_id(record: OutboxRecord) -> str:
    return record.event_id if record.round == 0 else f"{record.event_id}-r{record.round}"


class CloudTasksDispatcher:
    def __init__(
        self,
        *,
        client: TaskCreator,
        outbox: OutboxStore,
        project: str,
        location: str,
        queue: str,
        base_url: str,
        service_account_email: str,
        audience: str,
        dispatch_deadline_seconds: float,
    ) -> None:
        self._client = client
        self._outbox = outbox
        self._queue_path = f"projects/{project}/locations/{location}/queues/{queue}"
        self._base_url = base_url
        self._service_account_email = service_account_email
        self._audience = audience
        self._dispatch_deadline = timedelta(seconds=dispatch_deadline_seconds)

    async def enqueue(self, event_id: EventId) -> None:
        record = await self._outbox.get(event_id)
        if record is None:
            raise NotFoundError
        task = tasks_v2.Task(
            name=f"{self._queue_path}/tasks/{task_id(record)}",
            http_request=tasks_v2.HttpRequest(
                url=deliver_url(self._base_url, event_id),
                http_method=tasks_v2.HttpMethod.POST,
                headers={ATTEMPT_BASE_HEADER: str(record.attempt_base)},
                oidc_token=tasks_v2.OidcToken(
                    service_account_email=self._service_account_email,
                    audience=self._audience,
                ),
            ),
            dispatch_deadline=self._dispatch_deadline,
        )
        try:
            await self._client.create_task(
                request=tasks_v2.CreateTaskRequest(parent=self._queue_path, task=task)
            )
        except AlreadyExists:
            # This round's task is already in the queue or has finished: nothing to do.
            return
