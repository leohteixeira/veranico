# 0013. Mock carrier as a second Cloud Run service from the same image

Status: Accepted (2026-11-10)

## Context

The original brief ran the mock carrier in process, as a function the API called directly. That proves nothing about webhook delivery: there is no network hop, no signature to verify on the other side and no way for the receiver to fail. The delivery path (ADR 0003) is one of the things the project is meant to show, so it needs a real receiver. Cost and maintenance still have to stay low.

## Decision

Governs SPEC sections 3 (roles), 7 (mock carrier), 11.4 and 17.

* One container image, two deployable roles: `APP_ROLE=api` (the product) and `APP_ROLE=carrier` (the mock carrier). Each role is its own Cloud Run service (min 0, max 2 instances).
* The carrier role exposes `POST /carrier/v1/submissions` and `GET /healthz`.
* It verifies the HMAC SHA-256 signature, rejects requests older than 5 minutes, deduplicates by event id (a replayed event returns the original receipt) and returns a receipt. Receipts are stored in `carriers_receipts`.
* In the demo it answers the first attempt of each event with 503, so the retry path is exercised and visible on every run. This is configurable and off by default in tests.
* In development the carrier role runs as its own Compose service on port 8510.

## Consequences

* Delivery crosses a real network hop, with real signature verification and real failure modes, on every demo run.
* No extra build and no idle cost: the image is the same and the service scales to zero.
* There is a second service to deploy, configure and secure: its own service account, its own settings, and the shared signing secret in both roles.
* `main.py` has to build two different applications from one codebase, and tests and Compose have to run both roles.
* The deliberate 503 makes every first delivery slower and adds a failed attempt to every audit trail in the demo. That is the intent: the Approvals panel shows it as delivery progress.

## Alternatives considered

* **In-process function call (the brief):** proves nothing about delivery.
* **A separate codebase for the carrier:** more to maintain.
