#!/usr/bin/env bash

# Supabase requirement helpers.

if [ -z "${N8N_OWNER_RESET_DONE+x}" ]; then
    declare -A N8N_OWNER_RESET_DONE=()
fi

if [ -z "${TREE_SUPABASE_CACHE+x}" ]; then
    declare -A TREE_SUPABASE_CACHE=()
fi
if [ -z "${TREE_N8N_CACHE+x}" ]; then
    declare -A TREE_N8N_CACHE=()
fi
if [ -z "${SUPABASE_TREE_PROJECTS+x}" ]; then
    declare -A SUPABASE_TREE_PROJECTS=()
fi
if [ -z "${SUPABASE_TREE_NETWORK_NAMES+x}" ]; then
    declare -A SUPABASE_TREE_NETWORK_NAMES=()
fi
if [ -z "${SUPABASE_TREE_AUTH_RESET_DONE+x}" ]; then
    declare -A SUPABASE_TREE_AUTH_RESET_DONE=()
fi
if [ -z "${SUPABASE_TREE_DB_PASSWORDS+x}" ]; then
    declare -A SUPABASE_TREE_DB_PASSWORDS=()
fi
if [ -z "${SUPABASE_TREE_DB_PORTS+x}" ]; then
    declare -A SUPABASE_TREE_DB_PORTS=()
fi
if [ -z "${SUPABASE_TREE_PUBLIC_PORTS+x}" ]; then
    declare -A SUPABASE_TREE_PUBLIC_PORTS=()
fi
if [ -z "${SUPABASE_TREE_PUBLIC_URLS+x}" ]; then
    declare -A SUPABASE_TREE_PUBLIC_URLS=()
fi
if [ -z "${SUPABASE_TREE_JWT_SECRETS+x}" ]; then
    declare -A SUPABASE_TREE_JWT_SECRETS=()
fi
if [ -z "${SUPABASE_TREE_ANON_KEYS+x}" ]; then
    declare -A SUPABASE_TREE_ANON_KEYS=()
fi
if [ -z "${SUPABASE_TREE_SERVICE_ROLE_KEYS+x}" ]; then
    declare -A SUPABASE_TREE_SERVICE_ROLE_KEYS=()
fi

# When run.sh is executed inside a container (e.g. OpenClaw Docker), localhost
# refers to that container, not the host where Supabase/n8n ports are published.
# Allow overriding, and default to Docker Desktop's host gateway.
run_sh_internal_host() {
    if [ -n "${RUN_SH_HOST:-}" ]; then
        echo "$RUN_SH_HOST"
        return 0
    fi
    if [ -f "/.dockerenv" ]; then
        echo "host.docker.internal"
        return 0
    fi
    echo "localhost"
}

supabase_docker_cmd() {
    if [ "$(type -t docker_cmd)" = "function" ]; then
        docker_cmd "$@"
        return $?
    fi
    docker "$@"
}

supabase_docker_probe() {
    if [ "$(type -t docker_probe)" = "function" ]; then
        docker_probe "$@"
        return $?
    fi
    supabase_docker_cmd "$@"
}

supabase_docker_compose() {
    local tree_dir=$1
    shift || true
    [ -n "$tree_dir" ] || return 1
    if [ "$(type -t docker_run_with_timeout)" = "function" ]; then
        local timeout_sec=""
        timeout_sec=$(supabase_docker_compose_timeout_for_args "$@")
        if ! [[ "$timeout_sec" =~ ^[0-9]+$ ]] || [ "$timeout_sec" -le 0 ]; then
            timeout_sec="${RUN_SH_DOCKER_COMPOSE_TIMEOUT_SEC:-120}"
        fi
        (cd "$tree_dir" && docker_run_with_timeout "$timeout_sec" compose "$@")
        return $?
    fi
    # Fallback: try to use system timeout binary even when docker.sh isn't loaded
    local timeout_sec="${RUN_SH_DOCKER_COMPOSE_TIMEOUT_SEC:-120}"
    local timeout_bin=""
    if command -v timeout >/dev/null 2>&1; then
        timeout_bin="timeout"
    elif command -v gtimeout >/dev/null 2>&1; then
        timeout_bin="gtimeout"
    fi
    if [ -n "$timeout_bin" ]; then
        (cd "$tree_dir" && "$timeout_bin" "$timeout_sec" docker compose "$@")
    else
        (cd "$tree_dir" && docker compose "$@")
    fi
}

supabase_docker_compose_timeout_for_args() {
    local default_timeout="${RUN_SH_DOCKER_COMPOSE_TIMEOUT_SEC:-120}"
    local probe_timeout="${RUN_SH_DOCKER_COMPOSE_PROBE_TIMEOUT_SEC:-10}"
    local cmd=""
    local arg=""
    local skip_next=false

    for arg in "$@"; do
        if [ "$skip_next" = true ]; then
            skip_next=false
            continue
        fi
        case "$arg" in
            -p|-f|--project-name|--file|--profile|--env-file|--project-directory)
                skip_next=true
                continue
                ;;
            --)
                continue
                ;;
            -*)
                continue
                ;;
            *)
                cmd="$arg"
                break
                ;;
        esac
    done

    case "$cmd" in
        ps|config|images|top|events)
            echo "$probe_timeout"
            ;;
        *)
            echo "$default_timeout"
            ;;
    esac
}

tree_usage_cache_enabled() {
    if [ "${RUN_SH_FAST_STARTUP:-false}" != true ]; then
        return 1
    fi
    if [ "${RUN_SH_REFRESH_CACHE:-false}" = true ]; then
        return 1
    fi
    return 0
}

tree_uses_supabase() {
    local tree_dir=$1
    [ -n "$tree_dir" ] || return 1
    tree_dir=$(cd "$tree_dir" && pwd -P 2>/dev/null) || return 1
    if tree_usage_cache_enabled; then
        local cached="${TREE_SUPABASE_CACHE[$tree_dir]:-}"
        if [ -n "$cached" ]; then
            [ "$cached" = "true" ]
            return $?
        fi
    fi
    if [ ! -f "${tree_dir%/}/supabase/docker-compose.yml" ]; then
        if tree_usage_cache_enabled; then
            TREE_SUPABASE_CACHE["$tree_dir"]="false"
        fi
        return 1
    fi

    local base_dir=""
    if [ -n "${BASE_DIR:-}" ]; then
        base_dir=$(cd "$BASE_DIR" && pwd -P 2>/dev/null) || base_dir="$BASE_DIR"
    fi

    if [ -n "$base_dir" ] && [ "$tree_dir" = "$base_dir" ]; then
        if [ "$SUPABASE_MAIN_ENABLE" = "true" ]; then
            if tree_usage_cache_enabled; then
                TREE_SUPABASE_CACHE["$tree_dir"]="true"
            fi
            return 0
        fi
        if tree_usage_cache_enabled; then
            TREE_SUPABASE_CACHE["$tree_dir"]="false"
        fi
        return 1
    fi

    if [ "$SUPABASE_ALL_TREES" = "true" ]; then
        if tree_usage_cache_enabled; then
            TREE_SUPABASE_CACHE["$tree_dir"]="true"
        fi
        return 0
    fi

    local marker_file="${tree_dir%/}/supabase/.env.supabase"
    local example_file="${tree_dir%/}/supabase/.env.example"
    local enabled_value=""
    if [ -f "$marker_file" ]; then
        enabled_value=$(read_env_value "$marker_file" "SUPABASE_ENABLED")
        if [ "$enabled_value" = "false" ]; then
            if tree_usage_cache_enabled; then
                TREE_SUPABASE_CACHE["$tree_dir"]="false"
            fi
            return 1
        fi
        if [ "$enabled_value" = "true" ]; then
            if tree_usage_cache_enabled; then
                TREE_SUPABASE_CACHE["$tree_dir"]="true"
            fi
            return 0
        fi
    fi
    if [ -f "$example_file" ]; then
        enabled_value=$(read_env_value "$example_file" "SUPABASE_ENABLED")
        if [ "$enabled_value" = "false" ]; then
            if tree_usage_cache_enabled; then
                TREE_SUPABASE_CACHE["$tree_dir"]="false"
            fi
            return 1
        fi
        if [ "$enabled_value" = "true" ]; then
            if tree_usage_cache_enabled; then
                TREE_SUPABASE_CACHE["$tree_dir"]="true"
            fi
            return 0
        fi
    fi

    local identity=""
    identity=$(worktree_identity_from_dir "$tree_dir" 2>/dev/null || true)
    local feature_name=""
    if [ -n "$identity" ]; then
        feature_name="${identity%%|*}"
    fi
    if [ -z "$feature_name" ]; then
        feature_name=$(basename "$tree_dir")
    fi

    local filter="$SUPABASE_TREE_FILTER"
    if [ -z "$filter" ]; then
        if tree_usage_cache_enabled; then
            TREE_SUPABASE_CACHE["$tree_dir"]="false"
        fi
        return 1
    fi

    local entry=""
    IFS=',' read -r -a filter_entries <<< "$filter"
    for entry in "${filter_entries[@]}"; do
        entry=$(trim "$entry")
        [ -z "$entry" ] && continue
        if [ "$entry" = "$feature_name" ]; then
            if tree_usage_cache_enabled; then
                TREE_SUPABASE_CACHE["$tree_dir"]="true"
            fi
            return 0
        fi
    done
    if tree_usage_cache_enabled; then
        TREE_SUPABASE_CACHE["$tree_dir"]="false"
    fi
    return 1
}

compose_file_has_service() {
    local compose_file=$1
    local service=$2
    [ -n "$compose_file" ] || return 1
    [ -n "$service" ] || return 1
    [ -f "$compose_file" ] || return 1

    if command -v rg >/dev/null 2>&1; then
        rg -q "^[[:space:]]*${service}:" "$compose_file"
        return $?
    fi

    grep -qE "^[[:space:]]*${service}:" "$compose_file"
}

tree_uses_n8n() {
    local tree_dir=$1
    [ -n "$tree_dir" ] || return 1
    tree_dir=$(cd "$tree_dir" && pwd -P 2>/dev/null) || return 1
    if tree_usage_cache_enabled; then
        local cached="${TREE_N8N_CACHE[$tree_dir]:-}"
        if [ -n "$cached" ]; then
            [ "$cached" = "true" ]
            return $?
        fi
    fi
    if [ "${N8N_ENABLE:-true}" != "true" ]; then
        if tree_usage_cache_enabled; then
            TREE_N8N_CACHE["$tree_dir"]="false"
        fi
        return 1
    fi
    local base_dir=""
    if [ -n "${BASE_DIR:-}" ]; then
        base_dir=$(cd "$BASE_DIR" && pwd -P 2>/dev/null) || base_dir="$BASE_DIR"
    fi
    if [ -n "$base_dir" ] && [ "$tree_dir" = "$base_dir" ]; then
        if [ "${N8N_MAIN_ENABLE:-false}" != "true" ]; then
            if tree_usage_cache_enabled; then
                TREE_N8N_CACHE["$tree_dir"]="false"
            fi
            return 1
        fi
    fi
    local compose_file="${tree_dir%/}/docker-compose.yml"
    if ! compose_file_has_service "$compose_file" "n8n"; then
        if tree_usage_cache_enabled; then
            TREE_N8N_CACHE["$tree_dir"]="false"
        fi
        return 1
    fi

    if [ -n "$base_dir" ] && [ "$tree_dir" != "$base_dir" ]; then
        if [ "${N8N_ALL_TREES:-false}" = "true" ]; then
            if tree_usage_cache_enabled; then
                TREE_N8N_CACHE["$tree_dir"]="true"
            fi
            return 0
        fi

        local filter="${N8N_TREE_FILTER:-}"
        if [ -n "$filter" ]; then
            local identity=""
            identity=$(worktree_identity_from_dir "$tree_dir" 2>/dev/null || true)
            local feature_name=""
            if [ -n "$identity" ]; then
                feature_name="${identity%%|*}"
            fi
            if [ -z "$feature_name" ]; then
                feature_name=$(basename "$tree_dir")
            fi
            local entry=""
            IFS=',' read -r -a filter_entries <<< "$filter"
            for entry in "${filter_entries[@]}"; do
                entry=$(trim "$entry")
                [ -z "$entry" ] && continue
                if [ "$entry" = "$feature_name" ]; then
                    if tree_usage_cache_enabled; then
                        TREE_N8N_CACHE["$tree_dir"]="true"
                    fi
                    return 0
                fi
            done
            if tree_usage_cache_enabled; then
                TREE_N8N_CACHE["$tree_dir"]="false"
            fi
            return 1
        fi
    fi

    if tree_usage_cache_enabled; then
        TREE_N8N_CACHE["$tree_dir"]="true"
    fi
    return 0
}

supabase_env_file_for_tree() {
    local tree_dir=$1
    [ -n "$tree_dir" ] || return 1
    tree_dir=$(cd "$tree_dir" && pwd -P 2>/dev/null) || return 1
    local supabase_dir="${tree_dir%/}/supabase"
    if [ -f "$supabase_dir/.env.supabase" ]; then
        echo "$supabase_dir/.env.supabase"
        return 0
    fi
    if [ -f "$supabase_dir/.env.example" ]; then
        echo "$supabase_dir/.env.example"
        return 0
    fi
    return 1
}

feature_requests_supabase() {
    local feature_name=$1
    local plan_file=$2
    local combined="${feature_name} ${plan_file}"
    local prev_nocase
    prev_nocase=$(shopt -p nocasematch)
    shopt -s nocasematch
    if [[ "$combined" == *supabase* ]]; then
        eval "$prev_nocase"
        return 0
    fi
    eval "$prev_nocase"
    return 1
}

ensure_supabase_marker_for_tree() {
    local tree_dir=$1
    [ -n "$tree_dir" ] || return 0
    tree_dir=$(cd "$tree_dir" && pwd -P 2>/dev/null) || return 0
    local supabase_dir="${tree_dir%/}/supabase"
    [ -d "$supabase_dir" ] || return 0
    local marker_file="${supabase_dir}/.env.supabase"
    if [ -f "$marker_file" ]; then
        if grep -q "^SUPABASE_ENABLED=false" "$marker_file"; then
            return 0
        fi
        if grep -q "^SUPABASE_ENABLED=" "$marker_file"; then
            return 0
        fi
        echo "SUPABASE_ENABLED=true" >> "$marker_file"
        return 0
    fi
    echo "SUPABASE_ENABLED=true" > "$marker_file"
}

