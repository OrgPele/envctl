#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "python --resume loads shell pointer/state compatibility payload" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
set -euo pipefail
repo_tmp=$(mktemp -d)
repo="$repo_tmp/repo"
runtime="$repo_tmp/runtime"
mkdir -p "$repo/.git" "$runtime/python-engine" "$runtime/states"

state_file="$runtime/states/run_legacy.state"
cat > "$state_file" <<'"'"'STATE'"'"'
#!/bin/bash
# envctl State File
export TIMESTAMP="20260224_101500"
export TREES_MODE="false"
declare -a services=(
  "Main Backend|http://localhost:8000|Backend docs"
  "Main Frontend|http://localhost:9000|Frontend docs"
)
declare -A service_info=(
  [Main\ Backend]="321|8000|/tmp/backend.log|backend|/tmp/main/backend"
  [Main\ Frontend]="654|9000|/tmp/frontend.log|frontend|/tmp/main/frontend"
)
declare -A actual_ports=(
  [Main\ Backend]="8010"
  [Main\ Frontend]="9002"
)
STATE

printf "%s\n" "$state_file" > "$runtime/python-engine/.last_state.main"

out=$(RUN_SH_RUNTIME_DIR="$runtime" PYTHON_BIN="$1" "$2" --repo "$repo" --resume)
echo "$out"
[[ "$out" == *"Resumed run_id=20260224_101500"* ]]

RUNTIME_DIR="$runtime" PYTHONPATH="$3/python" "$1" - <<'"'"'PY'"'"'
import json
import os
import pathlib

runtime = pathlib.Path(os.environ["RUNTIME_DIR"]) / "python-engine"
runtime_map = json.loads((runtime / "runtime_map.json").read_text(encoding="utf-8"))
projection = runtime_map["projection"]["Main"]
assert projection["backend_url"] is None, projection
assert projection["frontend_url"] is None, projection
assert projection["backend_status"] == "stale", projection
assert projection["frontend_status"] == "stale", projection
print("ok")
PY
  ' _ "$PYTHON_BIN" "$BIN" "$REPO_ROOT"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}
