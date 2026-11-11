# Veranico: the one entry point for people and CI. `make help` lists the targets.

# --- Environment file -------------------------------------------------------------------
# The owner keeps real keys in a Git-ignored `.env`. It is loaded here when it exists, so a
# recipe receives the keys without anyone opening the file. `env.example` documents the names.
#
# * One `NAME=value` per line. The value is passed verbatim (JSON, `$` and all); an unquoted
#   `#` starts a comment.
# * Quotes are not needed. A value of one word wrapped in one pair of quotes (`NAME="value"`,
#   the habit of other dotenv readers) loses that pair; a value with spaces keeps its quotes.
# * A name left empty in the file is unset for the recipes, so it never replaces a default or
#   a generated development secret. This holds even when the calling shell exported a value.
# * A non-empty value in the file wins over the calling shell.
# * Only the names the file defines are exported. No recipe prints the environment.
#
# `ENV_FILE` exists for the test of this loader (backend/tests/architecture/test_makefile_env.py).
ENV_FILE ?= .env
_env_before := $(foreach v,$(.VARIABLES),$(if $(filter file,$(origin $v)),$v))
-include $(ENV_FILE)
_env_names := $(filter-out $(_env_before) _env_before,$(foreach v,$(.VARIABLES),$(if $(filter file,$(origin $v)),$v)))
$(foreach v,$(_env_names),$(if $(filter 1,$(words $(value $v))),$(eval $v := $$(patsubst '%',%,$$(patsubst "%",%,$$(value $v))))))
$(foreach v,$(_env_names),$(if $(strip $(value $v)),$(eval $v := $$(value $v))$(eval export $v),$(eval undefine $v)))

# --- Shared definitions -----------------------------------------------------------------
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

# The project name is explicit, so no recipe depends on the directory name or on
# COMPOSE_PROJECT_NAME. `--env-file /dev/null` replaces Compose's default environment file,
# so Compose never reads `.env` itself: the loader above is its only reader, and a container
# receives exactly what a recipe exports and compose.yaml passes on by name.
COMPOSE := docker compose --env-file /dev/null -p veranico

# Default suites leave out what needs the emulators, the network, the fault proxy or a
# stored campaign result (`evidence`, which only the traceability run includes).
FAST := not integration and not live and not failure and not evidence

# Development ports (SPEC section 17), published by compose.yaml. WEB_PORT can be
# overridden for one run (`make dev WEB_PORT=3501`).
WEB_PORT ?= 3500
API_PORT := 8500
CARRIER_PORT := 8510
FIRESTORE_HOST := 127.0.0.1:8580
STORAGE_HOST := http://127.0.0.1:8590

# A fresh random secret, printed to stdout for a `$$(...)` capture and written nowhere.
GEN_SECRET := head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'

# Result files of the campaigns (plan 09 reads them): .evidence/<kind>/<run_id>/.
EVIDENCE := $(CURDIR)/.evidence
ifndef RUN_ID
RUN_ID := $(shell date -u +%Y%m%dT%H%M%SZ)
endif

# $(call with_emulators,<command>): run a command in backend/ against the emulators. They are
# stopped afterwards only when this call started them, so a running `make dev` survives.
define with_emulators
running="$$($(COMPOSE) ps -q --status running)"; \
export FIRESTORE_EMULATOR_HOST=$(FIRESTORE_HOST) STORAGE_EMULATOR_HOST=$(STORAGE_HOST); \
$(COMPOSE) up -d --wait firestore storage; \
status=0; (cd backend && $(1)) || status=$$?; \
if [ -z "$$running" ]; then $(COMPOSE) down; fi; \
exit $$status
endef

.PHONY: help dev test test-integration test-failure lint fmt gen-client ingest build-cube \
	mutation-proof evals record-replay load evidence traceability \
	verify-m0 verify-m1 verify-m2 verify-m3 verify-m4 verify-m5 verify-m6

help:
	@echo "make dev               the whole stack locally; needs no .env and no key"
	@echo "make test              backend unit and architecture tests; frontend tests and type check"
	@echo "make test-integration  tests against the emulators"
	@echo "make test-failure      failure campaign with the fault proxy"
	@echo "make lint | fmt        ruff, mypy, import-linter, boundary script, eslint | ruff format, prettier"
	@echo "make gen-client        export OpenAPI and regenerate the typed client (CHECK=1: fail on drift)"
	@echo "make ingest LAT= LON=  fetch and cache point history"
	@echo "make build-cube REGION= [SYNTHETIC=1 SEED=] [MEASURE=1]"
	@echo "make mutation-proof | evals | record-replay LOCALE= | load | evidence | traceability"
	@echo "make verify-m0 .. verify-m6   the executable gate of each milestone"