ensure_supabase_marker_for_root() {
    local tree_root=$1
    [ -n "$tree_root" ] || return 0
    if [ ! -d "$tree_root" ]; then
        return 0
    fi
    local dir
    while IFS= read -r dir; do
        [ -n "$dir" ] || continue
        ensure_supabase_marker_for_tree "$dir"
    done < <(list_numeric_dirs "$tree_root")
}

supabase_value_for_tree() {
    local tree_dir=$1
    local key=$2
    local fallback=$3
    local value=""
    local env_file=""
    tree_dir=$(cd "$tree_dir" && pwd -P 2>/dev/null) || true
    env_file=$(supabase_env_file_for_tree "$tree_dir" 2>/dev/null || true)
    if [ -n "$env_file" ]; then
        value=$(read_env_value "$env_file" "$key")
    fi
    if [ -z "$value" ]; then
        value="${!key:-$fallback}"
    fi
    echo "$value"
}

escape_sql_literal() {
    local value=$1
    value=${value//\'/\'\'}
    printf "%s" "$value"
}

supabase_auth_password_sql() {
    local password=$1
    local escaped=""
    escaped=$(escape_sql_literal "$password")
    printf "ALTER ROLE supabase_auth_admin WITH PASSWORD '%s';" "$escaped"
}

n8n_compose_uses_host_port_var() {
    local compose_file=$1
    [ -n "$compose_file" ] || return 1
    [ -f "$compose_file" ] || return 1
    # Exclude YAML comment lines (leading whitespace + #) to avoid false positives
    if command -v rg >/dev/null 2>&1; then
        rg -v '^\s*#' "$compose_file" | rg -q '\$\{N8N_HOST_PORT'
        return $?
    fi
    grep -v '^\s*#' "$compose_file" | grep -q '\${N8N_HOST_PORT'
}

supabase_reset_auth_admin_password() {
    local tree_dir=$1
    local db_container=$2
    local db_password=$3
    [ -n "$db_container" ] || return 0
    [ -n "$db_password" ] || return 0

    local label="$tree_dir"
    if [ -n "$tree_dir" ]; then
        local identity=""
        identity=$(worktree_identity_from_dir "$tree_dir" 2>/dev/null || true)
        if [ -n "$identity" ]; then
            label="${identity//|/-}"
        else
            label=$(basename "$tree_dir")
        fi
    fi

    local password_sql=""
    if [ "$(type -t debug_trace_suppress_begin)" = "function" ]; then
        debug_trace_suppress_begin
    fi
    password_sql=$(supabase_auth_password_sql "$db_password")
    if [ "$(type -t debug_trace_suppress_end)" = "function" ]; then
        debug_trace_suppress_end
    fi
    local attempts="${SUPABASE_AUTH_RESET_RETRIES:-10}"
    local delay="${SUPABASE_AUTH_RESET_DELAY_SECONDS:-1}"
    local last_error=""
    local attempt
    for ((attempt=1; attempt<=attempts; attempt++)); do
        if [ "$(type -t debug_trace_suppress_begin)" = "function" ]; then
            debug_trace_suppress_begin
        fi
        if last_error=$(supabase_docker_cmd exec -e PGPASSWORD="$db_password" "$db_container" \
            psql -h localhost -U supabase_admin -d postgres -c "$password_sql" 2>&1); then
            if [ "$(type -t debug_trace_suppress_end)" = "function" ]; then
                debug_trace_suppress_end
            fi
            echo -e "${GREEN}✓ Supabase auth admin password reset (${label})${NC}"
            return 0
        fi
        if [ "$(type -t debug_trace_suppress_end)" = "function" ]; then
            debug_trace_suppress_end
        fi
        sleep "$delay"
    done

    last_error=$(echo "$last_error" | head -n 1)
    echo -e "${YELLOW}⚠ Supabase auth admin password reset failed (${label}); auth may not start${NC}"
    [ -n "$last_error" ] && echo -e "${YELLOW}  ↳ ${last_error}${NC}"
    return 1
}

supabase_reset_auth_admin_password_once() {
    local tree_dir=$1
    [ -n "$tree_dir" ] || return 0
    if [ -n "${SUPABASE_TREE_AUTH_RESET_DONE[$tree_dir]:-}" ]; then
        return 0
    fi
    SUPABASE_TREE_AUTH_RESET_DONE["$tree_dir"]=1
    supabase_reset_auth_admin_password "$@"
}

supabase_compose_project_name() {
    local tree_dir=$1
    [ -n "$tree_dir" ] || return 1
    tree_dir=$(cd "$tree_dir" && pwd -P 2>/dev/null) || return 1
    local identity
    identity=$(worktree_identity_from_dir "$tree_dir" 2>/dev/null || true)
    local name=""
    if [ -n "$identity" ] && [[ "$identity" == *"|"* ]]; then
        local feature="${identity%%|*}"
        local iter="${identity#*|}"
        name="${ENVCTL_PROJECT_PREFIX:-supportopia}-supabase-${feature}-${iter}"
    else
        name="${ENVCTL_PROJECT_PREFIX:-supportopia}-supabase-$(basename "$tree_dir")"
    fi
    echo "$(slugify "$name")"
}

supabase_network_name() {
    local tree_dir=$1
    [ -n "$tree_dir" ] || return 1
    tree_dir=$(cd "$tree_dir" && pwd -P 2>/dev/null) || return 1
    local cached="${SUPABASE_TREE_NETWORK_NAMES[$tree_dir]:-}"
    if [ -n "$cached" ]; then
        echo "$cached"
        return 0
    fi
    local project_name="${SUPABASE_TREE_PROJECTS[$tree_dir]:-}"
    if [ -z "$project_name" ]; then
        project_name=$(supabase_compose_project_name "$tree_dir")
        SUPABASE_TREE_PROJECTS["$tree_dir"]="$project_name"
    fi
    local network_name="${project_name}-net"
    SUPABASE_TREE_NETWORK_NAMES["$tree_dir"]="$network_name"
    echo "$network_name"
}

supabase_compose_network_label() {
    echo "${SUPABASE_COMPOSE_NETWORK_LABEL:-supabase-net}"
}

ensure_supabase_compose_network() {
    local tree_dir=$1
    local network_name=${2:-}
    local project_name=${3:-}
    [ -n "$tree_dir" ] || return 0
    tree_dir=$(cd "$tree_dir" && pwd -P 2>/dev/null) || return 0
    if ! command -v docker >/dev/null 2>&1; then
        return 0
    fi
    if [ -z "$network_name" ]; then
        network_name=$(supabase_network_name "$tree_dir" 2>/dev/null || true)
    fi
    [ -n "$network_name" ] || return 0
    if [ -z "$project_name" ]; then
        project_name="${SUPABASE_TREE_PROJECTS[$tree_dir]:-}"
        if [ -z "$project_name" ]; then
            project_name=$(supabase_compose_project_name "$tree_dir")
            SUPABASE_TREE_PROJECTS["$tree_dir"]="$project_name"
        fi
    fi
    local compose_network_label=""
    compose_network_label=$(supabase_compose_network_label)
    [ -n "$compose_network_label" ] || compose_network_label="supabase-net"

    if ! supabase_docker_cmd network inspect "$network_name" >/dev/null 2>&1; then
        supabase_docker_cmd network create \
            --label "com.docker.compose.project=${project_name}" \
            --label "com.docker.compose.network=${compose_network_label}" \
            "$network_name" >/dev/null 2>&1 || true
        return 0
    fi

    local current_project_label=""
    local current_network_label=""
    current_project_label=$(supabase_docker_cmd network inspect -f '{{index .Labels "com.docker.compose.project"}}' \
        "$network_name" 2>/dev/null || true)
    current_network_label=$(supabase_docker_cmd network inspect -f '{{index .Labels "com.docker.compose.network"}}' \
        "$network_name" 2>/dev/null || true)
    if [ "$current_project_label" = "$project_name" ] && \
        [ "$current_network_label" = "$compose_network_label" ]; then
        return 0
    fi

    debug_log_line_safe "INFO" \
        "supabase.network.normalize tree=${tree_dir} network=${network_name} project=${project_name} expected=${compose_network_label} actual_project=${current_project_label:-none} actual_network=${current_network_label:-none}"

    local attached_count=""
    attached_count=$(supabase_docker_cmd network inspect -f '{{len .Containers}}' "$network_name" 2>/dev/null || true)
    if [[ "$attached_count" =~ ^[0-9]+$ ]] && [ "$attached_count" -gt 0 ]; then
        local fallback_index=2
        local fallback_network="${network_name}-${fallback_index}"
        while supabase_docker_cmd network inspect "$fallback_network" >/dev/null 2>&1; do
            local fallback_project_label=""
            local fallback_network_label=""
            fallback_project_label=$(supabase_docker_cmd network inspect -f '{{index .Labels "com.docker.compose.project"}}' \
                "$fallback_network" 2>/dev/null || true)
            fallback_network_label=$(supabase_docker_cmd network inspect -f '{{index .Labels "com.docker.compose.network"}}' \
                "$fallback_network" 2>/dev/null || true)
            if [ "$fallback_project_label" = "$project_name" ] && [ "$fallback_network_label" = "$compose_network_label" ]; then
                SUPABASE_TREE_NETWORK_NAMES["$tree_dir"]="$fallback_network"
                return 0
            fi
            fallback_index=$((fallback_index + 1))
            fallback_network="${network_name}-${fallback_index}"
        done
        if supabase_docker_cmd network create \
            --label "com.docker.compose.project=${project_name}" \
            --label "com.docker.compose.network=${compose_network_label}" \
            "$fallback_network" >/dev/null 2>&1; then
            SUPABASE_TREE_NETWORK_NAMES["$tree_dir"]="$fallback_network"
            return 0
        fi
        return 1
    fi

    local endpoint_id=""
    while IFS= read -r endpoint_id; do
        [ -n "$endpoint_id" ] || continue
        supabase_docker_cmd network disconnect "$network_name" "$endpoint_id" >/dev/null 2>&1 || true
    done < <(supabase_docker_cmd network inspect -f '{{range $id, $_ := .Containers}}{{println $id}}{{end}}' \
        "$network_name" 2>/dev/null || true)
    if ! supabase_docker_cmd network rm "$network_name" >/dev/null 2>&1; then
        debug_log_line_safe "WARN" \
            "supabase.network.normalize tree=${tree_dir} network=${network_name} status=remove_failed"
        return 1
    fi
    if supabase_docker_cmd network inspect "$network_name" >/dev/null 2>&1; then
        debug_log_line_safe "WARN" \
            "supabase.network.normalize tree=${tree_dir} network=${network_name} status=still_exists"
        return 1
    fi
    if ! supabase_docker_cmd network create \
        --label "com.docker.compose.project=${project_name}" \
        --label "com.docker.compose.network=${compose_network_label}" \
        "$network_name" >/dev/null 2>&1; then
        return 1
    fi
    return 0
}

compose_service_container_id() {
    local project=$1
    local service=$2
    [ -n "$project" ] || return 1
    [ -n "$service" ] || return 1
    local id=""
    id=$(supabase_docker_cmd ps --filter "label=com.docker.compose.project=${project}" \
        --filter "label=com.docker.compose.service=${service}" \
        --format '{{.ID}}' 2>/dev/null | head -n 1)
    [ -n "$id" ] || return 1
    echo "$id"
}

supabase_service_container_id() {
    local tree_dir=$1
    local service=$2
    [ -n "$tree_dir" ] || return 1
    [ -n "$service" ] || return 1
    tree_dir=$(cd "$tree_dir" && pwd -P 2>/dev/null) || return 1
    local project_name="${SUPABASE_TREE_PROJECTS[$tree_dir]:-}"
    if [ -z "$project_name" ]; then
        project_name=$(supabase_compose_project_name "$tree_dir")
    fi
    local compose_file="${tree_dir%/}/supabase/docker-compose.yml"
    local container_id=""
    if [ -f "$compose_file" ]; then
        container_id=$(supabase_docker_compose "$tree_dir" -p "$project_name" -f "supabase/docker-compose.yml" ps -q "$service" 2>/dev/null || true)
        if [ -n "$container_id" ]; then
            echo "$container_id"
            return 0
        fi
    fi
    container_id=$(compose_service_container_id "$project_name" "$service" 2>/dev/null || true)
    if [ -n "$container_id" ]; then
        echo "$container_id"
        return 0
    fi
    local fallback=""
    fallback=$(supabase_container_name "$tree_dir" "$service" 2>/dev/null || true)
    if [ -n "$fallback" ] && [ "$(type -t docker_ps_all_names_contains)" = "function" ]; then
        if docker_ps_all_names_contains "$fallback"; then
            echo "$fallback"
            return 0
        fi
    fi
    return 1
}

debug_log_line_safe() {
    local level=$1
    shift || true
    if [ "$(type -t debug_log_line)" != "function" ]; then
        return 0
    fi
    if [ "$(type -t debug_enabled)" = "function" ]; then
        if ! debug_enabled; then
            return 0
        fi
    fi
    debug_log_line "$level" "$*"
}

ensure_service_on_supabase_network() {
    local tree_dir=$1
    local service=${2:-supabase-db}
    [ -n "$tree_dir" ] || return 0
    tree_dir=$(cd "$tree_dir" && pwd -P 2>/dev/null) || return 0
    [ -n "$service" ] || return 0
    if ! command -v docker >/dev/null 2>&1; then
        return 0
    fi
    local network_name=""
    network_name=$(supabase_network_name "$tree_dir" 2>/dev/null || true)
    [ -n "$network_name" ] || return 0
    ensure_supabase_compose_network "$tree_dir" "$network_name"
    local container_id=""
    container_id=$(supabase_service_container_id "$tree_dir" "$service" 2>/dev/null || true)
    [ -n "$container_id" ] || return 0
    debug_log_line_safe "INFO" \
        "supabase.network.ensure tree=${tree_dir} network=${network_name} container=${container_id} alias=${service}"
    local networks=""
    networks=$(supabase_docker_cmd inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{println $k}}{{end}}' \
        "$container_id" 2>/dev/null || true)
    local connected=false
    if printf '%s\n' "$networks" | grep -Fxq "$network_name"; then
        connected=true
    fi
    if [ "$connected" != true ]; then
        supabase_docker_cmd network connect --alias "$service" "$network_name" "$container_id" >/dev/null 2>&1 || true
        debug_log_line_safe "INFO" \
            "supabase.network.alias tree=${tree_dir} network=${network_name} container=${container_id} alias=${service} status=attached"
        return 0
    fi
    local aliases=""
    aliases=$(supabase_docker_cmd inspect -f "{{if (index .NetworkSettings.Networks \"${network_name}\")}}{{range (index .NetworkSettings.Networks \"${network_name}\").Aliases}}{{println .}}{{end}}{{end}}" \
        "$container_id" 2>/dev/null || true)
    if ! printf '%s\n' "$aliases" | grep -Fxq "$service"; then
        supabase_docker_cmd network disconnect "$network_name" "$container_id" >/dev/null 2>&1 || true
        supabase_docker_cmd network connect --alias "$service" "$network_name" "$container_id" >/dev/null 2>&1 || true
        debug_log_line_safe "INFO" \
            "supabase.network.alias tree=${tree_dir} network=${network_name} container=${container_id} alias=${service} status=alias_reset"
    else
        debug_log_line_safe "INFO" \
            "supabase.network.alias tree=${tree_dir} network=${network_name} container=${container_id} alias=${service} status=alias_present"
    fi
}

supabase_public_port_for_db_port() {
    local tree_dir=$1
    local db_port=$2
    [ -n "$tree_dir" ] || return 1
    [ -n "$db_port" ] || return 1
    tree_dir=$(cd "$tree_dir" && pwd -P 2>/dev/null) || return 1
    local supabase_db_base="${SUPABASE_DB_PORT_BASE:-54322}"
    local legacy_db_base="${DB_PORT_BASE:-5432}"
    local supabase_public_base="${SUPABASE_PUBLIC_PORT_BASE:-54321}"
    local offset=$((db_port - supabase_db_base))
    if [ "$offset" -lt 0 ]; then
        local legacy_offset=$((db_port - legacy_db_base))
        if [ "$legacy_offset" -ge 0 ]; then
            offset="$legacy_offset"
        else
            offset=0
        fi
    fi
    local port=$((supabase_public_base + offset))
    port=$(reserve_requirement_port "$port" "$db_port" "" "${tree_dir}:supabase-public")
    echo "$port"
}

register_supabase_tree_config() {
    local tree_dir=$1
    local db_port=$2
    [ -n "$tree_dir" ] || return 1
    [ -n "$db_port" ] || return 1
    tree_dir=$(cd "$tree_dir" && pwd -P 2>/dev/null) || return 1

    local public_port
    public_port=$(supabase_public_port_for_db_port "$tree_dir" "$db_port")
    local public_url="http://localhost:${public_port}"
    local db_password
    db_password=$(supabase_value_for_tree "$tree_dir" "SUPABASE_DB_PASSWORD" "supabase-db-password")
    local jwt_secret
    jwt_secret=$(supabase_value_for_tree "$tree_dir" "SUPABASE_JWT_SECRET" "supabase-local-jwt-secret")
    local anon_key
    anon_key=$(supabase_value_for_tree "$tree_dir" "SUPABASE_ANON_KEY" "local-anon-key")
    local service_role_key
    service_role_key=$(supabase_value_for_tree "$tree_dir" "SUPABASE_SERVICE_ROLE_KEY" "local-service-role-key")
    local project_name
    project_name=$(supabase_compose_project_name "$tree_dir")

    SUPABASE_TREE_PUBLIC_URLS["$tree_dir"]="$public_url"
    SUPABASE_TREE_PUBLIC_PORTS["$tree_dir"]="$public_port"
    SUPABASE_TREE_DB_PORTS["$tree_dir"]="$db_port"
    SUPABASE_TREE_DB_PASSWORDS["$tree_dir"]="$db_password"
    SUPABASE_TREE_JWT_SECRETS["$tree_dir"]="$jwt_secret"
    SUPABASE_TREE_ANON_KEYS["$tree_dir"]="$anon_key"
    SUPABASE_TREE_SERVICE_ROLE_KEYS["$tree_dir"]="$service_role_key"
    SUPABASE_TREE_PROJECTS["$tree_dir"]="$project_name"
}

apply_supabase_env_for_tree() {
    local tree_dir=$1
    local db_port=${2:-}
    local redis_port=${3:-}
    [ -n "$tree_dir" ] || return 0
    tree_dir=$(cd "$tree_dir" && pwd -P 2>/dev/null) || return 0
    local public_url="${SUPABASE_TREE_PUBLIC_URLS[$tree_dir]:-}"
    if [ -z "$public_url" ]; then
        return 0
    fi
    local public_port="${SUPABASE_TREE_PUBLIC_PORTS[$tree_dir]:-}"
    if [ -z "$public_port" ]; then
        public_port=$(supabase_value_for_tree "$tree_dir" "SUPABASE_PUBLIC_PORT" "${SUPABASE_PUBLIC_PORT_BASE:-54321}")
    fi
    local internal_host
    internal_host=$(run_sh_internal_host)
    local internal_url="http://${internal_host}:${public_port}"
    local jwt_secret="${SUPABASE_TREE_JWT_SECRETS[$tree_dir]:-supabase-local-jwt-secret}"
    local anon_key="${SUPABASE_TREE_ANON_KEYS[$tree_dir]:-local-anon-key}"
    local jwt_aud
    jwt_aud=$(supabase_value_for_tree "$tree_dir" "SUPABASE_JWT_AUD" "authenticated")
    if [ "$(type -t debug_trace_suppress_begin)" = "function" ]; then
        debug_trace_suppress_begin
    fi
    if [ "$(type -t debug_trace_suppress_begin)" = "function" ]; then
        debug_trace_suppress_begin
    fi
    local db_password="${SUPABASE_TREE_DB_PASSWORDS[$tree_dir]:-supabase-db-password}"
    local db_user="${SUPABASE_DB_USER:-postgres}"
    local db_name="${SUPABASE_DB_NAME:-postgres}"
    if [ -z "$db_port" ]; then
        db_port="${SUPABASE_TREE_DB_PORTS[$tree_dir]:-}"
    fi
    if [ -z "$db_port" ]; then
        db_port=$(supabase_value_for_tree "$tree_dir" "SUPABASE_DB_PORT" "${SUPABASE_DB_PORT_BASE:-54322}")
    fi

    local backend_dir
    backend_dir=$(find_backend_dir "$tree_dir" 2>/dev/null || true)
    if [ -n "$backend_dir" ] && [ -f "$backend_dir/.env" ]; then
        upsert_env_value "$backend_dir/.env" "AUTH_MODE" "supabase"
        upsert_env_value "$backend_dir/.env" "SUPABASE_URL" "$internal_url"
        upsert_env_value "$backend_dir/.env" "SUPABASE_JWKS_URL" "${internal_url}/auth/v1/.well-known/jwks.json"
        upsert_env_value "$backend_dir/.env" "SUPABASE_JWT_AUD" "$jwt_aud"
        upsert_env_value "$backend_dir/.env" "SUPABASE_JWT_SECRET" "$jwt_secret"
        upsert_env_value "$backend_dir/.env" "ALLOW_LEGACY_SUPABASE_HS256" "true"
        if [ -n "$db_port" ]; then
            upsert_env_value "$backend_dir/.env" "DATABASE_URL" "postgresql+asyncpg://${db_user}:${db_password}@${internal_host}:${db_port}/${db_name}"
        fi
        if [ -n "$redis_port" ]; then
            upsert_env_value "$backend_dir/.env" "REDIS_URL" "redis://${internal_host}:${redis_port}"
        fi
    fi

    local tree_env="${tree_dir%/}/.env"
    if [ -f "$tree_env" ]; then
        if [ -n "$db_port" ]; then
            upsert_env_value "$tree_env" "DB_PORT" "$db_port"
        fi
        if [ -n "$redis_port" ]; then
            upsert_env_value "$tree_env" "REDIS_PORT" "$redis_port"
        fi
    fi

    local frontend_dir
    frontend_dir=$(find_frontend_dir "$tree_dir" 2>/dev/null || true)
    if [ -n "$frontend_dir" ]; then
        local frontend_env="$frontend_dir/.env.local"
        if [ ! -f "$frontend_env" ] && [ -f "$frontend_dir/.env" ]; then
            frontend_env="$frontend_dir/.env"
        fi
        # Frontend runs in the host browser; keep localhost-based URL.
        upsert_env_value "$frontend_env" "VITE_SUPABASE_URL" "$public_url"
        upsert_env_value "$frontend_env" "VITE_SUPABASE_ANON_KEY" "$anon_key"
    fi
}

tree_n8n_port_for_dir() {
    local tree_dir=$1
    local backend_port=$2
    local out_var=${3:-}
    [ -n "$tree_dir" ] || return 1
    tree_dir=$(cd "$tree_dir" && pwd -P 2>/dev/null) || return 1

    if [ "$(type -t container_host_port)" = "function" ] && tree_uses_n8n "$tree_dir"; then
        local n8n_container=""
        local n8n_container_id=""
        n8n_container_id=$(supabase_service_container_id "$tree_dir" "n8n" 2>/dev/null || true)
        n8n_container=$(supabase_container_name "$tree_dir" "n8n" 2>/dev/null || true)
        local resolved_container=""
        if [ -n "$n8n_container_id" ]; then
            resolved_container="$n8n_container_id"
        elif [ -n "$n8n_container" ]; then
            resolved_container="$n8n_container"
            if command -v docker >/dev/null 2>&1; then
                local name=""
                while IFS= read -r name; do
                    case "$name" in
                        "$n8n_container"|*"_$n8n_container"|*"-${n8n_container}")
                            resolved_container="$name"
                            break
                            ;;
                    esac
                done < <(supabase_docker_cmd ps --format '{{.Names}}')
            fi
        fi
        if [ -n "$resolved_container" ]; then
            local container_port=""
            container_port=$(container_host_port "$resolved_container" "5678")
            if [ -n "$container_port" ]; then
                N8N_TREE_PORTS["$tree_dir"]="$container_port"
                if [ -n "$out_var" ]; then
                    printf -v "$out_var" '%s' "$container_port"
                    return 0
                fi
                echo "$container_port"
                return 0
            fi
        fi
    fi

    local existing="${N8N_TREE_PORTS[$tree_dir]:-}"
    if [ -n "$existing" ]; then
        if [ -n "$out_var" ]; then
            printf -v "$out_var" '%s' "$existing"
            return 0
        fi
        echo "$existing"
        return 0
    fi

    local env_file="${tree_dir%/}/.env"
    local n8n_port=""
    n8n_port=$(read_env_value "$env_file" "N8N_PORT")
    local n8n_base="${N8N_PORT_BASE:-5678}"
    if [ -z "$n8n_port" ]; then
        local base_offset=0
        if [ -n "$backend_port" ]; then
            base_offset=$((backend_port - BACKEND_PORT_BASE))
            if [ "$base_offset" -lt 0 ]; then
                base_offset=0
            fi
        fi
        n8n_port=$((n8n_base + base_offset))
    fi

    n8n_port=$(reserve_requirement_port "$n8n_port" "$backend_port" "" "${tree_dir}:n8n")
    N8N_TREE_PORTS["$tree_dir"]="$n8n_port"
    if [ -n "$out_var" ]; then
        printf -v "$out_var" '%s' "$n8n_port"
        return 0
    fi
    echo "$n8n_port"
}

