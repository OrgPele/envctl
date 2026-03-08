#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "python action command families execute in python mode without unsupported-command fallback" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    repo_tmp=$(mktemp -d)
    repo="$repo_tmp/repo"
    runtime="$repo_tmp/runtime"
    mkdir -p "$repo/.git" "$repo/trees/feature-a/1" "$repo/trees/feature-b/1"

    export RUN_SH_RUNTIME_DIR="$runtime"
    export PYTHON_BIN="$1"
    export ENVCTL_ACTION_TEST_CMD=true
    export ENVCTL_ACTION_PR_CMD=true
    export ENVCTL_ACTION_COMMIT_CMD=true
    export ENVCTL_ACTION_ANALYZE_CMD=true
    export ENVCTL_ACTION_MIGRATE_CMD=true

    for cmd in test pr commit analyze migrate; do
      set +e
      out=$("$2" --repo "$repo" --trees "$cmd" --project feature-a-1 2>&1)
      rc=$?
      set -e
      echo "$cmd:$rc"
      [ "$rc" -eq 0 ] || exit 1
      [[ "$out" != *"not yet fully implemented in the Python runtime"* ]] || exit 1
      [[ "$out" != *"envctl Python engine run summary"* ]] || exit 1
    done

    test -d "$repo/trees/feature-a/1"
    test -d "$repo/trees/feature-b/1"
    "$2" --repo "$repo" --trees delete-worktree --all --yes >/tmp/envctl_actions_delete.out
    test ! -d "$repo/trees/feature-a/1"
    test ! -d "$repo/trees/feature-b/1"
    echo "ok"
  ' _ "$PYTHON_BIN" "$BIN"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}
