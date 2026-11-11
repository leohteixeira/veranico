# Verification record

This document says what was checked, how to repeat each check, what each check proves and
what it does not. The measured sections are generated from stored results; everything else
is written by hand.

## 1. How to read this document

**Measured blocks.** The text between `<!-- evidence:<kind>:begin -->` and
`<!-- evidence:<kind>:end -->` is written by `backend/scripts/evidence.py` from the result
of one run. It is never edited by hand: `evidence.py check` fails when a block differs from
a fresh render.

**One run per block.** A block shows the newest run of its campaign and only that run.
Counts of two runs are never added. A campaign that has not run shows "not run yet".

**Identity.** Every block names the code it measured: the short commit when the tree was
clean, otherwise "working tree" with the UTC date and the commit it was based on. A result
measured on a working tree is a result about that tree, not about a commit. Sections may
have been measured on different commits; `evidence.py check` prints each section that was
not measured on `HEAD`.

**Pass and fail.** A failed run is rendered as failed, with its findings. It is not
replaced by an older passing run.

Commands:

| Command | Does |
|---|---|
| `make evidence` | runs the traceability tests, the mutation proof and the failure campaign, then renders this document. Load and evaluation blocks show their newest stored run; they are not re-run, and no model API is called |
| `cd backend && uv run python scripts/evidence.py check --require traceability,mutation,failure,load,evals` | exits non-zero when a block is stale, a required campaign has no result, or its newest run failed |

## 2. Scope and limits that apply to everything below

1. **The weather data of the showcase regions is synthetic.** Human gate H1 (a Copernicus
   Climate Data Store account) is open, so the three regional cubes are generated from a
   seed (`make build-cube REGION=<id> SYNTHETIC=1 SEED=<n>`) and labelled synthetic
   wherever they are shown. Every figure in this record that involves a regional cube
   (prices, cell metrics, load latencies) shows the engine working on generated rain. None
   of it is evidence about real weather, and nothing here is presented as such.
2. **Nothing was deployed.** Human gate H2 (the first deploy to Google Cloud) is open. The
   Terraform configuration is validated and tested without credentials; no resource exists.
   All measurements were made on one development machine with emulators.
3. **Emulators are not the services.** Firestore and Cloud Storage are their emulators.
   Behaviour that depends on the real services (index requirements, TTL deletion, quotas,
   latency) is not measured.
4. **Tests prove what they assert, on the inputs they use.** A passing requirement in the
   matrix means at least one test marked with that requirement passed and none failed. It
   does not mean the requirement holds for every input.

### Human gates

| Gate | Needs | State | Closed by |
|---|---|---|---|
| H1 | Copernicus CDS account and `CDS_API_KEY` | **open** | `make build-cube REGION=<id>` for the three regions, then the chunking measurement of ADR 0016 on the real cubes |
| H2 | first deploy to the Google Cloud project | **open** | the bootstrap `terraform apply`, then the first tag `v*.*.*` (workflow `deploy.yml`), the live `/healthz`, the uptime check and the budget alert |
| H3 | the owner | **open** | README section 12 written by the author, the interface finish review decision, the portfolio page |

Requirements that can only be proven after a gate closes are open, not passed. Among them:
the real-data cube build (R-4.1-2 to R-4.1-5 and R-4.1-7 on ERA5-Land data), the deployed
address (R-17-4) and everything that needs a live Cloud Run service (Cloud Trace export,
Cloud Tasks delivery, the uptime check and the budget alert firing). The traceability block
below lists every requirement that has no passing test in its run.

## 3. Requirement traceability

**Method.** `docs/SPEC.md` is split into requirements in `backend/tests/requirements.yaml`.
A test names the requirements it proves with `@pytest.mark.req`. `make traceability` runs
the backend unit, architecture and integration suites and the frontend suite, then
`scripts/traceability.py` builds the matrix. An identifier that does not exist fails the
run.

**Reproduce.** `make traceability` (needs Docker for the emulators). The full matrix is
`.evidence/traceability/<run_id>/matrix.md`.

**Does not prove.** That a test is strong enough for its requirement: the marker is a claim
made by the author of the test. The mutation proof (section 4) checks that claim for the
pricing rules only.

<!-- evidence:traceability:begin -->
Not run yet: there is no stored result of `make traceability`.
<!-- evidence:traceability:end -->

## 4. Mutation proof of the pricing rules

**Method.** `backend/tests/unit/pricing/mutation_catalogue.py` is a hand-written catalogue
of mutants of `pricing/domain`: each one removes or inverts one rule of SPEC section 5 (a
clamp, a direction, a rounding mode, a load, a boundary). `scripts/mutation_proof.py`
applies one mutant at a time to a copy of the sources and runs the pricing unit tests. A
mutant is killed when a test fails. A mutant whose text no longer matches the source is
stale and fails the run, so the catalogue cannot rot silently. The unmutated baseline must
pass first.

**Reproduce.** `make mutation-proof`.

**The catalogue.** The table below has one row per mutant: the rule it removes and the
first test that failed because of it.

