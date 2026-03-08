#!/usr/bin/env bash

if [ -z "${PORT_SNAPSHOT+x}" ]; then
    declare -A PORT_SNAPSHOT=()
fi
PORT_SNAPSHOT_READY=${PORT_SNAPSHOT_READY:-false}

if [ -z "${PORT_STATE_CACHE+x}" ]; then
    declare -A PORT_STATE_CACHE=()
fi
PORT_STATE_LOADED=${PORT_STATE_LOADED:-false}
PORT_STATE_SOURCE_FILE="${PORT_STATE_SOURCE_FILE:-}"

if [ -z "${RUN_RESERVED_PORTS+x}" ]; then
    declare -A RUN_RESERVED_PORTS=()
fi

RUN_SH_PORT_RESERVATION_SESSION="${RUN_SH_PORT_RESERVATION_SESSION:-${BASHPID:-$$}}"

port_state_file_path() {
    if [ -n "${PORT_STATE_FILE:-}" ]; then
        echo "$PORT_STATE_FILE"
        return 0
    fi
    if [ -n "${LOGS_DIR:-}" ]; then
        echo "${LOGS_DIR%/}/ports.state"
        return 0
    fi
    echo "/tmp/envctl-ports-${$}.state"
}

port_state_write() {
    local file
    file=$(port_state_file_path)
    [ -n "$file" ] || return 0
    local dir
    dir=$(dirname "$file")
    mkdir -p "$dir" 2>/dev/null || true

    {
        echo "# port|state|label|updated_at"
        local port
        for port in "${!PORT_STATE_CACHE[@]}"; do
            echo "$port|${PORT_STATE_CACHE[$port]}"
        done | sort -n
    } > "$file" 2>/dev/null || true
}

port_state_record() {
    local port=$1
    local label=$2
    local state=$3
    if ! [[ "$port" =~ ^[0-9]+$ ]]; then
        return 0
    fi
    local timestamp=""
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date +"%Y-%m-%dT%H:%M:%SZ")
    PORT_STATE_CACHE["$port"]="${state:-unknown}|${label:-}|${timestamp}"
    port_state_write
}

port_state_load_once() {
    if [ "$PORT_STATE_LOADED" = true ]; then
        return 0
    fi
    PORT_STATE_LOADED=true

    local file=""
    local current_file
    current_file=$(port_state_file_path)
    if [ -f "$current_file" ]; then
        file="$current_file"
    elif [ -n "${LAST_STATE_FILE:-}" ] && [ -f "$LAST_STATE_FILE" ]; then
        local last_state=""
        last_state=$(cat "$LAST_STATE_FILE" 2>/dev/null || true)
        if [ -n "$last_state" ] && [ -f "$last_state" ]; then
            local last_dir
            last_dir=$(dirname "$last_state")
            if [ -f "$last_dir/ports.state" ]; then
                file="$last_dir/ports.state"
            fi
        fi
    fi

    if [ -z "$file" ]; then
        return 0
    fi
    PORT_STATE_SOURCE_FILE="$file"
    local line=""
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        case "$line" in
            \#*) continue ;;
        esac
        local port state label ts
        IFS='|' read -r port state label ts <<< "$line"
        if [[ "$port" =~ ^[0-9]+$ ]]; then
            PORT_STATE_CACHE["$port"]="${state:-unknown}|${label:-}|${ts:-}"
        fi
    done < "$file"
}

port_state_clear() {
    local file
    file=$(port_state_file_path)
    if [ -n "$file" ]; then
        rm -f "$file" 2>/dev/null || true
    fi
    if [ -n "$PORT_STATE_SOURCE_FILE" ] && [ "$PORT_STATE_SOURCE_FILE" != "$file" ]; then
        rm -f "$PORT_STATE_SOURCE_FILE" 2>/dev/null || true
    fi
    PORT_STATE_CACHE=()
    PORT_STATE_SOURCE_FILE=""
    PORT_STATE_LOADED=false
}

