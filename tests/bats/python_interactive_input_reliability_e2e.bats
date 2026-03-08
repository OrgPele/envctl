#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "interactive dashboard falls back safely without a TTY" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    tmp=$(mktemp -d)
    repo="$tmp/repo"
    runtime="$tmp/runtime"
    mkdir -p "$repo/.git"
    BIN="$1/bin/envctl"

    RUNTIME_DIR="$runtime" PYTHONPATH="$1/python" "$2" - <<"PY"
from pathlib import Path
import os
from envctl_engine.models import RunState, ServiceRecord
from envctl_engine.state import dump_state

runtime = Path(os.environ["RUNTIME_DIR"])
run_dir = runtime / "python-engine"
run_dir.mkdir(parents=True, exist_ok=True)
state = RunState(
    run_id="run-1",
    mode="main",
    services={
        "Main Backend": ServiceRecord(
            name="Main Backend",
            type="backend",
            cwd=str(runtime),
            requested_port=8000,
            actual_port=8001,
            status="running",
        ),
        "Main Frontend": ServiceRecord(
            name="Main Frontend",
            type="frontend",
            cwd=str(runtime),
            requested_port=9000,
            actual_port=9001,
            status="running",
        ),
    },
)
dump_state(state, str(run_dir / "run_state.json"))
PY

    out=$(PYTHONPATH="$1/python" RUN_REPO_ROOT="$repo" RUN_SH_RUNTIME_DIR="$runtime" ENVCTL_ENGINE_PYTHON_V1=true NO_COLOR=1 \
      "$BIN" --repo "$repo" dashboard --interactive 2>&1)
    echo "$out" | grep -q "Interactive dashboard requires a TTY" || exit 1
    echo "$out" | grep -q "Running Services" || exit 1
    echo "ok"
  ' _ "$REPO_ROOT" "$PYTHON_BIN"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}