**Does not prove.** Anything outside the catalogue. This is not exhaustive mutation
testing: a rule with no mutant in the catalogue is not covered by this proof, and modules
other than `pricing/domain` are not mutated.

<!-- evidence:mutation:begin -->
Not run yet: there is no stored result of `make mutation-proof`.
<!-- evidence:mutation:end -->

## 5. Failure campaign

**Method.** `make test-failure` runs `backend/tests/failure` against the emulators, the
carrier role as a Compose service and, for the network faults, a fault proxy (Toxiproxy)
between the sender and the carrier. Each test is marked with the scenario of SPEC 16.3 it
belongs to; the block groups the results by scenario. A scenario with no passing test
makes the run a failure.

**Reproduce.** `make test-failure` (refuses to start while `make dev` holds the carrier).

**What proves each scenario.**

| Scenario | Fault | Observable asserted |
|---|---|---|
| R-16.3-1 | the weather source answers 429 or 5xx, or times out | the number of HTTP calls made (four attempts, then `unavailable`), no retry on 400 or 404, the configured timeout on every attempt, and delays inside the exponential bounds, identical for one seed |
| R-16.3-2 | the process stops between the approval commit and the enqueue | the outbox event is `pending` after the commit with nothing enqueued; the sweep route enqueues it exactly once (a second sweep enqueues nothing) and the audit trail holds one approval |
| R-16.3-3 | the carrier answers 503, then 200 | two recorded attempts, the second delivered, one receipt |
| R-16.3-4 | the same event is delivered twice | the carrier returns the original receipt and stores one; the same attempt number sent twice is recorded once |
| R-16.3-5 | two decisions on one approval at the same time | one outcome is stored and the other caller gets a conflict, repeated twenty times |
| R-16.3-6 | concurrent `POST /quotes` with one idempotency key (2 and 20 callers) | one quote document and one idempotency record; every caller receives the same `quote_id` |
| R-16.3-7 | the model call fails before any output, and after two tools | the stream ends with `error` (`model_unavailable`, naming the completed tools) then `done`, the usage of every call is recorded, and the next message of the conversation is accepted |
| R-16.3-8 | the client disconnects during a turn | the model stream is closed, the usage of the interrupted call is still recorded, the stored turn holds the tool that finished, and the next message of the conversation is accepted |
| R-16.3-9 | connection reset, disabled proxy, latency above the timeout, truncated response | each fault is recorded as the error class the sender documents (connection error, timeout, retryable failure), and an unfaulted call is delivered through the same proxy |

**Does not prove.** Behaviour under faults that were not injected (emulator loss, disk
full, clock jumps), behaviour of Cloud Tasks (development uses the in-process relay), or
anything about real networks: the proxy runs on the same host.

<!-- evidence:failure:begin -->
Not run yet: there is no stored result of `make test-failure`.
<!-- evidence:failure:end -->

## 6. Load with an oracle

**Method.** `make load` starts a stack of its own (Compose project `veranico-load`: the
image of the `Dockerfile` for the API and the carrier role, and both emulators, all empty)
and removes it afterwards. k6 runs from its pinned container image on the network of that
stack against `http://api:8080`; the target is not configurable and the script refuses any
other host.

**Declared profile** (`load/profile.json`, written before the first measured run and never
changed after one):

| Scenario | Requests | Virtual users | Threshold |
|---|---|---|---|
| `POST /api/v1/quotes` | 200 distinct idempotency keys, each sent 5 times (1,000) | 20 | 95th percentile under 2,000 ms |
| `GET /api/v1/regions/{id}/cells` | 600 (24 distinct requests, each 25 times) | 10 | 95th percentile under 1,000 ms |

Both scenarios run together. Two more thresholds apply to the whole run: no unexpected
status, and every check true. The schedule is built from a seed (`load/fixtures.py`), so
every request is known before the run: the first two sends of each key are adjacent and
race, the others are mixed with other keys.

**The oracle** (`load/oracle.py`) reads only the files of the run: the schedule, one
evidence line per request written by k6, the k6 summary, and a snapshot of
`quoting_quotes` and `quoting_idempotency` read from the emulator after the run. It
asserts:

1. one well-formed evidence line per scheduled request: none missing, none twice;
2. all acknowledged responses of one key carry the same `quote_id`;
3. every acknowledged `quote_id` exists in the workspace of the run;
4. at most one quote per key, exactly the recorded one where a record exists, and no quote
   without a key of the run;
5. the thresholds in the k6 summary are the declared ones, and all hold.

**Detection proof.** `load/tests/test_oracle.py` builds a passing run directory, plants one
defect at a time (two quotes for one key, an acknowledged quote missing, two ids
acknowledged for one key, an orphan quote, a missing or duplicated evidence line, an
unexpected status, a failed threshold, a threshold that differs from the profile) and
asserts that the oracle reports each one and passes only the clean directory.

**Reproduce.** `make load`. The run directory is `.evidence/load/<run_id>/`.

**Does not prove.** Capacity. The generator and the service share one host, state is in an
emulator, and the cubes are synthetic. The per-key rate limit is raised for the run, so
the campaign measures idempotency under contention and the two latencies on this machine,
not the rate limiter and not production latency. The limits are repeated inside the block.

