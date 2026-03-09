#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "requirements adapter base parity suite stays green" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"
  run bash -lc 'PYTHONPATH="$1/python" "$2" -m unittest tests/python/requirements/test_requirements_adapter_base.py tests/python/requirements/test_requirements_adapters_real_contracts.py tests/python/requirements/test_requirements_orchestrator.py tests/python/requirements/test_requirements_retry.py' _ "$REPO_ROOT" "$PYTHON_BIN"
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK"* ]]
}
