#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "python stop and blast-all clean runtime artifacts and lock reservations" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    repo_tmp=$(mktemp -d)
    repo="$repo_tmp/repo"
    runtime="$repo_tmp/runtime"
    mkdir -p "$repo/.git" "$repo/trees/feature-a-1"
    backend_base=$((50000 + RANDOM % 1000))
    frontend_base=$((backend_base + 1000))
    db_port=$((backend_base + 2000))
    redis_port=$((backend_base + 3000))
    n8n_base=$((backend_base + 4000))

    ENVCTL_REQUIREMENTS_STRICT=false \
    BACKEND_PORT_BASE="$backend_base" \
    FRONTEND_PORT_BASE="$frontend_base" \
    DB_PORT="$db_port" \
    REDIS_PORT="$redis_port" \
    N8N_PORT_BASE="$n8n_base" \
    ENVCTL_BACKEND_START_CMD="$1 -m http.server {port} --bind 127.0.0.1" \
    ENVCTL_FRONTEND_START_CMD="$1 -m http.server {port} --bind 127.0.0.1" \
    RUN_SH_RUNTIME_DIR="$runtime" PYTHON_BIN="$1" "$2" --repo "$repo" --plan feature-a >/tmp/envctl_stop_plan.out
    test -f "$runtime/python-engine/run_state.json"
    test -f "$runtime/python-engine/shell_prune_report.json"
    ls "$runtime/python-engine/locks/"*.lock >/dev/null 2>&1

    ENVCTL_REQUIREMENTS_STRICT=false \
    BACKEND_PORT_BASE="$backend_base" \
    FRONTEND_PORT_BASE="$frontend_base" \
    DB_PORT="$db_port" \
    REDIS_PORT="$redis_port" \
    N8N_PORT_BASE="$n8n_base" \
    ENVCTL_BACKEND_START_CMD="$1 -m http.server {port} --bind 127.0.0.1" \
    ENVCTL_FRONTEND_START_CMD="$1 -m http.server {port} --bind 127.0.0.1" \
    RUN_SH_RUNTIME_DIR="$runtime" PYTHON_BIN="$1" "$2" --repo "$repo" stop >/tmp/envctl_stop_cmd.out
    test ! -f "$runtime/python-engine/run_state.json"
    test ! -f "$runtime/python-engine/runtime_map.json"
    test ! -f "$runtime/python-engine/ports_manifest.json"
    test ! -f "$runtime/python-engine/shell_prune_report.json"
    if ls "$runtime/python-engine/locks/"*.lock >/dev/null 2>&1; then
      echo "locks-still-exist"
      exit 1
    fi

    ENVCTL_BLAST_ALL_ECOSYSTEM=false \
    ENVCTL_REQUIREMENTS_STRICT=false \
    BACKEND_PORT_BASE="$backend_base" \
    FRONTEND_PORT_BASE="$frontend_base" \
    DB_PORT="$db_port" \
    REDIS_PORT="$redis_port" \
    N8N_PORT_BASE="$n8n_base" \
    ENVCTL_BACKEND_START_CMD="$1 -m http.server {port} --bind 127.0.0.1" \
    ENVCTL_FRONTEND_START_CMD="$1 -m http.server {port} --bind 127.0.0.1" \
    RUN_SH_RUNTIME_DIR="$runtime" PYTHON_BIN="$1" "$2" --repo "$repo" blast-all >/tmp/envctl_blast_cmd.out
    test ! -f "$runtime/python-engine/run_state.json"
    test ! -f "$runtime/python-engine/runtime_map.json"
    test ! -f "$runtime/python-engine/ports_manifest.json"
    test ! -f "$runtime/python-engine/shell_prune_report.json"
    if ls "$runtime/python-engine/locks/"*.lock >/dev/null 2>&1; then
      echo "locks-still-exist-after-blast"
      exit 1
    fi

    echo "ok"
  ' _ "$PYTHON_BIN" "$BIN"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}
