# Veranico

Parametric rainfall cover agent for Brazilian agriculture. A broker describes a farm's weather exposure in plain language; the agent loads decades of reanalysis data, backtests a trigger, prices the cover, drafts a term sheet and routes a submission that only a person can approve. The map shows basis risk: how the same cover behaves in the grid cells around the farm.

This is a portfolio project built to be read by evaluators. This file extends `/workspace/AGENTS.md`, which stays binding (pnpm only, no `CLAUDE.md`, English inside the repository, no automatic commits, no AI co-author trailers).

## Read first

| Document | What it decides |
|---|---|
| `docs/SPEC.md` | scope, behaviour, API, milestones. Source of truth |
| `specs/adrs/` | why each material decision was taken |
| `docs/architecture.html` | module map, flows and data ownership, with diagrams |
| `PRODUCT.md` and `.impeccable/surfaces/frontend-src-app-tsx.md` | product register and the Atlas design direction |
| `docs/verification.md` | requirement to test traceability and measured results |
| `/workspace/docs/veranico/goal.md` | the delivery contract: order of work and executable gates |
| `/workspace/docs/veranico/contracts.md` | the module contracts as frozen before implementation |

## Working rules

1. **Scope is locked.** Anything not in `docs/SPEC.md` goes to `docs/NEXT_STEPS.md`, not into code.
2. **Numbers come from tools.** The agent never computes, rounds into new values or invents figures. The interface renders figures from API responses and never recomputes them.
3. **Money is integer centavos.** Monetary values cross the `pricing` boundary as `Money` (integer BRL centavos, rounded half to even once). Rates are fixed-decimal strings with six places. No `float` for money anywhere outside `pricing/domain` internals, and never in JSON.
4. **Module boundaries are hard.** A module's only public surface is `contracts.py`. Import another module only through its contracts, and only along the table in section 3.1 of the spec. `bootstrap.py` is the only composition root.
5. **Contracts are frozen.** Changing a `contracts.py`, a wire schema or a collection owner needs an ADR that names every consumer, and the consumers change in the same commit.
6. **Verify external APIs in official documentation** before using them (the list is section 21 of the spec). Do not rely on memory for parameter names, endpoints, defaults, model identifiers or prices.
7. **A milestone ends green.** Do not start a milestone while the previous gate (`make verify-m<N>`) fails. Never weaken a test, a linter rule, a type check or a threshold to pass a gate.
8. **Report evidence honestly.** A gate that needs a missing account (Copernicus CDS, Google Cloud) is reported as open, never as passed. Every measured result in `docs/verification.md` names its commit.
9. **Small explicit code over frameworks.** The agent loop is hand-written on the Anthropic Messages API so failure handling is visible. Add a dependency, abstraction, retry or state only for a failure or requirement you can name.
10. **Tests use fakes built from contracts**, not mocks (`backend/tests/fakes/`). Integration tests run against the Firestore and Cloud Storage emulators. Every source of randomness is seeded.
11. **No secrets** in code, fixtures, logs, spans or commits. Never log raw IP addresses, message text or tool payloads. Agents do not read, search or modify `.env` or `.env.*` files. The variables are documented in `env.example` (no leading dot, so the ignore rule does not hide it from agents); it holds names and safe defaults only.
12. **Licences are part of the design.** Every data and tile source shows its required attribution in the interface and the README. The code is MIT; the demo is non-commercial because of the Sentinel-2 cloudless licence.
13. **Text for people crosses boundaries as a code plus parameters.** Only presentation layers (HTTP problem mapper, term sheet, frontend) hold translated prose, in English and Brazilian Portuguese.

## Architecture in one screen

```text
backend/src/veranico/
  main.py            builds the FastAPI app for APP_ROLE=api or APP_ROLE=carrier
  bootstrap.py       composition root: constructs modules, wires facades and ports
  shared/
    kernel/          identifiers, Money, Rate, Principal, Coded, DomainError, Clock
    infrastructure/  settings, Firestore and Cloud Storage clients, telemetry, problem mapper
  modules/<name>/
    contracts.py     facade Protocol, DTOs, integration events (the only public surface)
    domain/          pure rules: standard library, shared kernel, NumPy and SciPy where the maths needs them; no I/O
    application/     use cases; depends on domain and on other modules' contracts
    infrastructure/  adapters: Firestore, Cloud Storage, HTTP clients, SDKs
    http/            routers and request mapping
    module.py        builds the module and returns its facade
```

Modules: `access`, `climate`, `pricing`, `quoting`, `carriers`, `documents`, `assistant`. Each owns its Firestore collections (prefix `<module>_`) and its Cloud Storage prefix (`<module>/`). Integration events leave a module through an outbox document written in the same transaction as the state change.

Skills to read before backend work: `python-modular-monolith` (structure and validation; if it is not listed as a skill in the session, read `/workspace/.claude/skills/python-modular-monolith/SKILL.md` directly) and `evolutionary-modular-architecture` (boundaries, outbox, resilience). Before any Anthropic SDK code: `claude-api`.

## Stack