resolve_n8n_db_name() {
    local tree_dir=$1
    local db_name=$2

    if [ -n "$db_name" ]; then
        echo "$db_name"
        return 0
    fi

    local env_file="${tree_dir%/}/.env"
    if [ -f "$env_file" ]; then
        db_name=$(read_env_value "$env_file" "N8N_DB_NAME")
    fi
    if [ -z "$db_name" ]; then
        db_name="${N8N_DB_NAME:-n8n}"
    fi
    echo "$db_name"
}

ensure_n8n_database() {
    local tree_dir=$1
    local db_name=$2
    [ -n "$tree_dir" ] || return 0
    tree_dir=$(cd "$tree_dir" && pwd -P 2>/dev/null) || return 0

    db_name=$(resolve_n8n_db_name "$tree_dir" "$db_name")

    if ! [[ "$db_name" =~ ^[A-Za-z0-9_]+$ ]]; then
        echo -e "${YELLOW}Skipping n8n DB init; invalid DB name '${db_name}'.${NC}"
        return 0
    fi

    local db_container=""
    db_container=$(supabase_container_name "$tree_dir" "supabase-db" 2>/dev/null || true)
    if [ -z "$db_container" ]; then
        return 0
    fi
    if ! docker_ps_names_contains "$db_container"; then
        return 0
    fi

    local exists=""
    exists=$(supabase_docker_cmd exec "$db_container" psql -U postgres -tAc \
        "SELECT 1 FROM pg_database WHERE datname='${db_name}'" 2>/dev/null | tr -d '[:space:]')
    if [ "$exists" = "1" ]; then
        return 0
    fi

    echo -e "${CYAN}Creating n8n database '${db_name}' for ${tree_dir}...${NC}"
    if ! supabase_docker_cmd exec "$db_container" psql -U postgres -c "CREATE DATABASE ${db_name}" >/dev/null 2>&1; then
        echo -e "${RED}✗ Failed to create n8n database '${db_name}'${NC}"
        return 1
    fi
    return 0
}

resolve_n8n_bootstrap_values() {
    local tree_env=$1
    local base_env=""
    if [ -n "${BASE_DIR:-}" ]; then
        base_env="${BASE_DIR%/}/.env"
    fi

    local bootstrap_enabled="${N8N_BOOTSTRAP_ENABLED:-}"
    if [ -z "$bootstrap_enabled" ] && [ -f "$tree_env" ]; then
        bootstrap_enabled=$(read_env_value "$tree_env" "N8N_BOOTSTRAP_ENABLED")
    fi
    if [ -z "$bootstrap_enabled" ] && [ -n "$base_env" ] && [ -f "$base_env" ]; then
        bootstrap_enabled=$(read_env_value "$base_env" "N8N_BOOTSTRAP_ENABLED")
    fi

    local owner_email="${N8N_OWNER_EMAIL:-}"
    local owner_first="${N8N_OWNER_FIRST_NAME:-}"
    local owner_last="${N8N_OWNER_LAST_NAME:-}"
    local owner_password="${N8N_OWNER_PASSWORD:-}"
    if [ -f "$tree_env" ]; then
        [ -z "$owner_email" ] && owner_email=$(read_env_value "$tree_env" "N8N_OWNER_EMAIL")
        [ -z "$owner_first" ] && owner_first=$(read_env_value "$tree_env" "N8N_OWNER_FIRST_NAME")
        [ -z "$owner_last" ] && owner_last=$(read_env_value "$tree_env" "N8N_OWNER_LAST_NAME")
        [ -z "$owner_password" ] && owner_password=$(read_env_value "$tree_env" "N8N_OWNER_PASSWORD")
    fi
    if [ -n "$base_env" ] && [ -f "$base_env" ]; then
        [ -z "$owner_email" ] && owner_email=$(read_env_value "$base_env" "N8N_OWNER_EMAIL")
        [ -z "$owner_first" ] && owner_first=$(read_env_value "$base_env" "N8N_OWNER_FIRST_NAME")
        [ -z "$owner_last" ] && owner_last=$(read_env_value "$base_env" "N8N_OWNER_LAST_NAME")
        [ -z "$owner_password" ] && owner_password=$(read_env_value "$base_env" "N8N_OWNER_PASSWORD")
    fi

    printf '%s\n' "$bootstrap_enabled" "$owner_email" "$owner_first" "$owner_last" "$owner_password"
}