port_state_clear_saved() {
    local removed=()
    local file=""

    if [ -n "${PORT_STATE_FILE:-}" ] && [ -f "$PORT_STATE_FILE" ]; then
        rm -f "$PORT_STATE_FILE" 2>/dev/null || true
        removed+=("$PORT_STATE_FILE")
    fi

    if [ -n "${LOGS_DIR:-}" ]; then
        file="${LOGS_DIR%/}/ports.state"
        if [ -f "$file" ]; then
            rm -f "$file" 2>/dev/null || true
            removed+=("$file")
        fi
    fi

    if [ -n "${LAST_STATE_FILE:-}" ] && [ -f "$LAST_STATE_FILE" ]; then
        local last_state=""
        last_state=$(cat "$LAST_STATE_FILE" 2>/dev/null || true)
        if [ -n "$last_state" ]; then
            local last_dir last_ports
            last_dir=$(dirname "$last_state")
            last_ports="$last_dir/ports.state"
            if [ -f "$last_ports" ]; then
                rm -f "$last_ports" 2>/dev/null || true
                removed+=("$last_ports")
            fi
        fi
    fi

    if [ ${#removed[@]} -gt 0 ]; then
        printf '%s\n' "${removed[@]}"
        return 0
    fi
    return 1
}

port_snapshot_enabled() {
    if [ "${RUN_SH_PORT_SNAPSHOT:-false}" != true ]; then
        return 1
    fi
    return 0
}

port_reservation_dir() {
    if [ -n "${RUN_SH_PORT_RESERVATION_ROOT:-}" ]; then
        echo "${RUN_SH_PORT_RESERVATION_ROOT}"
        return 0
    fi
    if [ -n "${LOGS_DIR:-}" ]; then
        echo "${LOGS_DIR%/}/port-reservations"
        return 0
    fi
    local runtime_dir=""
    if [ "$(type -t run_sh_runtime_dir)" = "function" ]; then
        runtime_dir=$(run_sh_runtime_dir)
    else
        runtime_dir="${RUN_SH_RUNTIME_DIR:-/tmp/envctl-runtime}"
        mkdir -p "$runtime_dir" 2>/dev/null || true
    fi
    echo "${runtime_dir%/}/port-reservations"
}

port_reservation_lock_dir() {
    local port=$1
    local dir
    dir=$(port_reservation_dir)
    echo "$dir/$port.lock"
}

port_reservation_write_owner() {
    local lock_dir=$1
    [ -n "$lock_dir" ] || return 1
    local timestamp
    timestamp=$(date +%s 2>/dev/null || echo 0)
    local owner_pid="${BASHPID:-$$}"
    local session_id="${RUN_SH_PORT_RESERVATION_SESSION:-${BASHPID:-$$}}"
    printf '%s|%s|%s\n' "$owner_pid" "$timestamp" "$session_id" > "$lock_dir/owner"
}

port_reservation_reclaim_stale() {
    local lock_dir=$1
    [ -d "$lock_dir" ] || return 1
    local stale_sec="${RUN_SH_PORT_RESERVATION_STALE_SEC:-120}"
    if ! [[ "$stale_sec" =~ ^[0-9]+$ ]]; then
        stale_sec=120
    fi

    local owner_file="$lock_dir/owner"
    local owner_pid=""
    local owner_ts=""
    local owner_session=""
    local now
    now=$(date +%s 2>/dev/null || echo 0)
    if [ ! -f "$owner_file" ]; then
        local dir_ts=0
        dir_ts=$(stat -f %m "$lock_dir" 2>/dev/null || true)
        if ! [[ "$dir_ts" =~ ^[0-9]+$ ]]; then
            dir_ts=$(stat -c %Y "$lock_dir" 2>/dev/null || true)
        fi
        if ! [[ "$dir_ts" =~ ^[0-9]+$ ]]; then
            dir_ts=0
        fi
        local dir_age=$((now - dir_ts))
        if [ "$dir_age" -lt "$stale_sec" ]; then
            return 1
        fi
        rm -rf "$lock_dir" 2>/dev/null || true
        return 0
    else
        IFS='|' read -r owner_pid owner_ts owner_session < "$owner_file"
    fi

    if [ -n "$owner_pid" ] && [[ "$owner_pid" =~ ^[0-9]+$ ]]; then
        if kill -0 "$owner_pid" 2>/dev/null; then
            return 1
        fi
    fi

    if ! [[ "$owner_ts" =~ ^[0-9]+$ ]]; then
        owner_ts=$(stat -f %m "$owner_file" 2>/dev/null || true)
        if ! [[ "$owner_ts" =~ ^[0-9]+$ ]]; then
            owner_ts=$(stat -c %Y "$owner_file" 2>/dev/null || true)
        fi
        if ! [[ "$owner_ts" =~ ^[0-9]+$ ]]; then
            owner_ts=0
        fi
    fi
    local age=$((now - owner_ts))
    if [ "$age" -lt "$stale_sec" ]; then
        return 1
    fi

    rm -rf "$lock_dir" 2>/dev/null || true
    return 0
}

port_is_reserved() {
    local port=$1
    [[ "$port" =~ ^[0-9]+$ ]] || return 1
    local lock_dir
    lock_dir=$(port_reservation_lock_dir "$port")
    if [ ! -d "$lock_dir" ]; then
        return 1
    fi
    local owner_file="$lock_dir/owner"
    local owner_pid=""
    local owner_session=""
    local current_owner_pid="${BASHPID:-$$}"
    local current_session="${RUN_SH_PORT_RESERVATION_SESSION:-${BASHPID:-$$}}"
    if [ -f "$owner_file" ]; then
        IFS='|' read -r owner_pid _ owner_session < "$owner_file"
        if [[ "$owner_pid" =~ ^[0-9]+$ ]] && [ "$owner_pid" = "$current_owner_pid" ]; then
            return 1
        fi
        if [ -n "$owner_session" ] && [ "$owner_session" = "$current_session" ]; then
            return 1
        fi
    fi
    port_reservation_reclaim_stale "$lock_dir" >/dev/null 2>&1 || true
    if [ ! -d "$lock_dir" ]; then
        return 1
    fi
    if [ -f "$owner_file" ]; then
        IFS='|' read -r owner_pid _ owner_session < "$owner_file"
        if [[ "$owner_pid" =~ ^[0-9]+$ ]] && [ "$owner_pid" = "$current_owner_pid" ]; then
            return 1
        fi
        if [ -n "$owner_session" ] && [ "$owner_session" = "$current_session" ]; then
            return 1
        fi
    fi
    return 0
}

port_reserve() {
    local port=$1
    [[ "$port" =~ ^[0-9]+$ ]] || return 1
    local dir
    dir=$(port_reservation_dir)
    mkdir -p "$dir" 2>/dev/null || true
    local lock_dir
    lock_dir=$(port_reservation_lock_dir "$port")
    if mkdir "$lock_dir" 2>/dev/null; then
        port_reservation_write_owner "$lock_dir" >/dev/null 2>&1 || true
        return 0
    fi
    port_reservation_reclaim_stale "$lock_dir" >/dev/null 2>&1 || true
    if mkdir "$lock_dir" 2>/dev/null; then
        port_reservation_write_owner "$lock_dir" >/dev/null 2>&1 || true
        return 0
    fi
    return 1
}

port_release() {
    local port=$1
    [[ "$port" =~ ^[0-9]+$ ]] || return 1
    local lock_dir
    lock_dir=$(port_reservation_lock_dir "$port")
    rm -rf "$lock_dir" 2>/dev/null || true
}

port_release_all() {
    local dir
    dir=$(port_reservation_dir)
    [ -d "$dir" ] || return 0
    local current_owner_pid="${BASHPID:-$$}"
    local current_session="${RUN_SH_PORT_RESERVATION_SESSION:-${BASHPID:-$$}}"
    local lock_dir=""
    for lock_dir in "$dir"/*.lock; do
        [ -d "$lock_dir" ] || continue
        local owner_file="$lock_dir/owner"
        local owner_pid=""
        local owner_session=""
        if [ -f "$owner_file" ]; then
            IFS='|' read -r owner_pid _ owner_session < "$owner_file"
        fi
        if [ -n "$owner_pid" ] && [ "$owner_pid" = "$current_owner_pid" ]; then
            rm -rf "$lock_dir" 2>/dev/null || true
            continue
        fi
        if [ -n "$owner_session" ] && [ "$owner_session" = "$current_session" ]; then
            rm -rf "$lock_dir" 2>/dev/null || true
            continue
        fi
        port_reservation_reclaim_stale "$lock_dir" >/dev/null 2>&1 || true
    done
}

port_snapshot_collect() {
    if command -v lsof >/dev/null 2>&1; then
        lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print $9}' \
            | sed -E 's/.*:([0-9]+).*/\1/' | grep -E '^[0-9]+$'
        return 0
    fi
    if command -v ss >/dev/null 2>&1; then
        ss -ltn 2>/dev/null | awk 'NR>1 {print $4}' \
            | sed -E 's/.*:([0-9]+)$/\1/' | grep -E '^[0-9]+$'
        return 0
    fi
    if command -v netstat >/dev/null 2>&1; then
        netstat -an 2>/dev/null | awk '{print $4}' \
            | sed -E 's/.*[.:]([0-9]+)$/\1/' | grep -E '^[0-9]+$'
        return 0
    fi
    return 1
}

port_snapshot_refresh() {
    PORT_SNAPSHOT=()
    local port=""
    while IFS= read -r port; do
        [ -n "$port" ] && PORT_SNAPSHOT["$port"]=1
    done < <(port_snapshot_collect || true)
    PORT_SNAPSHOT_READY=true
}

is_port_free() {
    local port=$1
    if port_is_reserved "$port"; then
        return 1
    fi
    if port_snapshot_enabled; then
        if [ "$PORT_SNAPSHOT_READY" != true ]; then
            port_snapshot_refresh
        fi
        if [ -n "${PORT_SNAPSHOT[$port]:-}" ]; then
            return 1
        fi
        return 0
    fi
    if command -v lsof >/dev/null 2>&1; then
        ! lsof -i ":$port" >/dev/null 2>&1
        return $?
    fi
    if command -v ss >/dev/null 2>&1; then
        ! ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[.:]${port}$"
        return $?
    fi
    if command -v netstat >/dev/null 2>&1; then
        ! netstat -an 2>/dev/null | grep -qE "[.:]${port}[[:space:]]"
        return $?
    fi
    # Unknown; treat as not free to avoid collisions.
    return 1
}

reserve_port() {
    local port=$1
    local _max_port=${2:-65000}
    while true; do
        if [ -z "${RUN_RESERVED_PORTS[$port]:-}" ] && is_port_free "$port"; then
            if [ "${RUN_SH_OPT_PARALLEL_TREES:-false}" = true ] && [ "${RUN_SH_PARALLEL_WORKER:-false}" = true ] && [ "$(type -t port_reserve)" = "function" ]; then
                if port_reserve "$port"; then
                    RUN_RESERVED_PORTS[$port]=1
                    echo "$port"
                    return 0
                fi
            else
                RUN_RESERVED_PORTS[$port]=1
                echo "$port"
                return 0
            fi
        fi
        port=$((port + 1))
        if [ "$port" -gt "$_max_port" ]; then
            echo "ERROR: No free port found in range" >&2
            return 1
        fi
    done
}

find_free_port() {
    # DEPRECATED: use reserve_port
    reserve_port "$@"
}

wait_for_port() {
    local port=$1
    local timeout=${2:-30}
    local start
    start=$(date +%s)
    while true; do
        if [ "${RUN_SH_FAST_WAIT:-false}" = true ]; then
            if port_is_open_fast "$port"; then
                return 0
            fi
        elif ! is_port_free "$port"; then
            return 0
        fi
        now=$(date +%s)
        if [ $((now - start)) -ge "$timeout" ]; then
            return 1
        fi
        if [ "${RUN_SH_FAST_WAIT:-false}" = true ]; then
            sleep 0.2
        else
            sleep 1
        fi
    done
}

port_is_open_fast() {
    local port=$1
    if [ -z "$port" ]; then
        return 1
    fi
    if [ -n "${BASH_VERSION:-}" ]; then
        (echo >/dev/tcp/127.0.0.1/"$port") >/dev/null 2>&1 && return 0
    fi
    if command -v nc >/dev/null 2>&1; then
        nc -z -w 1 127.0.0.1 "$port" >/dev/null 2>&1 && return 0
    fi
    return 1
}