<!-- evidence:load:begin -->
Not run yet: there is no stored result of `make load`.
<!-- evidence:load:end -->

## 7. Agent evaluation

**Method.** SPEC 16.6: an Inspect suite drives the real agent loop with its real tools
against fixture cubes, three epochs per case, and fails below a 90% pass rate. It is the
only campaign that calls the model API and the only one that costs money, so it runs on
demand (`make evals`, or the `evals.yml` workflow) and is never started by `make evidence`.

**Does not prove.** Behaviour on inputs outside the cases, or with another model or prompt
version than the one named in the block. A pass rate from three epochs is a small sample.

<!-- evidence:evals:begin -->
Not run yet: there is no stored result of `make evals`.
<!-- evidence:evals:end -->

## 8. Checks that are not campaigns

These run in `make test`, `make test-integration` or CI and appear in the traceability
matrix under their requirements. They have no block of their own.

| Check | Where | What it asserts |
|---|---|---|
| Span tree and cost | `backend/tests/integration/delivery/test_span_tree.py` | one scripted turn of the real assistant emits `http.request` → `agent.turn` → `llm.call`, `tool.<name>`, `climate.ingest`; the cost on each `llm.call` equals a value computed by hand from the configured prices; `outbox.deliver` is emitted under the request of the queue |
| Redaction | `backend/tests/integration/delivery/test_redaction.py` | sentinel values sent as message text, place name, API key, cookie, allowance code, query, path and client address appear in no span, no log line and no problem document |
| Graceful shutdown | `backend/tests/integration/delivery/test_graceful_shutdown.py`, `infra/smoke/container_smoke.sh` | readiness turns 503; a chat stream open during shutdown ends with `error` (`shutting_down`) then `done`; the container exits on SIGTERM before the grace period |
| Infrastructure guardrails | `infra/terraform/tests/guardrails.tftest.hcl` | on a mocked provider, plan only: instance limits, region, private bucket, image cleanup, federation restricted to one repository, no primitive role, secrets readable only by their role, the CDS key absent from every service, TTL policies on every expiring collection |
| Workflow rules | `.github/scripts/check_delivery.py` | every action pinned to a commit, every image to a digest, read-only default permissions, no key file and no `pull_request_target` |

The infrastructure checks never reach Google Cloud. They prove what the configuration
declares, not what a deployment does (gate H2).

## 9. Defects found while building these checks

Found by the delivery checks of this record and fixed before the results above:

| Found by | Defect | Fix |
|---|---|---|
| Redaction test | the HTTP client library logged full request URLs at INFO, which put place names typed by a visitor into the service log | that logger is set to WARNING when the service configures logging; the test asserts no sentinel in any log line |
| Review of the telemetry tests | building the application left a JSON handler and the INFO level on the root logger of the process, changing the logging of unrelated tests | logging is configured when the server starts and restored on shutdown; a test asserts the loggers are left as found |
| Span tree test, on its second run | the test used a fixed visitor on the shared emulator, so the daily allowance ran out and the turn was refused | each test application uses a Firestore project of its own in the emulator |
| The same test, once the allowance was fixed | the default scripted turn called the real geocoding and archive services from a test | the delivery tests answer every outgoing call locally; the weather archive is a stand-in inside the test |

Found by the campaigns and suites of the modules. Each row was checked against the commit
it names:

| Found by | Defect | State |
|---|---|---|
| Load campaign, run `20261111T114945Z` | under simultaneous quote pricing the per-cell route had a 95th percentile of 1,545 ms against the declared 1,000 ms (median 14.6 ms). Idempotency held in the same run: 200 keys, 200 quotes, no duplicate | **open**: being fixed in the service; the threshold and the profile are unchanged, and section 6 shows the newest run |
| Assistant failure tests (client disconnect) | a client disconnect did not close the content iterator of the stream, so the model call was left open; and a cancelled turn could record an incomplete token total | fixed in `c015f34`, with the tests that found them |
| Kernel invariant test, in the full suite | the mock carrier's wire errors (`invalid_signature`, `stale_timestamp`, `carrier_unavailable`) subclassed the product's error family, although they are not product error codes | fixed in `21ad632`: the carrier route maps them to problem documents itself |
| Integration and race tests on the Firestore emulator | concurrent writers on one document are refused by the emulator after about two seconds ("Transaction lock timeout", `ABORTED`) | `quoting` keeps the decision, the audit entry and the outbox event in one transaction, retries it, and answers exhausted contention as `conflict` (409) (`1eed6df`; proven by the race tests of `f44e62e`); the carrier's receipt store treats the same answer as a lost race (`2ddcb1a`) |
| Web tests of the risk legend | the `breaks` of a cell metric were read as having outer classes; they are class edges, n + 1 edges for n classes | fixed in `27026ab` |
| gitleaks, on the tree and the history | an invented sentinel value of the redaction test was flagged as an API key | a narrow allowlist for the exact sentinel shape in `.gitleaks.toml` (`db0a7e0`) |