# Frontend dependencies follow the lockfile; pnpm rewrites .modules.yaml on every install.
frontend/node_modules/.modules.yaml: frontend/pnpm-lock.yaml
	pnpm --dir frontend install --frozen-lockfile
	@touch $@

# --- Development stack ------------------------------------------------------------------
# Everything is a Compose service (compose.yaml): both roles from the image of the
# Dockerfile, the Vite dev server, the emulators and Jaeger. The recipe generates the secrets
# the roles need once per run; a non-empty value from the environment file is used instead.
# They reach the containers by name and are written nowhere. `--build` rebuilds the image
# from the working tree, so the roles never run stale code.
#
# The recipe follows the logs until Ctrl-C (or until the three services have ended), then
# removes what belongs to it: the whole project when nothing was running before, otherwise
# only its own services, so emulators a test run started keep running.
DEV_SERVICES := web api carrier cubes jaeger
dev:
	@export WEB_PORT=$(WEB_PORT); \
	export VERANICO_COOKIE_SIGNING_SECRET="$${VERANICO_COOKIE_SIGNING_SECRET:-$$($(GEN_SECRET))}"; \
	export VERANICO_ACCESS__IP_HASH_SALT="$${VERANICO_ACCESS__IP_HASH_SALT:-$$($(GEN_SECRET))}"; \
	export VERANICO_DELIVERY__WEBHOOK_SIGNING_SECRET="$${VERANICO_DELIVERY__WEBHOOK_SIGNING_SECRET:-$$($(GEN_SECRET))}"; \
	export VERANICO_DELIVERY__INTERNAL_TOKEN="$${VERANICO_DELIVERY__INTERNAL_TOKEN:-$$($(GEN_SECRET))}"; \
	frame_ancestors='["http://127.0.0.1:3450"]'; \
	export VERANICO_FRAME_ANCESTORS="$${VERANICO_FRAME_ANCESTORS:-$$frame_ancestors}"; \
	if [ -z "$${ANTHROPIC_API_KEY:-}" ]; then export VERANICO_ASSISTANT__MODEL_CLIENT=scripted; fi; \
	running="$$($(COMPOSE) ps -q --status running)"; \
	cleanup() { \
		trap - EXIT INT TERM; \
		if [ -z "$$running" ]; then $(COMPOSE) down; else $(COMPOSE) rm --stop --force $(DEV_SERVICES); fi; \
	}; \
	trap cleanup EXIT; trap 'exit 130' INT; trap 'exit 143' TERM; \
	$(COMPOSE) up -d --build --wait firestore storage jaeger carrier api web; \
	echo "dev: web http://127.0.0.1:$(WEB_PORT)  api http://127.0.0.1:$(API_PORT)  carrier http://127.0.0.1:$(CARRIER_PORT)  jaeger http://127.0.0.1:8516"; \
	real=""; \
	for region in sul-de-minas sorriso ribeirao-preto; do \
		if grep -qs '"source": *"era5-land/cds"' "backend/.data/weather/climate/cubes/$$region/manifest.json"; then real="$$real $$region"; fi; \
	done; \
	if [ "$$real" = " sul-de-minas sorriso ribeirao-preto" ]; then \
		echo "dev: the three showcase regions run on the real ERA5-Land cubes of backend/.data/weather"; \
	elif [ -n "$$real" ]; then \
		echo "dev: real ERA5-Land cubes for$$real; the other showcase regions run on seeded SYNTHETIC cubes"; \
	else \
		echo "dev: the three showcase regions run on seeded SYNTHETIC cubes, not on weather history"; \
	fi; \
	$(COMPOSE) logs --follow api carrier web

# --- Tests ------------------------------------------------------------------------------
test: frontend/node_modules/.modules.yaml
	cd backend && uv run pytest tests -q -m "$(FAST)"
	pnpm --dir frontend test
	pnpm --dir frontend typecheck

# `make test-integration TESTS=tests/integration/test_emulators_smoke.py` runs one file.
TESTS ?= tests
test-integration:
	@$(call with_emulators,uv run pytest $(TESTS) -m integration -q)

