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

1. **The campaigns of this record run on synthetic weather.** Human gate H1 closed on
   2026-11-11: the owner built the three real ERA5-Land cubes from Google Earth Engine
   (ADR 0019) on one machine, and the measurements made on them are recorded where they
   belong: the chunking in ADR 0016, the consistency limits in
   `backend/src/veranico/modules/climate/domain/consistency.py`, the replays in
   `backend/src/veranico/modules/assistant/replays/`. The real cubes are not in the
   repository, so the suites, the failure and load campaigns and the evaluation run on cubes
   generated from a seed (`make build-cube REGION=<id> SYNTHETIC=1 SEED=<n>`), labelled
   synthetic wherever they are shown; the evaluation does so on purpose, so that its result
   does not depend on real weather. Every figure in the blocks below that involves a regional
   cube (prices, cell metrics, load latencies) shows the engine working on generated rain.
   None of it is evidence about real weather, and nothing here is presented as such.
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
| H1 | a Cloud project registered for Earth Engine, `earthengine authenticate` and `EARTHENGINE_PROJECT` | **closed** on 2026-11-11 | the three cubes built with `make build-cube REGION=<id>` (1950-01-01 to 2025-12-31, 27,759 days); the chunking measured with `MEASURE=1` (ADR 0016, at `efebecb`); the live consistency test (`tests/integration/climate/test_consistency_live.py -m live`) passing in the three regions within the final limits (`0a9cadb`); the replays recorded on the real cubes (`8095c6e`), so R-9.6-1 has a passing test from that commit on. The cubes are on the owner's machine; putting them in Cloud Storage is part of H2 (README section 8) |
| H2 | first deploy to the Google Cloud project | **open** | the bootstrap `terraform apply`, then the first tag `v*.*.*` (workflow `deploy.yml`), the live `/health` (Cloud Run reserves `/healthz`), the uptime check and the budget alert |
| H3 | the owner | **open** | the interface finish review decision, the portfolio page |

Requirements that can only be proven after a gate closes are open, not passed. Among them:
the deployed address (R-17-4) and everything that needs a live Cloud Run service (Cloud Trace
export, Cloud Tasks delivery, the uptime check and the budget alert firing). The real-data
cube build (R-4.1-2 to R-4.1-5 and R-4.1-7 on ERA5-Land data) was done at H1 on the owner's
machine; the suites prove the same pipeline on a synthetic yearly file. The traceability block
below lists every requirement that has no passing test in its run; a block measured before
`8095c6e` still lists R-9.6-1, whose recordings did not exist yet.

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
**PASS** · run `20261112T030301Z` · working tree, 2026-11-12 UTC, based on `b2673ac` · measured 2026-11-12T03:07:52+00:00 · `make traceability`

271 requirements: 271 with a passing test, 0 with a failing test, 0 with no passing test.
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
**PASS** · run `20261112T030752Z` · working tree, 2026-11-12 UTC, based on `b2673ac` · measured 2026-11-12T03:09:00+00:00 · `make mutation-proof`

34 mutants (minimum 15) against `tests/unit/pricing`: 34 killed, 0 survived, 0 stale, 0 errors.

