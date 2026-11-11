# Veranico

> **Pricing is illustrative. It is not actuarial or insurance advice.** The demo is
> non-commercial. Until real weather cubes are built (human gate H1, below), the three
> showcase regions run on **synthetic** weather data, labelled as such wherever it is shown.

## 1. What it is

Veranico is an agent that structures parametric rainfall cover for Brazilian agriculture: a
broker describes a farm's exposure in plain language and gets a backtested trigger, an
indicative price, a term sheet and a submission that only a person can approve. Its map
shows basis risk: how the same cover would have behaved in the grid cells around the farm.

| | |
|---|---|
| Live demo | not deployed yet (human gate H2, section 8) |
| Recording | not recorded yet: there is no demo recording or screenshot in this repository |
| Run it | `make dev`, then http://127.0.0.1:3500 (section 8) |

"Veranico" is the Brazilian term for a dry spell inside the rainy season, the peril the main
index measures.

## 2. Context

A parametric (index) cover pays on a measured index, here rainfall over a window, and not on
an assessed loss. That makes it fast and cheap to settle, and it has one main weakness:

> "Basis risk in index insurance arises when the index measurements do not match an
> individual insured's actual losses."
> — Global Inclusive Insurance Facility (a World Bank Group program), "What is basis risk?",
> https://www.globalinclusiveinsuranceforum.org/faq/what-basis-risk, read on 2026-11-11.

A farm can sit in a grid cell that rarely triggers while a cell a few kilometres away
triggers often. A single quoted price hides that. Veranico's map makes it visible: it
prices the same cover in every cell of the region and shows how often each would have paid.

Rural insurance is a subject of current public policy in Brazil: the Ministry of
Agriculture's rural insurance page reports new legislation under which "o seguro rural
integre o conjunto de garantias das operações de crédito rural" (Ministério da Agricultura e
Pecuária, "Programa de Seguro Rural",
https://www.gov.br/agricultura/pt-br/assuntos/riscos-seguro/seguro-rural, read on
2026-11-11).

No market statistic is quoted here: only these two sources were opened and read for this
section, and neither was used for a number.

## 3. Architecture

A Python modular monolith with seven modules, one container image and two roles.

```text
 browser (React, Leaflet)            broker's system (API key)
        │  cookie session                    │  Bearer key, Idempotency-Key
        └──────────────┬─────────────────────┘
                       ▼
        ┌──────────────────────────────── APP_ROLE=api ────────────────────────────────┐
        │  assistant ──▶ climate ──▶ pricing ──▶ quoting ──▶ documents                 │
        │  (agent loop,   (cubes,     (index,     (quotes, approval,  (term sheet,     │
        │   7 tools)       points)     price)      outbox)             evidence file)  │
        │  access (workspaces, API keys, allowance, spend ceiling)                     │
        │  carriers (signed webhook sender)                                            │
        └───────┬──────────────────────┬───────────────────────────────┬───────────────┘
                ▼                      ▼                               ▼
           Firestore            Cloud Storage                 APP_ROLE=carrier
        (state, outbox)     (cubes, points, documents)      (mock carrier, receipts)
```

* A module's only public surface is its `contracts.py`; `bootstrap.py` is the only
  composition root. import-linter and architecture tests enforce both.
* An approval writes its outbox event in the same transaction as the state change; a queue
  delivers it to the carrier with retries, and a sweep recovers events that were never
  enqueued.
* Full document with diagrams, flows and data ownership:
  [docs/architecture.html](docs/architecture.html). Scope and contracts:
  [docs/SPEC.md](docs/SPEC.md).

## 4. How the agent stays reliable

* **Numbers come from tools.** The agent loop is hand-written on the Messages API. The
  model has seven tools (`resolve_location`, `get_weather_history`, `backtest_index`,
  `find_extreme_seasons`, `price_cover`, `draft_term_sheet`, `request_submission`), each
  with a typed input and output. Pricing is deterministic code with a fixed seed.
* **Grounding rule, checked at run time.** After each answer a pure function extracts every
  monetary value and percentage from the text and looks for it in the tool results of the
  conversation and in the user's own messages. A figure that is found nowhere is flagged in
  the interface; the answer is not blocked. The same function is the `numbers_grounded`
  check of the evaluation ([ADR 0005](specs/adrs/0005-runtime-grounding-check.md)).
* **A person approves.** `request_submission` only creates a pending approval. No tool and
  no API key can approve: only the browser session that owns the workspace can.
* **Bounded turns.** At most 10 tool calls per turn, a token budget per conversation, a
  stop after the same tool fails twice in a row, and a spend ceiling checked before every
  model call.
