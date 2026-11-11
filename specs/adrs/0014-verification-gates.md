# 0014. Verification gates: traceability, failure tests, mutation proof, load with an oracle

Status: Accepted (2026-11-10)

## Context

The original brief verified the project with tests and the agent evaluation. The owner asked for the same rigour as a reference project of theirs: beyond those two, a traceability matrix, failure tests with injected faults, a mutation proof and a load run checked by an oracle. The project is meant to be read by evaluators, so the evidence has to be explainable and reproducible, and the checks have to stay fast enough to run on every push.

## Decision

Governs SPEC section 16.

* **Deterministic and architecture tests** (16.1, 16.2) and the **agent evaluation** with Inspect (16.6: 3 epochs per case, the suite fails below a 90% overall pass rate) remain.
* **Traceability** (16.8): `docs/verification.md` holds a matrix from each requirement in the spec to a test. Every result names the commit it was measured on. Results from different runs are never summed.
* **Failure tests** (16.3): the listed faults, including a crash between the approval commit and the enqueue, concurrent decisions, concurrent `POST /quotes` with the same key, the model API failing mid-turn, and network faults on the webhook path injected with a fault proxy.
* **Mutation proof** (16.4): a catalogue of at least 15 named, hand-written mutations of `pricing/domain`. A script applies each one and asserts that the unit tests fail. The catalogue and its last result are part of the verification record.
* **Load with an oracle** (16.5): k6 against the local stack, never production, on `POST /quotes` with repeated idempotency keys and on the per-cell metrics endpoint. Afterwards an oracle script reads Firestore and asserts one quote per distinct key, no duplicates, every acknowledged quote exists, and the latency thresholds hold.
* **Baseline gates** (16.9) apply to every change.

## Consequences

* Each claim in the README can be followed to a test and a measured result on a named commit.
* More CI time: the mutation proof runs in `ci.yml` on every push.
* More test infrastructure to maintain: the requirements file and markers, the fault proxy, the mutation catalogue and its script, the k6 scripts and the oracle.
* The mutation proof covers only the mutants someone wrote down. It is evidence about those named faults, not a mutation score for the module.
* Load results describe the local stack. They say nothing about the deployed service.

## Alternatives considered

* **Tests and evaluation only (the brief):** does not meet the rigour the owner asked for.
* **A mutation testing framework:** a slower run and a result that is harder to explain than a short catalogue of named mutants.
