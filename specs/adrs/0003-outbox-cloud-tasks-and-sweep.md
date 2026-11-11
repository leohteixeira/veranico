# 0003. Outbox, Cloud Tasks and sweep for the carrier webhook

Status: Accepted (2026-11-10)

## Context

The original brief retried the carrier webhook in process. Cloud Run scales to zero and throttles CPU after the response is sent, so in-process retries and background tasks can die with the instance. A crash between the approval commit and the send would lose the webhook, leaving an approved quote that the carrier never receives.

## Decision

Governs SPEC section 7 and the internal endpoints of section 11.3.

* **Outbox:** the `SubmissionApproved` event is written to `quoting_outbox` in the same Firestore transaction as the decision and its audit entry (SPEC section 6).
* **Delivery:** the committed event is enqueued as a Cloud Tasks task named after the event id. Cloud Tasks calls the authenticated internal endpoint `POST /internal/outbox/{event_id}/deliver`, which performs one delivery attempt. A failed attempt returns an error so Cloud Tasks retries with backoff. The attempt, its status and its duration are appended to the audit trail.
* **Recovery:** an event that was committed but never enqueued is found and enqueued by `POST /internal/outbox/sweep`, called by a Cloud Scheduler job and opportunistically when the approvals queue is read.
* **Abandonment:** after the retry limit, the quote stays `approved` with a delivery-failed marker and the Approvals panel offers a manual redelivery (`POST /approvals/{id}/redeliver`).
* **Local and tests:** an in-process relay adapter polls the outbox and performs the same delivery call, so the path is restart-safe without Cloud Tasks.

## Consequences

* An approved submission cannot be lost between the commit and the send; the worst case is a delay.
* Delivery is at least once. The carrier must deduplicate by event id; the mock carrier returns the original receipt for a replayed event.
* An event recovered by the sweep waits for the next scheduled sweep or the next read of the approvals queue.
* There are two dispatchers to maintain behind the `OutboxDispatcher` port: the Cloud Tasks adapter and the in-process relay.
* More infrastructure: a queue with a retry policy, a scheduler job, and internal endpoints restricted to a service identity.
* Cloud Tasks HTTP targets with OIDC, task naming and Cloud Scheduler behaviour must be verified in official documentation before coding (SPEC section 21).

## Alternatives considered

* **In-process retries (the brief):** lost when the instance shuts down.
* **Pub/Sub push:** less direct control of backoff and of per-event deduplication by task name.
* **Polling only:** delivery latency is tied to the schedule.