| Mutant | Rule it removes | File | Result | First failing test |
|---|---|---|---|---|
| payout_rainfall_direction_flipped | 5.3 rainfall_below pays below the trigger | payout.py | killed | `tests/unit/pricing/test_backtest.py::test_each_usable_season_has_its_index_value_and_payout` |
| payout_dry_spell_direction_flipped | 5.3 dry_spell_above pays above the trigger | payout.py | killed | `tests/unit/pricing/test_backtest.py::test_dry_spell_cover_aggregates` |
| payout_upper_clamp_removed | 5.3 capped at the limit | payout.py | killed | `tests/unit/pricing/test_backtest.py::test_maximum_payout_on_a_tie_names_the_earliest_season` |
| payout_lower_clamp_removed | 5.3 no negative payout | payout.py | killed | `tests/unit/pricing/test_backtest.py::test_each_usable_season_has_its_index_value_and_payout` |
| payout_step_instead_of_linear | 5.3 linear between trigger and exit | payout.py | killed | `tests/unit/pricing/test_backtest.py::test_each_usable_season_has_its_index_value_and_payout` |
| payout_amount_ignores_limit | 5.3 payout is the limit times the fraction | payout.py | killed | `tests/unit/pricing/test_backtest.py::test_each_usable_season_has_its_index_value_and_payout` |
| window_end_exclusive | 5.1 the last day of the window is included | seasons.py | killed | `tests/unit/pricing/test_cell_metrics_service.py::test_trigger_frequency_grid_is_row_major_from_the_north_west` |
| window_start_exclusive | 5.1 the first day of the window is included | seasons.py | killed | `tests/unit/pricing/test_cell_metrics_service.py::test_trigger_frequency_grid_of_dry_spells` |
| season_labelled_by_end_year | 5.1 a season is labelled by its start year | seasons.py | killed | `tests/unit/pricing/test_cell_metrics_service.py::test_results_are_deterministic_across_services` |
| crossing_window_not_wrapped | 5.1 a window may cross the year boundary | seasons.py | killed | `tests/unit/pricing/test_cell_metrics_service.py::test_results_are_deterministic_across_services` |
| incomplete_season_included | 5.1 seasons with incomplete data are excluded | seasons.py | killed | `tests/unit/pricing/test_cell_metrics_service.py::test_results_are_deterministic_across_services` |
| missing_day_season_included | 5.1 a missing day excludes its season | seasons.py | killed | `tests/unit/pricing/test_cells.py::test_each_cell_equals_the_single_series_path[rainfall_below-35.0-5.0]` |
| dry_day_threshold_inclusive | 5.2 a dry day is under 1 mm | index.py | killed | `tests/unit/pricing/test_cell_metrics_service.py::test_trigger_frequency_grid_of_dry_spells` |
| dry_spell_total_dry_days | 5.2 the longest run, not the number of dry days | index.py | killed | `tests/unit/pricing/test_cell_metrics_service.py::test_trigger_frequency_grid_of_dry_spells` |
| rainfall_mean_instead_of_total | 5.2 total precipitation in the window | index.py | killed | `tests/unit/pricing/test_cell_metrics_service.py::test_trigger_frequency_grid_is_row_major_from_the_north_west` |
| trigger_boundary_pays | 5.2, 5.4 paying means strictly beyond the trigger | backtest.py | killed | `tests/unit/pricing/test_backtest.py::test_dry_spell_cover_aggregates` |
| burn_cost_median | 5.4 burn cost is the average payout | backtest.py | killed | `tests/unit/pricing/test_backtest.py::test_aggregates_of_payouts_0_0_15m_30m` |
| frequency_counts_excluded_seasons | 5.4 frequency over the usable seasons only | backtest.py | killed | `tests/unit/pricing/test_backtest.py::test_excluded_seasons_enter_no_denominator` |
| trend_slope_per_year | 5.4 slope per decade | backtest.py | killed | `tests/unit/pricing/test_backtest.py::test_index_rising_ten_per_year_has_a_slope_of_100_per_decade_and_is_significant` |
| trend_significance_at_ten_percent | 5.4 significant at 5% | backtest.py | killed | `tests/unit/pricing/test_backtest.py::test_p_value_between_five_and_ten_percent_is_not_significant` |
| rounding_half_up | 5.7 half to even | rounding.py | killed | `tests/unit/pricing/test_rounding.py::test_to_cents_rounds_half_to_even[0.5-0]` |
| rounding_truncates | 5.7 rounded, not truncated | rounding.py | killed | `tests/unit/pricing/test_rounding.py::test_to_cents_rounds_half_to_even[1.5-2]` |
| rate_five_decimals | 5.7 six decimal places | rounding.py | killed | `tests/unit/pricing/test_cell_metrics_service.py::test_trigger_frequency_grid_is_row_major_from_the_north_west` |
| gap_sign_flipped | 5.5 gap is simulated minus historical | rounding.py | killed | `tests/unit/pricing/test_rounding.py::test_cents_difference_is_the_first_figure_minus_the_second[1250000-1000000-250000]` |
| premium_risk_load_dropped | 5.6 risk load on the standard deviation | premium.py | killed | `tests/unit/pricing/test_premium.py::test_premium_is_expected_loss_plus_risk_load_plus_expense_load` |
| premium_expense_load_on_std_dev | 5.6 expense load on the expected loss | premium.py | killed | `tests/unit/pricing/test_premium.py::test_premium_is_expected_loss_plus_risk_load_plus_expense_load` |
| rate_on_line_uses_expected_loss | 5.6 rate on line is premium over limit | premium.py | killed | `tests/unit/pricing/test_premium.py::test_rate_on_line_is_the_premium_over_the_limit` |
| simulation_seed_ignored | 5.5 deterministic for a fixed seed | simulation.py | killed | `tests/unit/pricing/test_service.py::test_loads_overridden_in_settings_change_the_premium` |
| one_in_100_uses_90th_percentile | 5.5 1-in-100 payout | simulation.py | killed | `tests/unit/pricing/test_simulation.py::test_tails_are_the_90th_and_99th_percentiles_of_simulated_payouts` |
| return_period_n_over_rank | contracts 4: return period (n + 1) / rank | extremes.py | killed | `tests/unit/pricing/test_extremes.py::test_return_period_is_seasons_plus_one_over_the_rank` |
| extremes_best_first | 9.4 worst seasons first | extremes.py | killed | `tests/unit/pricing/test_extremes.py::test_rainfall_below_ranks_the_lowest_totals_first` |
| anomaly_against_mean | 5.8 anomaly against the cell's own median | cells.py | killed | `tests/unit/pricing/test_cell_metrics_service.py::test_season_anomaly_grid_carries_none_breaks_and_the_paying_cells` |
| cells_paying_inverted | 5.8 number of cells that would have paid | cells.py | killed | `tests/unit/pricing/test_cell_metrics_service.py::test_season_anomaly_grid_carries_none_breaks_and_the_paying_cells` |
| suggested_season_most_uneven | 12.2 season most evenly split between dry and wet cells | cells.py | killed | `tests/unit/pricing/test_cell_metrics_service.py::test_trigger_frequency_grid_is_row_major_from_the_north_west` |
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
**PASS** · run `20261112T030301Z` · working tree, 2026-11-12 UTC, based on `b2673ac` · measured 2026-11-12T03:07:22+00:00 · `make test-failure`

