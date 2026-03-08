#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "python --resume restores stale services when startup is allowed" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    repo_tmp=$(mktemp -d)
    repo="$repo_tmp/repo"
    runtime="$repo_tmp/runtime"
    mkdir -p "$repo/.git" "$repo/backend" "$repo/frontend"
    mkdir -p "$runtime/python-engine"

    cat > "$runtime/python-engine/run_state.json" <<"JSON"
{
  "schema_version": 1,
  "run_id": "run-1",
  "mode": "main",
  "services": {
    "Main Backend": {
      "actual_port": 8000,
      "cwd": "REPO_BACKEND_CWD",
      "name": "Main Backend",
      "pid": 999999,
      "requested_port": 8000,
      "status": "running",
      "synthetic": false,
      "type": "backend"
    }
  },
  "requirements": {},
  "pointers": {},
  "metadata": {
    "project_roots": {
      "Main": "REPO_ROOT_PATH"
    }
  }
}
JSON
    sed -i.bak "s|REPO_BACKEND_CWD|$repo/backend|g" "$runtime/python-engine/run_state.json"
    sed -i.bak "s|REPO_ROOT_PATH|$repo|g" "$runtime/python-engine/run_state.json"

    out=$(RUN_SH_RUNTIME_DIR="$runtime" \
      ENVCTL_RUNTIME_TRUTH_MODE=best_effort \
      POSTGRES_MAIN_ENABLE=false \
      REDIS_ENABLE=false \
      N8N_ENABLE=false \
      SUPABASE_MAIN_ENABLE=false \
      ENVCTL_BACKEND_START_CMD="sh -lc '\''sleep 5'\''" \
      ENVCTL_FRONTEND_START_CMD="sh -lc '\''sleep 5'\''" \
      PYTHON_BIN="$1" \
      "$2" --repo "$repo" --resume --batch)
    echo "$out"

    RUNTIME_DIR="$runtime" PYTHONPATH="$3/python" "$1" - <<"PY"
import json
import os
import pathlib

runtime = pathlib.Path(os.environ["RUNTIME_DIR"]) / "python-engine"
state = json.loads((runtime / "run_state.json").read_text(encoding="utf-8"))
services = state["services"]
backend = services["Main Backend"]
frontend = services["Main Frontend"]
assert backend["pid"] and backend["pid"] != 999999
assert frontend["pid"] and frontend["pid"] > 0
print("ok")
PY
  ' _ "$PYTHON_BIN" "$BIN" "$REPO_ROOT"

  [ "$status" -eq 0 ]
  [[ "$output" == *"Restoring stale services for project Main"* ]]
  [[ "$output" == *"ok"* ]]
}
