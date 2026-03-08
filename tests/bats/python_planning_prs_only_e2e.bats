#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "python --planning-prs runs PR actions and skips service startup" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    repo_tmp=$(mktemp -d)
    repo="$repo_tmp/repo"
    runtime="$repo_tmp/runtime"
    mkdir -p "$repo/.git"
    mkdir -p "$repo/trees/feature-a/1"

    set +e
    RUN_SH_RUNTIME_DIR="$runtime" \
    ENVCTL_ACTION_PR_CMD=true \
    PYTHON_BIN="$1" \
    "$2" --repo "$repo" --planning-prs feature-a --batch >"$repo_tmp/out" 2>&1
    rc=$?
    set -e
    cat "$repo_tmp/out"
    exit "$rc"
  ' _ "$PYTHON_BIN" "$BIN"

  [ "$status" -eq 0 ]
  [[ "$output" == *"pr action succeeded for feature-a-1."* ]]
  [[ "$output" == *"Planning PR mode complete; skipping service startup."* ]]
  [[ "$output" != *"envctl Python engine run summary"* ]]
}