* **Evaluation.** An Inspect suite drives the real loop with its real tools against fixture
  cubes, three epochs per case, and fails below a 90% pass rate. **Current pass rate: not
  run yet** (the evaluation block of [docs/verification.md](docs/verification.md) has no
  stored run).

## 5. Data

| | Showcase regions | Any other point |
|---|---|---|
| Source | ERA5-Land from the Copernicus Climate Data Store | ERA5 through the Open-Meteo Historical Weather API |
| Grid | 0.1°, three boxes of 20 by 20 cells (Sul de Minas, Sorriso, Ribeirão Preto) | the grid point the API answers from, keyed by its H3 resolution 6 cell |
| Built | offline, once per region; the running service never calls the CDS | on first use, cached |
| State today | **synthetic** cubes generated from a seed (H1 open) | real, fetched on demand |

* **Variable and years.** Daily precipitation in millimetres, from 1950 through the last
  complete year.
* **Pipeline for the regional cubes.** Yearly NetCDF files are downloaded, merged with
  xarray, converted from metres to millimetres, validated and written as one Zarr store per
  region with a `manifest.json` (source, request, years, checksums, build time). Yearly
  files are cached, so a rerun downloads only the missing years. The two decisions that
  differ from the first plan are recorded in
  [ADR 0017](specs/adrs/0017-point-path-uses-era5-from-open-meteo.md) and
  [ADR 0018](specs/adrs/0018-cubes-from-hourly-era5-land-two-steps-a-day.md) (both accepted,
  owner confirmation requested).
* **Chunking.** The cube keeps the whole time axis in one chunk with small spatial blocks,
  so one point's series is one read. **Measured read times and sizes: not measured, H1
  open.** They are recorded in ADR 0016 once the real cubes exist.
* **Storage layout.** `climate/cubes/<region>/` and `climate/points/<h3 cell>/` in the
  weather store (a local directory in development, Cloud Storage in production); documents
  under `documents/`.
* **Ingestion rules.** Validate before writing (no duplicate dates, no gaps, no negative
  rain); atomic writes; retries with exponential backoff and jitter on 429 and 5xx, at most
  four attempts with a timeout each.
* **Evidence export.** `GET /api/v1/quotes/{id}/evidence.nc` returns the exact daily slice
  a quote was priced on, as NetCDF with provenance attributes.

## 6. Pricing method and its limits

* **Index.** `rainfall_below`: total rain in a window, pays when it falls below the
  trigger. `dry_spell_above`: longest run of days under 1 mm, pays when it rises above the
  trigger. Windows may cross the year end.
* **Payout.** Linear between trigger and exit, capped at the limit.
* **Backtest.** Per season: index and payout. Aggregates: trigger frequency, historical
  average payout, maximum payout, and a linear trend of the index with a warning when it is
  significant at 5%.
* **Simulation.** A gamma distribution fitted to seasonal totals (`rainfall_below`) or a
  bootstrap of seasonal values (`dry_spell_above`), 100,000 seasons by default with a fixed
  seed.
* **Indicative premium.** `expected_loss + risk_load × std_dev + expense_load ×
  expected_loss`, with `risk_load` 0.3 and `expense_load` 0.15 from configuration.
* **Money.** Integer BRL centavos, rounded once, half to even, where a value leaves
  `pricing`. Rates are fixed-decimal strings with six places.

Limits: this is not actuarial pricing. There is no cost of capital, no reinsurance, no
correlation between covers, no climate projection and no loss adjustment. A short or
trending history understates or overstates the risk, and the output says so when the trend
is significant. A gridded reanalysis is not a rain gauge on the farm: that gap is the basis
risk of section 2. With synthetic cubes the figures only show the engine working.

## 7. Public API

* **Reference.** ReDoc at `/redoc` on the API (http://127.0.0.1:8500/redoc with
  `make dev`), generated from the code. The OpenAPI document is
  [backend/openapi.json](backend/openapi.json). Prefix `/api/v1`.
* **Authentication.** Create a key for your workspace in the interface (shown once, stored
  as a hash), then send `Authorization: Bearer <key>`. A key acts inside one workspace, is
  rate-limited (60 requests per minute by default) and expires with the workspace. It can
  create and read quotes; it can never approve a submission.
* **Idempotency.** `POST /api/v1/quotes` requires an `Idempotency-Key` header. The same key
  with the same body returns the same quote; with a different body it returns 409
  `idempotency_conflict`.
