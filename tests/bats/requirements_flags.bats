#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  REQUIREMENTS_CORE="$REPO_ROOT/lib/engine/lib/requirements_core.sh"
  REQUIREMENTS_SUPABASE="$REPO_ROOT/lib/engine/lib/requirements_supabase.sh"
  PORTS_LIB="$REPO_ROOT/lib/engine/lib/ports.sh"
  BASH_BIN="$(command -v bash || true)"
}

@test "start_postgres skips when POSTGRES_MAIN_ENABLE=false" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  "$BASH_BIN" -lc 'declare -A __bats_assoc_test=()' >/dev/null 2>&1 || skip "bash with associative arrays required"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    source "$1"
    YELLOW=""
    GREEN=""
    BLUE=""
    RED=""
    NC=""
    ENVCTL_SKIP_DEFAULT_INFRASTRUCTURE=false
    POSTGRES_MAIN_ENABLE=false
    DB_CONTAINER_NAME="envctl-test-postgres"
    DB_PORT=5432
    DB_USER=postgres
    DB_PASSWORD=postgres
    DB_NAME=postgres
    requirements_docker_cmd() {
      echo "docker-called"
      return 1
    }

    start_postgres
  ' _ "$REQUIREMENTS_CORE"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Skipping PostgreSQL container start (POSTGRES_MAIN_ENABLE=false)"* ]]
  [[ "$output" != *"docker-called"* ]]
}

@test "start_redis skips when REDIS_MAIN_ENABLE=false" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  "$BASH_BIN" -lc 'declare -A __bats_assoc_test=()' >/dev/null 2>&1 || skip "bash with associative arrays required"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    source "$1"
    YELLOW=""
    GREEN=""
    BLUE=""
    RED=""
    NC=""
    ENVCTL_SKIP_DEFAULT_INFRASTRUCTURE=false
    REDIS_MAIN_ENABLE=false
    REDIS_CONTAINER_NAME="envctl-test-redis"
    REDIS_PORT=6379
    requirements_docker_cmd() {
      echo "docker-called"
      return 1
    }

    start_redis
  ' _ "$REQUIREMENTS_CORE"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Skipping Redis container start (REDIS_MAIN_ENABLE=false)"* ]]
  [[ "$output" != *"docker-called"* ]]
}

@test "start_redis skips when REDIS_ENABLE=false" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  "$BASH_BIN" -lc 'declare -A __bats_assoc_test=()' >/dev/null 2>&1 || skip "bash with associative arrays required"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    source "$1"
    YELLOW=""
    GREEN=""
    BLUE=""
    RED=""
    NC=""
    ENVCTL_SKIP_DEFAULT_INFRASTRUCTURE=false
    REDIS_ENABLE=false
    REDIS_MAIN_ENABLE=true
    REDIS_CONTAINER_NAME="envctl-test-redis"
    REDIS_PORT=6379
    requirements_docker_cmd() {
      echo "docker-called"
      return 1
    }

    start_redis
  ' _ "$REQUIREMENTS_CORE"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Skipping Redis container start (REDIS_ENABLE=false)"* ]]
  [[ "$output" != *"docker-called"* ]]
}

@test "tree_uses_redis respects global REDIS_ENABLE toggle" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  "$BASH_BIN" -lc 'declare -A __bats_assoc_test=()' >/dev/null 2>&1 || skip "bash with associative arrays required"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    source "$1"
    tmp=$(mktemp -d)
    mkdir -p "$tmp/repo"
    BASE_DIR="$tmp/repo"
    REDIS_ENABLE=false
    REDIS_MAIN_ENABLE=true
    if tree_uses_redis "$tmp/repo"; then
      echo "enabled"
    else
      echo "disabled"
    fi
  ' _ "$REQUIREMENTS_CORE"
  [ "$status" -eq 0 ]
  [[ "$output" == *"disabled"* ]]
}

