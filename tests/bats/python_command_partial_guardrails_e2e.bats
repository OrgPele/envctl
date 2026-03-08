#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "python action commands never masquerade as startup success when targets are missing" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
set -euo pipefail
repo_tmp=$(mktemp -d)
repo="$repo_tmp/repo"
runtime="$repo_tmp/runtime"
mkdir -p "$repo/.git"

check_action_error() {
  local cmd="$1"
  set +e
  out=$(RUN_SH_RUNTIME_DIR="$runtime" PYTHON_BIN="$2" "$3" --repo "$repo" "$cmd" 2>&1)
  rc=$?
  set -e
  echo "$cmd:$rc"
  [[ "$out" != *"envctl Python engine run summary"* ]] || exit 1
  [[ "$out" != *"not yet fully implemented in the Python runtime"* ]] || exit 1
  [ "$rc" -eq 1 ] || exit 1
}

check_action_error test "$1" "$2"
check_action_error pr "$1" "$2"
check_action_error commit "$1" "$2"
check_action_error analyze "$1" "$2"
check_action_error migrate "$1" "$2"
check_action_error delete-worktree "$1" "$2"

set +e
out=$(RUN_SH_RUNTIME_DIR="$runtime" PYTHON_BIN="$1" "$2" --repo "$repo" --command test 2>&1)
rc=$?
set -e
echo "command:test:$rc"
[[ "$out" != *"not yet fully implemented in the Python runtime"* ]] || exit 1
[ "$rc" -eq 1 ] || exit 1

test ! -f "$runtime/python-engine/run_state.json"
echo "ok"
  ' _ "$PYTHON_BIN" "$BIN"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}
