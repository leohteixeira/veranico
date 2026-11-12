#!/usr/bin/env bash
# Smoke test of the container image, both roles (SPEC 17).
#
#   docker build -t veranico:smoke . && infra/smoke/container_smoke.sh veranico:smoke
#
# It starts the emulators of compose.yaml (and leaves them running: other work may be using
# them), runs one container per role on the Compose network, and checks what only the image
# can show: the built frontend is served by the API role, each role answers only its own
# routes, the process is not root, nothing local was copied into the image, and SIGTERM ends
# the server before the grace period. It prints one table, stops at the first failure with
# exit 1, and always removes its two containers.
#
# The containers publish port 8080 on a free loopback port chosen by Docker, so the test
# never competes for the development ports. Secrets are random values made for this run.
set -euo pipefail

IMAGE="${1:?usage: container_smoke.sh <image tag>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NETWORK="veranico"
API="veranico-smoke-api-$$"
CARRIER="veranico-smoke-carrier-$$"
EMBED_ORIGIN="https://portfolio.example"
GRACE_SECONDS=10

rows=()
cleanup() {
  docker rm --force "$API" "$CARRIER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

report() {
  printf '\n%-64s %s\n' "check" "result"
  printf '%-64s %s\n' "-----" "------"
  local row
  for row in "${rows[@]}"; do
    printf '%-64s %s\n' "${row%%|*}" "${row##*|}"
  done
}

# check <name> <command...>: run the command, record the row, stop at the first failure.
check() {
  local name="$1"
  shift
  if "$@"; then
    rows+=("$name|passed")
  else
    rows+=("$name|FAILED")
    report
    echo
    echo "container_smoke: FAILED at: $name" >&2
    echo "--- last log lines of $API" >&2
    docker logs --tail 20 "$API" >&2 2>&1 || true
    echo "--- last log lines of $CARRIER" >&2
    docker logs --tail 20 "$CARRIER" >&2 2>&1 || true
    exit 1
  fi
}

secret() {
  head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
}

# status <expected> <curl arguments...>: the HTTP status of one request equals <expected>.
status() {
  local expected="$1" actual
  shift
  actual="$(curl --silent --output /dev/null --max-time 5 --write-out '%{http_code}' "$@")" || true
  [ "$actual" = "$expected" ] || { echo "  expected HTTP $expected, got $actual: $*" >&2; return 1; }
}

wait_healthy() {
  local url="$1" attempt
  for attempt in $(seq 1 40); do
    if curl --silent --fail --output /dev/null --max-time 2 "$url/healthz"; then return 0; fi
    sleep 0.5
  done
  return 1
}

base_url() {
  # `docker port` prints `127.0.0.1:<port>`.
  echo "http://$(docker port "$1" 8080/tcp | head -n 1)"
}

serves_frontend() {
  local body
  body="$(curl --silent --fail --max-time 5 --header 'Accept: text/html' "$1/")" || return 1
  case "$body" in
    *'<div id="root"'*) return 0 ;;
    *) echo "  the page at / is not the built frontend" >&2; return 1 ;;
  esac
}

# header_is <url> <header name> <expected value>
header_is() {
  local actual
  actual="$(curl --silent --max-time 5 --output /dev/null --dump-header - --header 'Accept: text/html' "$1" \
    | tr -d '\r' | awk -v name="$2" -F': ' 'tolower($1) == tolower(name) { print $2 }')"
  [ "$actual" = "$3" ] || { echo "  $2 of $1 is '$actual', expected '$3'" >&2; return 1; }
}

not_root() {
  local uid
  uid="$(docker exec "$1" id -u)"
  [ "$uid" != "0" ] || { echo "  $1 runs as uid 0" >&2; return 1; }
}

# Nothing local in the image: no environment file, no Git directory, none of the
# repository's tests, no node_modules.
image_is_clean() {
  local found
  found="$(docker run --rm --network none --entrypoint sh "$IMAGE" -c \
    "find / -xdev \( -name '.env' -o -name '.env.*' -o -name '.git' -o -name 'node_modules' \
       -o -path '*/backend/tests' -o -path '*/tests/fakes' -o -name 'uv.lock' \) \
       -not -path '/proc/*' 2>/dev/null")"
  [ -z "$found" ] || { echo "  found in the image:" >&2; echo "$found" >&2; return 1; }
}

