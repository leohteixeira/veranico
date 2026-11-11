# 0001. Firestore for transactional state, Cloud Storage for blobs

Status: Accepted (2026-11-10)

## Context

The original brief stored quotes as JSON objects in Cloud Storage. Three requirements need a write that is atomic across more than one record:

* Approval writes the state change, the audit entry and the `SubmissionApproved` outbox event together (SPEC section 6).
* Two people can decide on the same approval at the same time, and exactly one outcome must result.
* The idempotency key of `POST /quotes` needs an atomic create.

Cloud Storage has no multi-object transaction. Cost is a standing constraint from the owner ("it cannot get expensive"), and the demo has near-zero traffic.

## Decision

Governs SPEC section 14 and the transaction rule of section 6.

* **Firestore in Native mode** holds transactional state. Collections are prefixed by their owning module: `access_workspaces`, `access_api_keys`, `access_allowances`, `access_spend`, `quoting_quotes` (audit trail as an append-only subcollection), `quoting_idempotency`, `quoting_outbox`, `assistant_conversations` (messages as a subcollection), and `carriers_receipts` for the carrier role. Workspace-scoped documents carry `expires_at` for the TTL policy.
* **Cloud Storage** holds blobs: `climate/cubes/`, `climate/points/`, `documents/<workspace>/<quote>/`.
* Invariants live in code and transactions; there are no foreign keys. An architecture test checks that a module touches only the collections and prefixes it owns.
* Local development and tests use the Firestore emulator and a Cloud Storage emulator; the local filesystem adapters remain for the weather store.

## Consequences

* The decision, the audit entry and the outbox event commit together; concurrent decisions produce one outcome; the idempotency record is created atomically.
* Firestore scales to zero and has a free tier, so there is no always-on database instance to pay for. The free tier limits must be verified in official documentation.
* There are no relational queries or joins. Each module owns its collections, and any view that spans modules is composed in code through facades.
* Integration tests need the Firestore emulator. Its limits against the real service (transactions, TTL) must be verified in official documentation (SPEC section 21).
* Weather cubes and PDFs stay as blobs, so there are two stores to configure, secure and emulate.

## Alternatives considered

* **Cloud SQL for PostgreSQL:** bills for an always-on instance every month, for a demo with near-zero traffic.
* **Cloud Storage with generation preconditions:** protects one object at a time; there is no atomicity across objects.
* **SQLite on disk:** Cloud Run instances are stateless.
