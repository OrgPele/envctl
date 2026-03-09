#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "process probe contract and fallback listener detection stay green" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"
  run bash -lc 'PYTHONPATH="$1/python" "$2" -m unittest tests/python/shared/test_process_probe_contract.py tests/python/shared/test_process_runner_listener_detection.py' _ "$REPO_ROOT" "$PYTHON_BIN"
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK"* ]]
}