@test "tree_uses_redis disables main when REDIS_MAIN_ENABLE=false" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  "$BASH_BIN" -lc 'declare -A __bats_assoc_test=()' >/dev/null 2>&1 || skip "bash with associative arrays required"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    source "$1"
    tmp=$(mktemp -d)
    mkdir -p "$tmp/repo"
    BASE_DIR="$tmp/repo"
    REDIS_ENABLE=true
    REDIS_MAIN_ENABLE=false
    if tree_uses_redis "$tmp/repo"; then
      echo "enabled"
    else
      echo "disabled"
    fi
  ' _ "$REQUIREMENTS_CORE"
  [ "$status" -eq 0 ]
  [[ "$output" == *"disabled"* ]]
}

@test "tree_uses_redis supports tree filters and all-trees override" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  "$BASH_BIN" -lc 'declare -A __bats_assoc_test=()' >/dev/null 2>&1 || skip "bash with associative arrays required"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    source "$1"
    tmp=$(mktemp -d)
    mkdir -p "$tmp/repo/tree-alpha"
    BASE_DIR="$tmp/repo"
    REDIS_ENABLE=true
    REDIS_MAIN_ENABLE=false
    REDIS_ALL_TREES=false
    REDIS_TREE_FILTER="tree-alpha"
    if tree_uses_redis "$tmp/repo/tree-alpha"; then
      echo "filter-enabled"
    else
      echo "filter-disabled"
    fi
    REDIS_TREE_FILTER="other-tree"
    if tree_uses_redis "$tmp/repo/tree-alpha"; then
      echo "mismatch-enabled"
    else
      echo "mismatch-disabled"
    fi
    REDIS_ALL_TREES=true
    REDIS_TREE_FILTER="other-tree"
    if tree_uses_redis "$tmp/repo/tree-alpha"; then
      echo "all-trees-enabled"
    else
      echo "all-trees-disabled"
    fi
  ' _ "$REQUIREMENTS_CORE"
  [ "$status" -eq 0 ]
  [[ "$output" == *"filter-enabled"* ]]
  [[ "$output" == *"mismatch-disabled"* ]]
  [[ "$output" == *"all-trees-enabled"* ]]
}

@test "tree_uses_n8n respects global N8N_ENABLE toggle" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  "$BASH_BIN" -lc 'declare -A __bats_assoc_test=()' >/dev/null 2>&1 || skip "bash with associative arrays required"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    source "$1"
    tmp=$(mktemp -d)
    mkdir -p "$tmp/repo"
    cat > "$tmp/repo/docker-compose.yml" <<YAML
services:
  n8n:
    image: n8nio/n8n
YAML
    BASE_DIR="$tmp/repo"
    N8N_ENABLE=false
    N8N_MAIN_ENABLE=true
    if tree_uses_n8n "$tmp/repo"; then
      echo "enabled"
    else
      echo "disabled"
    fi
  ' _ "$REQUIREMENTS_SUPABASE"
  [ "$status" -eq 0 ]
  [[ "$output" == *"disabled"* ]]
}

@test "tree_uses_n8n disables main when N8N_MAIN_ENABLE=false" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  "$BASH_BIN" -lc 'declare -A __bats_assoc_test=()' >/dev/null 2>&1 || skip "bash with associative arrays required"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    source "$1"
    tmp=$(mktemp -d)
    mkdir -p "$tmp/repo"
    cat > "$tmp/repo/docker-compose.yml" <<YAML
services:
  n8n:
    image: n8nio/n8n
YAML
    BASE_DIR="$tmp/repo"
    N8N_ENABLE=true
    N8N_MAIN_ENABLE=false
    if tree_uses_n8n "$tmp/repo"; then
      echo "enabled"
    else
      echo "disabled"
    fi
  ' _ "$REQUIREMENTS_SUPABASE"
  [ "$status" -eq 0 ]
  [[ "$output" == *"disabled"* ]]
}

