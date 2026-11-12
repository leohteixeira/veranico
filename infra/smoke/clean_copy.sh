#!/usr/bin/env bash
# Does the repository work from a clean copy? (SPEC 18, milestone M6: "someone can run it")
#
#   infra/smoke/clean_copy.sh              # as a person would: `make dev` on the usual ports
#   ISOLATED=1 infra/smoke/clean_copy.sh   # next to a running stack: own project, no host port
#   KEEP=1 infra/smoke/clean_copy.sh       # leave the copy in place afterwards
#   COPY_PARENT=<dir> infra/smoke/clean_copy.sh   # where the copy goes (default: ~/.cache)
#
# It copies exactly what Git would track (tracked files plus untracked files that are not
# ignored) into a new directory, so nothing ignored can be relied on: no environment file, no
# cache, no `node_modules`, no virtual environment, no generated file. In the copy it runs
# `make verify-m0`, then `make dev`, waits for `/healthz` on both roles and for the web
# server, and stops the stack. It prints one table and exits 1 when a row failed.
#
# Default mode runs `make dev` unchanged, as the Compose project `veranico` on the
# development ports. It therefore refuses to start while that project has containers or
# while one of the ports is taken (exit 2): it would otherwise act on a stack that is in use.
# `WEB_PORT=<port>` is passed on to `make dev`.
#
# `ISOLATED=1` starts the same stack as a project of its own (`veranico-clean-<pid>`) with
# infra/smoke/compose.clean.yaml, which publishes no port, and checks the containers by
# their addresses. Nothing of the project `veranico` is started, stopped or changed. What it
# does not show is the port publishing itself, and the gate's emulator smoke test still
# talks to 127.0.0.1:8580 and :8590, that is, to the emulators of the stack already running.
#
# The copy is not a Git repository, so the gate's history scan (`gitleaks git`) finds no
# commit there; the scan of the files themselves (`gitleaks dir`) does run.
#
# The copy has no `.env` file and this script creates none. If the stack needs one to start,
# the `make dev` row fails, and that is a finding.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Outside the repository: inside it the copy would sit in an ignored directory of the
# surrounding work tree, and tools that honour `.gitignore` or look for `.git` upwards would
# then skip the copy's files or read the surrounding repository instead.
# Not the temporary directory either: where it is mounted `noexec`, the copy's virtual
# environment cannot run. `COPY_PARENT=<directory>` chooses another place.
COPY_PARENT="${COPY_PARENT:-${XDG_CACHE_HOME:-$HOME/.cache}}"
COPY="$COPY_PARENT/veranico-clean-copy-$$"
ISOLATED="${ISOLATED:-0}"
KEEP="${KEEP:-0}"
WEB_PORT="${WEB_PORT:-3500}"
START_TIMEOUT_SECONDS=900 # the first `make dev` builds two images and seeds the cubes
GATE_TIMEOUT_SECONDS=1800
DEV_PORTS=("$WEB_PORT" 8500 8510 8516 8580 8590)

if [ "$ISOLATED" = "1" ]; then
  PROJECT="veranico-clean-$$"
else
  PROJECT="veranico"
fi
compose() { docker compose --env-file /dev/null -p "$PROJECT" "$@"; }

rows=()
failed=0
dev_pid=""

row() { # row <name> <passed|failed|not run> [detail]
  rows+=("$1|$2${3:+ ($3)}")
  if [ "$2" = "failed" ]; then failed=1; fi
}

report() {
  printf '\n%-58s %s\n' "step" "result"
  printf '%-58s %s\n' "----" "------"
  local line
  for line in "${rows[@]}"; do
    printf '%-58s %s\n' "${line%%|*}" "${line#*|}"
  done
}

cleanup() {
  trap - EXIT INT TERM
  if [ -n "$dev_pid" ] && kill -0 "$dev_pid" 2>/dev/null; then
    # `make dev` removes its own stack when it is interrupted.
    kill -TERM -- "-$dev_pid" 2>/dev/null || true
    wait "$dev_pid" 2>/dev/null || true
  fi
  # Whatever is left belongs to this run: the project was empty when the run began.
  # The volumes of the project `veranico` may be older than this run, so they stay.
  if [ -n "$(compose ps --all --quiet 2>/dev/null)" ]; then
    compose down --remove-orphans >/dev/null 2>&1 || true
  fi
  if [ "$ISOLATED" = "1" ]; then
    compose down --volumes >/dev/null 2>&1 || true
  fi
  if [ "$KEEP" = "1" ]; then
    echo "clean copy kept at $COPY"
  else
    rm -rf "$COPY"
  fi
}

port_taken() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

# --- Refuse before touching anything ---------------------------------------------------
if [ -n "$(compose ps --all --quiet 2>/dev/null)" ]; then
  echo "clean_copy: the Compose project $PROJECT has containers; stop it or use ISOLATED=1" >&2
  exit 2
fi
if [ "$ISOLATED" != "1" ]; then
  for port in "${DEV_PORTS[@]}"; do
    if port_taken "$port"; then
      echo "clean_copy: port $port is taken; free it, set WEB_PORT, or use ISOLATED=1" >&2
      exit 2
    fi
  done