* **Errors.** RFC 9457 problem documents with a stable `code` and a `trace_id`.
* **Webhook signature.** An approved submission is sent to the carrier as a signed POST:
  `Veranico-Timestamp` (Unix seconds) and `Veranico-Signature: v1=<hex>`, where the hex is
  the HMAC SHA-256 of `"<timestamp>.<raw body>"` under the shared secret. The mock carrier
  answers 200 with a receipt, 401 `invalid_signature`, 400 `stale_timestamp` for a
  timestamp older than 300 seconds, 503 `carrier_unavailable` when it simulates an outage,
  and 200 with the original receipt for a repeated `event_id`.
* **Changelog.** `v1`: first version. A breaking change would go to `/api/v2`.

## 8. Run locally

Prerequisites: Docker with Compose, and GNU Make. Nothing else is needed to run it: no
`.env` file, no API key, no cloud account. (For tests and linters: uv, Node.js 24 and
pnpm.)

```sh
make dev
```

This builds the image and starts everything as Compose services: the API, the mock carrier,
the web server, the emulators of Firestore and Cloud Storage, Jaeger, and a one-shot job
that generates the three **synthetic** showcase cubes (the command prints that they are
synthetic). Without `ANTHROPIC_API_KEY` the agent runs on a scripted model that plays the
happy path. Only the variables named in [compose.yaml](compose.yaml) reach the containers;
[env.example](env.example) documents every variable.

| What | Address |
|---|---|
| Web | http://127.0.0.1:3500 (`make dev WEB_PORT=<port>` when 3500 is taken) |
| API | http://127.0.0.1:8500 |
| Mock carrier | http://127.0.0.1:8510 |
| Jaeger UI | http://127.0.0.1:8516 (its query API is under `/api/v3`) |
| Emulators | Firestore 8580, Cloud Storage 8590 |

Other commands: `make test`, `make test-integration`, `make test-failure`, `make lint`,
`make mutation-proof`, `make load`, `make evidence`. To use the live model, put
`ANTHROPIC_API_KEY` in a Git-ignored `.env`; the Makefile reads it.

### Open human gates

| Gate | State | Closed by |
|---|---|---|
| H1: real weather cubes | open | a Copernicus CDS account: `export CDS_API_KEY=…`, then `make build-cube REGION=sul-de-minas`, `REGION=sorriso`, `REGION=ribeirao-preto`; the same with `MEASURE=1` for the chunking numbers; the live consistency test; then ADR 0016, the tolerances, the example covers, the replays and `make evidence` |
| H2: first deploy | open | the sequence below |
| H3: the author's part | open | section 12 of this file, the interface finish review decision, the portfolio page |

### Deploy (human gate H2, run by the owner)

Nothing has been deployed. The configuration in [infra/terraform](infra/terraform) is
validated and tested without credentials. The sequence:

1. Authenticate and create the state bucket:
   `gcloud auth login`, then
   `gcloud storage buckets create gs://<state bucket> --project=<project> --location=us-central1 --uniform-bucket-level-access --public-access-prevention`.
2. `terraform -chdir=infra/terraform init -backend-config="bucket=<state bucket>"`.
3. The one bootstrap apply, with a variables file that is not committed:
   `terraform -chdir=infra/terraform apply -target=module.foundation -var-file=<owner file>`.
4. Add a version to each of the five secrets, reading the value from standard input:
   `printf '%s' "<value>" | gcloud secrets versions add <name> --data-file=-` for
   `veranico-anthropic-api-key`, `veranico-webhook-signing-secret`,
   `veranico-cookie-signing-secret`, `veranico-allowance-code` and `veranico-ip-hash-salt`.
5. Store the repository variables the deploy workflow reads, each with
   `gh variable set <NAME> --body "<value>"`: `GCP_WORKLOAD_IDENTITY_PROVIDER` and
   `GCP_DEPLOYER_SERVICE_ACCOUNT` (Terraform outputs `federation_provider` and `deployer`),
   `GCP_PROJECT_ID`, `TF_STATE_BUCKET`, `GCP_BILLING_ACCOUNT`, `BUDGET_AMOUNT`,
   `BUDGET_CURRENCY`, `ALERT_EMAIL`, `FRAME_ANCESTORS` (a JSON list), and optionally
   `REPOSITORY_ID` and `CUSTOM_DOMAIN`.
6. `git tag v0.1.0 && git push origin v0.1.0`, then watch
   [deploy.yml](.github/workflows/deploy.yml). It authenticates through Workload Identity
   Federation (there is no key file), builds and pushes the image, applies Terraform with
   the new tag and requests `/healthz`.
7. Check: `curl -fsS <API URL>/healthz`; the happy path once in the browser; the uptime
   check and the budget in the console; one trace in Cloud Trace.