@test "tree_uses_n8n supports tree filters and all-trees override" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  "$BASH_BIN" -lc 'declare -A __bats_assoc_test=()' >/dev/null 2>&1 || skip "bash with associative arrays required"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    trim() {
      local s="${1:-}"
      s="${s#"${s%%[![:space:]]*}"}"
      s="${s%"${s##*[![:space:]]}"}"
      printf "%s" "$s"
    }
    source "$1"
    tmp=$(mktemp -d)
    mkdir -p "$tmp/repo/tree-alpha"
    cat > "$tmp/repo/tree-alpha/docker-compose.yml" <<YAML
services:
  n8n:
    image: n8nio/n8n
YAML
    BASE_DIR="$tmp/repo"
    N8N_ENABLE=true
    N8N_MAIN_ENABLE=false
    N8N_ALL_TREES=false
    N8N_TREE_FILTER="tree-alpha"
    if tree_uses_n8n "$tmp/repo/tree-alpha"; then
      echo "filter-enabled"
    else
      echo "filter-disabled"
    fi
    N8N_TREE_FILTER="other-tree"
    if tree_uses_n8n "$tmp/repo/tree-alpha"; then
      echo "mismatch-enabled"
    else
      echo "mismatch-disabled"
    fi
    N8N_ALL_TREES=true
    N8N_TREE_FILTER="other-tree"
    if tree_uses_n8n "$tmp/repo/tree-alpha"; then
      echo "all-trees-enabled"
    else
      echo "all-trees-disabled"
    fi
  ' _ "$REQUIREMENTS_SUPABASE"
  [ "$status" -eq 0 ]
  [[ "$output" == *"filter-enabled"* ]]
  [[ "$output" == *"mismatch-disabled"* ]]
  [[ "$output" == *"all-trees-enabled"* ]]
}

@test "reserve_requirement_port uses lock reservation in parallel workers" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  "$BASH_BIN" -lc 'declare -A __bats_assoc_test=()' >/dev/null 2>&1 || skip "bash with associative arrays required"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    source "$1"
    source "$2"
    declare -A service_ports=()
    is_port_free() { return 0; }
    port_state_record() { :; }
    attempts_file=$(mktemp)
    port_reserve() {
      echo 1 >> "$attempts_file"
      local attempts
      attempts=$(wc -l < "$attempts_file" | tr -d " ")
      if [ "$attempts" -eq 1 ]; then
        return 1
      fi
      return 0
    }
    RUN_SH_OPT_PARALLEL_TREES=true
    RUN_SH_PARALLEL_WORKER=true
    port=$(reserve_requirement_port 5432 "" "" "tree:db")
    attempts=$(wc -l < "$attempts_file" | tr -d " ")
    rm -f "$attempts_file"
    echo "port=$port attempts=$attempts"
  ' _ "$PORTS_LIB" "$REQUIREMENTS_CORE"
  [ "$status" -eq 0 ]
  [[ "$output" == *"port=5433 attempts=2"* ]]
}

@test "is_port_free ignores same-process reservations but blocks other workers" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  "$BASH_BIN" -lc 'declare -A __bats_assoc_test=()' >/dev/null 2>&1 || skip "bash with associative arrays required"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    source "$1"
    tmp=$(mktemp -d)
    RUN_SH_PORT_RESERVATION_ROOT="$tmp/locks"
    test_port=""
    for candidate in $(seq 6390 6490); do
      if is_port_free "$candidate"; then
        test_port="$candidate"
        break
      fi
    done
    [ -n "$test_port" ] || { echo "no-free-port"; exit 1; }
    port_reserve "$test_port"
    self_status="blocked"
    if is_port_free "$test_port"; then
      self_status="free"
    fi
    child_script="$tmp/check_other.sh"
    cat > "$child_script" <<CHILD
set -euo pipefail
source "\$1"
RUN_SH_PORT_RESERVATION_ROOT="\$2"
if is_port_free "\$3"; then
  echo free
else
  echo blocked
fi
CHILD
    other_status=$("$2" "$child_script" "$1" "$RUN_SH_PORT_RESERVATION_ROOT" "$test_port")
    rm -rf "$tmp"
    echo "self=${self_status} other=${other_status}"
  ' _ "$PORTS_LIB" "$BASH_BIN"
  [ "$status" -eq 0 ]
  [[ "$output" == *"self=free other=blocked"* ]]
}

