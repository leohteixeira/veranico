# Veranico. Task 13 of plan 00 completes this file; for now it holds the client targets.

.PHONY: gen-client

# Export the OpenAPI document and regenerate the typed frontend client from it.
# `make gen-client CHECK=1` writes nothing and fails when either file is out of date.
gen-client:
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