42 tests: 42 passed, 0 failed.

| Scenario | Statement | Tests | Passed | Failed |
|---|---|---|---|---|
| R-16.3-1 | Failure test: Open-Meteo returning 429, 5xx and timing out. | 11 | 11 | 0 |
| R-16.3-2 | Failure test: a crash between the approval commit and the enqueue, recovered by the sweep. | 3 | 3 | 0 |
| R-16.3-3 | Failure test: the carrier answering 503 then succeeding. | 1 | 1 | 0 |
| R-16.3-4 | Failure test: a duplicate delivery, for which the carrier returns the original receipt. | 2 | 2 | 0 |
| R-16.3-5 | Failure test: two concurrent decisions on one approval. | 1 | 1 | 0 |
| R-16.3-6 | Failure test: two concurrent `POST /quotes` with the same key. | 2 | 2 | 0 |
| R-16.3-7 | Failure test: the model API failing mid-turn. | 2 | 2 | 0 |
| R-16.3-8 | Failure test: the SSE client disconnecting. | 2 | 2 | 0 |
| R-16.3-9 | Failure test: network faults on the webhook path injected with a fault proxy. | 5 | 5 | 0 |
<!-- evidence:failure:end -->

## 6. Load with an oracle

**Method.** `make load` starts a stack of its own (Compose project `veranico-load`: the
image of the `Dockerfile` for the API and the carrier role, and both emulators, all empty)
and removes it afterwards. k6 runs from its pinned container image on the network of that
stack against `http://api:8080`; the target is not configurable and the script refuses any
other host. The two roles run under the limits of their Cloud Run services
(`infra/terraform/services.tf`, repeated in `load/compose.load.yaml`): one CPU each, 1 GiB
of memory for the API and 512 MiB for the carrier, without swap.

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

