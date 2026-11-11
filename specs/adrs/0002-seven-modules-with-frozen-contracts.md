# 0002. Seven business modules with layered folders and frozen contracts

Status: Accepted (2026-11-10)

## Context

The original brief organised the code by technical area (api, agent, tools, weather and so on). The build is done by agents working in parallel. That only works if the contracts between the parts are frozen before implementation starts and each agent can test against fakes built from those contracts.

## Decision

Governs SPEC section 3.

A modular monolith in Python: one FastAPI application, seven business modules with hard boundaries, shared infrastructure, one composition root.

| Module | May import the contracts of |
|---|---|
| `access` | none |
| `climate` | `access` |
| `pricing` | `climate` |
| `quoting` | `pricing`, `climate`, `access` |
| `carriers` | `quoting` |
| `documents` | `quoting`, `climate`, `access` |
| `assistant` | all of the above |

* A module's only public surface is `contracts.py` (facade `Protocol`, DTOs, integration events). `__init__.py` stays empty.
* Inside a module, folders are layered: `domain/`, `application/`, `infrastructure/`, `http/`, and `module.py` for wiring. Dependencies point inward.
* `bootstrap.py` is the only place that constructs modules and wires one module's facade into another.
* A port that would create a cycle is declared by the consumer and wired in `bootstrap.py` (`quoting` declares `CarrierCatalog`; `carriers` implements it).
* Each module owns its Firestore collections (prefix `<module>_`) and its Cloud Storage prefix (`<module>/`). No module reads another module's data.
* The rules are enforced by import-linter, the boundary script and architecture tests.
* The contracts are frozen in `docs/veranico/contracts.md` (workspace repository) and copied into each `contracts.py` in the foundation milestone. A contract changes only through an ADR that names every consumer, and the consumers change in the same commit.

## Consequences

* Each module can be built and tested alone against `backend/tests/fakes/`, so the modules can be written in parallel.
* More files and more ceremony than a codebase of this size would otherwise need.
* A contract change is slow on purpose: it needs an ADR and a coordinated change of every consumer.
* Data that spans modules is reached through facade calls, never by reading another module's collections.

## Alternatives considered

* **Packages by technical layer (the brief):** every change cuts across all packages and there is no boundary a tool can enforce.
* **Separate services:** operational cost with no benefit at this size.
