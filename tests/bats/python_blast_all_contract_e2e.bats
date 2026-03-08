#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "blast-all honors safety guards and succeeds without state" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    tmp=$(mktemp -d)
    repo="$tmp/repo"
    runtime="$tmp/runtime"
    mkdir -p "$repo/.git"
    BIN="$1/bin/envctl"

    out=$(RUN_SH_RUNTIME_DIR="$runtime" ENVCTL_ENGINE_PYTHON_V1=true ENVCTL_BLAST_ALL_ECOSYSTEM=false PYTHON_BIN="$2" \
      "$BIN" --repo "$repo" blast-all 2>&1)
    echo "$out" | grep -q "Stopped runtime state" || exit 1
    echo "ok"
  ' _ "$REPO_ROOT" "$PYTHON_BIN"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}