@test "port_is_reserved treats same-session subshell reservations as local ownership" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  "$BASH_BIN" -lc 'declare -A __bats_assoc_test=()' >/dev/null 2>&1 || skip "bash with associative arrays required"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    source "$1"
    tmp=$(mktemp -d)
    lock_root="$tmp/locks"
    test_port=45692
    (
      set -euo pipefail
      source "$1"
      RUN_SH_PORT_RESERVATION_ROOT="$lock_root"
      RUN_SH_PORT_RESERVATION_SESSION="shared-session"
      port_reserve "$test_port"
    )
    RUN_SH_PORT_RESERVATION_ROOT="$lock_root"
    RUN_SH_PORT_RESERVATION_SESSION="shared-session"
    if port_is_reserved "$test_port"; then
      same_session=reserved
    else
      same_session=local
    fi
    (
      set -euo pipefail
      source "$1"
      RUN_SH_PORT_RESERVATION_ROOT="$lock_root"
      RUN_SH_PORT_RESERVATION_SESSION="other-session"
      if port_is_reserved "$test_port"; then
        echo "other=reserved"
      else
        echo "other=free"
      fi
    ) > "$tmp/other.out"
    other_status=$(cat "$tmp/other.out")
    rm -rf "$tmp"
    echo "same=$same_session $other_status"
  ' _ "$PORTS_LIB"
  [ "$status" -eq 0 ]
  [[ "$output" == *"same=local other=reserved"* ]]
}

@test "start_tree_redis tolerates stale cache when target container already owns port" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  "$BASH_BIN" -lc 'declare -A __bats_assoc_test=()' >/dev/null 2>&1 || skip "bash with associative arrays required"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    source "$1"
    source "$2"
    YELLOW=""
    GREEN=""
    CYAN=""
    RED=""
    NC=""
    REDIS_CONTAINER_NAME="envctl-test-redis"
    SEED_REQUIREMENTS_ACTIVE=false
    SEED_REQUIREMENTS_MODE=volume
    declare -A service_ports=()
    tree_uses_redis() { return 0; }
    requirement_container_name() { echo "envctl-test-redis-tree"; }
    requirement_volume_name() { echo ""; }
    docker_ps_names_contains() { return 1; }
    docker_ps_all_names_contains() { return 0; }
    docker_ps_cache_refresh() { :; }
    is_port_free() { return 1; }
    requirements_fast_enabled() { return 0; }
    requirements_cache_healthy() { return 1; }
    requirements_cache_record() { :; }
    requirements_docker_probe() { return 0; }
    requirements_docker_cmd() {
      if [ "${1:-}" = "inspect" ] && [ "${2:-}" = "-f" ]; then
        case "${3:-}" in
          "{{.State.Status}}")
            echo "running"
            return 0
            ;;
          "{{(index (index .NetworkSettings.Ports \"6379/tcp\") 0).HostPort}}")
            echo "6380"
            return 0
            ;;
        esac
      fi
      return 0
    }
    start_tree_redis "/tmp/tree" 6380
  ' _ "$PORTS_LIB" "$REQUIREMENTS_CORE"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Redis container already running (envctl-test-redis-tree)"* ]]
}

