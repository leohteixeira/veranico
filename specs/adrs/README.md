# Architecture decision records

Each record states why a material decision was taken. `docs/SPEC.md` holds what was decided; section 22 of the spec lists every change from the original brief with its ADR. Format: Status, Context, Decision, Consequences, Alternatives considered; under one page.

| # | Title | Status | Decision |
|---|---|---|---|
| [0001](0001-firestore-for-state-cloud-storage-for-blobs.md) | Firestore for transactional state, Cloud Storage for blobs | Accepted | Firestore in Native mode holds transactional state in module-owned collections; Cloud Storage holds cubes, points and documents. |
| [0002](0002-seven-modules-with-frozen-contracts.md) | Seven business modules with layered folders and frozen contracts | Accepted | A modular monolith of seven modules whose only public surface is `contracts.py`, frozen before implementation and enforced by tooling. |
| [0003](0003-outbox-cloud-tasks-and-sweep.md) | Outbox, Cloud Tasks and sweep for the carrier webhook | Accepted | The approval writes an outbox event in its transaction; Cloud Tasks delivers it with retries; a sweep recovers events that were never enqueued. |
| [0004](0004-durable-conversations-deterministic-compaction.md) | Durable conversations with deterministic compaction and no retrieval | Accepted | Conversations and full tool results are stored in Firestore; code, not the model, compacts old tool results; there is no retrieval. |
| [0005](0005-runtime-grounding-check.md) | Runtime grounding check with a visible marker | Accepted | The function used by the `numbers_grounded` scorer runs on every answer and flags, without blocking, any figure not found in tool results. |
| [0006](0006-open-chat-allowance-ceiling-replay.md) | Open chat with visitor allowance, spend ceiling and recorded replay | Accepted | No access gate; a per-visitor daily allowance and a ceiling in dollars bound the cost, and a recorded replay is offered when they run out. |
| [0007](0007-anonymous-workspaces-and-api-keys.md) | Anonymous workspace per browser and API keys per workspace | Accepted | Each browser gets a workspace in a signed cookie; API keys act inside one workspace; only the owning browser session approves. |
| [0008](0008-integer-centavos-at-pricing-boundary.md) | Integer centavos at the pricing boundary | Accepted | Money leaves `pricing` as integer BRL centavos, rounded once, half to even; no other module does arithmetic on money. |
| [0009](0009-haiku-model-and-dollar-ceilings.md) | Haiku 5.5 and spend ceilings in dollars | Accepted | The agent defaults to `claude-haiku-5-5`; spending is capped in dollars (US$ 10 per month, US$ 0.50 per day) from configured prices. |
| [0010](0010-english-and-brazilian-portuguese.md) | English and Brazilian Portuguese | Accepted | The interface, the agent and the term sheet work in both languages; text for people crosses boundaries as a code plus parameters. |
| [0011](0011-basemaps-and-licences.md) | EOX basemaps, MIT code and a non-commercial demo | Accepted | EOX Terrain Light and Sentinel-2 cloudless are the basemaps; the code is MIT and the demo is declared non-commercial. |
| [0012](0012-continuous-risk-surface-atlas-direction.md) | Continuous risk surface by default, in the Atlas direction | Accepted | The risk opens as a display-only interpolated surface over real terrain; a Cells switch shows the raw 0.1° data. |
| [0013](0013-mock-carrier-as-second-service.md) | Mock carrier as a second Cloud Run service from the same image | Accepted | `APP_ROLE=carrier` runs the mock carrier as its own Cloud Run service, built from the same image as the API. |
| [0014](0014-verification-gates.md) | Verification gates: traceability, failure tests, mutation proof, load with an oracle | Accepted | Beyond tests and the agent evaluation: a traceability matrix, injected-fault tests, a hand-written mutation catalogue and local load checked by an oracle. |
| [0015](0015-landing-page-with-map-embed.md) | Landing page in the portfolio repository with a live map embed | Accepted | The presentation page lives in the portfolio repository and frames only `/embed/map`, from configured origins. |
| [0017](0017-point-path-uses-era5-from-open-meteo.md) | The point path uses ERA5 precipitation from Open-Meteo, labelled as such | Accepted (owner confirmation requested) | Open-Meteo serves no ERA5-Land precipitation, so points outside the regions use ERA5 at 0.25° and the source label says so. |

0016 (weather cube chunking) is reserved. It will be written with measured read times and sizes once the three real cubes exist (SPEC section 4.1; human gate H1 in the goal contract).
