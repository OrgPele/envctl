#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "python health degrades when persisted services are stale or unreachable" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    repo_tmp=$(mktemp -d)
    repo="$repo_tmp/repo"
    runtime="$repo_tmp/runtime"
    mkdir -p "$repo/.git" "$runtime/python-engine"

    cat > "$runtime/python-engine/run_state.json" <<JSON
{
  "schema_version": 1,
  "run_id": "run-1",
  "mode": "main",
  "services": {
    "Main Backend": {
      "type": "backend",
      "cwd": "$repo/backend",
      "pid": 999999,
      "requested_port": 8000,
      "actual_port": 8000,
      "log_path": null,
      "status": "running"
    }
  },
  "requirements": {},
  "pointers": {},
  "metadata": {}
}
JSON

    set +e
    out=$(ENVCTL_RUNTIME_TRUTH_MODE=strict RUN_SH_RUNTIME_DIR="$runtime" PYTHON_BIN="$1" "$2" --repo "$repo" --health 2>&1)
    rc=$?
    set -e
    echo "$out"
    [ "$rc" -eq 1 ] || exit 1
    [[ "$out" == *"status=stale"* || "$out" == *"status=unreachable"* ]] || exit 1
    echo "ok"
  ' _ "$PYTHON_BIN" "$BIN"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}