@test "n8n owner reset skips retry failures when endpoint returns 404" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  "$BASH_BIN" -lc 'declare -A __bats_assoc_test=()' >/dev/null 2>&1 || skip "bash with associative arrays required"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    source "$1"
    YELLOW=""
    GREEN=""
    CYAN=""
    RED=""
    NC=""
    declare -A N8N_OWNER_RESET_DONE=()
    tmp=$(mktemp -d)
    tree="$tmp/tree"
    mkdir -p "$tree"
    resolve_n8n_bootstrap_values() { printf "%s\n" "true" "owner@example.com" "Owner" "User" "secret"; }
    n8n_wait_for_health() { return 0; }
    resolve_n8n_db_name() { echo "n8n"; }
    n8n_owner_email_from_db() { echo ""; }
    run_sh_internal_host() { echo "localhost"; }
    n8n_login_calls=0
    n8n_login_status() {
      n8n_login_calls=$((n8n_login_calls + 1))
      if [ "$n8n_login_calls" -eq 1 ]; then
        echo "401"
      else
        echo "404"
      fi
    }
    supabase_compose_project_name() { echo "proj"; }
    supabase_network_name() { echo "proj_default"; }
    ensure_service_on_supabase_network() { :; }
    supabase_env_file_for_tree() { return 1; }
    supabase_docker_compose() { echo "n8n-container"; }
    supabase_docker_cmd() { return 0; }
    debug_log_line_safe() { :; }
    curl() { echo "404"; }
    n8n_reset_owner_if_needed "$tree" "5678" "5678"
    rm -rf "$tmp"
  ' _ "$REQUIREMENTS_SUPABASE"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Skipping n8n owner bootstrap retry"* ]]
  [[ "$output" != *"✗ n8n owner bootstrap retry failed"* ]]
}

@test "port reservations block sibling workers with different reservation sessions" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  "$BASH_BIN" -lc 'declare -A __bats_assoc_test=()' >/dev/null 2>&1 || skip "bash with associative arrays required"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    source "$1"
    tmp=$(mktemp -d)
    RUN_SH_PORT_RESERVATION_ROOT="$tmp/locks"
    (
      set -euo pipefail
      source "$1"
      RUN_SH_PORT_RESERVATION_ROOT="$tmp/locks"
      RUN_SH_PORT_RESERVATION_SESSION="worker-1"
      port_reserve 6391
      sleep 1
    ) &
    holder_pid=$!
    sleep 0.2
    sibling_result=$(
      (
        set -euo pipefail
        source "$1"
        RUN_SH_PORT_RESERVATION_ROOT="$tmp/locks"
        RUN_SH_PORT_RESERVATION_SESSION="worker-2"
        if is_port_free 6391; then
          echo free
        else
          echo blocked
        fi
      )
    )
    wait "$holder_pid"
    rm -rf "$tmp"
    echo "sibling=${sibling_result}"
  ' _ "$PORTS_LIB"
  [ "$status" -eq 0 ]
  [[ "$output" == *"sibling=blocked"* ]]
}

@test "reserve_requirement_port assigns distinct ports across parallel subshell workers" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  "$BASH_BIN" -lc 'declare -A __bats_assoc_test=()' >/dev/null 2>&1 || skip "bash with associative arrays required"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    tmp=$(mktemp -d)
    base=45670
    (
      set -euo pipefail
      source "$1"
      source "$2"
      RUN_SH_OPT_PARALLEL_TREES=true
      RUN_SH_PARALLEL_WORKER=true
      RUN_SH_PORT_RESERVATION_ROOT="$tmp/locks"
      RUN_SH_PORT_RESERVATION_SESSION="test-session"
      declare -A service_ports=()
      p=$(reserve_requirement_port "$base" "" "" "treeA:n8n")
      echo "$p" > "$tmp/a.port"
      sleep 1
    ) &
    pida=$!
    (
      set -euo pipefail
      source "$1"
      source "$2"
      RUN_SH_OPT_PARALLEL_TREES=true
      RUN_SH_PARALLEL_WORKER=true
      RUN_SH_PORT_RESERVATION_ROOT="$tmp/locks"
      RUN_SH_PORT_RESERVATION_SESSION="test-session"
      declare -A service_ports=()
      p=$(reserve_requirement_port "$base" "" "" "treeB:n8n")
      echo "$p" > "$tmp/b.port"
      sleep 1
    ) &
    pidb=$!
    wait "$pida"
    wait "$pidb"
    pa=$(cat "$tmp/a.port")
    pb=$(cat "$tmp/b.port")
    rm -rf "$tmp"
    echo "a=$pa b=$pb"
  ' _ "$PORTS_LIB" "$REQUIREMENTS_CORE"
  [ "$status" -eq 0 ]
  [[ "$output" == *"a="* ]]
  [[ "$output" == *"b="* ]]
  [[ "$output" != *"a=45670 b=45670"* ]]
}