n8n_validate_bootstrap_config() {
    local tree_env=$1
    local bootstrap_values=()
    local bootstrap_enabled=""
    local owner_email=""
    local owner_first=""
    local owner_last=""
    local owner_password=""
    mapfile -t bootstrap_values < <(resolve_n8n_bootstrap_values "$tree_env")
    bootstrap_enabled="${bootstrap_values[0]:-}"
    owner_email="${bootstrap_values[1]:-}"
    owner_first="${bootstrap_values[2]:-}"
    owner_last="${bootstrap_values[3]:-}"
    owner_password="${bootstrap_values[4]:-}"

    if [ "$bootstrap_enabled" != "true" ]; then
        return 0
    fi

    if [ -z "$owner_email" ] || [ -z "$owner_first" ] || [ -z "$owner_last" ] || [ -z "$owner_password" ]; then
        echo -e "${RED}✗ n8n bootstrap enabled but owner credentials are missing.${NC}"
        echo -e "${YELLOW}  ↳ Set N8N_OWNER_EMAIL, N8N_OWNER_FIRST_NAME, N8N_OWNER_LAST_NAME, N8N_OWNER_PASSWORD.${NC}"
        return 1
    fi
    return 0
}

n8n_bootstrap_env_for_tree() {
    local tree_env=$1
    local bootstrap_values=()
    local bootstrap_enabled=""
    local owner_email=""
    local owner_first=""
    local owner_last=""
    local owner_password=""
    mapfile -t bootstrap_values < <(resolve_n8n_bootstrap_values "$tree_env")
    bootstrap_enabled="${bootstrap_values[0]:-}"
    owner_email="${bootstrap_values[1]:-}"
    owner_first="${bootstrap_values[2]:-}"
    owner_last="${bootstrap_values[3]:-}"
    owner_password="${bootstrap_values[4]:-}"
    [ -n "$bootstrap_enabled" ] && printf 'N8N_BOOTSTRAP_ENABLED=%s\n' "$bootstrap_enabled"
    [ -n "$owner_email" ] && printf 'N8N_OWNER_EMAIL=%s\n' "$owner_email"
    [ -n "$owner_first" ] && printf 'N8N_OWNER_FIRST_NAME=%s\n' "$owner_first"
    [ -n "$owner_last" ] && printf 'N8N_OWNER_LAST_NAME=%s\n' "$owner_last"
    [ -n "$owner_password" ] && printf 'N8N_OWNER_PASSWORD=%s\n' "$owner_password"
}

n8n_owner_email_from_db() {
    local tree_dir=$1
    local db_name=$2
    [ -n "$tree_dir" ] || return 0
    [ -n "$db_name" ] || return 0
    tree_dir=$(cd "$tree_dir" && pwd -P 2>/dev/null) || return 0

    local db_container=""
    db_container=$(supabase_container_name "$tree_dir" "supabase-db" 2>/dev/null || true)
    if [ -z "$db_container" ]; then
        return 0
    fi
    if ! docker_ps_names_contains "$db_container"; then
        return 0
    fi

    supabase_docker_cmd exec "$db_container" psql -U postgres -d "$db_name" -tAc \
        "select coalesce(email,'') from \"user\" where coalesce(\"roleSlug\",'')='global:owner' order by \"createdAt\" asc limit 1;" \
        2>/dev/null | tr -d '[:space:]'
}

n8n_wait_for_health() {
    local base_url=$1
    local attempts=${2:-20}
    local delay=${3:-1}
    [ -n "$base_url" ] || return 1
    if ! command -v curl >/dev/null 2>&1; then
        return 1
    fi
    local last_status=""
    local i
    for ((i=1; i<=attempts; i++)); do
        last_status=$(curl -s -o /dev/null -w "%{http_code}" "${base_url}/healthz" 2>/dev/null || true)
        if [ "$last_status" = "200" ]; then
            return 0
        fi
        sleep "$delay"
    done
    debug_log_line_safe "WARN" \
        "n8n.health.timeout base_url=${base_url} attempts=${attempts} last_status=${last_status}"
    return 1
}

n8n_login_status() {
    local base_url=$1
    local email=$2
    local password=$3
    [ -n "$base_url" ] || return 1
    [ -n "$email" ] || return 1
    [ -n "$password" ] || return 1
    if ! command -v curl >/dev/null 2>&1; then
        return 1
    fi
    curl -s -o /dev/null -w "%{http_code}" \
        -H "Content-Type: application/json" \
        -d "{\"email\":\"${email}\",\"password\":\"${password}\"}" \
        "${base_url}/rest/login" || true
}

n8n_log_exit_diagnostics() {
    local container=$1
    [ -n "$container" ] || return 0
    if [ "$(type -t debug_log_line)" != "function" ]; then
        return 0
    fi
    if [ "$(type -t debug_enabled)" = "function" ] && ! debug_enabled; then
        return 0
    fi
    if ! command -v docker >/dev/null 2>&1; then
        debug_log_line_safe "WARN" "n8n.exit container=${container} error=docker_unavailable"
        return 0
    fi
    local exit_code=""
    local finished_at=""
    exit_code=$(supabase_docker_cmd inspect -f '{{.State.ExitCode}}' "$container" 2>/dev/null || true)
    finished_at=$(supabase_docker_cmd inspect -f '{{.State.FinishedAt}}' "$container" 2>/dev/null || true)
    debug_log_line_safe "WARN" \
        "n8n.exit container=${container} exit_code=${exit_code} finished_at=${finished_at}"
    local log_tail=""
    log_tail=$(supabase_docker_cmd logs --tail 50 "$container" 2>/dev/null || true)
    if [ -n "$log_tail" ]; then
        while IFS= read -r line; do
            [ -n "$line" ] || continue
            debug_log_line_safe "TRACE" "n8n.exit.log container=${container} line=${line}"
        done <<< "$log_tail"
    fi
}

n8n_reset_owner_if_needed() {
    local tree_dir=$1
    local n8n_port=$2
    local n8n_container_port=$3
    [ -n "$tree_dir" ] || return 0
    tree_dir=$(cd "$tree_dir" && pwd -P 2>/dev/null) || return 0

    local tree_env="${tree_dir%/}/.env"
    local bootstrap_values=()
    local bootstrap_enabled=""
    local owner_email=""
    local owner_first=""
    local owner_last=""
    local owner_password=""
    mapfile -t bootstrap_values < <(resolve_n8n_bootstrap_values "$tree_env")
    bootstrap_enabled="${bootstrap_values[0]:-}"
    owner_email="${bootstrap_values[1]:-}"
    owner_first="${bootstrap_values[2]:-}"
    owner_last="${bootstrap_values[3]:-}"
    owner_password="${bootstrap_values[4]:-}"

    if [ "$bootstrap_enabled" != "true" ]; then
        return 0
    fi
    if [ -z "$owner_email" ] || [ -z "$owner_first" ] || [ -z "$owner_last" ] || [ -z "$owner_password" ]; then
        return 0
    fi
    if [ -n "${N8N_OWNER_RESET_DONE[$tree_dir]:-}" ]; then
        return 0
    fi

    local n8n_host_port="$n8n_port"
    if [ -z "$n8n_host_port" ]; then
        local n8n_base="${N8N_PORT_BASE:-5678}"
        n8n_host_port="$n8n_base"
    fi
    local internal_host
    internal_host=$(run_sh_internal_host)
    local base_url="http://${internal_host}:${n8n_host_port}"
    if ! n8n_wait_for_health "$base_url"; then
        echo -e "${YELLOW}⚠ n8n health check timed out for ${tree_dir}; skipping owner reset.${NC}"
        return 0
    fi

    local n8n_db_name=""
    n8n_db_name=$(resolve_n8n_db_name "$tree_dir" "${N8N_DB_NAME:-}")
    local owner_email_db=""
    owner_email_db=$(n8n_owner_email_from_db "$tree_dir" "$n8n_db_name")

    local login_code=""
    login_code=$(n8n_login_status "$base_url" "$owner_email" "$owner_password")
    if [ "$login_code" = "404" ]; then
        debug_log_line_safe "INFO" \
            "n8n.login.skip tree=${tree_dir} base_url=${base_url} status=404 reason=not_ready"
        return 0
    fi
    if [ "$login_code" = "200" ] || [ "$login_code" = "204" ]; then
        debug_log_line_safe "INFO" \
            "n8n.owner.login.ok tree=${tree_dir} base_url=${base_url} status=${login_code} action=skip_reset"
        N8N_OWNER_RESET_DONE["$tree_dir"]=1
        return 0
    fi
    local needs_reset=false
    if [ -z "$owner_email_db" ] || [ "$owner_email_db" != "$owner_email" ]; then
        needs_reset=true
    elif [ "$login_code" = "401" ] || [ "$login_code" = "403" ]; then
        needs_reset=true
    fi

    if [ "$needs_reset" != true ]; then
        return 0
    fi

    local project_name="${SUPABASE_TREE_PROJECTS[$tree_dir]:-}"
    if [ -z "$project_name" ]; then
        project_name=$(supabase_compose_project_name "$tree_dir")
        SUPABASE_TREE_PROJECTS["$tree_dir"]="$project_name"
    fi
    local network_name=""
    network_name=$(supabase_network_name "$tree_dir" 2>/dev/null || true)
    ensure_service_on_supabase_network "$tree_dir" "supabase-db"

    local env_file=""
    env_file=$(supabase_env_file_for_tree "$tree_dir" 2>/dev/null || true)
    local env_args=()
    if [ -n "$env_file" ]; then
        env_args+=(--env-file "$env_file")
    fi
    if [ -f "$tree_env" ]; then
        env_args+=(--env-file "$tree_env")
    fi

    local n8n_container=""
    n8n_container=$(supabase_docker_compose "$tree_dir" "${env_args[@]}" -p "$project_name" \
        -f "docker-compose.yml" -f "supabase/docker-compose.yml" ps -q n8n 2>/dev/null || true)
    if [ -n "$n8n_container" ]; then
        echo -e "${YELLOW}Resetting n8n owner for ${tree_dir}...${NC}"
        supabase_docker_cmd exec "$n8n_container" n8n user-management:reset >/dev/null 2>&1 || true
        supabase_docker_cmd restart "$n8n_container" >/dev/null 2>&1 || true
    fi

    if ! n8n_wait_for_health "$base_url"; then
        echo -e "${YELLOW}⚠ n8n health check failed after reset for ${tree_dir}.${NC}"
        return 1
    fi

    local setup_code=""
    setup_code=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Content-Type: application/json" \
        -d "{\"email\":\"${owner_email}\",\"firstName\":\"${owner_first}\",\"lastName\":\"${owner_last}\",\"password\":\"${owner_password}\"}" \
        "${base_url}/rest/owner/setup" || true)
    if [ "$setup_code" != "200" ] && [ "$setup_code" != "201" ]; then
        local verify_code=""
        verify_code=$(n8n_login_status "$base_url" "$owner_email" "$owner_password")
        if [ "$verify_code" = "200" ] || [ "$verify_code" = "204" ]; then
            debug_log_line_safe "INFO" \
                "n8n.owner.setup.non_2xx tree=${tree_dir} setup_status=${setup_code} verify_status=${verify_code} action=accept"
            N8N_OWNER_RESET_DONE["$tree_dir"]=1
            return 0
        fi
        if [ "$setup_code" = "404" ] || [ "$verify_code" = "404" ]; then
            debug_log_line_safe "INFO" \
                "n8n.owner.setup.skip tree=${tree_dir} setup_status=${setup_code} verify_status=${verify_code} action=endpoint_unavailable"
            N8N_OWNER_RESET_DONE["$tree_dir"]=1
            echo -e "${YELLOW}Skipping n8n owner bootstrap retry for ${tree_dir}; endpoint unavailable (setup:${setup_code}, login:${verify_code:-n/a}).${NC}"
            return 0
        fi
        echo -e "${RED}✗ n8n owner bootstrap retry failed for ${tree_dir} (setup status ${setup_code}, verify login status ${verify_code:-n/a}).${NC}"
        return 1
    fi

    N8N_OWNER_RESET_DONE["$tree_dir"]=1
    return 0
}

n8n_personal_project_fix_sql() {
    local owner_id=$1
    [ -n "$owner_id" ] || return 0
    cat <<SQL
DO \$\$
DECLARE
    owner_id uuid := '${owner_id}';
    project_id varchar(36);
BEGIN
    SELECT id INTO project_id FROM project WHERE type = 'personal' AND "creatorId" = owner_id LIMIT 1;
    IF project_id IS NULL THEN
        SELECT id INTO project_id FROM project WHERE type = 'personal' AND "creatorId" IS NULL ORDER BY "createdAt" ASC LIMIT 1;
        IF project_id IS NOT NULL THEN
            UPDATE project SET "creatorId" = owner_id, "updatedAt" = now() WHERE id = project_id;
        ELSE
            project_id := gen_random_uuid()::text;
            INSERT INTO project (id, name, type, "creatorId", "createdAt", "updatedAt")
            VALUES (project_id, 'Unnamed Project', 'personal', owner_id, now(), now());
        END IF;
    END IF;

    IF project_id IS NOT NULL THEN
        IF NOT EXISTS (SELECT 1 FROM project_relation WHERE "projectId" = project_id AND "userId" = owner_id) THEN
            INSERT INTO project_relation ("projectId", "userId", role, "createdAt", "updatedAt")
            VALUES (project_id, owner_id, 'project:personalOwner', now(), now());
        END IF;
    END IF;
END
\$\$;
SQL
}

