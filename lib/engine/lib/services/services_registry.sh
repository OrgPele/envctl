#!/usr/bin/env bash

# Service registry helpers.

if [ -z "${BACKEND_DIR_CACHE+x}" ]; then
    declare -A BACKEND_DIR_CACHE=()
fi
if [ -z "${FRONTEND_DIR_CACHE+x}" ]; then
    declare -A FRONTEND_DIR_CACHE=()
fi
if [ -z "${SERVICE_DIR_CACHE_SIG+x}" ]; then
    declare -A SERVICE_DIR_CACHE_SIG=()
fi

service_dir_cache_enabled() {
    if [ "${RUN_SH_FAST_STARTUP:-false}" != true ]; then
        return 1
    fi
    return 0
}

service_dir_mtime() {
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

service_dir_cache_record() {
    local base_dir=$1
    local backend_dir=$2
    local frontend_dir=$3
    local sig=$4
    if [ -z "$base_dir" ] || [ -z "$sig" ]; then
        return 1
    fi
    if [ "$(type -t run_cache_set_dir_cache)" = "function" ]; then
        run_cache_set_dir_cache "$base_dir" "$sig" "$backend_dir" "$frontend_dir"
    fi
}

find_backend_dir() {
    local base_dir=$1
    if [ -z "$base_dir" ] || [ "${RUN_BACKEND:-true}" = "false" ]; then
        return 1
    fi

    if service_dir_cache_enabled; then
        local sig
        sig=$(service_dir_mtime "$base_dir")
        local cached="${BACKEND_DIR_CACHE[$base_dir]:-}"
        if [ -n "$cached" ] && [ -d "$cached" ] && [ "${SERVICE_DIR_CACHE_SIG[$base_dir]:-}" = "$sig" ]; then
            echo "$cached"
            return 0
        fi
        if [ "$(type -t run_cache_load)" = "function" ]; then
            run_cache_load
            local cached_sig="${RUN_CACHE_DIR_SIG[$base_dir]:-}"
            local cached_backend="${RUN_CACHE_DIR_BACKEND[$base_dir]:-}"
            if [ -n "$cached_backend" ] && [ "$cached_sig" = "$sig" ] && [ -d "$cached_backend" ]; then
                BACKEND_DIR_CACHE[$base_dir]="$cached_backend"
                SERVICE_DIR_CACHE_SIG[$base_dir]="$sig"
                echo "$cached_backend"
                return 0
            fi
        fi
    fi

    # First try exact match
    if [ -d "$base_dir/$BACKEND_DIR_NAME" ]; then
        local resolved="$base_dir/$BACKEND_DIR_NAME"
        if service_dir_cache_enabled; then
            local sig
            sig=$(service_dir_mtime "$base_dir")
            BACKEND_DIR_CACHE[$base_dir]="$resolved"
            SERVICE_DIR_CACHE_SIG[$base_dir]="$sig"
            service_dir_cache_record "$base_dir" "$resolved" "${FRONTEND_DIR_CACHE[$base_dir]:-}" "$sig"
        fi
        echo "$resolved"
        return 0
    fi

    # Try pattern matching (case-insensitive)
    IFS='|' read -ra patterns <<< "$BACKEND_PATTERNS"
    for pattern in "${patterns[@]}"; do
        # Check all directories in base_dir
        for dir in "$base_dir"/*; do
            if [ -d "$dir" ]; then
                local dirname=$(basename "$dir")
                # Case-insensitive match
                if [[ "${dirname,,}" =~ ${pattern,,} ]]; then
                    # Prefer directories that start with the pattern
                    if [[ "${dirname,,}" =~ ^${pattern,,} ]]; then
                        if service_dir_cache_enabled; then
                            local sig
                            sig=$(service_dir_mtime "$base_dir")
                            BACKEND_DIR_CACHE[$base_dir]="$dir"
                            SERVICE_DIR_CACHE_SIG[$base_dir]="$sig"
                            service_dir_cache_record "$base_dir" "$dir" "${FRONTEND_DIR_CACHE[$base_dir]:-}" "$sig"
                        fi
                        echo "$dir"
                        return 0
                    fi
                fi
            fi
        done
        # Second pass for directories that contain the pattern but don't start with it
        for dir in "$base_dir"/*; do
            if [ -d "$dir" ]; then
                local dirname=$(basename "$dir")
                if [[ "${dirname,,}" =~ ${pattern,,} ]]; then
                    if service_dir_cache_enabled; then
                        local sig
                        sig=$(service_dir_mtime "$base_dir")
                        BACKEND_DIR_CACHE[$base_dir]="$dir"
                        SERVICE_DIR_CACHE_SIG[$base_dir]="$sig"
                        service_dir_cache_record "$base_dir" "$dir" "${FRONTEND_DIR_CACHE[$base_dir]:-}" "$sig"
                    fi
                    echo "$dir"
                    return 0
                fi
            fi
        done
    done

    return 1
}

# Function to find frontend directory

find_frontend_dir() {
    local base_dir=$1
    if [ -z "$base_dir" ] || [ "${RUN_FRONTEND:-true}" = "false" ]; then
        return 1
    fi

    if service_dir_cache_enabled; then
        local sig
        sig=$(service_dir_mtime "$base_dir")
        local cached="${FRONTEND_DIR_CACHE[$base_dir]:-}"
        if [ -n "$cached" ] && [ -d "$cached" ] && [ "${SERVICE_DIR_CACHE_SIG[$base_dir]:-}" = "$sig" ]; then
            echo "$cached"
            return 0
        fi
        if [ "$(type -t run_cache_load)" = "function" ]; then
            run_cache_load
            local cached_sig="${RUN_CACHE_DIR_SIG[$base_dir]:-}"
            local cached_frontend="${RUN_CACHE_DIR_FRONTEND[$base_dir]:-}"
            if [ -n "$cached_frontend" ] && [ "$cached_sig" = "$sig" ] && [ -d "$cached_frontend" ]; then
                FRONTEND_DIR_CACHE[$base_dir]="$cached_frontend"
                SERVICE_DIR_CACHE_SIG[$base_dir]="$sig"
                echo "$cached_frontend"
                return 0
            fi
        fi
    fi

    # First try exact match
    if [ -d "$base_dir/$FRONTEND_DIR_NAME" ]; then
        local resolved="$base_dir/$FRONTEND_DIR_NAME"
        if service_dir_cache_enabled; then
            local sig
            sig=$(service_dir_mtime "$base_dir")
            FRONTEND_DIR_CACHE[$base_dir]="$resolved"
            SERVICE_DIR_CACHE_SIG[$base_dir]="$sig"
            service_dir_cache_record "$base_dir" "${BACKEND_DIR_CACHE[$base_dir]:-}" "$resolved" "$sig"
        fi
        echo "$resolved"
        return 0
    fi

    # Try pattern matching (case-insensitive)
    IFS='|' read -ra patterns <<< "$FRONTEND_PATTERNS"
    for pattern in "${patterns[@]}"; do
        # Check all directories in base_dir
        for dir in "$base_dir"/*; do
            if [ -d "$dir" ]; then
                local dirname=$(basename "$dir")
                # Case-insensitive match
                if [[ "${dirname,,}" =~ ${pattern,,} ]]; then
                    # Prefer directories that start with the pattern
                    if [[ "${dirname,,}" =~ ^${pattern,,} ]]; then
                        if service_dir_cache_enabled; then
                            local sig
                            sig=$(service_dir_mtime "$base_dir")
                            FRONTEND_DIR_CACHE[$base_dir]="$dir"
                            SERVICE_DIR_CACHE_SIG[$base_dir]="$sig"
                            service_dir_cache_record "$base_dir" "${BACKEND_DIR_CACHE[$base_dir]:-}" "$dir" "$sig"
                        fi
                        echo "$dir"
                        return 0
                    fi
                fi
            fi
        done
        # Second pass for directories that contain the pattern but don't start with it
        for dir in "$base_dir"/*; do
            if [ -d "$dir" ]; then
                local dirname=$(basename "$dir")
                if [[ "${dirname,,}" =~ ${pattern,,} ]]; then
                    if service_dir_cache_enabled; then
                        local sig
                        sig=$(service_dir_mtime "$base_dir")
                        FRONTEND_DIR_CACHE[$base_dir]="$dir"
                        SERVICE_DIR_CACHE_SIG[$base_dir]="$sig"
                        service_dir_cache_record "$base_dir" "${BACKEND_DIR_CACHE[$base_dir]:-}" "$dir" "$sig"
                    fi
                    echo "$dir"
                    return 0
                fi
            fi
        done
    done

    return 1
}

# Function to get service names for auto-complete

get_service_names() {
    local names=()
    for service in "${services[@]}"; do
        parse_service_entry "$service" name url docs || continue
        [ -n "$name" ] && names+=("$name")
    done
    printf '%s\n' "${names[@]}" | sort -u
}

# Function to get project names for grouped actions

get_project_names() {
    local names=()
    for service in "${services[@]}"; do
        parse_service_entry "$service" name url docs || continue
        [ -z "$name" ] && continue
        local project_name
        project_name=$(project_name_from_service_name "$name")
        [ -n "$project_name" ] && names+=("$project_name")
    done
    printf '%s\n' "${names[@]}" | sort -u
}

services_for_project() {
    local project_name=$1
    local matches=()
    for service in "${services[@]}"; do
        parse_service_entry "$service" name url docs || continue
        local svc_project
        svc_project=$(project_name_from_service_name "$name")
        if [ "$svc_project" = "$project_name" ]; then
            matches+=("$name")
        fi
    done
    printf '%s\n' "${matches[@]}"
}

parse_service_entry() {
    local entry=$1
    local -n out_name=$2
    local -n out_url=$3
    local -n out_docs=$4

    [ -n "$entry" ] || return 1
    IFS='|' read -r out_name out_url out_docs <<< "$entry"
    return 0
}

parse_service_info() {
    local entry=$1
    local -n out_pid=$2
    local -n out_port=$3
    local -n out_log=$4
    local -n out_type=$5
    local -n out_dir=$6

    [ -n "$entry" ] || return 1
    IFS='|' read -r out_pid out_port out_log out_type out_dir <<< "$entry"
    return 0
}

service_info_fields() {
    local name=$1
    local entry="${service_info[$name]:-}"
    [ -n "$entry" ] || return 1
    parse_service_info "$entry" "$2" "$3" "$4" "$5" "$6"
}

port_from_url() {
    local url=$1
    local tail="${url##*:}"
    tail="${tail%%/*}"
    if [[ "$tail" =~ ^[0-9]+$ ]]; then
        echo "$tail"
    fi
}

service_port_for_name() {
    local target=$1
    local service
    for service in "${services[@]}"; do
        parse_service_entry "$service" name url docs || continue
        if [ "$name" = "$target" ]; then
            port_from_url "$url"
            return 0
        fi
    done
    return 1
}

format_log_path() {
    local path=$1
    if [ -z "$path" ]; then
        echo ""
        return 0
    fi
    if [ -n "${BASE_DIR:-}" ] && [[ "$path" == "$BASE_DIR/"* ]]; then
        echo "${path#$BASE_DIR/}"
        return 0
    fi
    echo "$path"
}

resolve_service_pid() {
    local name=$1
    local pid port log type dir
    service_info_fields "$name" pid port log type dir || return 1
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        return 0
    fi

    if [ -n "$port" ]; then
        local new_pid
        new_pid=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -n 1)
        if [ -n "$new_pid" ]; then
            service_info["$name"]="$new_pid|$port|$log|$type|$dir"
            local seen=false
            for existing in "${pids[@]}"; do
                if [ "$existing" = "$new_pid" ]; then
                    seen=true
                    break
                fi
            done
            if [ "$seen" = false ]; then
                pids+=("$new_pid")
            fi
            return 0
        fi
    fi

    return 1
}
