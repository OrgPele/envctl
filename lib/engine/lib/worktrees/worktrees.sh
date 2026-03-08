#!/usr/bin/env bash

if [ -z "${TREE_PATHS_CACHE+x}" ]; then
    declare -A TREE_PATHS_CACHE=()
fi
if [ -z "${TREE_PATHS_CACHE_SIG+x}" ]; then
    declare -A TREE_PATHS_CACHE_SIG=()
fi
if [ -z "${WORKTREE_PORT_CACHE+x}" ]; then
    declare -A WORKTREE_PORT_CACHE=()
fi
if [ -z "${WORKTREE_PORT_CACHE_FEATURE+x}" ]; then
    declare -A WORKTREE_PORT_CACHE_FEATURE=()
fi

worktree_cache_enabled() {
    if [ "${RUN_SH_FAST_STARTUP:-false}" != true ]; then
        return 1
    fi
    return 0
}

worktree_port_cache_enabled() {
    if ! worktree_cache_enabled; then
        return 1
    fi
    if [ "${RUN_SH_DISABLE_PORT_CACHE:-false}" = true ]; then
        return 1
    fi
    return 0
}

_ports_file_lock_reclaim_stale() {
    local target_lock_dir=$1
    local target_stale_sec=$2
    [ -d "$target_lock_dir" ] || return 1

    local owner_file="$target_lock_dir/owner"
    local owner_pid=""
    local owner_ts=""
    if [ -f "$owner_file" ]; then
        IFS='|' read -r owner_pid owner_ts < "$owner_file"
    fi

    local now
    now=$(date +%s 2>/dev/null || echo 0)
    if [ -n "$owner_pid" ] && [[ "$owner_pid" =~ ^[0-9]+$ ]]; then
        if kill -0 "$owner_pid" 2>/dev/null; then
            return 1
        fi
    fi

    if ! [[ "$owner_ts" =~ ^[0-9]+$ ]]; then
        owner_ts=0
    fi

    local age=$((now - owner_ts))
    if [ "$age" -lt "$target_stale_sec" ]; then
        return 1
    fi

    rm -rf "$target_lock_dir" 2>/dev/null || true
    return 0
}

ports_file_lock_acquire() {
    local ports_file=$1
    [ -n "$ports_file" ] || return 1
    local lock_dir="${ports_file}.lockdir"
    local attempts="${RUN_SH_WORKTREE_LOCK_ATTEMPTS:-200}"
    local stale_sec="${RUN_SH_WORKTREE_LOCK_STALE_SEC:-120}"
    if ! [[ "$attempts" =~ ^[0-9]+$ ]]; then
        attempts=200
    fi
    if ! [[ "$stale_sec" =~ ^[0-9]+$ ]]; then
        stale_sec=120
    fi
    local waited=0

    while ! mkdir "$lock_dir" 2>/dev/null; do
        _ports_file_lock_reclaim_stale "$lock_dir" "$stale_sec" >/dev/null 2>&1 || true
        sleep 0.05
        waited=$((waited + 1))
        if [ "$waited" -ge "$attempts" ]; then
            return 1
        fi
    done
    local timestamp
    timestamp=$(date +%s 2>/dev/null || echo 0)
    printf '%s|%s\n' "$$" "$timestamp" > "$lock_dir/owner"
    echo "$lock_dir"
}

ports_file_lock_release() {
    local lock_dir=$1
    [ -n "$lock_dir" ] || return 0
    rm -rf "$lock_dir" 2>/dev/null || true
}

worktree_path_mtime() {
    local path=$1
    [ -n "$path" ] || return 1
    if command -v stat >/dev/null 2>&1; then
        local ts=""
        ts=$(stat -f %m "$path" 2>/dev/null || true)
        if ! [[ "$ts" =~ ^[0-9]+$ ]]; then
            ts=$(stat -c %Y "$path" 2>/dev/null || true)
        fi
        if [[ "$ts" =~ ^[0-9]+$ ]]; then
            echo "$ts"
            return 0
        fi
    fi
    echo "0"
}

worktree_roots_signature() {
    local roots=("$@")
    local sig=""
    local root
    for root in "${roots[@]}"; do
        [ -n "$root" ] || continue
        sig+="${root}:$(worktree_path_mtime "$root");"
    done
    echo "$sig"
}

