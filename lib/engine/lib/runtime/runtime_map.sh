#!/usr/bin/env bash

runtime_map_path() {
    local runtime_dir=""
    if [ "$(type -t run_sh_runtime_dir)" = "function" ]; then
        runtime_dir=$(run_sh_runtime_dir)
    else
        runtime_dir="${RUN_SH_RUNTIME_DIR:-/tmp/envctl-runtime}"
        mkdir -p "$runtime_dir" 2>/dev/null || true
    fi
    echo "${runtime_dir%/}/.runtime-map"
    return 0
}

write_runtime_map() {
    local map_path
    map_path=$(runtime_map_path) || return 1

    local tmp
    tmp=$(mktemp)

    local mode="main"
    if [ "${TREES_MODE:-false}" = true ]; then
        mode="trees"
    fi

    {
        echo "# envctl runtime map"
        echo "mode|$mode"
        echo "generated_at|$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    } > "$tmp"

    declare -A runtime_projects=()
    declare -A runtime_backend_ports=()
    declare -A runtime_frontend_ports=()
    declare -A runtime_backend_pids=()
    declare -A runtime_frontend_pids=()
    declare -A runtime_roots=()

    local service
    for service in "${services[@]}"; do
        parse_service_entry "$service" name url docs || continue
        local project
        project=$(project_name_from_service_name "$name")
        [ -z "$project" ] && continue

        local pid=""
        local port=""
        local type=""
        local dir=""
        service_info_fields "$name" pid port log type dir || true

        runtime_projects["$project"]=1
        if [ -n "$dir" ]; then
            runtime_roots["$project"]="$(dirname "$dir")"
        fi
        if [ "$type" = "backend" ]; then
            runtime_backend_ports["$project"]="$port"
            runtime_backend_pids["$project"]="$pid"
        elif [ "$type" = "frontend" ]; then
            runtime_frontend_ports["$project"]="$port"
            runtime_frontend_pids["$project"]="$pid"
        fi
    done

    local project_list=()
    local project
    for project in "${!runtime_projects[@]}"; do
        project_list+=("$project")
    done
    if [ ${#project_list[@]} -gt 0 ]; then
        IFS=$'\n' project_list=($(printf '%s\n' "${project_list[@]}" | sort))
    fi

    for project in "${project_list[@]}"; do
        local root="${runtime_roots[$project]:-}"
        if [ -z "$root" ]; then
            root=$(project_root_from_project_name "$project" 2>/dev/null || true)
        fi

        local backend_port="${runtime_backend_ports[$project]:-}"
        local frontend_port="${runtime_frontend_ports[$project]:-}"
        local backend_pid="${runtime_backend_pids[$project]:-}"
        local frontend_pid="${runtime_frontend_pids[$project]:-}"

        local db_port=""
        local redis_port=""
        if [ -n "$root" ]; then
            if per_tree_requirements_enabled; then
                local req_ports
                req_ports=$(tree_requirement_ports_for_dir "$root" "${backend_port:-${BACKEND_PORT_BASE:-8000}}")
                IFS='|' read -r db_port redis_port <<< "$req_ports"
            else
                db_port="${DB_PORT:-${DB_PORT_BASE:-5432}}"
                redis_port="${REDIS_PORT:-${REDIS_PORT_BASE:-6379}}"
            fi
        fi

        echo "${project}|${root}|${backend_port}|${frontend_port}|${db_port}|${redis_port}|${backend_pid}|${frontend_pid}" >> "$tmp"
    done

    mv "$tmp" "$map_path"
}

load_runtime_map() {
    local path=$1
    runtime_projects=()
    unset runtime_roots runtime_backend_ports runtime_frontend_ports runtime_db_ports runtime_redis_ports runtime_backend_pids runtime_frontend_pids
    declare -gA runtime_roots runtime_backend_ports runtime_frontend_ports runtime_db_ports runtime_redis_ports runtime_backend_pids runtime_frontend_pids 2>/dev/null || \
    declare -A runtime_roots runtime_backend_ports runtime_frontend_ports runtime_db_ports runtime_redis_ports runtime_backend_pids runtime_frontend_pids

    while IFS='|' read -r project root backend_port frontend_port db_port redis_port backend_pid frontend_pid; do
        [ -z "$project" ] && continue
        case "$project" in
            \#*|mode|generated_at)
                continue
                ;;
        esac

        runtime_projects+=("$project")
        runtime_roots["$project"]="$root"
        runtime_backend_ports["$project"]="$backend_port"
        runtime_frontend_ports["$project"]="$frontend_port"
        runtime_db_ports["$project"]="$db_port"
        runtime_redis_ports["$project"]="$redis_port"
        runtime_backend_pids["$project"]="$backend_pid"
        runtime_frontend_pids["$project"]="$frontend_pid"
    done < "$path"
}
