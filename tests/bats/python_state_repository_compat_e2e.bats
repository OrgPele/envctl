#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "state repository compatibility contract stays green" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"
  run bash -lc 'PYTHONPATH="$1/python" "$2" -m unittest tests/python/test_state_repository_contract.py tests/python/test_state_shell_compatibility.py' _ "$REPO_ROOT" "$PYTHON_BIN"
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK"* ]]
}