tree_config_signature() {
    local tree_dir=$1
    [ -n "$tree_dir" ] || return 1
    local env_file="${tree_dir%/}/.env"
    local env_mtime
    env_mtime=$(worktree_path_mtime "$env_file")

    local ports_mtime="0"
    local identity
    identity=$(worktree_identity_from_dir "$tree_dir" "${BASE_DIR:-}" "${TREES_DIR_NAME:-trees}" 2>/dev/null || true)
    if [ -n "$identity" ]; then
        local feature="${identity%%|*}"
        local ports_file="${BASE_DIR:-.}/.envctl-workspaces/${feature}.ports"
        ports_mtime=$(worktree_path_mtime "$ports_file")
    fi

    echo "${env_mtime}:${ports_mtime}"
}

worktree_cache_record_tree_paths() {
    local sig=$1
    shift
    if [ "$sig" = "" ]; then
        return 1
    fi
    if [ "$(type -t run_cache_set_tree_paths)" = "function" ]; then
        run_cache_set_tree_paths "$sig" "$@"
    fi
}

worktree_cache_record_ports() {
    local tree_dir=$1
    local backend_port=$2
    local frontend_port=$3
    local db_port=${4:-}
    local redis_port=${5:-}
    if [ "$(type -t run_cache_set_tree_ports)" = "function" ]; then
        local sig
        sig=$(tree_config_signature "$tree_dir")
        run_cache_set_tree_ports "$tree_dir" "$sig" "$backend_port" "$frontend_port" "$db_port" "$redis_port"
    fi
}

list_numeric_dir_names() {
    local dir=$1
    [ -d "$dir" ] || return 0
    find "$dir" -maxdepth 1 -type d -name "[0-9]*" -print 2>/dev/null | sed 's|.*/||' | sort -n
}

list_numeric_dirs() {
    local dir=$1
    [ -d "$dir" ] || return 0
    find "$dir" -maxdepth 1 -type d -name "[0-9]*" -print 2>/dev/null | sort
}

count_numeric_dir_names() {
    local dir=$1
    local count=0
    count=$(list_numeric_dir_names "$dir" | wc -l | tr -d ' ')
    echo "$count"
}

