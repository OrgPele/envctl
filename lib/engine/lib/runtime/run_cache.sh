#!/usr/bin/env bash

# Run cache helpers for fast startup.

RUN_CACHE_LOADED=${RUN_CACHE_LOADED:-false}
RUN_CACHE_TREE_PATHS_SIG=${RUN_CACHE_TREE_PATHS_SIG:-}
RUN_CACHE_TREE_PATHS=()

run_cache_ensure_assoc_array() {
    local name=$1
    [ -n "$name" ] || return 1
    local decl=""
    decl=$(declare -p "$name" 2>/dev/null || true)
    if [[ "$decl" == "declare -A"* ]]; then
        return 0
    fi
    unset "$name"
    if declare -g -A "$name" 2>/dev/null; then
        return 0
    fi
    declare -A "$name"
}

run_cache_ensure_assoc_array RUN_CACHE_DIR_BACKEND
run_cache_ensure_assoc_array RUN_CACHE_DIR_FRONTEND
run_cache_ensure_assoc_array RUN_CACHE_DIR_SIG
run_cache_ensure_assoc_array RUN_CACHE_TREE_PORTS
run_cache_ensure_assoc_array RUN_CACHE_TREE_PORT_SIG
run_cache_ensure_assoc_array RUN_CACHE_REQ_STATUS
run_cache_ensure_assoc_array RUN_CACHE_REQ_TS

run_cache_path() {
    local runtime_dir=""
    if [ "$(type -t run_sh_runtime_dir)" = "function" ]; then
        runtime_dir=$(run_sh_runtime_dir)
    else
        runtime_dir="${RUN_SH_RUNTIME_DIR:-/tmp/envctl-runtime}"
        mkdir -p "$runtime_dir" 2>/dev/null || true
    fi
    echo "${runtime_dir%/}/.run-cache"
}

run_cache_load() {
    if [ "$RUN_CACHE_LOADED" = true ]; then
        return 0
    fi
    RUN_CACHE_LOADED=true

    if [ "${RUN_SH_REFRESH_CACHE:-false}" = true ]; then
        return 0
    fi

    local file
    file=$(run_cache_path)
    [ -f "$file" ] || return 0

    local line
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        case "$line" in
            \#*) continue ;;
        esac
        local key rest
        IFS='|' read -r key rest <<< "$line"
        case "$key" in
            tree_paths_sig)
                RUN_CACHE_TREE_PATHS_SIG="$rest"
                ;;
            tree_paths)
                RUN_CACHE_TREE_PATHS=()
                if [ -n "$rest" ]; then
                    IFS=';' read -r -a RUN_CACHE_TREE_PATHS <<< "$rest"
                fi
                ;;
            dir_cache)
                local base_dir sig backend frontend
                IFS='|' read -r key base_dir sig backend frontend <<< "$line"
                [ -n "$base_dir" ] || continue
                RUN_CACHE_DIR_SIG["$base_dir"]="$sig"
                RUN_CACHE_DIR_BACKEND["$base_dir"]="$backend"
                RUN_CACHE_DIR_FRONTEND["$base_dir"]="$frontend"
                ;;
            tree_ports)
                local tree_dir sig backend frontend db redis
                IFS='|' read -r key tree_dir sig backend frontend db redis <<< "$line"
                [ -n "$tree_dir" ] || continue
                RUN_CACHE_TREE_PORT_SIG["$tree_dir"]="$sig"
                RUN_CACHE_TREE_PORTS["$tree_dir"]="${backend:-}|${frontend:-}|${db:-}|${redis:-}"
                ;;
            requirements)
                local label ts status
                IFS='|' read -r key label ts status <<< "$line"
                [ -n "$label" ] || continue
                RUN_CACHE_REQ_TS["$label"]="$ts"
                RUN_CACHE_REQ_STATUS["$label"]="$status"
                ;;
        esac
    done < "$file"
}

run_cache_set_tree_paths() {
    local sig=$1
    shift
    RUN_CACHE_TREE_PATHS_SIG="$sig"
    RUN_CACHE_TREE_PATHS=("$@")
}