ensure_n8n_owner_shell() {
    local tree_dir=$1
    local db_name=$2
    [ -n "$tree_dir" ] || return 0
    [ -n "$db_name" ] || return 0

    if ! [[ "$db_name" =~ ^[A-Za-z0-9_]+$ ]]; then
        return 0
    fi

    local tree_env="${tree_dir%/}/.env"
    local bootstrap_values=()
    local bootstrap_enabled=""
    local owner_email=""
    local owner_first=""
    local owner_last=""
    local owner_password=""
    mapfile -t bootstrap_values < <(resolve_n8n_bootstrap_values "$tree_env")
    bootstrap_enabled="${bootstrap_values[0]:-}"
    owner_email="${bootstrap_values[1]:-}"
    owner_first="${bootstrap_values[2]:-}"
    owner_last="${bootstrap_values[3]:-}"
    owner_password="${bootstrap_values[4]:-}"
    if [ "$bootstrap_enabled" != "true" ]; then
        return 0
    fi

    if [ -z "$owner_email" ] || [ -z "$owner_first" ] || [ -z "$owner_last" ] || [ -z "$owner_password" ]; then
        return 0
    fi

    local db_container=""
    db_container=$(supabase_container_name "$tree_dir" "supabase-db" 2>/dev/null || true)
    if [ -z "$db_container" ]; then
        return 0
    fi
    if ! docker_ps_names_contains "$db_container"; then
        return 0
    fi

    local owner_id=""
    if [ -n "$owner_email" ]; then
        owner_id=$(supabase_docker_cmd exec "$db_container" psql -U postgres -d "$db_name" -tAc \
            "select id from \"user\" where email='${owner_email}' order by \"createdAt\" asc limit 1;" \
            2>/dev/null | tr -d '[:space:]')
    fi
    if [ -z "$owner_id" ]; then
        owner_id=$(supabase_docker_cmd exec "$db_container" psql -U postgres -d "$db_name" -tAc \
            "select id from \"user\" where coalesce(\"roleSlug\",'')='global:owner' order by \"createdAt\" asc limit 1;" \
            2>/dev/null | tr -d '[:space:]')
    fi
    if [ -z "$owner_id" ]; then
        return 0
    fi

    local fix_sql=""
    fix_sql=$(n8n_personal_project_fix_sql "$owner_id")
    if [ -n "$fix_sql" ]; then
        printf '%s\n' "$fix_sql" | supabase_docker_cmd exec -i "$db_container" psql -U postgres -d "$db_name" >/dev/null 2>&1 || true
    fi
}

n8n_api_key_is_valid() {
    local api_key=$1
    [ -n "$api_key" ] || return 1
    if [[ "$api_key" == n8n_api_* ]]; then
        return 0
    fi
    if [[ "$api_key" =~ ^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$ ]]; then
        return 0
    fi
    return 1
}

generate_n8n_api_key() {
    local token=""
    if command -v openssl >/dev/null 2>&1; then
        token=$(openssl rand -hex 16 2>/dev/null)
    fi
    if [ -z "$token" ] && command -v uuidgen >/dev/null 2>&1; then
        token=$(uuidgen | tr -d '-' | tr '[:upper:]' '[:lower:]')
    fi
    if [ -z "$token" ]; then
        token=$(date +%s)${$}
    fi
    printf 'n8n_api_%s\n' "$token"
}

ensure_n8n_api_key_shell() {
    local tree_dir=$1
    local db_name=$2
    local api_key=$3
    [ -n "$tree_dir" ] || return 0
    [ -n "$db_name" ] || return 0
    [ -n "$api_key" ] || return 0

    if ! n8n_api_key_is_valid "$api_key"; then
        return 0
    fi
    if ! [[ "$db_name" =~ ^[A-Za-z0-9_]+$ ]]; then
        return 0
    fi

    local db_container=""
    db_container=$(supabase_container_name "$tree_dir" "supabase-db" 2>/dev/null || true)
    if [ -z "$db_container" ]; then
        return 0
    fi
    if ! docker_ps_names_contains "$db_container"; then
        return 0
    fi

    local owner_id=""
    owner_id=$(supabase_docker_cmd exec "$db_container" psql -U postgres -d "$db_name" -tAc \
        "select id from \"user\" where coalesce(\"roleSlug\",'')='global:owner' order by \"createdAt\" asc limit 1;" \
        2>/dev/null | tr -d '[:space:]')
    if [ -z "$owner_id" ]; then
        return 0
    fi

    local key_exists=""
    key_exists=$(supabase_docker_cmd exec "$db_container" psql -U postgres -d "$db_name" -tAc \
        "select 1 from \"user_api_keys\" where \"apiKey\"='${api_key}' limit 1;" \
        2>/dev/null | tr -d '[:space:]')
    if [ "$key_exists" = "1" ]; then
        return 0
    fi

    supabase_docker_cmd exec "$db_container" psql -U postgres -d "$db_name" -c \
        "insert into \"user_api_keys\" (\"id\", \"userId\", \"label\", \"apiKey\", \"scopes\", \"createdAt\", \"updatedAt\") values (gen_random_uuid(), '${owner_id}', '${ENVCTL_PROJECT_PREFIX:-supportopia}-bootstrap', '${api_key}', '[\"*\"]', now(), now());" \
        >/dev/null 2>&1 || true
}
apply_n8n_env_for_tree() {
    local tree_dir=$1
    local n8n_port=$2
    [ -n "$tree_dir" ] || return 0
    tree_dir=$(cd "$tree_dir" && pwd -P 2>/dev/null) || return 0
    local tree_env="${tree_dir%/}/.env"

    local resolved_port=""
    if [ "$(type -t tree_n8n_port_for_dir)" = "function" ]; then
        local tmp_out=""
        tmp_out=$(mktemp 2>/dev/null || mktemp -t n8n-port)
        tree_n8n_port_for_dir "$tree_dir" "" >"$tmp_out" 2>/dev/null || true
        if [ -s "$tmp_out" ]; then
            resolved_port=$(tr -d '[:space:]' < "$tmp_out")
        fi
        rm -f "$tmp_out"
    fi
    if [ -n "$resolved_port" ]; then
        n8n_port="$resolved_port"
    fi
    if [ -z "$n8n_port" ] || ! [[ "$n8n_port" =~ ^[0-9]+$ ]]; then
        return 0
    fi

    local base_dir=""
    if [ -n "${BASE_DIR:-}" ]; then
        base_dir=$(cd "$BASE_DIR" && pwd -P 2>/dev/null) || base_dir="$BASE_DIR"
    fi
    if [ -n "$base_dir" ] && [ "$tree_dir" = "$base_dir" ]; then
        local internal_host
        internal_host=$(run_sh_internal_host)
        echo "Using n8n base URL for main: http://${internal_host}:${n8n_port}"
    fi

    local backend_dir
    backend_dir=$(find_backend_dir "$tree_dir" 2>/dev/null || true)
    if [ -n "$backend_dir" ] && [ -f "$backend_dir/.env" ]; then
        local backend_env="$backend_dir/.env"
        local internal_host
        internal_host=$(run_sh_internal_host)
        upsert_env_value "$backend_env" "N8N_API_BASE_URL" "http://${internal_host}:${n8n_port}"
        upsert_env_value "$backend_env" "N8N_EDITOR_BASE_URL" "http://${internal_host}:${n8n_port}"

        local defaults_env=""
        if [ -n "${BASE_DIR:-}" ]; then
            if [ -f "${BASE_DIR%/}/backend/.env.main" ]; then
                defaults_env="${BASE_DIR%/}/backend/.env.main"
            elif [ -f "${BASE_DIR%/}/.env.main" ]; then
                defaults_env="${BASE_DIR%/}/.env.main"
            fi
        fi

        local default_api_key=""
        if [ -n "$defaults_env" ]; then
            default_api_key=$(read_env_value "$defaults_env" "N8N_API_KEY")
        fi
        if [ -z "$default_api_key" ]; then
            default_api_key="${N8N_API_KEY:-}"
        fi
        if ! n8n_api_key_is_valid "$default_api_key"; then
            default_api_key=$(generate_n8n_api_key)
        fi

        local default_webhook_secret=""
        if [ -n "$defaults_env" ]; then
            default_webhook_secret=$(read_env_value "$defaults_env" "N8N_WEBHOOK_SECRET")
        fi
        if [ -z "$default_webhook_secret" ]; then
            default_webhook_secret="${N8N_WEBHOOK_SECRET:-local-n8n-webhook-secret}"
        fi

        local default_service_token=""
        if [ -n "$defaults_env" ]; then
            default_service_token=$(read_env_value "$defaults_env" "N8N_SERVICE_TOKEN")
        fi
        if [ -z "$default_service_token" ]; then
            default_service_token="${N8N_SERVICE_TOKEN:-local-n8n-service-token}"
        fi

        local default_integrations_mode="${INTEGRATIONS_MODE:-n8n}"
        local default_ai_provider="${AI_PROVIDER:-n8n}"
        local default_ai_workflow=""
        if [ -n "$defaults_env" ]; then
            default_ai_workflow=$(read_env_value "$defaults_env" "N8N_AI_WORKFLOW_ID")
        fi
        if [ -z "$default_ai_workflow" ] && [ -n "${N8N_AI_WORKFLOW_ID:-}" ]; then
            default_ai_workflow="${N8N_AI_WORKFLOW_ID}"
        fi

        local existing_api_key=""
        existing_api_key=$(read_env_value "$backend_env" "N8N_API_KEY")
        local compose_api_key=""
        if [ -f "$tree_env" ]; then
            compose_api_key=$(read_env_value "$tree_env" "N8N_API_KEY")
        fi

        local resolved_api_key="$existing_api_key"
        if ! n8n_api_key_is_valid "$resolved_api_key"; then
            if n8n_api_key_is_valid "$compose_api_key"; then
                resolved_api_key="$compose_api_key"
            else
                resolved_api_key="$default_api_key"
            fi
        fi
        if ! n8n_api_key_is_valid "$resolved_api_key"; then
            resolved_api_key=$(generate_n8n_api_key)
        fi
        if ! n8n_api_key_is_valid "$existing_api_key" || [ "$existing_api_key" != "$resolved_api_key" ]; then
            upsert_env_value "$backend_env" "N8N_API_KEY" "$resolved_api_key"
        fi

        local existing_webhook_secret=""
        existing_webhook_secret=$(read_env_value "$backend_env" "N8N_WEBHOOK_SECRET")
        local compose_webhook_secret=""
        if [ -f "$tree_env" ]; then
            compose_webhook_secret=$(read_env_value "$tree_env" "N8N_WEBHOOK_SECRET")
        fi
        local resolved_webhook_secret="$existing_webhook_secret"
        if [ -z "$resolved_webhook_secret" ]; then
            resolved_webhook_secret="$compose_webhook_secret"
        fi
        if [ -z "$resolved_webhook_secret" ]; then
            resolved_webhook_secret="$default_webhook_secret"
        fi
        if [ -z "$existing_webhook_secret" ] || [ "$existing_webhook_secret" != "$resolved_webhook_secret" ]; then
            upsert_env_value "$backend_env" "N8N_WEBHOOK_SECRET" "$resolved_webhook_secret"
        fi

        local existing_service_token=""
        existing_service_token=$(read_env_value "$backend_env" "N8N_SERVICE_TOKEN")
        local compose_service_token=""
        if [ -f "$tree_env" ]; then
            compose_service_token=$(read_env_value "$tree_env" "N8N_SERVICE_TOKEN")
        fi
        local resolved_service_token="$existing_service_token"
        if [ -z "$resolved_service_token" ]; then
            resolved_service_token="$compose_service_token"
        fi
        if [ -z "$resolved_service_token" ]; then
            resolved_service_token="$default_service_token"
        fi
        if [ -z "$existing_service_token" ] || [ "$existing_service_token" != "$resolved_service_token" ]; then
            upsert_env_value "$backend_env" "N8N_SERVICE_TOKEN" "$resolved_service_token"
        fi

        if n8n_api_key_is_valid "$resolved_api_key"; then
            upsert_env_value "$tree_env" "N8N_API_KEY" "$resolved_api_key"
        fi
        if [ -n "$resolved_webhook_secret" ]; then
            upsert_env_value "$tree_env" "N8N_WEBHOOK_SECRET" "$resolved_webhook_secret"
        fi
        if [ -n "$resolved_service_token" ]; then
            upsert_env_value "$tree_env" "N8N_SERVICE_TOKEN" "$resolved_service_token"
        fi

        local bootstrap_values=()
        local bootstrap_enabled=""
        local owner_email=""
        local owner_first=""
        local owner_last=""
        local owner_password=""
        mapfile -t bootstrap_values < <(resolve_n8n_bootstrap_values "$tree_env")
        bootstrap_enabled="${bootstrap_values[0]:-}"
        owner_email="${bootstrap_values[1]:-}"
        owner_first="${bootstrap_values[2]:-}"
        owner_last="${bootstrap_values[3]:-}"
        owner_password="${bootstrap_values[4]:-}"

        if [ -n "$bootstrap_enabled" ]; then
            upsert_env_value "$tree_env" "N8N_BOOTSTRAP_ENABLED" "$bootstrap_enabled"
        fi
        if [ -n "$owner_email" ]; then
            upsert_env_value "$tree_env" "N8N_OWNER_EMAIL" "$owner_email"
        fi
        if [ -n "$owner_first" ]; then
            upsert_env_value "$tree_env" "N8N_OWNER_FIRST_NAME" "$owner_first"
        fi
        if [ -n "$owner_last" ]; then
            upsert_env_value "$tree_env" "N8N_OWNER_LAST_NAME" "$owner_last"
        fi
        if [ -n "$owner_password" ]; then
            upsert_env_value "$tree_env" "N8N_OWNER_PASSWORD" "$owner_password"
        fi

        local existing_mode=""
        existing_mode=$(read_env_value "$backend_env" "INTEGRATIONS_MODE")
        if [ -z "$existing_mode" ]; then
            upsert_env_value "$backend_env" "INTEGRATIONS_MODE" "$default_integrations_mode"
            existing_mode="$default_integrations_mode"
        fi

        local existing_ai_provider=""
        existing_ai_provider=$(read_env_value "$backend_env" "AI_PROVIDER")
        local mode_normalized=""
        mode_normalized=$(printf '%s' "$existing_mode" | tr '[:upper:]' '[:lower:]')
        local provider_normalized=""
        provider_normalized=$(printf '%s' "$existing_ai_provider" | tr '[:upper:]' '[:lower:]')
        if [ -z "$existing_ai_provider" ]; then
            upsert_env_value "$backend_env" "AI_PROVIDER" "$default_ai_provider"
        elif [ "$mode_normalized" = "n8n" ] && [ "$provider_normalized" != "n8n" ]; then
            upsert_env_value "$backend_env" "AI_PROVIDER" "n8n"
        fi

        if [ -n "$default_ai_workflow" ]; then
            local existing_ai_workflow=""
            existing_ai_workflow=$(read_env_value "$backend_env" "N8N_AI_WORKFLOW_ID")
            if [ -z "$existing_ai_workflow" ]; then
                upsert_env_value "$backend_env" "N8N_AI_WORKFLOW_ID" "$default_ai_workflow"
            fi
        fi
    fi
}

