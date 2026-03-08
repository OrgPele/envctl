#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  RUN_ALL_TREES_HELPERS="$REPO_ROOT/lib/engine/lib/run_all_trees_helpers.sh"
  BASH_BIN="$(command -v bash || true)"
}

@test "start_tree_job_with_offset applies assigned offset when env ports equal base defaults" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  "$BASH_BIN" -lc 'declare -A __bats_assoc_test=()' >/dev/null 2>&1 || skip "bash with associative arrays required"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    source "$1"
    BACKEND_PORT_BASE=8000
    FRONTEND_PORT_BASE=9000
    USE_FEATURE_LABELS=false
    read_env_value() {
      local _file=$1
      local key=$2
      if [ "$key" = "BACKEND_PORT" ]; then
        echo 8000
      elif [ "$key" = "FRONTEND_PORT" ]; then
        echo 9000
      fi
    }
    read_ports_from_worktree_config() { echo ""; }
    start_project_with_attach() {
      local _label=$1
      local _dir=$2
      local backend=$3
      local frontend=$4
      echo "backend=$backend frontend=$frontend"
    }
    start_tree_job_with_offset "/tmp/tree-alpha" "" 1 false 20
  ' _ "$RUN_ALL_TREES_HELPERS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"backend=8020 frontend=9020"* ]]
}

@test "start_tree_job_with_offset preserves explicit non-default env ports" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  "$BASH_BIN" -lc 'declare -A __bats_assoc_test=()' >/dev/null 2>&1 || skip "bash with associative arrays required"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    source "$1"
    BACKEND_PORT_BASE=8000
    FRONTEND_PORT_BASE=9000
    USE_FEATURE_LABELS=false
    read_env_value() {
      local _file=$1
      local key=$2
      if [ "$key" = "BACKEND_PORT" ]; then
        echo 8110
      elif [ "$key" = "FRONTEND_PORT" ]; then
        echo 9123
      fi
    }
    read_ports_from_worktree_config() { echo ""; }
    start_project_with_attach() {
      local _label=$1
      local _dir=$2
      local backend=$3
      local frontend=$4
      echo "backend=$backend frontend=$frontend"
    }
    start_tree_job_with_offset "/tmp/tree-beta" "" 1 false 20
  ' _ "$RUN_ALL_TREES_HELPERS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"backend=8110 frontend=9123"* ]]
}