# Failure campaign (SPEC 16.3): the emulators, the carrier service and the fault proxy of
# the `failure` Compose profile. The three VERANICO_FAULT_PROXY_* variables are in the
# proxy's own terms: its control API as the host reaches it, and the `upstream` (the carrier
# service on the Compose network) and `listen` values of the proxy the tests create. The
# host reaches the listener on the same port. The test process and the carrier service get
# the same webhook signing secret, and both use the Firestore emulator of this project.
# Results go to .evidence/failure/<run_id>/{junit.xml,req.json}.
#
# A carrier that is already running belongs to `make dev` and holds that run's secret; the
# campaign would replace it, so it refuses to start instead.
test-failure:
	@if [ -z "$$(find backend/tests/failure -name 'test_*.py' -print -quit 2>/dev/null)" ]; then \
		echo "test-failure: not implemented in this milestone (plans 01, 03, 04, 06)" >&2; exit 2; \
	fi
	@export FIRESTORE_EMULATOR_HOST=$(FIRESTORE_HOST) STORAGE_EMULATOR_HOST=$(STORAGE_HOST); \
	export VERANICO_DELIVERY__WEBHOOK_SIGNING_SECRET="$${VERANICO_DELIVERY__WEBHOOK_SIGNING_SECRET:-$$($(GEN_SECRET))}"; \
	export VERANICO_FAULT_PROXY_API=http://127.0.0.1:8521; \
	export VERANICO_FAULT_PROXY_UPSTREAM=carrier:8080; \
	export VERANICO_FAULT_PROXY_LISTEN=0.0.0.0:8520; \
	if [ -n "$$($(COMPOSE) ps -q --status running carrier)" ]; then \
		echo "test-failure: the carrier service is already running (make dev?); stop it first" >&2; exit 1; \
	fi; \
	running="$$($(COMPOSE) ps -q --status running)"; \
	cleanup() { \
		trap - EXIT INT TERM; \
		if [ -z "$$running" ]; then $(COMPOSE) --profile failure down; else $(COMPOSE) --profile failure rm --stop --force toxiproxy carrier; fi; \
	}; \
	trap cleanup EXIT; trap 'exit 130' INT; trap 'exit 143' TERM; \
	$(COMPOSE) --profile failure up -d --build --wait firestore storage carrier toxiproxy; \
	mkdir -p $(EVIDENCE)/failure/$(RUN_ID); \
	cd backend && uv run pytest tests/failure -m failure \
		--junitxml=$(EVIDENCE)/failure/$(RUN_ID)/junit.xml \
		--req-report=$(EVIDENCE)/failure/$(RUN_ID)/req.json

# --- Static checks ----------------------------------------------------------------------
lint: frontend/node_modules/.modules.yaml
	cd backend && uv run ruff check .
	cd backend && uv run ruff format --check .
	cd backend && uv run mypy
	cd backend && uv run lint-imports
	cd backend && uv run python scripts/validate_boundaries.py src/veranico/modules --strict
	pnpm --dir frontend lint

fmt: frontend/node_modules/.modules.yaml
	cd backend && uv run ruff format .
	pnpm --dir frontend format

# Export the OpenAPI document and regenerate the typed frontend client from it.
# `make gen-client CHECK=1` writes nothing and fails when either file is out of date.
gen-client: frontend/node_modules/.modules.yaml
ifeq ($(CHECK),1)
	cd backend && uv run python scripts/export_openapi.py --check
	@generated="$$(mktemp -d)" && trap 'rm -rf "$$generated"' EXIT && \
		pnpm --dir frontend exec openapi-typescript ../backend/openapi.json -o "$$generated/schema.d.ts" >/dev/null && \
		if cmp -s "$$generated/schema.d.ts" frontend/src/api/schema.d.ts; then \
			echo "frontend/src/api/schema.d.ts is up to date"; \
		else \
			echo "frontend/src/api/schema.d.ts is out of date: run \`make gen-client\` and commit the result" >&2; \
			exit 1; \
		fi
else
	cd backend && uv run python scripts/export_openapi.py
	pnpm --dir frontend gen-client
endif

# --- Data scripts (plan 01) -------------------------------------------------------------
# `--lat=<value>` keeps a negative coordinate from being read as an option.
ingest:
	@if [ -z "$(LAT)" ] || [ -z "$(LON)" ]; then echo "usage: make ingest LAT=<lat> LON=<lon>" >&2; exit 2; fi
	cd backend && uv run python scripts/ingest.py --lat=$(LAT) --lon=$(LON)

build-cube:
	@if [ -z "$(REGION)" ]; then echo "usage: make build-cube REGION=<id> [SYNTHETIC=1 SEED=<n>] [MEASURE=1]" >&2; exit 2; fi
	cd backend && uv run --group cube python scripts/build_cube.py --region $(REGION) \
		$(if $(filter 1,$(SYNTHETIC)),--synthetic $(if $(SEED),--seed $(SEED))) \
		$(if $(filter 1,$(MEASURE)),--measure)

# --- Campaigns --------------------------------------------------------------------------
# Result: .evidence/mutation/<run_id>/mutants.json. A run that wrote nothing leaves no directory.
mutation-proof:
	@mkdir -p $(EVIDENCE)/mutation/$(RUN_ID)
	@status=0; \
	(cd backend && uv run python scripts/mutation_proof.py --json $(EVIDENCE)/mutation/$(RUN_ID)/mutants.json) || status=$$?; \
	rmdir $(EVIDENCE)/mutation/$(RUN_ID) $(EVIDENCE)/mutation $(EVIDENCE) 2>/dev/null || true; \
	exit $$status

