#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "action families run natively without explicit command overrides" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    tmp=$(mktemp -d)
    repo="$tmp/repo"
    runtime="$tmp/runtime"
    mkdir -p "$repo/.git" "$repo/trees/feature-a/1" "$repo/.venv/bin"
    ln -s "$2" "$repo/.venv/bin/python"
    ln -s "$1/python" "$repo/python"
    BIN="$1/bin/envctl"

    git -C "$repo" init >/dev/null
    git -C "$repo" config user.name "Test"
    git -C "$repo" config user.email "test@example.com"

    export RUN_SH_RUNTIME_DIR="$runtime"
    export ENVCTL_ENGINE_PYTHON_V1=true
    export ENVCTL_DEFAULT_MODE=trees
    export PYTHON_BIN="$2"

    out_pr=$(PYTHONPATH="$1/python" "$BIN" --repo "$repo" --trees pr --project feature-a-1 2>&1)
    echo "$out_pr" | grep -q "pr action succeeded" || exit 1

    out_commit=$(PYTHONPATH="$1/python" "$BIN" --repo "$repo" --trees commit --project feature-a-1 2>&1)
    echo "$out_commit" | grep -q "commit action succeeded" || exit 1

    out_review=$(PYTHONPATH="$1/python" "$BIN" --repo "$repo" --trees review --project feature-a-1 2>&1)
    echo "$out_review" | grep -q "review action succeeded" || exit 1

    echo "ok"
  ' _ "$REPO_ROOT" "$PYTHON_BIN"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}