with_tree_db_overrides() {
    local tree_dir=$1
    shift
    tree_dir=$(cd "$tree_dir" && pwd -P 2>/dev/null) || true
    local old_user="${DB_USER:-}"
    local old_password="${DB_PASSWORD:-}"
    local old_name="${DB_NAME:-}"

    local db_password="${SUPABASE_TREE_DB_PASSWORDS[$tree_dir]:-}"
    if [ -n "$db_password" ]; then
        DB_USER="$SUPABASE_DB_USER"
        DB_PASSWORD="$db_password"
        DB_NAME="$SUPABASE_DB_NAME"
    fi

    "$@"
    local rc=$?

    DB_USER="$old_user"
    DB_PASSWORD="$old_password"
    DB_NAME="$old_name"
    return $rc
}

supabase_container_name() {
    local tree_dir=$1
    local service=$2
    [ -n "$tree_dir" ] || return 1
    [ -n "$service" ] || return 1
    tree_dir=$(cd "$tree_dir" && pwd -P 2>/dev/null) || return 1
    local project_name="${SUPABASE_TREE_PROJECTS[$tree_dir]:-}"
    if [ -z "$project_name" ]; then
        project_name=$(supabase_compose_project_name "$tree_dir")
    fi
    echo "${project_name}-${service}-1"
}

start_tree_supabase() {
    local tree_dir=$1
    local db_port=$2

    tree_dir=$(cd "$tree_dir" && pwd -P)
    local compose_dir="${tree_dir%/}/supabase"
    local compose_file="${compose_dir}/docker-compose.yml"
    if [ ! -f "$compose_file" ]; then
        echo -e "${RED}Supabase compose file not found at ${compose_file}${NC}"
        return 1
    fi

    if [ -z "${SUPABASE_TREE_PUBLIC_PORTS[$tree_dir]:-}" ]; then
        if [ -z "$db_port" ]; then
            db_port=$(supabase_value_for_tree "$tree_dir" "SUPABASE_DB_PORT" "${SUPABASE_DB_PORT_BASE:-54322}")
        fi
        register_supabase_tree_config "$tree_dir" "$db_port"
    fi

    local public_port="${SUPABASE_TREE_PUBLIC_PORTS[$tree_dir]:-}"
    local public_url="${SUPABASE_TREE_PUBLIC_URLS[$tree_dir]:-}"
    if [ -z "$public_port" ] && [ -n "$db_port" ]; then
        public_port=$(supabase_public_port_for_db_port "$tree_dir" "$db_port")
        SUPABASE_TREE_PUBLIC_PORTS["$tree_dir"]="$public_port"
    fi
    if [ -z "$public_url" ] && [ -n "$public_port" ]; then
        public_url="http://localhost:${public_port}"
        SUPABASE_TREE_PUBLIC_URLS["$tree_dir"]="$public_url"
    fi
    if [ -z "$public_port" ] || [ -z "$public_url" ]; then
        echo -e "${RED}Supabase public port/url not set for ${tree_dir}${NC}"
        return 1
    fi
    if [ "$(type -t debug_trace_suppress_begin)" = "function" ]; then
        debug_trace_suppress_begin
    fi
    local db_password="${SUPABASE_TREE_DB_PASSWORDS[$tree_dir]:-supabase-db-password}"
    local jwt_secret="${SUPABASE_TREE_JWT_SECRETS[$tree_dir]:-supabase-local-jwt-secret}"
    local anon_key="${SUPABASE_TREE_ANON_KEYS[$tree_dir]:-local-anon-key}"
    local service_role_key="${SUPABASE_TREE_SERVICE_ROLE_KEYS[$tree_dir]:-local-service-role-key}"
    local project_name="${SUPABASE_TREE_PROJECTS[$tree_dir]:-}"
    if [ -z "$project_name" ]; then
        project_name=$(supabase_compose_project_name "$tree_dir")
        SUPABASE_TREE_PROJECTS["$tree_dir"]="$project_name"
    fi
    local network_name=""
    network_name=$(supabase_network_name "$tree_dir" 2>/dev/null || true)
    ensure_supabase_compose_network "$tree_dir" "$network_name" "$project_name"

    local env_file=""
    env_file=$(supabase_env_file_for_tree "$tree_dir" 2>/dev/null || true)
    local env_args=()
    if [ -n "$env_file" ]; then
        env_args+=(--env-file "$env_file")
    fi
    local tree_env="${tree_dir%/}/.env"
    if [ -f "$tree_env" ]; then
        env_args+=(--env-file "$tree_env")
    fi
    local bootstrap_values=()
    local bootstrap_enabled=""
    local owner_email=""
    local owner_first=""
    local owner_last=""
    local owner_password=""
    mapfile -t bootstrap_values < <(resolve_n8n_bootstrap_values "$tree_env")
    bootstrap_enabled="${bootstrap_values[0]:-}"
    owner_email="${bootstrap_values[1]:-}"
    owner_first="${bootstrap_values[2]:-}"
    owner_last="${bootstrap_values[3]:-}"
    owner_password="${bootstrap_values[4]:-}"
    local bootstrap_env=()
    [ -n "$bootstrap_enabled" ] && bootstrap_env+=(N8N_BOOTSTRAP_ENABLED="$bootstrap_enabled")
    [ -n "$owner_email" ] && bootstrap_env+=(N8N_OWNER_EMAIL="$owner_email")
    [ -n "$owner_first" ] && bootstrap_env+=(N8N_OWNER_FIRST_NAME="$owner_first")
    [ -n "$owner_last" ] && bootstrap_env+=(N8N_OWNER_LAST_NAME="$owner_last")
    [ -n "$owner_password" ] && bootstrap_env+=(N8N_OWNER_PASSWORD="$owner_password")
    if [ "$(type -t debug_trace_suppress_end)" = "function" ]; then
        debug_trace_suppress_end
    fi
    local compose_args=("-f" "supabase/docker-compose.yml")
    local ignore_orphans=false
    if [ "$(type -t tree_uses_n8n)" = "function" ] && tree_uses_n8n "$tree_dir"; then
        ignore_orphans=true
    fi

    local legacy_container=""
    legacy_container=$(requirement_container_name "$DB_CONTAINER_NAME" "$tree_dir" 2>/dev/null || true)
    if [ -n "$legacy_container" ] && docker_ps_names_contains "$legacy_container"; then
        echo -e "${YELLOW}Stopping legacy Postgres container (${legacy_container})...${NC}"
        supabase_docker_cmd stop "$legacy_container" >/dev/null 2>&1 || true
    fi

    local db_container=""
    local db_running=false
    db_container=$(supabase_docker_compose "$tree_dir" "${env_args[@]}" -p "$project_name" "${compose_args[@]}" ps -q supabase-db 2>/dev/null || true)
    if [ -n "$db_container" ]; then
        local db_status=""
        local db_health=""
        db_status=$(supabase_docker_cmd inspect -f '{{.State.Status}}' "$db_container" 2>/dev/null || true)
        db_health=$(supabase_docker_cmd inspect -f '{{.State.Health.Status}}' "$db_container" 2>/dev/null || true)
        if [ "$db_status" = "running" ] && { [ -z "$db_health" ] || [ "$db_health" = "healthy" ]; }; then
            db_running=true
        fi
    fi

    if [ "$db_running" = true ]; then
        local actual_port=""
        if [ "$(type -t container_host_port)" = "function" ]; then
            actual_port=$(container_host_port "$db_container" "5432")
        fi
        if [ -n "$actual_port" ] && [ "$actual_port" != "$db_port" ]; then
            echo -e "${YELLOW}⚠ Supabase DB port mismatch (running ${actual_port}, expected ${db_port}); restarting...${NC}"
            supabase_docker_cmd stop "$db_container" >/dev/null 2>&1 || true
            supabase_docker_cmd rm "$db_container" >/dev/null 2>&1 || true
            db_running=false
        else
            echo -e "${GREEN}✓ Supabase database already running (db:${db_port})${NC}"
        fi
    else
        echo -e "${CYAN}Starting Supabase database for ${tree_dir} (db:${db_port})...${NC}"
        local compose_rc=0
        local compose_output=""
        local bind_retry=0
        local bind_retry_limit="${RUN_SH_SUPABASE_DB_BIND_RETRY_LIMIT:-10}"
        while true; do
            compose_output=""
            compose_rc=0
            if [ "$(type -t debug_trace_suppress_begin)" = "function" ]; then
                debug_trace_suppress_begin
            fi
            if [ "$ignore_orphans" = true ]; then
                compose_output=$(SUPABASE_PUBLIC_PORT="$public_port" \
                    SUPABASE_DB_PORT="$db_port" \
                    SUPABASE_PUBLIC_URL="$public_url" \
                    API_EXTERNAL_URL="$public_url" \
                    SUPABASE_DB_PASSWORD="$db_password" \
                    SUPABASE_JWT_SECRET="$jwt_secret" \
                    SUPABASE_ANON_KEY="$anon_key" \
                    SUPABASE_SERVICE_ROLE_KEY="$service_role_key" \
                    SUPABASE_NETWORK_NAME="$network_name" \
                    COMPOSE_IGNORE_ORPHANS=1 \
                    supabase_docker_compose "$tree_dir" "${env_args[@]}" -p "$project_name" "${compose_args[@]}" up -d supabase-db 2>&1) || compose_rc=$?
            else
                compose_output=$(SUPABASE_PUBLIC_PORT="$public_port" \
                    SUPABASE_DB_PORT="$db_port" \
                    SUPABASE_PUBLIC_URL="$public_url" \
                    API_EXTERNAL_URL="$public_url" \
                    SUPABASE_DB_PASSWORD="$db_password" \
                    SUPABASE_JWT_SECRET="$jwt_secret" \
                    SUPABASE_ANON_KEY="$anon_key" \
                    SUPABASE_SERVICE_ROLE_KEY="$service_role_key" \
                    SUPABASE_NETWORK_NAME="$network_name" \
                    supabase_docker_compose "$tree_dir" "${env_args[@]}" -p "$project_name" "${compose_args[@]}" up -d supabase-db 2>&1) || compose_rc=$?
            fi
            if [ "$(type -t debug_trace_suppress_end)" = "function" ]; then
                debug_trace_suppress_end
            fi
            if [ -n "$compose_output" ]; then
                printf '%s\n' "$compose_output"
            fi
            if [ "$compose_rc" -eq 0 ]; then
                break
            fi

            if ! printf '%s' "$compose_output" | grep -qiE 'port is already allocated|bind for 0\.0\.0\.0:[0-9]+ failed|address already in use'; then
                echo -e "${RED}✗ Supabase database failed to start for ${tree_dir}${NC}"
                return 1
            fi

            if [ "$bind_retry" -ge "$bind_retry_limit" ]; then
                echo -e "${RED}✗ Supabase database failed to start for ${tree_dir} after ${bind_retry_limit} bind retries${NC}"
                return 1
            fi

            bind_retry=$((bind_retry + 1))
            db_port=$(find_free_port $((db_port + 1)))
            public_port=$(supabase_public_port_for_db_port "$tree_dir" "$db_port")
            public_url="http://localhost:${public_port}"
            SUPABASE_TREE_DB_PORTS["$tree_dir"]="$db_port"
            SUPABASE_TREE_PUBLIC_PORTS["$tree_dir"]="$public_port"
            SUPABASE_TREE_PUBLIC_URLS["$tree_dir"]="$public_url"
            if [ -f "$tree_env" ]; then
                upsert_env_value "$tree_env" "DB_PORT" "$db_port"
                upsert_env_value "$tree_env" "SUPABASE_DB_PORT" "$db_port"
                upsert_env_value "$tree_env" "SUPABASE_PUBLIC_PORT" "$public_port"
                upsert_env_value "$tree_env" "SUPABASE_PUBLIC_URL" "$public_url"
            fi
            if [ "$(type -t read_ports_from_worktree_config)" = "function" ] && [ "$(type -t update_worktree_port_config)" = "function" ]; then
                local ports_from_cfg=""
                local cfg_backend=""
                local cfg_frontend=""
                local cfg_db=""
                local cfg_redis=""
                ports_from_cfg=$(read_ports_from_worktree_config "${tree_dir%/}")
                if [ -n "$ports_from_cfg" ]; then
                    IFS='|' read -r cfg_backend cfg_frontend cfg_db cfg_redis <<< "$ports_from_cfg"
                    if [ -n "$cfg_backend" ] && [ -n "$cfg_frontend" ]; then
                        update_worktree_port_config "$tree_dir" "$cfg_backend" "$cfg_frontend" "$db_port" "$cfg_redis"
                    fi
                fi
            fi
            echo -e "${YELLOW}⚠ Supabase DB bind conflict detected; retrying with db:${db_port} public:${public_port} (attempt ${bind_retry}/${bind_retry_limit})${NC}"
        done
        db_container=$(supabase_docker_compose "$tree_dir" "${env_args[@]}" -p "$project_name" "${compose_args[@]}" ps -q supabase-db 2>/dev/null || true)
    fi

    if [ -n "$db_container" ]; then
        for i in {1..30}; do
            if supabase_docker_probe exec "$db_container" pg_isready -U postgres >/dev/null 2>&1; then
                break
            fi
            sleep 1
        done
        if [ -n "$db_password" ]; then
            if [ "$(type -t debug_trace_suppress_begin)" = "function" ]; then
                debug_trace_suppress_begin
            fi
            supabase_reset_auth_admin_password_once "$tree_dir" "$db_container" "$db_password"
            if [ "$(type -t debug_trace_suppress_end)" = "function" ]; then
                debug_trace_suppress_end
            fi
        fi
    fi

    local auth_container=""
    local kong_container=""
    local auth_running=false
    local kong_running=false
    auth_container=$(supabase_docker_compose "$tree_dir" "${env_args[@]}" -p "$project_name" "${compose_args[@]}" ps -q supabase-auth 2>/dev/null || true)
    if [ -n "$auth_container" ]; then
        local auth_status=""
        auth_status=$(supabase_docker_cmd inspect -f '{{.State.Status}}' "$auth_container" 2>/dev/null || true)
        [ "$auth_status" = "running" ] && auth_running=true
    fi
    kong_container=$(supabase_docker_compose "$tree_dir" "${env_args[@]}" -p "$project_name" "${compose_args[@]}" ps -q supabase-kong 2>/dev/null || true)
    if [ -n "$kong_container" ]; then
        local kong_status=""
        kong_status=$(supabase_docker_cmd inspect -f '{{.State.Status}}' "$kong_container" 2>/dev/null || true)
        [ "$kong_status" = "running" ] && kong_running=true
    fi

    if [ -n "$db_container" ]; then
        local actual_db_port=""
        actual_db_port=$(container_host_port "$db_container" "5432")
        if [ -n "$actual_db_port" ] && [ "$actual_db_port" != "$db_port" ]; then
            db_port="$actual_db_port"
            SUPABASE_TREE_DB_PORTS["$tree_dir"]="$db_port"
        fi
    fi

    if [ "$kong_running" = true ]; then
        local actual_public_port=""
        actual_public_port=$(container_host_port "$kong_container" "8000")
        if [ -n "$actual_public_port" ] && [ "$actual_public_port" != "$public_port" ]; then
            public_port="$actual_public_port"
            public_url="http://localhost:${public_port}"
            SUPABASE_TREE_PUBLIC_PORTS["$tree_dir"]="$public_port"
            SUPABASE_TREE_PUBLIC_URLS["$tree_dir"]="$public_url"
        fi
    fi

    if [ "$auth_running" = true ] && [ "$kong_running" = true ]; then
        echo -e "${GREEN}✓ Supabase auth/gateway already running (public:${public_port})${NC}"
    else
        echo -e "${CYAN}Starting Supabase auth/gateway for ${tree_dir} (public:${public_port})...${NC}"
        local compose_rc=0
        if [ "$(type -t debug_trace_suppress_begin)" = "function" ]; then
            debug_trace_suppress_begin
        fi
        if [ "$ignore_orphans" = true ]; then
            (SUPABASE_PUBLIC_PORT="$public_port" \
                SUPABASE_DB_PORT="$db_port" \
                SUPABASE_PUBLIC_URL="$public_url" \
                API_EXTERNAL_URL="$public_url" \
                SUPABASE_DB_PASSWORD="$db_password" \
                SUPABASE_JWT_SECRET="$jwt_secret" \
                SUPABASE_ANON_KEY="$anon_key" \
                SUPABASE_SERVICE_ROLE_KEY="$service_role_key" \
                SUPABASE_NETWORK_NAME="$network_name" \
                COMPOSE_IGNORE_ORPHANS=1 \
                supabase_docker_compose "$tree_dir" "${env_args[@]}" -p "$project_name" "${compose_args[@]}" up -d supabase-auth supabase-kong) || compose_rc=$?
        else
            (SUPABASE_PUBLIC_PORT="$public_port" \
                SUPABASE_DB_PORT="$db_port" \
                SUPABASE_PUBLIC_URL="$public_url" \
                API_EXTERNAL_URL="$public_url" \
                SUPABASE_DB_PASSWORD="$db_password" \
                SUPABASE_JWT_SECRET="$jwt_secret" \
                SUPABASE_ANON_KEY="$anon_key" \
                SUPABASE_SERVICE_ROLE_KEY="$service_role_key" \
                SUPABASE_NETWORK_NAME="$network_name" \
                supabase_docker_compose "$tree_dir" "${env_args[@]}" -p "$project_name" "${compose_args[@]}" up -d supabase-auth supabase-kong) || compose_rc=$?
        fi
        if [ "$(type -t debug_trace_suppress_end)" = "function" ]; then
            debug_trace_suppress_end
        fi
        if [ "$compose_rc" -ne 0 ]; then
            echo -e "${RED}✗ Supabase auth/gateway failed to start for ${tree_dir}${NC}"
            return 1
        fi
    fi

    local internal_host
    internal_host=$(run_sh_internal_host)
    local internal_url="http://${internal_host}:${public_port}"

    if curl -s -f --connect-timeout 1 --max-time 2 "${internal_url}/auth/v1/health" >/dev/null 2>&1; then
        echo -e "${GREEN}✓ Supabase already healthy (${public_url})${NC}"
        return 0
    fi

    local health_timeout="${SUPABASE_HEALTH_TIMEOUT:-120}"
    echo -e "${YELLOW}Waiting for Supabase (${public_url}) to be ready...${NC}"
    for ((i=1; i<=health_timeout; i++)); do
        if curl -s -f --connect-timeout 1 --max-time 2 "${internal_url}/auth/v1/health" >/dev/null 2>&1; then
            echo -e "${GREEN}✓ Supabase ready (${public_url})${NC}"
            return 0
        fi
        sleep 1
    done

    echo -e "${RED}✗ Supabase failed to become healthy (${public_url})${NC}"
    if command -v docker >/dev/null 2>&1; then
        echo -e "\n${YELLOW}Fetching recent Supabase container logs to diagnose failure:${NC}"
        local -a log_services=("supabase-auth" "supabase-kong" "supabase-db")
        if compose_file_has_service "$compose_file" "supabase-rest"; then
            log_services+=("supabase-rest")
        fi
        supabase_docker_compose "$tree_dir" "${env_args[@]}" -p "$project_name" "${compose_args[@]}" logs --tail 20 "${log_services[@]}" || true

        local auth_logs=""
        auth_logs=$(supabase_docker_compose "$tree_dir" "${env_args[@]}" -p "$project_name" "${compose_args[@]}" logs --tail 80 supabase-auth 2>/dev/null || true)
        if [ -n "$auth_logs" ] && printf '%s' "$auth_logs" | grep -q "operator does not exist: uuid = text"; then
            echo -e "${YELLOW}Detected stale Supabase auth schema/data in the existing DB volume for ${tree_dir}.${NC}"
            echo -e "${YELLOW}Suggested fix: reset this project's Supabase DB volume, then retry startup.${NC}"
            echo -e "${YELLOW}Run: envctl stop-all --stop-all-remove-volumes${NC}"
        fi
    fi
    return 1
}