fi
mkdir -p "$COPY_PARENT"
if findmnt --target "$COPY_PARENT" --noheadings --output OPTIONS | grep -qw noexec; then
  echo "clean_copy: $COPY_PARENT is mounted noexec; set COPY_PARENT to another directory" >&2
  exit 2
fi
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# --- 1. The copy -------------------------------------------------------------------------
mkdir -p "$COPY"
# A tracked file that was deleted in the working tree is listed but cannot be read.
if (cd "$ROOT" && git ls-files -co --exclude-standard -z |
  tar --null --files-from=- --ignore-failed-read -cf - 2>/dev/null) | tar -xf - -C "$COPY"; then
  row "copy of what Git would track" passed "$(find "$COPY" -type f | wc -l) files"
else
  row "copy of what Git would track" failed
  report
  exit 1
fi
# Names only: the files themselves are never opened.
if [ -n "$(find "$COPY" -name '.env' -o -name '.env.*' | head -1)" ]; then
  row "no environment file in the copy" failed
else
  row "no environment file in the copy" passed
fi
if [ -e "$COPY/frontend/node_modules" ] || [ -e "$COPY/backend/.venv" ]; then
  row "no installed dependency in the copy" failed
else
  row "no installed dependency in the copy" passed
fi

# Make passes a variable of its command line on to the Make calls below it, so in isolated
# mode the gate's emulator step starts its emulators in this run's project as well.
make_arguments=("WEB_PORT=$WEB_PORT")
if [ "$ISOLATED" = "1" ]; then
  files="-f compose.yaml -f infra/smoke/compose.clean.yaml"
  make_arguments=("COMPOSE=docker compose --env-file /dev/null -p $PROJECT $files")
fi

# --- 2. The first gate, in the copy --------------------------------------------------------
if (cd "$COPY" && timeout "$GATE_TIMEOUT_SECONDS" make verify-m0 "${make_arguments[@]}") \
  >"$COPY/verify-m0.log" 2>&1; then
  row "make verify-m0 in the copy" passed
else
  row "make verify-m0 in the copy" failed "see verify-m0.log; rerun with KEEP=1"
  grep -E "failed|open" "$COPY/verify-m0.log" | tail -15
fi

# --- 3. `make dev`, in the copy ------------------------------------------------------------
# A session of its own, so one signal reaches the recipe's shell and its children.
(cd "$COPY" && exec setsid make dev "${make_arguments[@]}") >"$COPY/dev.log" 2>&1 &
dev_pid=$!

address_of() { # address_of <service> <container port>: where this script reaches it
  if [ "$ISOLATED" != "1" ]; then
    case "$1" in
      api) echo "127.0.0.1:8500" ;;
      carrier) echo "127.0.0.1:8510" ;;
      web) echo "127.0.0.1:$WEB_PORT" ;;
    esac
    return
  fi
  local container
  container="$(compose ps --quiet "$1" 2>/dev/null | head -1)"
  [ -n "$container" ] || return 1
  # Only the address is read from the container's description, never its environment.
  echo "$(docker inspect --format \
    '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$container"):$2"
}

answers() { # answers <service> <container port> <path>
  local address
  address="$(address_of "$1" "$2")" || return 1
  curl --fail --silent --show-error --max-time 5 --output /dev/null "http://$address$3" 2>/dev/null
}

wait_for() { # wait_for <row name> <service> <container port> <path>
  local deadline=$((SECONDS + START_TIMEOUT_SECONDS))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if answers "$2" "$3" "$4"; then
      row "$1" passed
      return 0
    fi
    if ! kill -0 "$dev_pid" 2>/dev/null; then
      row "$1" failed "make dev ended; see dev.log, rerun with KEEP=1"
      tail -15 "$COPY/dev.log"
      return 1
    fi
    sleep 3
  done
  row "$1" failed "no answer in ${START_TIMEOUT_SECONDS} s"
  return 1
}

if wait_for "make dev: API role answers /healthz" api 8080 /healthz; then
  wait_for "make dev: carrier role answers /healthz" carrier 8080 /healthz
  wait_for "make dev: web server answers" web 3500 /
  # The notice is printed when Compose reports every service healthy, which can be a few
  # seconds after the servers first answer.
  notice_deadline=$((SECONDS + 120))
  until grep -q "SYNTHETIC" "$COPY/dev.log" || [ "$SECONDS" -ge "$notice_deadline" ] ||
    ! kill -0 "$dev_pid" 2>/dev/null; do
    sleep 2
  done
  if grep -q "SYNTHETIC" "$COPY/dev.log"; then
    row "make dev says the showcase cubes are synthetic" passed
  else
    row "make dev says the showcase cubes are synthetic" failed
  fi
else
  row "make dev: carrier role answers /healthz" "not run"
  row "make dev: web server answers" "not run"
fi

# --- 4. Stop, as Ctrl-C would ---------------------------------------------------------------
kill -TERM -- "-$dev_pid" 2>/dev/null || true
wait "$dev_pid" 2>/dev/null || true
dev_pid=""
if [ -z "$(compose ps --all --quiet 2>/dev/null)" ]; then
  row "make dev removes its stack when interrupted" passed
else
  row "make dev removes its stack when interrupted" failed
fi

report
exit "$failed"