## 9. Cost

Configured values (their source in brackets):

| What | Value |
|---|---|
| Spend ceiling of the live agent | US$ 0.50 per day and US$ 10 per month across all visitors, checked before every model call (`VERANICO_ACCESS__DAY_CEILING_USD_MICROS`, `…MONTH_CEILING_USD_MICROS`) |
| Visitor allowance | 2 conversations and 15 messages per day per visitor; 6 and 60 with the code carried by the portfolio link (`VERANICO_ACCESS__ALLOWANCE_*`, `…BOOSTED_*`) |
| Cost per call | computed from token counts with prices in configuration (`AccessSettings.model_prices`) and recorded on each `llm.call` span |
| Instances | two Cloud Run services, each from 0 to 2 instances; one CPU each, 1 GiB of memory for the API and 512 MiB for the carrier (`infra/terraform/services.tf`). Under the load campaign with the same limits the API process peaked at 958 MiB of 1,024 MiB with three regions decoded, so a fourth region needs a larger instance or a smaller `VERANICO_CLIMATE__CUBE_CACHE_SIZE` ([docs/verification.md](docs/verification.md), section 6) |
| Images kept | the last 3 (`infra/terraform/foundation/main.tf`) |
| Uptime check | one, on `/healthz`, every 900 seconds (`infra/terraform/monitoring.tf`) |
| Budget alert | a monthly budget of `budget_amount` in the billing currency, with email alerts at 50%, 90% and 100% (`infra/terraform/variables.tf`); the owner chooses the amount |

Measured values:

| What | Value |
|---|---|
| Cost of one evaluation run | not measured: the evaluation has not run yet |
| Tokens per recorded conversation | not measured |
| Cloud cost of the deployed demo | not measured before H2 |

When the allowance or a ceiling is exhausted, the chat answers with a problem document and
the interface offers a recorded replay; the map, quotes and the public API keep working.

Provider prices and free quotas are not restated here. See
https://platform.claude.com/docs/en/about-claude/pricing for the model and
https://cloud.google.com/free for Google Cloud. A spend limit is also set in the Anthropic
Console as the outer bound that covers evaluation runs too; that is an operational step of
the owner, not something this repository tests.

## 10. Licences and attribution

The source code is MIT ([LICENSE](LICENSE)). The attribution strings below are the ones the
interface shows.

| Source | Attribution | Licence |
|---|---|---|
| Weather, region with a synthetic cube | Weather: the surface of this region is synthetic, generated for the demonstration; it is not weather history. A point outside the showcase regions uses ERA5 through Open-Meteo (Copernicus Climate Change Service, CC BY 4.0). | generated data; CC BY 4.0 for the ERA5 points |
| Weather, region with a real cube | Weather: Copernicus Climate Change Service. ERA5-Land for the regional cubes; ERA5 through Open-Meteo for any other point. CC BY 4.0. | CC BY 4.0 |
| Relief basemap | Terrain Light { Data © OpenStreetMap contributors and others, Rendering © EOX } (https://maps.eox.at/#data) | EOX::Maps, free to use with attribution |
| Satellite basemap | EOxCloudless https://cloudless.eox.at by EOX IT Services GmbH (Contains modified Copernicus Sentinel data 2025) | CC BY-NC-SA 4.0 |

**Why the demo is non-commercial.** The Sentinel-2 cloudless imagery after 2016 is licensed
CC BY-NC-SA 4.0, which does not allow commercial use, so the demo is declared non-commercial
here and in the interface ([ADR 0011](specs/adrs/0011-basemaps-and-licences.md)).

The weather line depends on the region. While human gate H1 is open all three showcase
regions run on synthetic cubes, so the interface shows the first line; the ERA5-Land line is
shown for a region whose cube was built from the real data. Synthetic cubes are generated
data and are also labelled "Synthetic weather data" in the interface.

## 11. Decisions and verification

* **Decisions.** Every material decision has a record of under a page:
  [specs/adrs/README.md](specs/adrs/README.md) lists them (0001 to 0018; 0016, the cube
  chunking, is reserved until the real cubes exist). What was left out on purpose is in
  [docs/NEXT_STEPS.md](docs/NEXT_STEPS.md).
* **Verification.** [docs/verification.md](docs/verification.md) records what was checked,
  how to repeat each check and what each one does not prove: the requirement-to-test matrix,
  the mutation proof of the pricing rules, the failure campaign, the load campaign with its
  oracle and the agent evaluation. Its measured blocks are generated from stored results and
  name the commit they measured; a failed run is shown as failed.

## 12. What I would change

_Written by the author after the build (human gate H3). Not generated._