start_tree_n8n() {
    local tree_dir=$1
    local n8n_port=$2

    tree_dir=$(cd "$tree_dir" && pwd -P)
    if ! tree_uses_n8n "$tree_dir"; then
        return 0
    fi

    local compose_file="${tree_dir%/}/docker-compose.yml"
    local supabase_compose="${tree_dir%/}/supabase/docker-compose.yml"
    if [ ! -f "$compose_file" ] || [ ! -f "$supabase_compose" ]; then
        echo -e "${RED}n8n compose files not found for ${tree_dir}${NC}"
        return 1
    fi
    local bootstrap_service=false
    if compose_file_has_service "$compose_file" "n8n-bootstrap"; then
        bootstrap_service=true
    fi

    local project_name="${SUPABASE_TREE_PROJECTS[$tree_dir]:-}"
    if [ -z "$project_name" ]; then
        project_name=$(supabase_compose_project_name "$tree_dir")
        SUPABASE_TREE_PROJECTS["$tree_dir"]="$project_name"
    fi
    local network_name=""
    network_name=$(supabase_network_name "$tree_dir" 2>/dev/null || true)
    ensure_supabase_compose_network "$tree_dir" "$network_name" "$project_name"

    local env_file=""
    env_file=$(supabase_env_file_for_tree "$tree_dir" 2>/dev/null || true)
    local env_args=()
    if [ -n "$env_file" ]; then
        env_args+=(--env-file "$env_file")
    fi
    local tree_env="${tree_dir%/}/.env"
    if [ -f "$tree_env" ]; then
        env_args+=(--env-file "$tree_env")
    fi
    if ! n8n_validate_bootstrap_config "$tree_env"; then
        return 1
    fi

    if [ -z "$n8n_port" ]; then
        tree_n8n_port_for_dir "$tree_dir" "" n8n_port
    fi
    local n8n_base="${N8N_PORT_BASE:-5678}"
    [ -n "$n8n_port" ] || n8n_port="$n8n_base"
    local n8n_container_port="${N8N_CONTAINER_PORT:-5678}"
    local n8n_host_port="$n8n_port"
    local n8n_port_env="$n8n_container_port"
    if ! n8n_compose_uses_host_port_var "$compose_file"; then
        n8n_port_env="$n8n_host_port"
    fi

    local db_port="${SUPABASE_TREE_DB_PORTS[$tree_dir]:-}"
    local public_port="${SUPABASE_TREE_PUBLIC_PORTS[$tree_dir]:-}"
    local public_url="${SUPABASE_TREE_PUBLIC_URLS[$tree_dir]:-}"
    local db_port_base="${SUPABASE_DB_PORT_BASE:-54322}"
    local public_port_base="${SUPABASE_PUBLIC_PORT_BASE:-54321}"
    if [ -z "$db_port" ]; then
        db_port=$(supabase_value_for_tree "$tree_dir" "SUPABASE_DB_PORT" "$db_port_base")
    fi
    if [ -z "$public_port" ]; then
        public_port=$(supabase_value_for_tree "$tree_dir" "SUPABASE_PUBLIC_PORT" "$public_port_base")
    fi
    if [ -z "$public_url" ]; then
        public_url=$(supabase_value_for_tree "$tree_dir" "SUPABASE_PUBLIC_URL" "http://localhost:${public_port}")
    fi

    local db_password="${SUPABASE_TREE_DB_PASSWORDS[$tree_dir]:-supabase-db-password}"
    local default_editor="http://localhost:5678"
    local default_webhook="http://localhost:5678/"
    local editor_url="${N8N_EDITOR_BASE_URL:-}"
    local webhook_url="${N8N_WEBHOOK_URL:-}"
    if [ -z "$editor_url" ] || [ "$editor_url" = "$default_editor" ]; then
        editor_url="http://localhost:${n8n_port}"
    fi
    if [ -z "$webhook_url" ] || [ "$webhook_url" = "$default_webhook" ]; then
        webhook_url="http://localhost:${n8n_port}/"
    fi

    local n8n_db_name=""
    n8n_db_name=$(resolve_n8n_db_name "$tree_dir" "${N8N_DB_NAME:-}")
    if ! ensure_n8n_database "$tree_dir" "$n8n_db_name"; then
        return 1
    fi
    ensure_n8n_owner_shell "$tree_dir" "$n8n_db_name"
    local backend_dir=""
    local backend_env=""
    local n8n_api_key=""
    backend_dir=$(find_backend_dir "$tree_dir" 2>/dev/null || true)
    if [ -n "$backend_dir" ] && [ -f "$backend_dir/.env" ]; then
        backend_env="$backend_dir/.env"
        n8n_api_key=$(read_env_value "$backend_env" "N8N_API_KEY")
    fi
    if [ -n "$n8n_api_key" ]; then
        ensure_n8n_api_key_shell "$tree_dir" "$n8n_db_name" "$n8n_api_key"
    fi

    local bootstrap_env=()
    if [ -f "$tree_env" ]; then
        while IFS= read -r line; do
            [ -n "$line" ] && bootstrap_env+=("$line")
        done < <(n8n_bootstrap_env_for_tree "$tree_env")
    fi
    local has_base_url=false
    if command -v rg >/dev/null 2>&1; then
        if printf '%s\n' "${bootstrap_env[@]}" | rg -q "^N8N_BASE_URL="; then
            has_base_url=true
        fi
    else
        if printf '%s\n' "${bootstrap_env[@]}" | grep -q "^N8N_BASE_URL="; then
            has_base_url=true
        fi
    fi
    if [ "$has_base_url" != true ]; then
        bootstrap_env+=("N8N_BASE_URL=http://n8n:${n8n_container_port}")
    fi
    if [ "$(type -t debug_trace_suppress_end)" = "function" ]; then
        debug_trace_suppress_end
    fi
    if [ "$(type -t debug_trace_suppress_end)" = "function" ]; then
        debug_trace_suppress_end
    fi

    local n8n_container=""
    local n8n_container_name=""
    n8n_container_name=$(supabase_container_name "$tree_dir" "n8n" 2>/dev/null || true)
    if [ -n "$n8n_container_name" ] && command -v docker >/dev/null 2>&1; then
        local status=""
        status=$(supabase_docker_cmd inspect -f '{{.State.Status}}' "$n8n_container_name" 2>/dev/null || true)
        if [ -n "$status" ]; then
            n8n_container="$n8n_container_name"
        else
            local candidate=""
            while IFS= read -r candidate; do
                case "$candidate" in
                    "$n8n_container_name"|*"_$n8n_container_name"|*"-${n8n_container_name}")
                        n8n_container="$candidate"
                        break
                        ;;
                esac
            done < <(supabase_docker_cmd ps --format '{{.Names}}')
        fi
    fi
    if [ -z "$n8n_container" ]; then
        n8n_container=$(supabase_docker_compose "$tree_dir" "${env_args[@]}" -p "$project_name" \
            -f "docker-compose.yml" -f "supabase/docker-compose.yml" ps -q n8n 2>/dev/null || true)
    fi
    if [ -n "$n8n_container" ]; then
        local n8n_status=""
        n8n_status=$(supabase_docker_cmd inspect -f '{{.State.Status}}' "$n8n_container" 2>/dev/null || true)
        if [ "$n8n_status" = "running" ]; then
            if [ "$bootstrap_service" = true ]; then
                local skip_bootstrap_on_running="${RUN_SH_SKIP_N8N_BOOTSTRAP_ON_RUNNING:-true}"
                if [ "$skip_bootstrap_on_running" = true ]; then
                    echo -e "${GREEN}✓ n8n already running; skipping bootstrap for ${tree_dir}${NC}"
                else
                    echo -e "${CYAN}Ensuring n8n owner bootstrap for ${tree_dir}...${NC}"
                    local compose_rc=0
                    if [ "$(type -t debug_trace_suppress_begin)" = "function" ]; then
                        debug_trace_suppress_begin
                    fi
                    (
                        export N8N_HOST_PORT="$n8n_host_port"
                        export N8N_PORT="$n8n_port_env"
                        export N8N_CONTAINER_PORT="$n8n_container_port"
                        export N8N_EDITOR_BASE_URL="$editor_url"
                        export N8N_WEBHOOK_URL="$webhook_url"
                        export SUPABASE_DB_PASSWORD="$db_password"
                        export SUPABASE_DB_PORT="$db_port"
                        export SUPABASE_PUBLIC_PORT="$public_port"
                        export SUPABASE_PUBLIC_URL="$public_url"
                        export API_EXTERNAL_URL="$public_url"
                        export SUPABASE_NETWORK_NAME="$network_name"
                        for kv in "${bootstrap_env[@]}"; do export "$kv"; done
                        supabase_docker_compose "$tree_dir" "${env_args[@]}" -p "$project_name" \
                        -f "docker-compose.yml" -f "supabase/docker-compose.yml" up -d --no-deps n8n-bootstrap
                    ) || compose_rc=$?
                    if [ "$(type -t debug_trace_suppress_end)" = "function" ]; then
                        debug_trace_suppress_end
                    fi
                    if [ "$compose_rc" -ne 0 ]; then
                        echo -e "${RED}✗ n8n bootstrap failed for ${tree_dir}${NC}"
                        return 1
                    fi
                fi
            fi
            if command -v curl >/dev/null 2>&1; then
                if n8n_api_key_is_valid "$n8n_api_key"; then
                    local api_status=""
                    local internal_host
                    internal_host=$(run_sh_internal_host)
                    api_status=$(curl -s -o /dev/null -w "%{http_code}" \
                        -H "X-N8N-API-KEY: ${n8n_api_key}" \
                        "http://${internal_host}:${n8n_host_port}/api/v1/workflows" || true)
                    if [ "$api_status" = "401" ] || [ "$api_status" = "403" ]; then
                        echo -e "${YELLOW}n8n API key mismatch detected; restarting n8n...${NC}"
                        restart_tree_n8n "$tree_dir" "$n8n_port"
                        return $?
                    fi
                fi
            fi
            n8n_reset_owner_if_needed "$tree_dir" "$n8n_host_port" "$n8n_container_port"
            echo -e "${GREEN}✓ n8n already running (port:${n8n_port})${NC}"
            return 0
        fi
        if [ "$n8n_status" = "exited" ]; then
            n8n_log_exit_diagnostics "$n8n_container"
        fi
    fi

    ensure_service_on_supabase_network "$tree_dir" "supabase-db"
    echo -e "${CYAN}Starting n8n for ${tree_dir} (port:${n8n_port})...${NC}"
    local n8n_services=("n8n")
    if [ "$bootstrap_service" = true ]; then
        n8n_services+=("n8n-bootstrap")
    fi
    local compose_rc=0
    if [ "$(type -t debug_trace_suppress_begin)" = "function" ]; then
        debug_trace_suppress_begin
    fi
    (
        export N8N_HOST_PORT="$n8n_host_port"
        export N8N_PORT="$n8n_port_env"
        export N8N_CONTAINER_PORT="$n8n_container_port"
        export N8N_EDITOR_BASE_URL="$editor_url"
        export N8N_WEBHOOK_URL="$webhook_url"
        export SUPABASE_DB_PASSWORD="$db_password"
        export SUPABASE_DB_PORT="$db_port"
        export SUPABASE_PUBLIC_PORT="$public_port"
        export SUPABASE_PUBLIC_URL="$public_url"
        export API_EXTERNAL_URL="$public_url"
        export SUPABASE_NETWORK_NAME="$network_name"
        for kv in "${bootstrap_env[@]}"; do export "$kv"; done
        supabase_docker_compose "$tree_dir" "${env_args[@]}" -p "$project_name" \
        -f "docker-compose.yml" -f "supabase/docker-compose.yml" up -d --no-deps "${n8n_services[@]}"
    ) || compose_rc=$?
    if [ "$(type -t debug_trace_suppress_end)" = "function" ]; then
        debug_trace_suppress_end
    fi
    if [ "$compose_rc" -ne 0 ]; then
        echo -e "${RED}✗ n8n failed to start for ${tree_dir}${NC}"
        return 1
    fi
    n8n_reset_owner_if_needed "$tree_dir" "$n8n_host_port" "$n8n_container_port"
    return 0
}

