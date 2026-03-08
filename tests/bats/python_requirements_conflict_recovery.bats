#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "python requirements recover from bind conflicts with non-colliding final ports" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    repo_tmp=$(mktemp -d)
    repo="$repo_tmp/repo"
    runtime="$repo_tmp/runtime"
    base=$((30000 + (RANDOM % 10000)))
    mkdir -p "$repo/.git" "$repo/trees/feature-a-1" "$repo/trees/feature-b-1"

    RUN_SH_RUNTIME_DIR="$runtime" \
    ENVCTL_BACKEND_PORT_BASE="$base" \
    ENVCTL_FRONTEND_PORT_BASE="$((base + 1000))" \
    ENVCTL_DB_PORT_BASE="$((base + 2000))" \
    ENVCTL_REDIS_PORT_BASE="$((base + 3000))" \
    ENVCTL_N8N_PORT_BASE="$((base + 4000))" \
    ENVCTL_RUNTIME_TRUTH_MODE=best_effort \
    ENVCTL_REQUIREMENTS_STRICT=false \
    PYTHON_BIN="$1" \
    ENVCTL_REQUIREMENT_LISTENER_TIMEOUT_SECONDS=0.1 \
    ENVCTL_BACKEND_START_CMD="sh -lc true" \
    ENVCTL_FRONTEND_START_CMD="sh -lc true" \
    ENVCTL_REQUIREMENT_POSTGRES_CMD="sh -lc true" \
    ENVCTL_REQUIREMENT_REDIS_CMD="sh -lc true" \
    ENVCTL_REQUIREMENT_N8N_CMD="sh -lc true" \
    ENVCTL_REQUIREMENT_SUPABASE_CMD="sh -lc true" \
    ENVCTL_TEST_CONFLICT_POSTGRES=1 \
    ENVCTL_TEST_CONFLICT_REDIS=1 \
    ENVCTL_TEST_CONFLICT_N8N=1 \
    "$2" --repo "$repo" --plan feature-a,feature-b --no-parallel-trees --batch

    RUNTIME_DIR="$runtime" PYTHONPATH="$3/python" "$1" - <<"PY"
import json
import os
import pathlib

runtime = pathlib.Path(os.environ["RUNTIME_DIR"]) / "python-engine"
manifest = json.loads((runtime / "ports_manifest.json").read_text(encoding="utf-8"))

db_retries = [project["ports"]["db"]["retries"] for project in manifest["projects"]]
redis_retries = [project["ports"]["redis"]["retries"] for project in manifest["projects"]]
n8n_retries = [project["ports"]["n8n"]["retries"] for project in manifest["projects"]]

assert any(retries >= 1 for retries in db_retries), db_retries
assert any(retries >= 1 for retries in redis_retries), redis_retries
assert any(retries >= 1 for retries in n8n_retries), n8n_retries

all_db = [p["ports"]["db"]["final"] for p in manifest["projects"]]
all_redis = [p["ports"]["redis"]["final"] for p in manifest["projects"]]
all_n8n = [p["ports"]["n8n"]["final"] for p in manifest["projects"]]
assert len(all_db) == len(set(all_db))
assert len(all_redis) == len(set(all_redis))
assert len(all_n8n) == len(set(all_n8n))
print("ok")
PY

    RUN_SH_RUNTIME_DIR="$runtime" \
    PYTHON_BIN="$1" \
    "$2" --repo "$repo" --stop-all >/tmp/envctl_requirements_conflict_stop.out
  ' _ "$PYTHON_BIN" "$BIN" "$REPO_ROOT"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}
