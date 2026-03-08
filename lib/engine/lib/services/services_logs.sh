#!/usr/bin/env bash

# Service logging and health helpers.

if [ "$(type -t ensure_assoc_array)" = "function" ]; then
    ensure_assoc_array SERVICE_PID_RESOLVE_TS
    ensure_assoc_array SERVICE_PID_STATUS_CACHE
    ensure_assoc_array N8N_HEALTH_STATUS
    ensure_assoc_array N8N_HEALTH_STATUS_TS
else
    if [ -z "${SERVICE_PID_RESOLVE_TS+x}" ]; then
        declare -A SERVICE_PID_RESOLVE_TS=()
    fi
    if [ -z "${SERVICE_PID_STATUS_CACHE+x}" ]; then
        declare -A SERVICE_PID_STATUS_CACHE=()
    fi
    if [ -z "${N8N_HEALTH_STATUS+x}" ]; then
        declare -A N8N_HEALTH_STATUS=()
    fi
    if [ -z "${N8N_HEALTH_STATUS_TS+x}" ]; then
        declare -A N8N_HEALTH_STATUS_TS=()
    fi
fi

status_render_fast_defaults() {
    if [ "${RUN_SH_STATUS_FAST:-false}" != true ]; then
        return 0
    fi
    if [ -z "${RUN_SH_STATUS_CACHE_TTL+x}" ]; then
        RUN_SH_STATUS_CACHE_TTL=5
    fi
    if [ -z "${RUN_SH_PID_TTL+x}" ]; then
        RUN_SH_PID_TTL=10
    fi
    if [ -z "${RUN_SH_N8N_HEALTH_TTL+x}" ]; then
        RUN_SH_N8N_HEALTH_TTL=5
    fi
    if [ -z "${RUN_SH_N8N_HEALTH_PARALLEL+x}" ]; then
        RUN_SH_N8N_HEALTH_PARALLEL=4
    fi
}

listener_pids_for_port() {
    local port=$1
    [[ "$port" =~ ^[0-9]+$ ]] || return 1
    if ! command -v lsof >/dev/null 2>&1; then
        return 1
    fi
    local raw=""
    raw=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)
    [ -n "$raw" ] || return 1

    local joined=""
    local seen=""
    local pid=""
    while IFS= read -r pid; do
        [ -n "$pid" ] || continue
        if printf '%s\n' "$seen" | grep -Fxq "$pid"; then
            continue
        fi
        if [ -z "$seen" ]; then
            seen="$pid"
        else
            seen="${seen}"$'\n'"$pid"
        fi
        if [ -z "$joined" ]; then
            joined="$pid"
        else
            joined="${joined},${pid}"
        fi
    done <<< "$raw"

    [ -n "$joined" ] || return 1
    printf '%s\n' "$joined"
    return 0
}

guess_service_log_path() {
    local service_name=$1
    local type=$2
    local port=$3

    [ -n "${LOGS_DIR:-}" ] || return 1
    [ -d "$LOGS_DIR" ] || return 1
    [ -n "$type" ] || return 1

    local project_name=""
    if [ "$(type -t project_name_from_service_name)" = "function" ]; then
        project_name=$(project_name_from_service_name "$service_name")
    fi
    [ -n "$project_name" ] || return 1

    local safe_project="${project_name// /_}"
    local -a candidates=()
    local prev_nullglob
    prev_nullglob=$(shopt -p nullglob 2>/dev/null || true)
    shopt -s nullglob

    if [[ "$port" =~ ^[0-9]+$ ]]; then
        candidates+=("$LOGS_DIR/${safe_project}_b"*"_f"*"_${type}_p${port}/${type}.log")
        candidates+=("$LOGS_DIR/${safe_project}_${type}_p${port}/${type}.log")
    fi
    candidates+=("$LOGS_DIR/${safe_project}"*"/${type}.log")

    eval "$prev_nullglob"

    local candidate=""
    for candidate in "${candidates[@]}"; do
        [ -f "$candidate" ] || continue
        printf '%s\n' "$candidate"
        return 0
    done
    return 1
}

check_service_health() {
    local name=$1
    local url=$2
    local type=$3

    if [ "$type" = "backend" ]; then
        # Check multiple endpoints for backends
        local endpoints=("/api/v1/health" "/health" "/docs")
        for endpoint in "${endpoints[@]}"; do
            if curl -s -f -m 2 "${url}${endpoint}" >/dev/null 2>&1; then
                return 0
            fi
        done
        return 1
    else
        # For frontends, just check if port responds
        local port
        port=$(port_from_url "$url")
        if [ -n "${TIMEOUT_BIN:-}" ]; then
            "$TIMEOUT_BIN" 2 bash -c "echo >/dev/tcp/localhost/$port" 2>/dev/null
        else
            bash -c "echo >/dev/tcp/localhost/$port" 2>/dev/null
        fi
    fi
}

n8n_health_status() {
    local port=$1
    if [ -z "$port" ]; then
        echo "unknown"
        return 0
    fi
    if ! command -v curl >/dev/null 2>&1; then
        echo "unknown"
        return 0
    fi
    if n8n_cached_status "$port"; then
        return 0
    fi
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 1 --max-time 2 "http://localhost:${port}/healthz" || true)
    local status=""
    if [ "$code" = "200" ]; then
        status="healthy"
    elif [ -z "$code" ] || [ "$code" = "000" ]; then
        status="unreachable"
    else
        status="unhealthy:${code}"
    fi
    n8n_cache_status "$port" "$status"
    echo "$status"
}

n8n_cached_status() {
    local port=$1
    local ttl="${RUN_SH_N8N_HEALTH_TTL:-0}"
    if ! [[ "$ttl" =~ ^[0-9]+$ ]] || [ "$ttl" -le 0 ]; then
        return 1
    fi
    local cached_ts="${N8N_HEALTH_STATUS_TS[$port]:-0}"
    local now
    now=$(date +%s)
    if [ "$cached_ts" -gt 0 ] && [ $((now - cached_ts)) -le "$ttl" ]; then
        local cached="${N8N_HEALTH_STATUS[$port]:-}"
        if [ -n "$cached" ]; then
            echo "$cached"
            return 0
        fi
    fi
    return 1
}