run_cache_set_dir_cache() {
    local base_dir=$1
    local sig=$2
    local backend_dir=$3
    local frontend_dir=$4
    [ -n "$base_dir" ] || return 1
    [ -n "$sig" ] || return 1

    RUN_CACHE_DIR_SIG["$base_dir"]="$sig"
    if [ -n "$backend_dir" ]; then
        RUN_CACHE_DIR_BACKEND["$base_dir"]="$backend_dir"
    fi
    if [ -n "$frontend_dir" ]; then
        RUN_CACHE_DIR_FRONTEND["$base_dir"]="$frontend_dir"
    fi
}

run_cache_set_tree_ports() {
    local tree_dir=$1
    local sig=$2
    local backend_port=$3
    local frontend_port=$4
    local db_port=${5:-}
    local redis_port=${6:-}
    [ -n "$tree_dir" ] || return 1
    [ -n "$sig" ] || return 1
    RUN_CACHE_TREE_PORT_SIG["$tree_dir"]="$sig"
    RUN_CACHE_TREE_PORTS["$tree_dir"]="${backend_port:-}|${frontend_port:-}|${db_port:-}|${redis_port:-}"
}

run_cache_tree_ports_for_dir() {
    local tree_dir=$1
    local sig=${2:-}
    [ -n "$tree_dir" ] || return 1
    local cached_sig="${RUN_CACHE_TREE_PORT_SIG[$tree_dir]:-}"
    if [ -n "$sig" ] && [ -n "$cached_sig" ] && [ "$sig" != "$cached_sig" ]; then
        return 1
    fi
    local ports="${RUN_CACHE_TREE_PORTS[$tree_dir]:-}"
    [ -n "$ports" ] || return 1
    echo "$ports"
}

run_cache_set_requirements() {
    local label=$1
    local status=$2
    local ts=${3:-}
    [ -n "$label" ] || return 1
    if [ -z "$ts" ]; then
        ts=$(date +%s)
    fi
    RUN_CACHE_REQ_STATUS["$label"]="$status"
    RUN_CACHE_REQ_TS["$label"]="$ts"
}

run_cache_requirements_fresh() {
    local label=$1
    local ttl=${2:-0}
    [ -n "$label" ] || return 1
    [ "$ttl" -gt 0 ] || return 1
    local status="${RUN_CACHE_REQ_STATUS[$label]:-}"
    local ts="${RUN_CACHE_REQ_TS[$label]:-0}"
    local now
    now=$(date +%s)
    if [ "$status" = "healthy" ] && [ "$ts" -gt 0 ] && [ $((now - ts)) -le "$ttl" ]; then
        return 0
    fi
    return 1
}

run_cache_save() {
    if [ "${RUN_SH_FAST_STARTUP:-false}" != true ] && [ "${RUN_SH_REFRESH_CACHE:-false}" != true ]; then
        return 0
    fi

    local file
    file=$(run_cache_path)
    mkdir -p "$(dirname "$file")"

    {
        echo "# envctl run cache"
        echo "version|1"
        if [ -n "$RUN_CACHE_TREE_PATHS_SIG" ]; then
            echo "tree_paths_sig|$RUN_CACHE_TREE_PATHS_SIG"
        fi
        if [ ${#RUN_CACHE_TREE_PATHS[@]} -gt 0 ]; then
            local joined=""
            joined=$(IFS=';'; echo "${RUN_CACHE_TREE_PATHS[*]}")
            echo "tree_paths|$joined"
        fi
        local base_dir
        for base_dir in "${!RUN_CACHE_DIR_SIG[@]}"; do
            echo "dir_cache|$base_dir|${RUN_CACHE_DIR_SIG[$base_dir]:-}|${RUN_CACHE_DIR_BACKEND[$base_dir]:-}|${RUN_CACHE_DIR_FRONTEND[$base_dir]:-}"
        done
        local tree_dir
        for tree_dir in "${!RUN_CACHE_TREE_PORT_SIG[@]}"; do
            local ports="${RUN_CACHE_TREE_PORTS[$tree_dir]:-}"
            local backend=""
            local frontend=""
            local db=""
            local redis=""
            IFS='|' read -r backend frontend db redis <<< "$ports"
            echo "tree_ports|$tree_dir|${RUN_CACHE_TREE_PORT_SIG[$tree_dir]:-}|${backend:-}|${frontend:-}|${db:-}|${redis:-}"
        done
        local label
        for label in "${!RUN_CACHE_REQ_STATUS[@]}"; do
            echo "requirements|$label|${RUN_CACHE_REQ_TS[$label]:-0}|${RUN_CACHE_REQ_STATUS[$label]:-}"
        done
    } > "$file"
}
