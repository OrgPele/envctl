#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "python config can disable main startup and operational startup is blocked" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    repo_tmp=$(mktemp -d)
    repo="$repo_tmp/repo"
    runtime="$repo_tmp/runtime"
    mkdir -p "$repo/.git"

    RUN_SH_RUNTIME_DIR="$runtime" "$1" --repo "$repo" config --set MAIN_STARTUP_ENABLE=false --headless >/tmp/envctl_config.out
    RUN_SH_RUNTIME_DIR="$runtime" "$1" --repo "$repo" explain-startup --json >/tmp/envctl_explain.json

    RUNTIME_DIR="$runtime" PYTHONPATH="$2/python" "$3" - <<"PY"
import json
import pathlib

payload = json.loads(pathlib.Path("/tmp/envctl_explain.json").read_text(encoding="utf-8"))
assert payload["mode"] == "main", payload
assert payload["startup_enabled"] is False, payload
assert payload["reason"] == "config_startup_disabled", payload
assert payload["services"] == {"backend": False, "frontend": False}, payload
assert payload["dependencies"] == [], payload
print("explain-ok")
PY

    set +e
    RUN_SH_RUNTIME_DIR="$runtime" "$1" --repo "$repo" start >/tmp/envctl_start.out 2>&1
    status=$?
    set -e

    cat /tmp/envctl_start.out
    echo "status=$status"
  ' _ "$BIN" "$REPO_ROOT" "$PYTHON_BIN"

  [ "$status" -eq 0 ]
  [[ "$output" == *"explain-ok"* ]]
  [[ "$output" == *"envctl runs are disabled for main in .envctl. Run 'envctl config' to enable them."* ]]
  [[ "$output" == *"status=1"* ]]
}