n8n_cache_status() {
    local port=$1
    local status=$2
    local ttl="${RUN_SH_N8N_HEALTH_TTL:-0}"
    if ! [[ "$ttl" =~ ^[0-9]+$ ]] || [ "$ttl" -le 0 ]; then
        return 0
    fi
    local now
    now=$(date +%s)
    N8N_HEALTH_STATUS["$port"]="$status"
    N8N_HEALTH_STATUS_TS["$port"]="$now"
}

# Function to start a service

show_status() {
    local include_header=${1:-true}
    if [ "$(type -t status_render_fast_defaults)" = "function" ]; then
        status_render_fast_defaults
    fi
    if [ "$(type -t profile_start)" = "function" ]; then
        profile_start "interactive_render"
    fi
    if [ "$(type -t debug_log_line)" = "function" ] && [ "${RUN_SH_DEBUG_VERBOSE:-false}" = true ] && [ "${RUN_SH_DEBUG_TRACE_INTERACTIVE:-true}" = true ]; then
        debug_log_line "TRACE" "interactive_render.start services=${#services[@]}"
    fi
    local status_mode="${RUN_SH_STATUS_MODE:-full}"
    if [ -z "$status_mode" ]; then
        status_mode="full"
    fi
    local lite_mode=false
    if [ "$status_mode" = "lite" ]; then
        lite_mode=true
    fi
    local show_pr_in_lite="${RUN_SH_LITE_SHOW_PR:-false}"
    local show_run_hints="${RUN_SH_STATUS_SHOW_RUN_HINTS:-false}"
    local show_run_all_together_hints=true
    case "${RUN_SH_STATUS_SHOW_RUN_ALL_HINTS:-true}" in
        0|false|FALSE|no|NO|n|N|off|OFF)
            show_run_all_together_hints=false
            ;;
    esac
    if [ "$include_header" = true ]; then
        echo -e "${CYAN}========================================${NC}"
    fi
    echo -e "${CYAN}Running Services:${NC}"
    echo -e "${CYAN}========================================${NC}"

    if [ ${#services[@]} -eq 0 ]; then
        echo -e "${YELLOW}No services currently running${NC}"
        echo
        if [ "$(type -t debug_log_line)" = "function" ] && [ "${RUN_SH_DEBUG_VERBOSE:-false}" = true ] && [ "${RUN_SH_DEBUG_TRACE_INTERACTIVE:-true}" = true ]; then
            debug_log_line "TRACE" "interactive_render.end services=0"
        fi
        if [ "$(type -t profile_end)" = "function" ]; then
            profile_end "interactive_render"
        fi
        return 0
    fi

    local -A service_urls=()
    local -A project_pr_labels=()
    local -A project_pr_urls=()
    local -A project_pr_checked=()
    local -A project_test_summaries=()
    local -A project_analysis_paths=()
    local -A project_analysis_states=()
    local -A project_roots=()
    local -A project_git_states=()
    local -A seen_projects=()
    local -A project_services=()
    local -a project_order=()
    local service

    for service in "${services[@]}"; do
        parse_service_entry "$service" name url docs || continue
        [ -n "$name" ] || continue
        service_urls["$name"]="$url"
        local project_name
        project_name=$(project_name_from_service_name "$name")
        if [ -n "$project_name" ]; then
            project_services["$project_name"]+="${name}"$'\n'
            if [ -z "${seen_projects[$project_name]:-}" ]; then
                project_order+=("$project_name")
                seen_projects[$project_name]=1
            fi
            if [ -z "${project_roots[$project_name]:-}" ]; then
                local pid port log type dir
                if service_info_fields "$name" pid port log type dir; then
                    if [ -n "$dir" ]; then
                        local root
                        root=$(dirname "$dir")
                        if [ -n "$root" ]; then
                            project_roots["$project_name"]="$root"
                            PROJECT_ROOT_CACHE["$project_name"]="$root"
                        fi
                    fi
                fi
            fi
        fi
    done

    local single_project_mode=false
    if [ "$TREES_MODE" != true ]; then
        single_project_mode=true
    fi

    local service_indent="    "
    local log_indent="      "
    local meta_indent="    "
    if [ "$single_project_mode" = true ]; then
        service_indent="  "
        log_indent="    "
        meta_indent="  "
    fi
    local now_ts
    now_ts=$(date +%s)

    local -A n8n_port_for_project=()
    local -A n8n_status_for_port=()
    local -A n8n_container_ports=()
    local -a docker_ps_names=()
    local docker_ps_loaded=false
    local docker_available=false
    if command -v docker >/dev/null 2>&1; then
        docker_available=true
    fi
    local n8n_parallel="${RUN_SH_N8N_HEALTH_PARALLEL:-0}"

    if [ "$(type -t tree_uses_n8n)" = "function" ] && [ ${#project_order[@]} -gt 0 ]; then
        local project_name_pre=""
        for project_name_pre in "${project_order[@]}"; do
            local project_root=""
            project_root="${project_roots[$project_name_pre]:-}"
            if [ -z "$project_root" ]; then
                project_root=$(project_root_from_project_name "$project_name_pre" 2>/dev/null || true)
            fi
            [ -n "$project_root" ] || continue
            if ! tree_uses_n8n "$project_root"; then
                continue
            fi

            local n8n_container=""
            local n8n_port=""
            local n8n_running=false
            if [ "$(type -t supabase_container_name)" = "function" ]; then
                n8n_container=$(supabase_container_name "$project_root" "n8n" 2>/dev/null || true)
            fi
            if [ -n "$n8n_container" ] && [ "$docker_available" = true ]; then
                if [ "$docker_ps_loaded" = false ]; then
                    local name=""
                    while IFS= read -r name; do
                        [ -n "$name" ] && docker_ps_names+=("$name")
                    done < <(docker ps --format '{{.Names}}')
                    docker_ps_loaded=true
                fi
                local resolved_container=""
                local name=""
                for name in "${docker_ps_names[@]}"; do
                    case "$name" in
                        "$n8n_container"|*"_$n8n_container"|*"-${n8n_container}")
                            resolved_container="$name"
                            n8n_running=true
                            break
                            ;;
                    esac
                done
                if [ -n "$resolved_container" ]; then
                    n8n_container="$resolved_container"
                fi
                if [ "$n8n_running" = true ] && [ "$(type -t container_host_port)" = "function" ]; then
                    if [ -n "${n8n_container_ports[$n8n_container]:-}" ]; then
                        n8n_port="${n8n_container_ports[$n8n_container]}"
                    else
                        n8n_port=$(container_host_port "$n8n_container" "5678")
                        n8n_container_ports[$n8n_container]="$n8n_port"
                    fi
                fi
            fi
            if [ "$n8n_running" = true ] && [ -z "$n8n_port" ]; then
                local project_root_real=""
                project_root_real=$(cd "$project_root" && pwd -P 2>/dev/null || true)
                if [ -n "$project_root_real" ]; then
                    n8n_port="${N8N_TREE_PORTS[$project_root_real]:-}"
                fi
            fi
            if [ -z "$n8n_port" ]; then
                local project_root_real=""
                project_root_real=$(cd "$project_root" && pwd -P 2>/dev/null || true)
                if [ -n "$project_root_real" ]; then
                    n8n_port="${N8N_TREE_PORTS[$project_root_real]:-}"
                fi
            fi
            if [ -z "$n8n_port" ] && [ -n "$project_root" ] && [ "$(type -t read_env_value)" = "function" ]; then
                n8n_port=$(read_env_value "${project_root%/}/.env" "N8N_PORT")
            fi
            if [ -n "$n8n_port" ]; then
                n8n_port_for_project["$project_name_pre"]="$n8n_port"
            fi
        done

        if [ -n "$n8n_parallel" ] && [ "$n8n_parallel" -gt 1 ] && [ ${#n8n_port_for_project[@]} -gt 0 ]; then
            local tmp_dir
            tmp_dir=$(mktemp -d)
            local -A n8n_ports_seen=()
            local -a job_pids=()
            local port=""
            for project_name_pre in "${!n8n_port_for_project[@]}"; do
                port="${n8n_port_for_project[$project_name_pre]}"
                [ -n "$port" ] || continue
                if [ -n "${n8n_ports_seen[$port]:-}" ]; then
                    continue
                fi
                local cached_status=""
                cached_status=$(n8n_cached_status "$port" 2>/dev/null || true)
                if [ -n "$cached_status" ]; then
                    n8n_status_for_port["$port"]="$cached_status"
                    n8n_ports_seen["$port"]=1
                    continue
                fi
                n8n_ports_seen["$port"]=1
                local out_file="${tmp_dir}/n8n_${port}.status"
                (
                    n8n_health_status "$port" > "$out_file"
                ) &
                job_pids+=("$!")

                while [ ${#job_pids[@]} -ge "$n8n_parallel" ]; do
                    local idx
                    for idx in "${!job_pids[@]}"; do
                        if ! kill -0 "${job_pids[$idx]}" 2>/dev/null; then
                            wait "${job_pids[$idx]}" 2>/dev/null || true
                            unset 'job_pids[idx]'
                            job_pids=("${job_pids[@]}")
                            break
                        fi
                    done
                    if [ ${#job_pids[@]} -ge "$n8n_parallel" ]; then
                        sleep 0.05
                    fi
                done
            done
            local pid
            for pid in "${job_pids[@]}"; do
                wait "$pid" 2>/dev/null || true
            done
            for port in "${!n8n_ports_seen[@]}"; do
                local file="${tmp_dir}/n8n_${port}.status"
                if [ -f "$file" ]; then
                    local status=""
                    status=$(cat "$file")
                    n8n_status_for_port["$port"]="$status"
                    n8n_cache_status "$port" "$status"
                fi
            done
            rm -rf "$tmp_dir"
        fi
    fi

    local project_name
    for project_name in "${project_order[@]}"; do
        local project_root=""
        project_root="${project_roots[$project_name]:-}"
        if [ -z "$project_root" ]; then
            project_root=$(project_root_from_project_name "$project_name" 2>/dev/null || true)
            if [ -n "$project_root" ]; then
                project_roots["$project_name"]="$project_root"
                PROJECT_ROOT_CACHE["$project_name"]="$project_root"
            fi
        fi
        local current_state=""
        if [ "$lite_mode" != true ] && [ -n "$project_root" ]; then
            current_state="${project_git_states[$project_name]:-}"
            if [ -z "$current_state" ]; then
                current_state=$(git_state_for_dir "$project_root" 2>/dev/null || true)
                project_git_states[$project_name]="$current_state"
            fi
        fi
        if [ -z "${project_pr_checked[$project_name]:-}" ]; then
            if [ "$lite_mode" != true ] || [ "$show_pr_in_lite" = true ]; then
                local pr_info=""
                local pr_label=""
                local pr_url=""
                pr_info=$(pr_info_for_project "$project_name")
                IFS='|' read -r pr_label pr_url <<< "$pr_info"
                project_pr_labels[$project_name]="$pr_label"
                project_pr_urls[$project_name]="$pr_url"
            fi
            project_pr_checked[$project_name]=1
        fi
        local summary_path=""
        local summary_timestamp=""
        local analysis_path=""
        local analysis_state=""
        if [ "$lite_mode" != true ]; then
            if [ -z "${project_test_summaries[$project_name]:-}" ]; then
                local test_info=""
                test_info=$(test_info_for_project "$project_name" "$current_state" 2>/dev/null || true)
                if [ -n "$test_info" ]; then
                    IFS='|' read -r summary_path test_state <<< "$test_info"
                    project_test_summaries[$project_name]="$summary_path"
                fi
            fi
            summary_path="${project_test_summaries[$project_name]:-}"
            if [ -n "$summary_path" ]; then
                summary_timestamp=$(format_summary_timestamp "$summary_path" 2>/dev/null || true)
            fi
            if [ -z "${project_analysis_paths[$project_name]:-}" ]; then
                local analysis_info=""
                analysis_info=$(analysis_info_for_project "$project_name" "$current_state" 2>/dev/null || true)
                if [ -n "$analysis_info" ]; then
                    IFS='|' read -r analysis_path analysis_state <<< "$analysis_info"
                    project_analysis_paths[$project_name]="$analysis_path"
                    project_analysis_states[$project_name]="$analysis_state"
                fi
            fi
            analysis_path="${project_analysis_paths[$project_name]:-}"
            analysis_state="${project_analysis_states[$project_name]:-}"
        fi
        local pr_label="${project_pr_labels[$project_name]:-}"
        local pr_suffix=""
        local pr_url="${project_pr_urls[$project_name]:-}"
        local pr_url_suffix=""
        if [ -n "$pr_url" ]; then
            pr_url_suffix=" ${GRAY}(${pr_url})${NC}"
        fi
        if [ -n "$pr_label" ]; then
            if [ "$pr_label" != "open" ] || [ -z "$pr_url" ]; then
                pr_suffix=" ${YELLOW}[${pr_label}]${NC}"
            fi
        fi

        if [ "$single_project_mode" != true ]; then
            echo -e "  ${BOLD}${YELLOW}${project_name}${NC}${pr_suffix}${pr_url_suffix}"
        fi

        local service_names=()
        local svc_name=""
        local service_list="${project_services[$project_name]:-}"
        if [ -n "$service_list" ]; then
            while IFS= read -r svc_name; do
                [ -n "$svc_name" ] && service_names+=("$svc_name")
            done <<< "$service_list"
        fi

        local ordered_services=()
        local candidate
        for candidate in "$project_name Backend" "$project_name Frontend"; do
            local i
            for i in "${!service_names[@]}"; do
                if [ "${service_names[$i]}" = "$candidate" ]; then
                    ordered_services+=("$candidate")
                    service_names[$i]=""
                fi
            done
        done
        for svc_name in "${service_names[@]}"; do
            [ -n "$svc_name" ] && ordered_services+=("$svc_name")
        done

        if [ ${#ordered_services[@]} -eq 0 ]; then
            echo -e "    ${YELLOW}No services found${NC}"
            echo
            continue
        fi

        for svc_name in "${ordered_services[@]}"; do
            local label=""
            local label_color="${WHITE}"
            case "$svc_name" in
                "$project_name Backend")
                    label="Backend"
                    label_color="${GREEN}"
                    ;;
                "$project_name Frontend")
                    label="Frontend"
                    label_color="${MAGENTA}"
                    ;;
                *)
                    label="$svc_name"
                    label_color="${BLUE}"
                    ;;
            esac

            local url="${service_urls[$svc_name]:-}"
            local health_suffix
            health_suffix=$(service_health_suffix "$svc_name")

            local pid="" port="" log="" type="" dir=""
            if service_info_fields "$svc_name" pid port log type dir; then
                local status_icon="${GREEN}✓${NC}"
                local status_note=""
                local should_resolve=true
                local skip_pid_check=false
                local pid_ttl="${RUN_SH_PID_TTL:-0}"
                local last_ts="${SERVICE_PID_RESOLVE_TS[$svc_name]:-0}"
                if [ "$pid_ttl" -gt 0 ] && [ "$last_ts" -gt 0 ]; then
                    if [ $((now_ts - last_ts)) -lt "$pid_ttl" ] && [ -n "${SERVICE_PID_STATUS_CACHE[$svc_name]:-}" ]; then
                        skip_pid_check=true
                    fi
                fi
                if [ "${RUN_SH_RESOLVE_PIDS:-true}" != true ]; then
                    should_resolve=false
                elif [ "$lite_mode" = true ] && [ "${RUN_SH_LITE_RESOLVE_PIDS:-false}" != true ]; then
                    should_resolve=false
                fi
                if [ "$should_resolve" = true ] && [ "$skip_pid_check" = true ]; then
                    should_resolve=false
                fi

                if [ "$should_resolve" = true ]; then
                    if ! resolve_service_pid "$svc_name"; then
                        status_icon="${RED}✗${NC}"
                        status_note=" (PID: $pid - NOT RUNNING)"
                        SERVICE_PID_STATUS_CACHE["$svc_name"]="missing"
                    else
                        status_note=" (PID: $pid)"
                        SERVICE_PID_STATUS_CACHE["$svc_name"]="running"
                    fi
                    SERVICE_PID_RESOLVE_TS["$svc_name"]="$now_ts"
                else
                    if [ "$skip_pid_check" = true ] && [ -n "${SERVICE_PID_STATUS_CACHE[$svc_name]:-}" ]; then
                        if [ "${SERVICE_PID_STATUS_CACHE[$svc_name]}" = "running" ]; then
                            if [ -n "$pid" ]; then
                                status_note=" (PID: $pid)"
                            fi
                        else
                            status_icon="${RED}✗${NC}"
                            status_note=" (PID: $pid - NOT RUNNING)"
                        fi
                    elif [ -n "$pid" ]; then
                        if kill -0 "$pid" 2>/dev/null; then
                            status_note=" (PID: $pid)"
                            SERVICE_PID_STATUS_CACHE["$svc_name"]="running"
                        else
                            status_icon="${RED}✗${NC}"
                            status_note=" (PID: $pid - NOT RUNNING)"
                            SERVICE_PID_STATUS_CACHE["$svc_name"]="missing"
                        fi
                    fi
                fi

                if [ -n "$url" ]; then
                    local listener_note=""
                    local show_listener_pid="${RUN_SH_SHOW_LISTENER_PID:-true}"
                    case "$show_listener_pid" in
                        1|true|TRUE|yes|YES|y|Y|on|ON)
                            local listener_pids=""
                            listener_pids=$(listener_pids_for_port "$port" 2>/dev/null || true)
                            if [ -n "$listener_pids" ]; then
                                listener_note=" [Listener PID: ${listener_pids}]"
                            fi
                            ;;
                    esac
                    echo -e "${service_indent}${status_icon} ${label_color}${label}${NC}${health_suffix}: ${url}${status_note}${listener_note}"
                else
                    local listener_note=""
                    local show_listener_pid="${RUN_SH_SHOW_LISTENER_PID:-true}"
                    case "$show_listener_pid" in
                        1|true|TRUE|yes|YES|y|Y|on|ON)
                            local listener_pids=""
                            listener_pids=$(listener_pids_for_port "$port" 2>/dev/null || true)
                            if [ -n "$listener_pids" ]; then
                                listener_note=" [Listener PID: ${listener_pids}]"
                            fi
                            ;;
                    esac
                    echo -e "${service_indent}${status_icon} ${label_color}${label}${NC}${health_suffix}${status_note}${listener_note}"
                fi

                local display_log
                if [ -z "$log" ]; then
                    local guessed_log=""
                    guessed_log=$(guess_service_log_path "$svc_name" "$type" "$port" 2>/dev/null || true)
                    if [ -n "$guessed_log" ]; then
                        log="$guessed_log"
                        service_info["$svc_name"]="$pid|$port|$log|$type|$dir"
                    fi
                fi
                display_log=$(format_log_path "$log")
                if [ -n "$display_log" ]; then
                    echo -e "${log_indent}${GRAY}log:${NC} ${display_log}"
                fi
            else
                if [ -n "$url" ]; then
                    echo -e "${service_indent}${label_color}${label}${NC}${health_suffix}: ${url}"
                else
                    echo -e "${service_indent}${label_color}${label}${NC}${health_suffix}"
                fi
            fi
        done
        if [ "$lite_mode" != true ] && [ -n "$summary_path" ]; then
            local tests_status=""
            tests_status=$(tests_status_for_summary_file "$summary_path" 2>/dev/null || true)
            local tests_icon="${RED}✗${NC}"
            if [ "$tests_status" = "passed" ]; then
                tests_icon="${GREEN}✓${NC}"
            fi
            local summary_display
            summary_display=$(format_log_path "$summary_path")
            if [ -n "$summary_timestamp" ]; then
                echo -e "${meta_indent}${tests_icon} ${RED}tests:${NC} ${summary_display} ${GRAY}(${summary_timestamp})${NC}"
            else
                echo -e "${meta_indent}${tests_icon} ${RED}tests:${NC} ${summary_display}"
            fi
        fi
        if [ "$lite_mode" != true ] && [ -n "$analysis_path" ] && [ -n "$analysis_state" ]; then
            local analysis_display
            analysis_display=$(format_log_path "$analysis_path")
            local analysis_timestamp=""
            analysis_timestamp=$(format_summary_timestamp "$analysis_state" 2>/dev/null || true)
            if [ -n "$analysis_timestamp" ]; then
                echo -e "${meta_indent}${GREEN}✓${NC} ${CYAN}analysis:${NC} ${analysis_display} ${GRAY}(${analysis_timestamp})${NC}"
            else
                echo -e "${meta_indent}${GREEN}✓${NC} ${CYAN}analysis:${NC} ${analysis_display}"
            fi
        fi

        local n8n_port="${n8n_port_for_project[$project_name]:-}"
        if [ -n "$n8n_port" ]; then
            local n8n_status="${n8n_status_for_port[$n8n_port]:-}"
            if [ -z "$n8n_status" ]; then
                n8n_status=$(n8n_health_status "$n8n_port")
                n8n_status_for_port["$n8n_port"]="$n8n_status"
            fi
            local n8n_icon="${GREEN}✓${NC}"
            local n8n_suffix=" [Healthy]"
            local n8n_note=""
            case "$n8n_status" in
                healthy)
                    ;;
                unreachable)
                    n8n_icon="${RED}✗${NC}"
                    n8n_suffix=" [Unreachable]"
                    ;;
                unhealthy:*)
                    n8n_icon="${RED}✗${NC}"
                    n8n_suffix=" [Unhealthy]"
                    n8n_note=" ${GRAY}(healthz ${n8n_status#unhealthy:})${NC}"
                    ;;
                *)
                    n8n_icon="${YELLOW}!${NC}"
                    n8n_suffix=" [Unknown]"
                    ;;
            esac
            echo -e "${meta_indent}${n8n_icon} ${CYAN}n8n${NC}: http://localhost:${n8n_port}${n8n_suffix}${n8n_note}"
        fi
        if [ "$show_run_hints" = true ]; then
            if [ "$project_name" = "Main" ]; then
                echo -e "${meta_indent}${CYAN}run:${NC} envctl --main --resume"
            elif [ "${TREES_MODE:-false}" = true ]; then
                local project_command=""
                printf -v project_command 'envctl trees=true --resume --project %q' "$project_name"
                echo -e "${meta_indent}${CYAN}run:${NC} ${project_command}"
            elif [ "$single_project_mode" = true ]; then
                echo -e "${meta_indent}${CYAN}run:${NC} envctl --main --resume"
            fi
        fi
        echo
    done

    if [ "$show_run_hints" = true ] && [ "$show_run_all_together_hints" = true ] && [ "${TREES_MODE:-false}" = true ] && [ ${#project_order[@]} -gt 0 ]; then
        local -a run_all_projects=()
        local -a tree_projects=()
        local has_main=false
        local p=""
        for p in "${project_order[@]}"; do
            [ -n "$p" ] || continue
            run_all_projects+=("$p")
            if [ "$p" = "Main" ]; then
                has_main=true
                continue
            fi
            tree_projects+=("$p")
        done
        if [ ${#tree_projects[@]} -gt 0 ] || [ "$has_main" = true ]; then
            echo -e "${CYAN}Run All Together:${NC}"
            local all_command=""
            if [ ${#run_all_projects[@]} -eq 1 ] && [ "${run_all_projects[0]}" = "Main" ]; then
                all_command="envctl --main --resume"
            elif [ ${#run_all_projects[@]} -gt 0 ]; then
                local projects_csv
                projects_csv=$(IFS=','; echo "${run_all_projects[*]}")
                printf -v all_command 'envctl trees=true --resume --projects %s' "$projects_csv"
            else
                all_command="envctl trees=true --resume"
            fi
            echo -e "  ${all_command}"
            echo
        fi
    fi

    if [ "$(type -t profile_end)" = "function" ]; then
        profile_end "interactive_render"
    fi
    if [ "$(type -t debug_log_line)" = "function" ] && [ "${RUN_SH_DEBUG_VERBOSE:-false}" = true ] && [ "${RUN_SH_DEBUG_TRACE_INTERACTIVE:-true}" = true ]; then
        debug_log_line "TRACE" "interactive_render.end services=${#services[@]}"
    fi
}

# Function to check health of all services

check_health() {
    echo -e "\n${CYAN}Checking health of all services...${NC}"

    if [ "${RUN_SH_SKIP_HEALTH:-false}" = true ]; then
        echo -e "${YELLOW}Health checks skipped (RUN_SH_SKIP_HEALTH=true).${NC}"
        echo
        return 0
    fi

    local cache_enabled=false
    if [ "${RUN_SH_FAST_STARTUP:-false}" = true ]; then
        cache_enabled=true
    fi

    local max_parallel="${RUN_SH_HEALTH_PARALLEL:-0}"
    if [ -n "$max_parallel" ] && [ "$max_parallel" -gt 1 ]; then
        local tmp_dir
        tmp_dir=$(mktemp -d)
        local -A service_files=()
        local -A service_types=()
        local -A service_cached=()
        local -a job_pids=()

        local service
        for service in "${services[@]}"; do
            parse_service_entry "$service" name url docs || continue

            local type
            type=$(service_type_from_name "$name")
            [ -z "$type" ] && type="frontend"
            service_types["$name"]="$type"

            local now_ts
            now_ts=$(date +%s)
            if [ "$cache_enabled" = true ]; then
                local cached_ts="${HEALTH_STATUS_TS[$name]:-0}"
                if [ "$cached_ts" -gt 0 ] && [ $((now_ts - cached_ts)) -le "$HEALTH_STATUS_TTL" ]; then
                    service_cached["$name"]=1
                    continue
                fi
            fi

            local safe_name
            if [ "$(type -t sanitize_label)" = "function" ]; then
                safe_name=$(sanitize_label "$name")
            else
                safe_name=$(printf '%s' "$name" | tr ' /' '__' | tr -c 'A-Za-z0-9._-' '_')
            fi
            local out_file="${tmp_dir}/${safe_name}.health"
            service_files["$name"]="$out_file"

            (
                local status="unhealthy"
                local version=""
                if check_service_health "$name" "$url" "$type"; then
                    status="healthy"
                    if [ "$type" = "backend" ]; then
                        version=$(curl -s "${url}/api/v1/health" 2>/dev/null | jq -r '.version' 2>/dev/null)
                        [ "$version" = "null" ] && version=""
                    fi
                fi
                printf '%s|%s|%s\n' "$status" "$version" "$now_ts" > "$out_file"
            ) &
            job_pids+=("$!")

            while [ ${#job_pids[@]} -ge "$max_parallel" ]; do
                local idx
                for idx in "${!job_pids[@]}"; do
                    if ! kill -0 "${job_pids[$idx]}" 2>/dev/null; then
                        wait "${job_pids[$idx]}" 2>/dev/null || true
                        unset 'job_pids[idx]'
                        job_pids=("${job_pids[@]}")
                        break
                    fi
                done
                if [ ${#job_pids[@]} -ge "$max_parallel" ]; then
                    sleep 0.1
                fi
            done
        done

        local pid
        for pid in "${job_pids[@]}"; do
            wait "$pid" 2>/dev/null || true
        done

        for service in "${services[@]}"; do
            parse_service_entry "$service" name url docs || continue
            echo -n "  Checking $name... "

            local type="${service_types[$name]:-}"
            local now_ts
            now_ts=$(date +%s)

            if [ -n "${service_cached[$name]:-}" ]; then
                local cached_status="${HEALTH_STATUS[$name]:-unhealthy}"
                if [ "$cached_status" = "healthy" ]; then
                    echo -e "${GREEN}✓ Healthy (cached)${NC}"
                else
                    echo -e "${RED}✗ Not responding (cached)${NC}"
                fi
                continue
            fi

            local out_file="${service_files[$name]:-}"
            if [ -n "$out_file" ] && [ -f "$out_file" ]; then
                local status="" version="" ts=""
                IFS='|' read -r status version ts < "$out_file"
                HEALTH_STATUS["$name"]="$status"
                HEALTH_STATUS_TS["$name"]="$now_ts"
                if [ "$status" = "healthy" ]; then
                    echo -e "${GREEN}✓ Healthy${NC}"
                    if [ "$type" = "backend" ] && [ -n "$version" ]; then
                        echo -e "    Version: $version"
                    fi
                else
                    echo -e "${RED}✗ Not responding${NC}"
                fi
            else
                echo -e "${RED}✗ Not responding${NC}"
                HEALTH_STATUS["$name"]="unhealthy"
                HEALTH_STATUS_TS["$name"]="$now_ts"
            fi
        done
        rm -rf "$tmp_dir"
        echo
        return 0
    fi

    for service in "${services[@]}"; do
        parse_service_entry "$service" name url docs || continue
        echo -n "  Checking $name... "

        # Determine service type
        local type
        type=$(service_type_from_name "$name")
        [ -z "$type" ] && type="frontend"

        # Check health
        local now_ts
        now_ts=$(date +%s)
        if [ "$cache_enabled" = true ]; then
            local cached_ts="${HEALTH_STATUS_TS[$name]:-0}"
            if [ "$cached_ts" -gt 0 ] && [ $((now_ts - cached_ts)) -le "$HEALTH_STATUS_TTL" ]; then
                local cached_status="${HEALTH_STATUS[$name]:-unhealthy}"
                if [ "$cached_status" = "healthy" ]; then
                    echo -e "${GREEN}✓ Healthy (cached)${NC}"
                else
                    echo -e "${RED}✗ Not responding (cached)${NC}"
                fi
                continue
            fi
        fi

        if check_service_health "$name" "$url" "$type"; then
            echo -e "${GREEN}✓ Healthy${NC}"
            HEALTH_STATUS["$name"]="healthy"
            HEALTH_STATUS_TS["$name"]="$now_ts"

            # For backends, show API version if available
            if [ "$type" = "backend" ]; then
                local version=$(curl -s "${url}/api/v1/health" 2>/dev/null | jq -r '.version' 2>/dev/null)
                [ -n "$version" ] && [ "$version" != "null" ] && echo -e "    Version: $version"
            fi
        else
            echo -e "${RED}✗ Not responding${NC}"
            HEALTH_STATUS["$name"]="unhealthy"
            HEALTH_STATUS_TS["$name"]="$now_ts"
        fi
    done
    echo
}

# Function to show recent errors

show_errors() {
    local requested=("$@")
    local use_filter=false
    declare -A allowed=()

    if [ ${#requested[@]} -gt 0 ]; then
        use_filter=true
        for name in "${requested[@]}"; do
            [ -n "$name" ] && allowed["$name"]=1
        done
        echo -e "\n${CYAN}Recent errors from selected services:${NC}"
    else
        echo -e "\n${CYAN}Recent errors from all services:${NC}"
    fi
    echo -e "${CYAN}========================================${NC}"

    local found_errors=false

    # Define colors for service names (same as tail_logs)
    local colors=("${LOG_COLORS[@]}")
    local color_index=0
    local highlight_start=$'\033[1;31m'
    local highlight_end=$'\033[0m'
    local highlight_pattern="$LOG_ERROR_PATTERN"

    for service in "${services[@]}"; do
        parse_service_entry "$service" name url docs || continue
        if [ "$use_filter" = true ] && [ -z "${allowed[$name]:-}" ]; then
            continue
        fi
        if service_info_fields "$name" pid port log type dir; then
            if [ -f "$log" ]; then
                local errors=$(grep -i -E "$highlight_pattern" "$log" | tail -10)
                if [ -n "$errors" ]; then
                    found_errors=true
                    local service_color="${colors[$color_index]}"
                    echo ""
                    echo "$errors" | while IFS= read -r line; do
                        # Highlight the trigger word without coloring the whole line
                        local highlighted=$(echo "$line" | sed -E "s/${highlight_pattern}/${highlight_start}\\1${highlight_end}/gi")
                        echo -e "${service_color}[$name]${NC} ${highlighted}${NC}"
                    done
                fi
            fi
            ((color_index = (color_index + 1) % ${#colors[@]}))
        fi
    done

    if [ "$found_errors" = false ]; then
        echo -e "${GREEN}No recent errors found${NC}"
    fi
    echo
}

# Function to restart a service

tail_multiple_logs() {
    local matches=("$@")
    local temp_file="/tmp/envctl_tail_$$"
    > "$temp_file"
    local colors=("${LOG_COLORS[@]}")
    local color_index=0

    for match in "${matches[@]}"; do
        [ -z "$match" ] && continue
        if service_info_fields "$match" pid port log type dir; then
            if [ -f "$log" ]; then
                local service_color="${colors[$color_index]}"
                ((color_index = (color_index + 1) % ${#colors[@]}))

                echo -e "${service_color}$match${NC} (port $port):"
                tail -f "$log" | while IFS= read -r line; do
                    if echo "$line" | grep -qiE "$LOG_ERROR_PATTERN"; then
                        echo -e "${service_color}[$match]${NC} \033[91m${line}${NC}"
                    else
                        echo -e "${service_color}[$match]${NC} $line"
                    fi
                done &
                echo $! >> "$temp_file"
            fi
        fi
    done

    if [ -s "$temp_file" ]; then
        echo -e "${CYAN}Tailing logs for all matching services (press Enter or Esc to stop):${NC}"
        local tty_state=""
        tty_state=$(tty_raw_on 2>/dev/null || true)
        menu_setup
        tty_flush_input
        tput civis >&2 2>/dev/null || true
        while true; do
            key=$(read_key)
            case "$key" in
                esc|q|Q|enter)
                    break
                    ;;
            esac
        done
        menu_cleanup "$tty_state"

        while IFS= read -r tail_pid; do
            pkill -P $tail_pid 2>/dev/null
            kill -TERM $tail_pid 2>/dev/null
        done < "$temp_file"

        rm -f "$temp_file"
        sleep 0.5
        echo -e "${CYAN}Stopped tailing logs${NC}"
        return 0
    fi

    rm -f "$temp_file"
    return 1
}

# Function to tail logs for a service

tail_logs() {
    local search_name=$1
    local matches=()

    if [ "$search_name" = "__ALL__" ] || [ "${search_name,,}" = "all" ]; then
        for service in "${services[@]}"; do
            parse_service_entry "$service" name url docs || continue
            matches+=("$name")
        done
        tail_multiple_logs "${matches[@]}"
        return $?
    fi

    # Check if search is a number (port pattern)
    if [[ "$search_name" =~ ^[0-9]+$ ]]; then
        # Search by port pattern
        for service in "${services[@]}"; do
            parse_service_entry "$service" name url docs || continue
            # Extract port from URL
            local port
            port=$(port_from_url "$url")

            # Check if port ends with the search pattern
            if [[ "$port" =~ $search_name$ ]]; then
                matches+=("$name")
            fi
        done

        # If we found multiple matches (e.g., backend and frontend), tail both
        if [ ${#matches[@]} -gt 1 ]; then
            echo -e "${CYAN}Found ${#matches[@]} services matching port pattern '$search_name':${NC}"
            tail_multiple_logs "${matches[@]}"
            return $?
        elif [ ${#matches[@]} -eq 1 ]; then
            # Single match, use the original logic
            search_name="${matches[0]}"
        fi
    fi

    # If not a port pattern or single match, use the original service name search
    local service_name=$(find_service_by_name "$search_name")

    if [ -z "$service_name" ]; then
        echo -e "${RED}No service found matching '$search_name'${NC}"
        echo "Available services:"
        get_service_names | sed 's/^/  - /'
        return 1
    fi

    # Find the service
    local found=false
    for service in "${services[@]}"; do
        parse_service_entry "$service" name url docs || continue
        if [ "$name" = "$service_name" ] && service_info_fields "$name" pid port log type dir; then
            found=true

            if [ -f "$log" ]; then
                # Assign color based on service name hash (excluding red to avoid confusion with errors)
                local name_hash=$(echo -n "$name" | cksum | cut -d' ' -f1)
                local color_index=$((name_hash % ${#LOG_COLORS[@]}))
                local service_color="${LOG_COLORS[$color_index]}"

                echo -e "${CYAN}Tailing logs for ${service_color}$name${CYAN} (press Enter or Esc to stop):${NC}"
                # Start tail in background with colored prefix
                tail -f "$log" | while IFS= read -r line; do
                    # Check if line contains error patterns
                    if echo "$line" | grep -qiE "$LOG_ERROR_PATTERN"; then
                        # Light red color for errors
                        echo -e "${service_color}[$name]${NC} \033[91m${line}${NC}"
                    else
                        echo -e "${service_color}[$name]${NC} $line"
                    fi
                done &
                local tail_pid=$!

                # Wait for Enter or Esc
                while true; do
                    IFS= read -rsn1 key
                    if [ "$key" = $'\x1b' ] || [ -z "$key" ]; then
                        break
                    fi
                done

                # Kill the tail process and its children
                pkill -P $tail_pid 2>/dev/null
                kill -TERM $tail_pid 2>/dev/null
                sleep 0.5

                echo -e "${CYAN}Stopped tailing logs${NC}"
            else
                echo -e "${RED}Log file not found: $log${NC}"
            fi
            break
        fi
    done

    if [ "$found" = false ]; then
        echo -e "${RED}Service '$service_name' not found${NC}"
    fi
}

tail_logs_noninteractive() {
    local search_name=$1
    local matches=()

    if [ "$search_name" = "__ALL__" ] || [ "${search_name,,}" = "all" ]; then
        for service in "${services[@]}"; do
            parse_service_entry "$service" name url docs || continue
            matches+=("$name")
        done
        tail_multiple_logs_noninteractive "${matches[@]}"
        return $?
    fi

    if [[ "$search_name" =~ ^[0-9]+$ ]]; then
        for service in "${services[@]}"; do
            parse_service_entry "$service" name url docs || continue
            local port
            port=$(port_from_url "$url")
            if [[ "$port" =~ $search_name$ ]]; then
                matches+=("$name")
            fi
        done
        if [ ${#matches[@]} -gt 1 ]; then
            tail_multiple_logs_noninteractive "${matches[@]}"
            return $?
        elif [ ${#matches[@]} -eq 1 ]; then
            search_name="${matches[0]}"
        fi
    fi

    local service_name=""
    if command -v find_service_by_name >/dev/null 2>&1; then
        service_name=$(find_service_by_name "$search_name")
    else
        service_name="$search_name"
    fi
    if [ -z "$service_name" ]; then
        echo -e "${RED}No service found matching '$search_name'${NC}"
        echo "Available services:"
        if command -v get_service_names >/dev/null 2>&1; then
            get_service_names | sed 's/^/  - /'
        fi
        return 1
    fi

    local tail_lines="${RUN_SH_COMMAND_LOGS_TAIL:-200}"
    if ! [[ "$tail_lines" =~ ^[0-9]+$ ]]; then
        tail_lines=200
    fi
    local follow="${RUN_SH_COMMAND_LOGS_FOLLOW:-false}"
    local duration="${RUN_SH_COMMAND_LOGS_DURATION:-}"
    local no_color="${RUN_SH_COMMAND_LOGS_NO_COLOR:-false}"

    local found=false
    for service in "${services[@]}"; do
        parse_service_entry "$service" name url docs || continue
        if [ "$name" = "$service_name" ] && service_info_fields "$name" pid port log type dir; then
            found=true
            if [ ! -f "$log" ]; then
                echo -e "${RED}Log file not found: $log${NC}"
                return 1
            fi
            if [ "$no_color" != true ]; then
                echo -e "${CYAN}Logs for ${name}:${NC}"
            fi
            if [ "$follow" = true ]; then
                local timeout_bin="${TIMEOUT_BIN:-}"
                if [ -z "$timeout_bin" ]; then
                    if command -v timeout >/dev/null 2>&1; then
                        timeout_bin="timeout"
                    elif command -v gtimeout >/dev/null 2>&1; then
                        timeout_bin="gtimeout"
                    fi
                fi
                if [ -n "$duration" ] && [[ "$duration" =~ ^[0-9]+$ ]] && [ -n "$timeout_bin" ]; then
                    "$timeout_bin" "$duration" tail -n "$tail_lines" -f "$log"
                else
                    tail -n "$tail_lines" -f "$log"
                fi
            else
                tail -n "$tail_lines" "$log"
            fi
            return 0
        fi
    done

    if [ "$found" = false ]; then
        echo -e "${RED}Service '$service_name' not found${NC}"
    fi
    return 1
}

tail_multiple_logs_noninteractive() {
    local tail_lines="${RUN_SH_COMMAND_LOGS_TAIL:-200}"
    if ! [[ "$tail_lines" =~ ^[0-9]+$ ]]; then
        tail_lines=200
    fi
    local follow="${RUN_SH_COMMAND_LOGS_FOLLOW:-false}"
    local duration="${RUN_SH_COMMAND_LOGS_DURATION:-}"
    local no_color="${RUN_SH_COMMAND_LOGS_NO_COLOR:-false}"

    local -a log_files=()
    local service_name
    for service_name in "$@"; do
        local resolved
        if command -v find_service_by_name >/dev/null 2>&1; then
            resolved=$(find_service_by_name "$service_name")
        else
            resolved="$service_name"
        fi
        [ -n "$resolved" ] || continue
        local service
        for service in "${services[@]}"; do
            parse_service_entry "$service" name url docs || continue
            if [ "$name" = "$resolved" ] && service_info_fields "$name" pid port log type dir; then
                if [ -f "$log" ]; then
                    log_files+=("$log")
                fi
                break
            fi
        done
    done

    if [ ${#log_files[@]} -eq 0 ]; then
        echo -e "${RED}No logs found for selected services.${NC}"
        return 1
    fi

    if [ "$no_color" != true ]; then
        echo -e "${CYAN}Logs for selected services:${NC}"
    fi

    if [ "$follow" = true ]; then
        local timeout_bin="${TIMEOUT_BIN:-}"
        if [ -z "$timeout_bin" ]; then
            if command -v timeout >/dev/null 2>&1; then
                timeout_bin="timeout"
            elif command -v gtimeout >/dev/null 2>&1; then
                timeout_bin="gtimeout"
            fi
        fi
        if [ -n "$duration" ] && [[ "$duration" =~ ^[0-9]+$ ]] && [ -n "$timeout_bin" ]; then
            "$timeout_bin" "$duration" tail -n "$tail_lines" -f "${log_files[@]}"
        else
            tail -n "$tail_lines" -f "${log_files[@]}"
        fi
    else
        tail -n "$tail_lines" "${log_files[@]}"
    fi

    return 0
}

# Spawn a long-lived command detached from terminal interrupts and print its PID.