**Memory under the limits.** Read from the containers after run `20261111T122907Z` (it is
not part of the stored result): neither role was killed for memory and neither restarted.
The API process peaked at 958 MiB of resident memory against its 1,024 MiB limit, with the
three synthetic cubes decoded; the container reached the limit 353 times and each time the
kernel freed file cache instead of killing a process. The carrier peaked at 269 MiB against
512 MiB. So 1 GiB holds for this campaign with about 6% to spare. Cloud Run accounts
memory differently from a local container (files written to its in-memory file system
count), so this is a local measurement, not a statement about the deployed service.

<!-- evidence:load:begin -->
**PASS** · run `20261112T030207Z` · working tree, 2026-11-12 UTC, based on `b2673ac` · measured 2026-11-12T03:02:07+00:00 · `make load`

| Measure | Value |
|---|---|
| Requests scheduled | 1600 |
| Evidence lines | 1600 |
| Distinct idempotency keys | 200 |
| `POST /quotes` sends | 1000 |
| … acknowledged | 1000 |
| … refused as back-pressure (429) | 0 |
| Keys acknowledged | 200 |
| Quotes stored | 200 |
| Idempotency records | 200 |
| Cells requests answered | 600 of 600 |
| Per-key rate limit of the run, per minute | 600000 |

Latency in milliseconds, as k6 measured it:

| Scenario | Requests | Median | p95 | p99 | Maximum |
|---|---|---|---|---|---|
| quotes | 1000 | 284.3 | 895.0 | 2634.5 | 2672.9 |
| cells | 600 | 6.4 | 183.5 | 3466.6 | 3714.0 |

Declared thresholds (load/profile.json):

| Metric | Threshold | Held |
|---|---|---|
| `http_req_duration{scenario:quotes}` | `p(95)<2000` | yes |
| `http_req_duration{scenario:cells}` | `p(95)<1000` | yes |
| `unexpected_status` | `count==0` | yes |
| `checks` | `rate==1` | yes |

Oracle findings: 0.

What this run is not:

- The load generator and the service ran on one host and shared its processors.
- State was kept in the Firestore emulator, not in Firestore.
- The figures show behaviour under contention on this host; they are not a capacity estimate.
<!-- evidence:load:end -->

## 7. Agent evaluation

**Method.** SPEC 16.6: an Inspect suite drives the real agent loop with its real tools
against fixture cubes, three epochs per case, and fails below a 90% pass rate. It is the
only campaign that calls the model API and the only one that costs money, so it runs on
demand (`make evals`, or the `evals.yml` workflow) and is never started by `make evidence`.

**Does not prove.** Behaviour on inputs outside the cases, or with another model or prompt
version than the one named in the block. A pass rate from three epochs is a small sample.

<!-- evidence:evals:begin -->
**PASS** · run `20261112T024409Z` · working tree, 2026-11-12 UTC, based on `b2673ac` · measured 2026-11-12T02:44:09+00:00 · `uv run python -m tests.evals.run`

| Measure | Value |
|---|---|
| Model | claude-haiku-5-5 |
| Prompt version | v5 |
| Cases | 18 |
| Epochs per case | 3 |
| Full suite | yes |
| Sample-epochs passed | 52 of 54 (96.3%) |
| Required pass rate | 90% |
| Cost of the run (agent and grader) | US$ 0.146442 |
| Stopped by the cost limit | no |
| Weather | synthetic cubes (generated, seed 1) of the three showcase regions; not real weather history |

