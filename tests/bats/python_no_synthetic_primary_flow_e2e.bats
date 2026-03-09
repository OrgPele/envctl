#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "strict profile blocks synthetic defaults in primary flow" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    tmp=$(mktemp -d)
    repo="$tmp/repo"
    runtime="$tmp/runtime"
    mkdir -p "$repo/.git" "$repo/backend" "$repo/frontend"
    printf "ENVCTL_DEFAULT_MODE=main\n" >"$repo/.envctl"

    set +e
    out=$(PYTHONPATH="$1/python" \
      RUN_REPO_ROOT="$repo" \
      RUN_SH_RUNTIME_DIR="$runtime" \
      POSTGRES_MAIN_ENABLE=false \
      REDIS_ENABLE=false \
      N8N_ENABLE=false \
      SUPABASE_MAIN_ENABLE=false \
      ENVCTL_RUNTIME_TRUTH_MODE=strict \
      ENVCTL_ALLOW_SYNTHETIC_DEFAULTS=true \
      ENVCTL_SYNTHETIC_TEST_MODE=true \
      BATCH=true \
      "$2" -m envctl_engine.runtime.cli start --main 2>&1)
    rc=$?
    set -e
    echo "$out"
    [ "$rc" -ne 0 ] || exit 1
    [[ "$out" == *"missing_service_start_command"* ]] || exit 1
    echo "ok"
  ' _ "$REPO_ROOT" "$PYTHON_BIN"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}

@test "strict profile blocks dashboard when saved state is synthetic" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    tmp=$(mktemp -d)
    repo="$tmp/repo"
    runtime="$tmp/runtime"
    mkdir -p "$repo/.git"
    printf "ENVCTL_DEFAULT_MODE=main\n" >"$repo/.envctl"

    RUNTIME_DIR="$runtime" PYTHONPATH="$1/python" "$2" - <<"PY"
from pathlib import Path
import os
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.state import dump_state

runtime = Path(os.environ["RUNTIME_DIR"])
run_dir = runtime / "python-engine"
run_dir.mkdir(parents=True, exist_ok=True)
state = RunState(
    run_id="run-synthetic",
    mode="main",
    services={
        "Main Backend": ServiceRecord(
            name="Main Backend",
            type="backend",
            cwd=str(runtime),
            requested_port=8000,
            actual_port=8000,
            status="running",
            synthetic=True,
        )
    },
)
dump_state(state, str(run_dir / "run_state.json"))
PY

    set +e
    out=$(PYTHONPATH="$1/python" \
      RUN_REPO_ROOT="$repo" \
      RUN_SH_RUNTIME_DIR="$runtime" \
      ENVCTL_ENGINE_PYTHON_V1=true \
      ENVCTL_RUNTIME_TRUTH_MODE=strict \
      "$2" -m envctl_engine.runtime.cli dashboard 2>&1)
    rc=$?
    set -e
    echo "$out"
    [ "$rc" -ne 0 ] || exit 1
    [[ "$out" == *"Dashboard blocked: synthetic placeholder defaults detected"* ]] || exit 1
    echo "ok"
  ' _ "$REPO_ROOT" "$PYTHON_BIN"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}