# stops_gracefully <container>: SIGTERM ends it before the grace period, not by SIGKILL (137).
stops_gracefully() {
  local started elapsed code
  started="$(date +%s)"
  docker stop --time "$GRACE_SECONDS" "$1" >/dev/null
  elapsed=$(( $(date +%s) - started ))
  code="$(docker inspect --format '{{.State.ExitCode}}' "$1")"
  [ "$code" != "137" ] && [ "$elapsed" -lt "$GRACE_SECONDS" ] \
    || { echo "  $1 took ${elapsed}s and exited $code" >&2; return 1; }
}

# The requests above were served without an access log line (the server's access log prints
# the client address), and the application logs JSON lines that name the role. The few
# lines the server prints before the application starts and after it stops are plain text.
logs_have_no_access_line() {
  local logs
  logs="$(docker logs "$1" 2>&1)"
  if grep --quiet 'HTTP/1' <<<"$logs"; then
    echo "  an access log line was written" >&2
    return 1
  fi
  grep --quiet '"severity": "INFO".*"role": "api"' <<<"$logs" \
    || { echo "  no JSON log line of the application was found" >&2; return 1; }
}

cd "$ROOT"
docker compose -p veranico up -d --wait firestore storage >/dev/null

common=(
  --detach --network "$NETWORK" --publish 127.0.0.1::8080
  --env VERANICO_ENVIRONMENT=development
  --env FIRESTORE_EMULATOR_HOST=firestore:8580
  --env STORAGE_EMULATOR_HOST=http://storage:8590
  --env "VERANICO_DELIVERY__WEBHOOK_SIGNING_SECRET=$(secret)"
)
docker run "${common[@]}" --name "$API" \
  --env APP_ROLE=api \
  --env "VERANICO_COOKIE_SIGNING_SECRET=$(secret)" \
  --env "VERANICO_ACCESS__IP_HASH_SALT=$(secret)" \
  --env VERANICO_DELIVERY__INTERNAL_AUTH=token \
  --env "VERANICO_DELIVERY__INTERNAL_TOKEN=$(secret)" \
  --env VERANICO_ASSISTANT__MODEL_CLIENT=scripted \
  --env "VERANICO_FRAME_ANCESTORS=[\"$EMBED_ORIGIN\"]" \
  "$IMAGE" >/dev/null
docker run "${common[@]}" --name "$CARRIER" --env APP_ROLE=carrier "$IMAGE" >/dev/null

api="$(base_url "$API")"
carrier="$(base_url "$CARRIER")"

check "api: /healthz answers 200" wait_healthy "$api"
check "carrier: /healthz answers 200" wait_healthy "$carrier"
check "api: /readyz answers 200" status 200 "$api/readyz"
check "api: / serves the built frontend" serves_frontend "$api"
check "api: /embed/map may be framed by the configured origin only" \
  header_is "$api/embed/map" content-security-policy "frame-ancestors $EMBED_ORIGIN"
check "api: every other page refuses to be framed" \
  header_is "$api/" content-security-policy "frame-ancestors 'none'"
check "api: a public API route exists (not 404)" status 401 --request POST "$api/api/v1/quotes"
check "api: the carrier route answers 404" \
  status 404 --request POST --header 'Content-Type: application/json' --data '{}' "$api/carrier/v1/submissions"
check "carrier: an API route answers 404" status 404 "$carrier/api/v1/regions"
check "carrier: serves no frontend (/ answers 404)" status 404 --header 'Accept: text/html' "$carrier/"
check "api: the process is not root" not_root "$API"
check "carrier: the process is not root" not_root "$CARRIER"
check "image: no .env, .git, tests, lock file or node_modules" image_is_clean
check "api: SIGTERM ends it within ${GRACE_SECONDS}s, not by SIGKILL" stops_gracefully "$API"
check "carrier: SIGTERM ends it within ${GRACE_SECONDS}s, not by SIGKILL" stops_gracefully "$CARRIER"
check "api: JSON logs, and no access log line for the requests" logs_have_no_access_line "$API"

report
echo
echo "container_smoke: passed ($IMAGE)"