# Paid: calls the model API and prints the cost of the run. A part of the suite, with a hard
# stop: `make evals EVALS_ARGS="--cases a,b,c --epochs 1 --max-cost-usd 0.25"`.
evals:
	@if [ ! -f backend/tests/evals/run.py ]; then echo "evals: not implemented in this milestone (plan 06)" >&2; exit 2; fi
	cd backend && uv run python -m tests.evals.run $(EVALS_ARGS)

# Paid: records the replay of one language on the real cubes (SPEC 9.6), about US$ 0.01, with a
# hard stop: `make record-replay LOCALE=en` (or pt-BR) [MAX_COST_USD=0.10]. Needs the emulators.
record-replay:
	@if [ -z "$(LOCALE)" ]; then echo "usage: make record-replay LOCALE=en|pt-BR [MAX_COST_USD=0.10]" >&2; exit 2; fi
	cd backend && FIRESTORE_EMULATOR_HOST=$(FIRESTORE_HOST) STORAGE_EMULATOR_HOST=$(STORAGE_HOST) \
		uv run python -m tests.evals.record_replay --locale $(LOCALE) --max-cost-usd $(or $(MAX_COST_USD),0.10)

# The runner starts its own Compose project (`veranico-load`, compose.yaml plus
# load/compose.load.yaml) and never the development one, so this does not depend on `dev`.
# `KEEP_STACK=1 make load` and `make load KEEP_STACK=1` both reach it: Make passes the
# variables of its environment and of its command line on to a recipe.
load:
	@if [ ! -f load/run.py ]; then echo "load: not implemented in this milestone (plan 09)" >&2; exit 2; fi
	cd backend && uv run python ../load/run.py

# The requirement-to-test matrix of the current tree, from every suite that can run here:
# the backend suites, the failure campaign (`make test-failure`, under the same run id), the
# frontend unit tests and the Playwright flow on a fresh build.
# Results: .evidence/traceability/<run_id>/{backend.req.json,backend-integration.req.json,
# failure.req.json,frontend.req.json,matrix.json,matrix.md} and .evidence/failure/<run_id>/.
# `REQUIRE_ALL=1` also fails when a requirement has no passing test, including one that
# waits for a human gate. The matrix is written even when a test fails; the target then
# exits non-zero.
TRACE := $(EVIDENCE)/traceability/$(RUN_ID)
traceability: frontend/node_modules/.modules.yaml
	@mkdir -p $(TRACE); status=0; \
	(cd backend && uv run pytest tests -q -m "$(FAST)" --req-report=$(TRACE)/backend.req.json) || status=1; \
	($(call with_emulators,uv run pytest tests -q -m "integration or evidence" --req-report=$(TRACE)/backend-integration.req.json)) || status=1; \
	$(MAKE) test-failure RUN_ID=$(RUN_ID) || status=1; \
	rm -f frontend/.cache/req.json frontend/.cache/vitest.json frontend/.cache/playwright.json; \
	pnpm --dir frontend test || status=1; \
	(pnpm --dir frontend build && pnpm --dir frontend exec playwright test) || status=1; \
	pnpm --dir frontend req-report || status=1; \
	reports="--report $(TRACE)/backend.req.json --report $(TRACE)/backend-integration.req.json"; \
	for report in failure:$(EVIDENCE)/failure/$(RUN_ID)/req.json frontend:frontend/.cache/req.json; do \
		if [ -f "$${report#*:}" ]; then \
			cp "$${report#*:}" "$(TRACE)/$${report%%:*}.req.json"; \
			reports="$$reports --report $(TRACE)/$${report%%:*}.req.json"; \
		fi; \
	done; \
	(cd backend && uv run python scripts/traceability.py --check-ids --matrix --json $(TRACE)/matrix.json \
		$(if $(filter 1,$(REQUIRE_ALL)),--require-all) $$reports > $(TRACE)/matrix.md) || status=1; \
	echo "traceability: results in $(TRACE)"; \
	exit $$status

# The three campaigns run even when one fails, so the record shows the failure; the target
# then exits non-zero. The failure campaign runs inside the traceability run. Load and
# evaluation sections come from their newest stored run.
evidence:
	@if [ ! -f backend/scripts/evidence.py ]; then echo "evidence: not implemented in this milestone (plan 09)" >&2; exit 2; fi
	@status=0; \
	$(MAKE) traceability || status=1; \
	$(MAKE) mutation-proof || status=1; \
	(cd backend && uv run python scripts/evidence.py render) || status=1; \
	exit $$status

# --- Gates ------------------------------------------------------------------------------
verify-m0 verify-m1 verify-m2 verify-m3 verify-m4 verify-m5 verify-m6: verify-%:
	cd backend && uv run python scripts/gate.py $*
