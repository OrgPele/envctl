#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "python dashed command aliases do not silently route to startup" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    repo_tmp=$(mktemp -d)
    repo="$repo_tmp/repo"
    runtime="$repo_tmp/runtime"
    mkdir -p "$repo/.git"

    run_cmd() {
      local cmd="$1"
      shift || true
      set +e
      out=$(RUN_SH_RUNTIME_DIR="$runtime" PYTHON_BIN="$1" "$2" --repo "$repo" "$cmd" 2>&1)
      rc=$?
      set -e
      echo "$cmd:$rc"
      if [[ "$out" == *"envctl Python engine run summary"* ]]; then
        echo "unexpected-start:$cmd"
        exit 1
      fi
      if [ "$cmd" = "--doctor" ] || [ "$cmd" = "--dashboard" ]; then
        [ "$rc" -eq 0 ] || exit 1
      else
        [ "$rc" -eq 1 ] || exit 1
      fi
    }

    run_cmd --doctor "$1" "$2"
    run_cmd --dashboard "$1" "$2"
    run_cmd --logs "$1" "$2"
    run_cmd --health "$1" "$2"
    run_cmd --errors "$1" "$2"
    run_cmd --test "$1" "$2"
    run_cmd --pr "$1" "$2"
    run_cmd --commit "$1" "$2"
    run_cmd --analyze "$1" "$2"
    run_cmd --migrate "$1" "$2"

    [ ! -f "$runtime/python-engine/run_state.json" ]
    echo "ok"
  ' _ "$PYTHON_BIN" "$BIN"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}