discover_tree_roots() {
    local base_dir=$1
    local trees_dir_name=$2

    local normalized="${trees_dir_name%/}"
    if [[ "$normalized" = /* ]]; then
        if [ -d "$normalized" ]; then
            printf '%s\n' "$normalized"
        fi
        return 0
    fi

    if [ -d "$base_dir/$normalized" ]; then
        printf '%s\n' "$base_dir/$normalized"
    fi

    for candidate in "$base_dir"/trees-*; do
        [ -d "$candidate" ] || continue
        printf '%s\n' "$candidate"
    done
}

list_tree_paths() {
    local base_dir=$1
    local trees_dir_name=$2

    local roots=()
    while IFS= read -r root; do
        [ -n "$root" ] && roots+=("$root")
    done < <(discover_tree_roots "$base_dir" "$trees_dir_name")

    local cache_key="${base_dir}|${trees_dir_name}"
    local sig
    sig=$(worktree_roots_signature "${roots[@]}")

    if worktree_cache_enabled; then
        local cached_sig="${TREE_PATHS_CACHE_SIG[$cache_key]:-}"
        if [ -n "$cached_sig" ] && [ "$cached_sig" = "$sig" ]; then
            if [ "$(type -t profile_counter_increment)" = "function" ]; then
                profile_counter_increment "tree_paths.cache_hit"
            fi
            local cached="${TREE_PATHS_CACHE[$cache_key]:-}"
            if [ -n "$cached" ]; then
                printf '%s\n' "$cached"
            fi
            return 0
        fi

        if [ "$(type -t run_cache_load)" = "function" ]; then
            run_cache_load
            if [ -n "${RUN_CACHE_TREE_PATHS_SIG:-}" ] && [ "$RUN_CACHE_TREE_PATHS_SIG" = "$sig" ]; then
                if [ "$(type -t profile_counter_increment)" = "function" ]; then
                    profile_counter_increment "tree_paths.cache_hit"
                fi
                if [ ${#RUN_CACHE_TREE_PATHS[@]} -gt 0 ]; then
                    local joined
                    joined=$(printf '%s\n' "${RUN_CACHE_TREE_PATHS[@]}")
                    TREE_PATHS_CACHE[$cache_key]="$joined"
                    TREE_PATHS_CACHE_SIG[$cache_key]="$sig"
                    printf '%s\n' "${RUN_CACHE_TREE_PATHS[@]}"
                    return 0
                fi
            fi
        fi

        if [ "$(type -t profile_counter_increment)" = "function" ]; then
            profile_counter_increment "tree_paths.cache_miss"
        fi
    fi

    local results=()
    local root
    for root in "${roots[@]}"; do
        [ -d "$root" ] || continue
        local -a depth1=()
        local -a depth2=()
        local path
        while IFS= read -r path; do
            [ -n "$path" ] || continue
            local rel="${path#$root/}"
            if [[ "$rel" == */* ]]; then
                depth2+=("$path")
            else
                depth1+=("$path")
            fi
        done < <(find "$root" -maxdepth 2 -type d -name "[0-9]*" -print 2>/dev/null)

        if [ ${#depth1[@]} -gt 0 ]; then
            while IFS= read -r path; do
                [ -n "$path" ] && results+=("$path")
            done < <(printf '%s\n' "${depth1[@]}" | sort)
        else
            while IFS= read -r path; do
                [ -n "$path" ] && results+=("$path")
            done < <(printf '%s\n' "${depth2[@]}" | sort)
        fi
    done

    if worktree_cache_enabled; then
        local joined=""
        if [ ${#results[@]} -gt 0 ]; then
            joined=$(printf '%s\n' "${results[@]}")
        fi
        TREE_PATHS_CACHE[$cache_key]="$joined"
        TREE_PATHS_CACHE_SIG[$cache_key]="$sig"
        worktree_cache_record_tree_paths "$sig" "${results[@]}"
    fi

    printf '%s\n' "${results[@]}"
}

worktree_identity_from_dir() {
    local tree_dir=$1
    local base_dir=${2:-${BASE_DIR:-}}
    local trees_dir_name=${3:-${TREES_DIR_NAME:-trees}}

    [ -n "$base_dir" ] || return 1

    local rel="${tree_dir#$base_dir/}"

    local feature=""
    local iter=""
    local first=""
    local second=""
    local third=""
    local rest=""

    IFS='/' read -r first second third rest <<< "$rel"
    if [ "$first" = "$trees_dir_name" ] && [ -n "$second" ] && [ -n "$third" ] && [ -z "$rest" ]; then
        feature="$second"
        iter="$third"
    elif [[ "$rel" =~ ^trees-([^/]+)/([^/]+)$ ]]; then
        feature="${BASH_REMATCH[1]}"
        iter="${BASH_REMATCH[2]}"
    fi

    if [ -n "$feature" ] && [ -n "$iter" ]; then
        echo "${feature}|${iter}"
        return 0
    fi
    return 1
}

read_ports_from_worktree_config() {
    local tree_dir=$1
    local identity
    identity=$(worktree_identity_from_dir "$tree_dir" "${BASE_DIR:-}" "${TREES_DIR_NAME:-trees}") || return 0

    local feature="${identity%%|*}"
    local iter="${identity#*|}"

    local ports_file="${BASE_DIR:-.}/.envctl-workspaces/${feature}.ports"
    if worktree_port_cache_enabled; then
        if [ -z "${WORKTREE_PORT_CACHE_FEATURE[$feature]:-}" ]; then
            if [ "$(type -t run_cache_load)" = "function" ]; then
                run_cache_load
                if [ "$(type -t run_cache_tree_ports_for_dir)" = "function" ]; then
                    local cached_ports
                    cached_ports=$(run_cache_tree_ports_for_dir "$tree_dir" "$(tree_config_signature "$tree_dir")")
                    if [ -n "$cached_ports" ]; then
                        if [ "$(type -t profile_counter_increment)" = "function" ]; then
                            profile_counter_increment "ports.cache_hit"
                        fi
                        printf '%s' "$cached_ports"
                        return 0
                    fi
                fi
            fi
            WORKTREE_PORT_CACHE_FEATURE[$feature]=1
            if [ -f "$ports_file" ]; then
                local line
                while IFS= read -r line; do
                    [ -n "$line" ] || continue
                    local line_iter="${line%%:*}"
                    local ports="${line#*:}"
                    local backend=""
                    local frontend=""
                    local db=""
                    local redis=""
                    IFS=',' read -r backend frontend <<< "$ports"
                    if [[ "$ports" == *"|"* ]]; then
                        IFS='|' read -r backend frontend db redis <<< "$ports"
                    fi
                    WORKTREE_PORT_CACHE["${feature}|${line_iter}"]="${backend:-}|${frontend:-}|${db:-}|${redis:-}"
                done < "$ports_file"
            fi
        fi
        local cached="${WORKTREE_PORT_CACHE["${feature}|${iter}"]:-}"
        if [ -n "$cached" ]; then
            if [ "$(type -t profile_counter_increment)" = "function" ]; then
                profile_counter_increment "ports.cache_hit"
            fi
            printf '%s' "$cached"
        else
            if [ "$(type -t profile_counter_increment)" = "function" ]; then
                profile_counter_increment "ports.cache_miss"
            fi
        fi
        return 0
    fi

    if [ -f "$ports_file" ]; then
        local line
        line=$(grep -E "^${iter}:" "$ports_file" | tail -n 1)
        if [ -n "$line" ]; then
            local ports="${line#*:}"
            local backend=""
            local frontend=""
            local db=""
            local redis=""
            IFS=',' read -r backend frontend <<< "$ports"
            if [[ "$ports" == *"|"* ]]; then
                IFS='|' read -r backend frontend db redis <<< "$ports"
            fi
            printf '%s|%s|%s|%s' "${backend:-}" "${frontend:-}" "${db:-}" "${redis:-}"
        fi
    fi
}

update_worktree_port_config() {
    local tree_dir=$1
    local backend_port=$2
    local frontend_port=$3
    local db_port=${4:-}
    local redis_port=${5:-}

    local identity
    identity=$(worktree_identity_from_dir "$tree_dir" "${BASE_DIR:-}" "${TREES_DIR_NAME:-trees}") || return 0

    local feature="${identity%%|*}"
    local iter="${identity#*|}"

    local ports_file="${BASE_DIR:-.}/.envctl-workspaces/${feature}.ports"
    mkdir -p "${BASE_DIR:-.}/.envctl-workspaces"

    local lock_dir=""
    lock_dir=$(ports_file_lock_acquire "$ports_file") || return 1

    if [ -f "$ports_file" ]; then
        grep -v "^${iter}:" "$ports_file" > "${ports_file}.tmp" || true
        mv "${ports_file}.tmp" "$ports_file"
    fi

    local entry="${iter}:${backend_port},${frontend_port}"
    if [ -n "$db_port" ] || [ -n "$redis_port" ]; then
        entry="${iter}:${backend_port}|${frontend_port}|${db_port}|${redis_port}"
    fi
    echo "$entry" >> "$ports_file"
    ports_file_lock_release "$lock_dir"

    if worktree_port_cache_enabled; then
        WORKTREE_PORT_CACHE_FEATURE["$feature"]=1
        WORKTREE_PORT_CACHE["${feature}|${iter}"]="${backend_port}|${frontend_port}|${db_port}|${redis_port}"
    fi
    worktree_cache_record_ports "$tree_dir" "$backend_port" "$frontend_port" "$db_port" "$redis_port"
}

remove_worktree_port_config() {
    local tree_dir=$1
    local identity
    identity=$(worktree_identity_from_dir "$tree_dir" "${BASE_DIR:-}" "${TREES_DIR_NAME:-trees}") || return 0

    local feature="${identity%%|*}"
    local iter="${identity#*|}"
    local ports_file="${BASE_DIR:-.}/.envctl-workspaces/${feature}.ports"
    if [ -f "$ports_file" ]; then
        local lock_dir=""
        lock_dir=$(ports_file_lock_acquire "$ports_file") || return 1
        grep -v "^${iter}:" "$ports_file" > "${ports_file}.tmp" || true
        mv "${ports_file}.tmp" "$ports_file"
        if [ ! -s "$ports_file" ]; then
            rm -f "$ports_file"
        fi
        ports_file_lock_release "$lock_dir"
    fi
}

preferred_tree_root_for_feature() {
    local feature_name=$1
    if [ -z "$feature_name" ]; then
        echo "${BASE_DIR:-.}/${TREES_DIR_NAME:-trees}"
        return 0
    fi

    local candidate="${BASE_DIR:-.}/${TREES_DIR_NAME:-trees}-${feature_name}"
    if [ -d "$candidate" ]; then
        echo "$candidate"
        return 0
    fi

    echo "${BASE_DIR:-.}/${TREES_DIR_NAME:-trees}/${feature_name}"
}

resolve_tree_root_for_feature() {
    local feature_name=$1
    local tree_root
    tree_root=$(preferred_tree_root_for_feature "$feature_name")
    if [ -d "$tree_root" ]; then
        echo "$tree_root"
        return 0
    fi
    return 1
}