| Area | Choice |
|---|---|
| Backend | Python 3.12 managed by uv, FastAPI, Pydantic v2, anthropic SDK, httpx |
| Data | xarray, zarr, h5netcdf, cdsapi (offline cube build only), h3, NumPy, SciPy |
| State | Firestore in Native mode; Cloud Storage for cubes, points and documents |
| Async delivery | transactional outbox, Cloud Tasks, Cloud Scheduler sweep; in-process relay in development |
| Documents | reportlab |
| Agent evaluation | Inspect (`inspect_ai`); read https://inspect.aisi.org.uk/llms.txt before writing tasks |
| Observability | OpenTelemetry; Jaeger in development, Cloud Trace in production |
| Frontend | React, TypeScript strict, Vite, TanStack Query, Leaflet with react-leaflet, Recharts; pnpm |
| API client | OpenAPI from FastAPI; typed client from openapi-typescript and openapi-fetch |
| Quality | ruff, mypy strict, import-linter, pytest, Vitest, Testing Library, Playwright, k6, gitleaks, lefthook |
| Infrastructure | Docker, Terraform (Google provider), Cloud Run, Artifact Registry, Secret Manager, `us-central1` |
| CI/CD | GitHub Actions pinned by commit SHA, Workload Identity Federation, no JSON keys |

## Commands

Everything goes through the `Makefile`, so people and CI run the same thing.

| Command | Does |
|---|---|
| `make dev` | the whole stack locally: API, carrier role, Vite, Firestore and Cloud Storage emulators, Jaeger. Needs no `.env` and no key: without `ANTHROPIC_API_KEY` the agent runs on the scripted model client |
| `make test` | backend unit and architecture tests; frontend unit tests and type check |
| `make test-integration` | API and persistence tests against the emulators |
| `make test-failure` | failure campaign (section 16.3 of the spec), with the fault proxy |
| `make lint` / `make fmt` | ruff, mypy, import-linter, boundary script, eslint / ruff format, prettier |
| `make gen-client` | export OpenAPI and regenerate the typed client; CI fails on drift |
| `make ingest LAT=.. LON=..` | fetch and cache point history from Open-Meteo |
| `make build-cube REGION=..` | download ERA5-Land from the CDS and build the regional cube (needs `CDS_API_KEY`) |
| `make mutation-proof` | apply the mutation catalogue to `pricing/domain` and assert the tests fail |
| `make evals` | Inspect suite against fixture cubes (needs `ANTHROPIC_API_KEY`) |
| `make load` | k6 against the local stack, then the Firestore oracle |
| `make evidence` | regenerate the measured sections of `docs/verification.md` for the current commit |
| `make verify-m0` … `make verify-m6` | the executable gate of each milestone |

Ports: web 3500, API 8500, carrier 8510, Jaeger UI 8516, Firestore emulator 8580, Cloud Storage emulator 8590; fault proxy 8520 and 8521 during the failure campaign. Bind development servers to `0.0.0.0`.

## Conventions

* Python: ruff for lint and format, mypy strict on `src/`, pytest with `asyncio_mode = auto`. Pydantic models for every tool input and output and every HTTP body. Timezone-aware UTC datetimes through the `Clock` port.
* Frontend: no `any`. API types come only from the generated client. Components stay presentational; data fetching lives in hooks. All visible text goes through the i18n catalogue.
* Errors: raise `DomainError` subclasses with a stable `code`; HTTP answers are RFC 9457 problem documents; tools return a `ToolError`.
* ADRs: `specs/adrs/NNNN-short-title.md` with Status, Context, Decision, Consequences. Keep them under a page.
* Commits: Conventional Commits in English, scoped by module (`feat(pricing): …`). Commit only when the user asks.

## Interface work

The design direction is recorded and binding: Atlas (real relief and satellite basemaps, the risk as a continuous surface, floating cards). Before changing any interface file, load the `impeccable-v2` skill and read `.impeccable/surfaces/frontend-src-app-tsx.md`. The interface is not finished until Impeccable's finish review has run, its verdict is recorded and `DESIGN.md` exists. A schematic grid of flat squares on a blank ground was rejected by the owner; do not return to it.

## Prerequisites

| Account | Used for | Status on 2026-11-10 |
|---|---|---|
| Anthropic Console | `ANTHROPIC_API_KEY` for the agent and the evaluation suite | available |
| Copernicus Climate Data Store | `CDS_API_KEY` for the offline cube build; never reaches the running service | missing |
| Google Cloud project with billing | deployment | missing |

Everything else (Open-Meteo, EOX tiles, emulators, Inspect, libraries) needs no account.

## Layout

```text
veranico/
  AGENTS.md  README.md  PRODUCT.md  DESIGN.md  Makefile  Dockerfile  compose.yaml  lefthook.yml
  docs/            SPEC.md, NEXT_STEPS.md, verification.md, architecture.html
  specs/adrs/
  backend/
    pyproject.toml  uv.lock
    src/veranico/  (see above)
    scripts/       validate_boundaries.py, export_openapi.py, traceability.py, mutation_proof.py,
                   ingest.py, build_cube.py, price_demo.py
    tests/
      unit/  integration/  api/  architecture/  failure/  fakes/
      evals/       veranico_eval.py, cases.yaml, fixtures/
  frontend/        pnpm project: src/, e2e/
  load/            k6 scripts and the Firestore oracle
  infra/terraform/
  .github/workflows/   ci.yml, evals.yml, load.yml, deploy.yml
```
