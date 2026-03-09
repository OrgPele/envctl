#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "python pr/commit/review use native defaults when no command is configured" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    repo_tmp=$(mktemp -d)
    repo="$repo_tmp/repo"
    runtime="$repo_tmp/runtime"
    mkdir -p "$repo" "$repo/trees/feature-a/1" "$repo/.venv/bin"
    git -C "$repo" init >/dev/null
    git -C "$repo" config user.name "Test"
    git -C "$repo" config user.email "test@example.com"
    ln -s "$1" "$repo/.venv/bin/python"

    set +e
    RUN_SH_RUNTIME_DIR="$runtime" \
    PYTHON_BIN="$1" \
    "$2" --repo "$repo" --trees pr --project feature-a-1 >"$repo_tmp/pr.out" 2>&1
    pr_rc=$?
    RUN_SH_RUNTIME_DIR="$runtime" \
    PYTHON_BIN="$1" \
    "$2" --repo "$repo" --trees commit --project feature-a-1 >"$repo_tmp/commit.out" 2>&1
    commit_rc=$?
    RUN_SH_RUNTIME_DIR="$runtime" \
    PYTHON_BIN="$1" \
    "$2" --repo "$repo" --trees review --project feature-a-1 >"$repo_tmp/review.out" 2>&1
    review_rc=$?
    set -e

    cat "$repo_tmp/pr.out"
    cat "$repo_tmp/commit.out"
    cat "$repo_tmp/review.out"

    [ "$pr_rc" -eq 0 ] || exit 1
    [ "$commit_rc" -eq 0 ] || exit 1
    [ "$review_rc" -eq 0 ] || exit 1

    grep -q "pr action succeeded" "$repo_tmp/pr.out" || exit 1
    grep -q "commit action succeeded" "$repo_tmp/commit.out" || exit 1
    grep -q "review action succeeded" "$repo_tmp/review.out" || exit 1
    echo "ok"
  ' _ "$PYTHON_BIN" "$BIN"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}