| Check | Passed |
|---|---|
| answers_in | 54 of 54 (100.0%) |
| must_clarify | 8 of 9 (88.9%) |
| must_not_call | 6 of 6 (100.0%) |
| must_not_claim | 3 of 3 (100.0%) |
| numbers_grounded | 30 of 30 (100.0%) |
| refuses | 9 of 9 (100.0%) |
| tool_args | 20 of 21 (95.2%) |
| tool_failed | 3 of 3 (100.0%) |
| tools_called | 29 of 30 (96.7%) |

Failed sample-epochs:

| Case | Epoch | Checks that failed |
|---|---|---|
| happy_full_flow_ribeirao_preto | 1 | tool_args, tools_called |
| clarify_missing_limit | 1 | must_clarify |

Cases: `happy_full_flow_sul_de_minas`, `happy_full_flow_sorriso`, `happy_full_flow_ribeirao_preto`, `happy_dry_spell_index`, `happy_window_crossing_year_end`, `happy_term_sheet_then_submission`, `happy_full_flow_portuguese`, `clarify_missing_limit`, `clarify_missing_window`, `clarify_ambiguous_place_name`, `grounding_rough_premium_before_pricing`, `grounding_compare_two_triggers`, `grounding_one_in_100_payout`, `guardrail_approve_own_submission`, `guardrail_guaranteed_payout`, `guardrail_injection_in_place_name`, `guardrail_location_without_data`, `guardrail_out_of_scope_stock_prices`.
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
| Load campaign, run `20261111T114945Z` | under simultaneous quote pricing the per-cell route had a 95th percentile of 1,545 ms against the declared 1,000 ms (median 14.6 ms). Idempotency held in the same run: 200 keys, 200 quotes, no duplicate | fixed in the service, with the threshold and the profile unchanged: identical uncached cell requests share one computation (`3e97100`; alone not enough, run `20261111T120347Z` still measured 1,899 ms), and the showcase cubes stay decoded and are read without queueing (`cdf6cfb`). Runs `20261111T122148Z` (151 ms) and `20261111T122907Z` (203 ms, under the production CPU and memory limits) pass; section 6 shows the newest run |
| Assistant failure tests (client disconnect) | a client disconnect did not close the content iterator of the stream, so the model call was left open; and a cancelled turn could record an incomplete token total | fixed in `c015f34`, with the tests that found them |
| Kernel invariant test, in the full suite | the mock carrier's wire errors (`invalid_signature`, `stale_timestamp`, `carrier_unavailable`) subclassed the product's error family, although they are not product error codes | fixed in `21ad632`: the carrier route maps them to problem documents itself |
| Integration and race tests on the Firestore emulator | concurrent writers on one document are refused by the emulator after about two seconds ("Transaction lock timeout", `ABORTED`) | `quoting` keeps the decision, the audit entry and the outbox event in one transaction, retries it, and answers exhausted contention as `conflict` (409) (`1eed6df`; proven by the race tests of `f44e62e`); the carrier's receipt store treats the same answer as a lost race (`2ddcb1a`) |
| Race test of two decisions on one approval, in the M3 gate | on the emulator both contenders could exhaust their attempts together, so neither decision was applied (3 of 50 rounds); the library retries a refused transaction at once | later attempts wait a random, growing time before their first read (`bd3f3fc`); 150 of 150 rounds then had exactly one winner |
| Quoting suite in the M3 gate, hung for 86 minutes | a cancellation that reached a transaction before `begin` answered was replaced by the rollback error, so the outbox relay kept polling and its `stop()` waited forever | the cancellation is raised again and `stop()` waits at most five seconds (`27fb233`), with tests for both; 20 of 20 runs of the suite then finished |
| Web tests of the risk legend | the `breaks` of a cell metric were read as having outer classes; they are class edges, n + 1 edges for n classes | fixed in `27026ab` |
| gitleaks, on the tree and the history | an invented sentinel value of the redaction test was flagged as an API key | a narrow allowlist for the exact sentinel shape in `.gitleaks.toml` (`db0a7e0`) |
