#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "shipability gate fails when required implementation scope has untracked files" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    repo_tmp=$(mktemp -d)
    repo="$repo_tmp/repo"
    mkdir -p "$repo"
    git -C "$repo" init >/dev/null
    git -C "$repo" config user.name "Test"
    git -C "$repo" config user.email "test@example.com"
    mkdir -p "$repo/python/envctl_engine"
    echo "x=1" > "$repo/python/envctl_engine/tracked.py"
    git -C "$repo" add python/envctl_engine/tracked.py
    git -C "$repo" commit -m init >/dev/null
    echo "x=2" > "$repo/python/envctl_engine/untracked.py"

    set +e
    out=$(PYTHONPATH="$1/python" "$2" "$1/scripts/release_shipability_gate.py" \
      --repo "$repo" \
      --required-path python/envctl_engine \
      --required-scope python/envctl_engine \
      --skip-parity-sync 2>&1)
    rc=$?
    set -e
    echo "$out"
    [ "$rc" -eq 1 ] || exit 1
    [[ "$out" == *"untracked"* ]] || exit 1
    echo "ok"
  ' _ "$REPO_ROOT" "$PYTHON_BIN"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}
