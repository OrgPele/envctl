#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "python logs honors tail and no-color flags" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    repo_tmp=$(mktemp -d)
    repo="$repo_tmp/repo"
    runtime="$repo_tmp/runtime"
    log_path="$repo_tmp/backend.log"
    mkdir -p "$repo/.git"
    printf "old-line\n\033[31mnew-line\033[0m plain\n" > "$log_path"

    RUN_REPO_ROOT="$repo" RUN_SH_RUNTIME_DIR="$runtime" LOG_PATH="$log_path" PYTHONPATH="$3/python" "$1" - <<'\''PY'\''
from envctl_engine.config import load_config
from envctl_engine.engine_runtime import PythonEngineRuntime
from envctl_engine.models import RunState, ServiceRecord
from envctl_engine.state import dump_state
import os

repo = os.environ["RUN_REPO_ROOT"]
runtime = os.environ["RUN_SH_RUNTIME_DIR"]
log_path = os.environ["LOG_PATH"]
config = load_config({"RUN_REPO_ROOT": repo, "RUN_SH_RUNTIME_DIR": runtime})
engine = PythonEngineRuntime(config, env={})
state = RunState(
    run_id="run-logs",
    mode="main",
    services={
        "Main Backend": ServiceRecord(
            name="Main Backend",
            type="backend",
            cwd=repo,
            pid=1,
            requested_port=8000,
            actual_port=8000,
            status="running",
            log_path=log_path,
        )
    },
)
dump_state(state, str(engine._run_state_path()))
PY

    set +e
    RUN_SH_RUNTIME_DIR="$runtime" PYTHON_BIN="$1" "$2" --repo "$repo" logs --all --logs-tail 1 --logs-no-color --batch >"$repo_tmp/out" 2>&1
    rc=$?
    set -e
    cat "$repo_tmp/out"
    exit "$rc"
  ' _ "$PYTHON_BIN" "$BIN" "$REPO_ROOT"

  [ "$status" -eq 0 ]
  [[ "$output" == *"new-line plain"* ]]
  [[ "$output" != *$'\033[31m'* ]]
  [[ "$output" != *"old-line"* ]]
}

@test "python logs follow duration streams appended lines" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    repo_tmp=$(mktemp -d)
    repo="$repo_tmp/repo"
    runtime="$repo_tmp/runtime"
    log_path="$repo_tmp/backend.log"
    mkdir -p "$repo/.git"
    printf "boot\n" > "$log_path"

    RUN_REPO_ROOT="$repo" RUN_SH_RUNTIME_DIR="$runtime" LOG_PATH="$log_path" PYTHONPATH="$3/python" "$1" - <<'\''PY'\''
from envctl_engine.config import load_config
from envctl_engine.engine_runtime import PythonEngineRuntime
from envctl_engine.models import RunState, ServiceRecord
from envctl_engine.state import dump_state
import os

repo = os.environ["RUN_REPO_ROOT"]
runtime = os.environ["RUN_SH_RUNTIME_DIR"]
log_path = os.environ["LOG_PATH"]
config = load_config({"RUN_REPO_ROOT": repo, "RUN_SH_RUNTIME_DIR": runtime})
engine = PythonEngineRuntime(config, env={})
state = RunState(
    run_id="run-logs-follow",
    mode="main",
    services={
        "Main Backend": ServiceRecord(
            name="Main Backend",
            type="backend",
            cwd=repo,
            pid=1,
            requested_port=8000,
            actual_port=8000,
            status="running",
            log_path=log_path,
        )
    },
)
dump_state(state, str(engine._run_state_path()))
PY

    (
      sleep 0.3
      printf "follow-line\n" >> "$log_path"
    ) &

    set +e
    RUN_SH_RUNTIME_DIR="$runtime" PYTHON_BIN="$1" "$2" --repo "$repo" logs --all --logs-tail 0 --logs-follow --logs-duration 1 --batch >"$repo_tmp/out" 2>&1
    rc=$?
    set -e
    cat "$repo_tmp/out"
    exit "$rc"
  ' _ "$PYTHON_BIN" "$BIN" "$REPO_ROOT"

  [ "$status" -eq 0 ]
  [[ "$output" == *"follow-line"* ]]
}