restart_tree_n8n() {
    local tree_dir=$1
    local n8n_port=$2

    tree_dir=$(cd "$tree_dir" && pwd -P)
    if ! tree_uses_n8n "$tree_dir"; then
        return 0
    fi

    local compose_file="${tree_dir%/}/docker-compose.yml"
    local supabase_compose="${tree_dir%/}/supabase/docker-compose.yml"
    if [ ! -f "$compose_file" ] || [ ! -f "$supabase_compose" ]; then
        echo -e "${RED}n8n compose files not found for ${tree_dir}${NC}"
        return 1
    fi
    local bootstrap_service=false
    if compose_file_has_service "$compose_file" "n8n-bootstrap"; then
        bootstrap_service=true
    fi

    local project_name="${SUPABASE_TREE_PROJECTS[$tree_dir]:-}"
    if [ -z "$project_name" ]; then
        project_name=$(supabase_compose_project_name "$tree_dir")
        SUPABASE_TREE_PROJECTS["$tree_dir"]="$project_name"
    fi
    local network_name=""
    network_name=$(supabase_network_name "$tree_dir" 2>/dev/null || true)
    ensure_supabase_compose_network "$tree_dir" "$network_name" "$project_name"
    ensure_service_on_supabase_network "$tree_dir" "supabase-db"

    local env_file=""
    env_file=$(supabase_env_file_for_tree "$tree_dir" 2>/dev/null || true)
    local env_args=()
    if [ -n "$env_file" ]; then
        env_args+=(--env-file "$env_file")
    fi
    local tree_env="${tree_dir%/}/.env"
    if [ -f "$tree_env" ]; then
        env_args+=(--env-file "$tree_env")
    fi
    if ! n8n_validate_bootstrap_config "$tree_env"; then
        return 1
    fi

    if [ -z "$n8n_port" ]; then
        tree_n8n_port_for_dir "$tree_dir" "" n8n_port
    fi
    local n8n_base="${N8N_PORT_BASE:-5678}"
    [ -n "$n8n_port" ] || n8n_port="$n8n_base"
    local n8n_container_port="${N8N_CONTAINER_PORT:-5678}"
    local n8n_host_port="$n8n_port"
    local n8n_port_env="$n8n_container_port"
    if ! n8n_compose_uses_host_port_var "$compose_file"; then
        n8n_port_env="$n8n_host_port"
    fi

    local db_port="${SUPABASE_TREE_DB_PORTS[$tree_dir]:-}"
    local public_port="${SUPABASE_TREE_PUBLIC_PORTS[$tree_dir]:-}"
    local public_url="${SUPABASE_TREE_PUBLIC_URLS[$tree_dir]:-}"
    local db_port_base="${SUPABASE_DB_PORT_BASE:-54322}"
    local public_port_base="${SUPABASE_PUBLIC_PORT_BASE:-54321}"
    if [ -z "$db_port" ]; then
        db_port=$(supabase_value_for_tree "$tree_dir" "SUPABASE_DB_PORT" "$db_port_base")
    fi
    if [ -z "$public_port" ]; then
        public_port=$(supabase_value_for_tree "$tree_dir" "SUPABASE_PUBLIC_PORT" "$public_port_base")
    fi
    if [ -z "$public_url" ]; then
        public_url=$(supabase_value_for_tree "$tree_dir" "SUPABASE_PUBLIC_URL" "http://localhost:${public_port}")
    fi

    local db_password="${SUPABASE_TREE_DB_PASSWORDS[$tree_dir]:-supabase-db-password}"
    local default_editor="http://localhost:5678"
    local default_webhook="http://localhost:5678/"
    local editor_url="${N8N_EDITOR_BASE_URL:-}"
    local webhook_url="${N8N_WEBHOOK_URL:-}"
    if [ -z "$editor_url" ] || [ "$editor_url" = "$default_editor" ]; then
        editor_url="http://localhost:${n8n_port}"
    fi
    if [ -z "$webhook_url" ] || [ "$webhook_url" = "$default_webhook" ]; then
        webhook_url="http://localhost:${n8n_port}/"
    fi

    local n8n_db_name=""
    n8n_db_name=$(resolve_n8n_db_name "$tree_dir" "${N8N_DB_NAME:-}")
    if ! ensure_n8n_database "$tree_dir" "$n8n_db_name"; then
        return 1
    fi
    ensure_n8n_owner_shell "$tree_dir" "$n8n_db_name"

    local bootstrap_env=()
    if [ -f "$tree_env" ]; then
        while IFS= read -r line; do
            [ -n "$line" ] && bootstrap_env+=("$line")
        done < <(n8n_bootstrap_env_for_tree "$tree_env")
    fi
    local has_base_url=false
    if command -v rg >/dev/null 2>&1; then
        if printf '%s\n' "${bootstrap_env[@]}" | rg -q "^N8N_BASE_URL="; then
            has_base_url=true
        fi
    else
        if printf '%s\n' "${bootstrap_env[@]}" | grep -q "^N8N_BASE_URL="; then
            has_base_url=true
        fi
    fi
    if [ "$has_base_url" != true ]; then
        bootstrap_env+=("N8N_BASE_URL=http://n8n:${n8n_container_port}")
    fi

    local n8n_container=""
    n8n_container=$(supabase_docker_compose "$tree_dir" "${env_args[@]}" -p "$project_name" \
        -f "docker-compose.yml" -f "supabase/docker-compose.yml" ps -q n8n 2>/dev/null || true)
    if [ -z "$n8n_container" ]; then
        start_tree_n8n "$tree_dir" "$n8n_port"
        return $?
    fi

    echo -e "${CYAN}Restarting n8n for ${tree_dir} (port:${n8n_port})...${NC}"
    local n8n_services=("n8n")
    if [ "$bootstrap_service" = true ]; then
        n8n_services+=("n8n-bootstrap")
    fi
    local compose_rc=0
    if [ "$(type -t debug_trace_suppress_begin)" = "function" ]; then
        debug_trace_suppress_begin
    fi
    (
        export N8N_HOST_PORT="$n8n_host_port"
        export N8N_PORT="$n8n_port_env"
        export N8N_CONTAINER_PORT="$n8n_container_port"
        export N8N_EDITOR_BASE_URL="$editor_url"
        export N8N_WEBHOOK_URL="$webhook_url"
        export SUPABASE_DB_PASSWORD="$db_password"
        export SUPABASE_DB_PORT="$db_port"
        export SUPABASE_PUBLIC_PORT="$public_port"
        export SUPABASE_PUBLIC_URL="$public_url"
        export API_EXTERNAL_URL="$public_url"
        export SUPABASE_NETWORK_NAME="$network_name"
        for kv in "${bootstrap_env[@]}"; do export "$kv"; done
        supabase_docker_compose "$tree_dir" "${env_args[@]}" -p "$project_name" \
        -f "docker-compose.yml" -f "supabase/docker-compose.yml" up -d --no-deps --force-recreate "${n8n_services[@]}"
    ) || compose_rc=$?
        if [ "$(type -t debug_trace_suppress_end)" = "function" ]; then
        debug_trace_suppress_end
    fi
    if [ "$compose_rc" -ne 0 ]; then
        echo -e "${RED}✗ n8n failed to restart for ${tree_dir}${NC}"
        return 1
    fi
    n8n_reset_owner_if_needed "$tree_dir" "$n8n_host_port" "$n8n_container_port"
    return 0
}

stop_tree_supabase() {
    local tree_dir=$1
    local remove_volumes=${2:-false}

    tree_dir=$(cd "$tree_dir" && pwd -P)
    local compose_file="${tree_dir%/}/supabase/docker-compose.yml"
    if [ ! -f "$compose_file" ]; then
        return 0
    fi

    local project_name="${SUPABASE_TREE_PROJECTS[$tree_dir]:-}"
    if [ -z "$project_name" ]; then
        project_name=$(supabase_compose_project_name "$tree_dir")
    fi

    local env_file=""
    env_file=$(supabase_env_file_for_tree "$tree_dir" 2>/dev/null || true)
    local env_args=()
    if [ -n "$env_file" ]; then
        env_args+=(--env-file "$env_file")
    fi
    local tree_env="${tree_dir%/}/.env"
    if [ -f "$tree_env" ]; then
        env_args+=(--env-file "$tree_env")
    fi
    local has_n8n=false
    if [ "$(type -t tree_uses_n8n)" = "function" ] && tree_uses_n8n "$tree_dir"; then
        has_n8n=true
    fi
    local main_compose="${tree_dir%/}/docker-compose.yml"
    local compose_args=("-f" "supabase/docker-compose.yml")
    if [ "$has_n8n" = true ] && [ -f "$main_compose" ]; then
        compose_args=("-f" "docker-compose.yml" "-f" "supabase/docker-compose.yml")
    fi
    local ignore_orphans=false
    if [ "$has_n8n" = true ] && [ ${#compose_args[@]} -eq 2 ]; then
        ignore_orphans=true
    fi

    if [ "$remove_volumes" = true ]; then
        if [ "$ignore_orphans" = true ]; then
            (COMPOSE_IGNORE_ORPHANS=1 supabase_docker_compose "$tree_dir" "${env_args[@]}" -p "$project_name" "${compose_args[@]}" down -v >/dev/null 2>&1) || true
        else
            (supabase_docker_compose "$tree_dir" "${env_args[@]}" -p "$project_name" "${compose_args[@]}" down -v >/dev/null 2>&1) || true
        fi
    else
        if [ "$ignore_orphans" = true ]; then
            (COMPOSE_IGNORE_ORPHANS=1 supabase_docker_compose "$tree_dir" "${env_args[@]}" -p "$project_name" "${compose_args[@]}" down >/dev/null 2>&1) || true
        else
            (supabase_docker_compose "$tree_dir" "${env_args[@]}" -p "$project_name" "${compose_args[@]}" down >/dev/null 2>&1) || true
        fi
    fi
}
