#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  SERVICES_LIFECYCLE="$REPO_ROOT/lib/engine/lib/services_lifecycle.sh"
  BASH_BIN="$(command -v bash || true)"
}

@test "service_wait_for_bound_port returns nearest listener in process tree" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  "$BASH_BIN" -lc 'declare -A __bats_assoc_test=()' >/dev/null 2>&1 || skip "bash with associative arrays required"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    source "$1"
    service_listener_ports_for_tree() {
      printf "%s\n" "9002" "24678"
    }
    port=$(service_wait_for_bound_port "$$" 9000 1)
    echo "port=$port"
  ' _ "$SERVICES_LIFECYCLE"
  [ "$status" -eq 0 ]
  [[ "$output" == *"port=9002"* ]]
}

@test "start_service_with_retry stores detected actual port" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  "$BASH_BIN" -lc 'declare -A __bats_assoc_test=()' >/dev/null 2>&1 || skip "bash with associative arrays required"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    source "$1"
    FORCE_PORTS=true
    declare -A actual_ports=()
    start_service() {
      local name=$1
      local type=$3
      service_record_actual_port "$name" "$type" "9002"
      return 0
    }
    maybe_release_reserved_port() { :; }
    start_service_with_retry "Demo" "/tmp" "frontend" "9000" "" "/tmp/envctl-test-logs"
    echo "actual=${actual_ports["Demo Frontend"]:-}"
  ' _ "$SERVICES_LIFECYCLE"
  [ "$status" -eq 0 ]
  [[ "$output" == *"actual=9002"* ]]
}

@test "start_service_with_retry clears transient failed entries after successful retry" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  "$BASH_BIN" -lc 'declare -A __bats_assoc_test=()' >/dev/null 2>&1 || skip "bash with associative arrays required"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    source "$1"
    YELLOW=""
    RED=""
    BLUE=""
    NC=""
    FORCE_PORTS=false
    declare -A actual_ports=()
    declare -a failed_services=()
    attempts=0
    start_service() {
      attempts=$((attempts + 1))
      if [ "$attempts" -eq 1 ]; then
        failed_services+=("Demo Backend|/tmp/fail.log")
        return 1
      fi
      service_record_actual_port "Demo" "backend" "8010"
      return 0
    }
    is_port_binding_error() { return 0; }
    service_next_retry_port() { echo "8010"; }
    reserve_port() { echo "$1"; }
    maybe_release_reserved_port() { :; }
    service_log_dir_for_attempt() { echo "/tmp/envctl-test-logs"; }
    sleep() { :; }
    start_service_with_retry "Demo" "/tmp" "backend" "8000" "" "/tmp/envctl-test-logs"
    echo "attempts=$attempts failures=${#failed_services[@]}"
  ' _ "$SERVICES_LIFECYCLE"
  [ "$status" -eq 0 ]
  [[ "$output" == *"attempts=2 failures=0"* ]]
}
