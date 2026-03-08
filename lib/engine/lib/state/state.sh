#!/usr/bin/env bash

# State and summary helpers (extracted from run.sh).

if [ -z "${PROJECT_TEST_INFO_CACHE+x}" ]; then
    declare -A PROJECT_TEST_INFO_CACHE=()
fi
if [ -z "${PROJECT_TEST_INFO_CACHE_TS+x}" ]; then
    declare -A PROJECT_TEST_INFO_CACHE_TS=()
fi
if [ -z "${PROJECT_ANALYSIS_INFO_CACHE+x}" ]; then
    declare -A PROJECT_ANALYSIS_INFO_CACHE=()
fi
if [ -z "${PROJECT_ANALYSIS_INFO_CACHE_TS+x}" ]; then
    declare -A PROJECT_ANALYSIS_INFO_CACHE_TS=()
fi

status_cache_ttl() {
    local ttl="${RUN_SH_STATUS_CACHE_TTL:-0}"
    if [[ "$ttl" =~ ^[0-9]+$ ]] && [ "$ttl" -gt 0 ]; then
        echo "$ttl"
        return 0
    fi
    echo 0
}

state_file_matches() {
    local state_file=$1
    local dir=$2
    local current_state=$3
    [ -n "$state_file" ] || return 1
    [ -f "$state_file" ] || return 1
    [ -n "$dir" ] || return 1
    [ -n "$current_state" ] || return 1

    local line=""
    while IFS= read -r line; do
        [[ "$line" == state\|* ]] || continue
        local tag entry_name dir_val head_val hash_val lines_val
        IFS='|' read -r tag entry_name dir_val head_val hash_val lines_val <<< "$line"
        if [ "$dir_val" = "$dir" ]; then
            if [ "${head_val}|${hash_val}|${lines_val}" = "$current_state" ]; then
                return 0
            fi
        fi
    done < "$state_file"

    return 1
}


analysis_info_for_project() {
    local project_name=$1
    local current_state_override=$2
    local ttl
    ttl=$(status_cache_ttl)
    if [ "$ttl" -gt 0 ]; then
        local cached_ts="${PROJECT_ANALYSIS_INFO_CACHE_TS[$project_name]:-0}"
        local now
        now=$(date +%s)
        if [ "$cached_ts" -gt 0 ] && [ $((now - cached_ts)) -le "$ttl" ]; then
            local cached="${PROJECT_ANALYSIS_INFO_CACHE[$project_name]:-}"
            if [ "$cached" = "__NONE__" ]; then
                return 1
            fi
            if [ -n "$cached" ]; then
                echo "$cached"
                return 0
            fi
        fi
    fi
    local results_dir="$BASE_DIR/tree-diffs"
    [ -d "$results_dir" ] || return 1
    local project_root
    project_root=$(project_root_from_project_name "$project_name" 2>/dev/null || true)
    [ -n "$project_root" ] || return 1
    local current_state
    current_state="${current_state_override:-}"
    if [ -z "$current_state" ]; then
        current_state=$(git_state_for_dir "$project_root" 2>/dev/null || true)
    fi
    [ -n "$current_state" ] || return 1

    local safe_project
    safe_project=$(sanitize_label "$project_name")
    local state_file=""
    while IFS= read -r state_file; do
        [ -n "$state_file" ] || continue
        if state_file_matches "$state_file" "$project_root" "$current_state"; then
            local output_dir
            output_dir=$(dirname "$state_file")
            local output="${output_dir}/all.md|${state_file}"
            if [ "$ttl" -gt 0 ]; then
                PROJECT_ANALYSIS_INFO_CACHE["$project_name"]="$output"
                PROJECT_ANALYSIS_INFO_CACHE_TS["$project_name"]="$(date +%s)"
            fi
            echo "$output"
            return 0
        fi
    done < <(ls -t "$results_dir"/analysis_"$safe_project"_*/analysis_state.txt 2>/dev/null)

    if [ "$ttl" -gt 0 ]; then
        PROJECT_ANALYSIS_INFO_CACHE["$project_name"]="__NONE__"
        PROJECT_ANALYSIS_INFO_CACHE_TS["$project_name"]="$(date +%s)"
    fi
    return 1
}


test_info_for_project() {
    local project_name=$1
    local current_state_override=$2
    local ttl
    ttl=$(status_cache_ttl)
    if [ "$ttl" -gt 0 ]; then
        local cached_ts="${PROJECT_TEST_INFO_CACHE_TS[$project_name]:-0}"
        local now
        now=$(date +%s)
        if [ "$cached_ts" -gt 0 ] && [ $((now - cached_ts)) -le "$ttl" ]; then
            local cached="${PROJECT_TEST_INFO_CACHE[$project_name]:-}"
            if [ "$cached" = "__NONE__" ]; then
                return 1
            fi
            if [ -n "$cached" ]; then
                echo "$cached"
                return 0
            fi
        fi
    fi
    local results_dir="$BASE_DIR/test-results"
    [ -d "$results_dir" ] || return 1
    local project_root
    project_root=$(project_root_from_project_name "$project_name" 2>/dev/null || true)
    [ -n "$project_root" ] || return 1
    local current_state
    current_state="${current_state_override:-}"
    if [ -z "$current_state" ]; then
        current_state=$(git_state_for_dir "$project_root" 2>/dev/null || true)
    fi
    [ -n "$current_state" ] || return 1
    local safe_project="${project_name// /_}"
    local state_file=""
    while IFS= read -r state_file; do
        [ -n "$state_file" ] || continue
        if state_file_matches "$state_file" "$project_root" "$current_state"; then
            local output_dir
            output_dir=$(dirname "$state_file")
            local summary_file="$output_dir/failed_tests_summary.txt"
            if [ -f "$summary_file" ]; then
                local output="${summary_file}|${state_file}"
                if [ "$ttl" -gt 0 ]; then
                    PROJECT_TEST_INFO_CACHE["$project_name"]="$output"
                    PROJECT_TEST_INFO_CACHE_TS["$project_name"]="$(date +%s)"
                fi
                echo "$output"
                return 0
            fi
        fi
    done < <(ls -t "$results_dir"/run_*/"$safe_project"/test_state.txt 2>/dev/null)
    if [ "$ttl" -gt 0 ]; then
        PROJECT_TEST_INFO_CACHE["$project_name"]="__NONE__"
        PROJECT_TEST_INFO_CACHE_TS["$project_name"]="$(date +%s)"
    fi
    return 1
}


format_summary_timestamp() {
    local summary_file=$1
    if [ -z "$summary_file" ] || [ ! -f "$summary_file" ]; then
        return 1
    fi
    local epoch=""

    file_mtime_epoch() {
        local path=$1
        [ -n "$path" ] || return 1
        [ -f "$path" ] || return 1
        local ts=""
        ts=$(stat -f %m "$path" 2>/dev/null || true)
        if ! [[ "$ts" =~ ^[0-9]+$ ]]; then
            ts=$(stat -c %Y "$path" 2>/dev/null || true)
        fi
        if [[ "$ts" =~ ^[0-9]+$ ]]; then
            echo "$ts"
            return 0
        fi
        return 1
    }

    format_epoch_short() {
        local ts=$1
        [ -n "$ts" ] || return 1
        date -r "$ts" +"%b %d %H:%M" 2>/dev/null && return 0
        date -d "@$ts" +"%b %d %H:%M" 2>/dev/null && return 0
        return 1
    }

    local summary_dir
    summary_dir=$(dirname "$summary_file")
    local candidate
    local latest_epoch=0
    for candidate in "$summary_dir/backend_test.log" "$summary_dir/frontend_test.log" "$summary_file"; do
        epoch=$(file_mtime_epoch "$candidate" 2>/dev/null || true)
        if [[ "$epoch" =~ ^[0-9]+$ ]] && [ "$epoch" -gt "$latest_epoch" ]; then
            latest_epoch=$epoch
        fi
    done
    if [ "$latest_epoch" -gt 0 ]; then
        format_epoch_short "$latest_epoch" && return 0
    fi

    local generated_at=""
    generated_at=$(grep -m1 '^Generated at:' "$summary_file" | sed 's/^Generated at:[[:space:]]*//')
    if [ -n "$generated_at" ]; then
        date -j -f "%a %b %d %H:%M:%S %Z %Y" "$generated_at" +"%b %d %H:%M" 2>/dev/null && return 0
        date -d "$generated_at" +"%b %d %H:%M" 2>/dev/null && return 0
    fi

    local run_dir
    run_dir=$(basename "$(dirname "$summary_dir")")
    if [[ "$run_dir" =~ ^run_([0-9]{8})_([0-9]{6})$ ]]; then
        local date_part="${BASH_REMATCH[1]}"
        local time_part="${BASH_REMATCH[2]}"
        local year="${date_part:0:4}"
        local month="${date_part:4:2}"
        local day="${date_part:6:2}"
        local hour="${time_part:0:2}"
        local minute="${time_part:2:2}"
        date -j -f "%Y%m%d%H%M" "${year}${month}${day}${hour}${minute}" +"%b %d %H:%M" 2>/dev/null && return 0
        date -d "${year}-${month}-${day} ${hour}:${minute}:00" +"%b %d %H:%M" 2>/dev/null && return 0
    fi
    return 1
}


latest_test_summary_file() {
    local results_dir="$BASE_DIR/test-results"
    [ -d "$results_dir" ] || return 1
    local summary
    summary=$(ls -t "$results_dir"/run_*/summary.txt 2>/dev/null | head -n 1)
    [ -n "$summary" ] || return 1
    echo "$summary"
}


tests_status_for_summary_file() {
    local summary_file=$1
    if [ -z "$summary_file" ] || [ ! -f "$summary_file" ]; then
        return 1
    fi
    if grep -q "No failed tests." "$summary_file"; then
        echo "passed"
    else
        echo "failed"
    fi
}


project_tests_status() {
    local project_name=$1
    local test_info=""
    test_info=$(test_info_for_project "$project_name" 2>/dev/null || true)
    if [ -z "$test_info" ]; then
        echo "none"
        return 0
    fi
    local summary_path=""
    IFS='|' read -r summary_path _ <<< "$test_info"
    if [ -z "$summary_path" ]; then
        echo "none"
        return 0
    fi
    tests_status_for_summary_file "$summary_path" 2>/dev/null || echo "none"
}


has_passing_tests() {
    local project
    while IFS= read -r project; do
        [ -n "$project" ] || continue
        if [ "$(project_tests_status "$project")" = "passed" ]; then
            return 0
        fi
    done < <(get_project_names)
    return 1
}


list_untested_projects() {
    local project
    while IFS= read -r project; do
        [ -n "$project" ] || continue
        local status
        status=$(project_tests_status "$project")
        if [ "$status" != "passed" ]; then
            echo "$project"
        fi
    done < <(get_project_names)
}


format_last_test_line() {
    local summary
    summary=$(latest_test_summary_file) || return 1

    local generated_at total_projects passed failed skipped
    generated_at=$(grep -m1 '^Generated at:' "$summary" | sed 's/^Generated at:[[:space:]]*//')
    total_projects=$(grep -m1 '^Total Projects:' "$summary" | awk -F: '{print $2}')
    passed=$(grep -m1 '^Passed:' "$summary" | awk -F: '{print $2}')
    failed=$(grep -m1 '^Failed:' "$summary" | awk -F: '{print $2}')
    skipped=$(grep -m1 '^Skipped:' "$summary" | awk -F: '{print $2}')

    total_projects=$(trim "${total_projects:-}")
    passed=$(trim "${passed:-}")
    failed=$(trim "${failed:-}")
    skipped=$(trim "${skipped:-}")

    local status_label="PASSED"
    local status_color="${GREEN}"
    if [ -z "$generated_at" ]; then
        generated_at="unknown"
    fi
    if [ "${failed:-0}" -gt 0 ]; then
        status_label="FAILED"
        status_color="${RED}"
    elif [ -z "$passed" ] || [ "${passed:-0}" -eq 0 ]; then
        status_label="NO TESTS"
        status_color="${YELLOW}"
    fi

    local summary_path
    summary_path=$(format_log_path "$summary")

    echo "${generated_at} | ${status_color}${status_label}${NC} (Passed: ${passed:-0}, Failed: ${failed:-0}, Skipped: ${skipped:-0}, Projects: ${total_projects:-0}) | summary: ${summary_path}"
}


service_health_suffix() {
    local name=$1
    local health_value="${HEALTH_STATUS[$name]:-}"
    if [ -z "$health_value" ]; then
        echo ""
        return 0
    fi

    local checked_ts="${HEALTH_STATUS_TS[$name]:-0}"
    local now_ts
    now_ts=$(date +%s)
    if [ "$checked_ts" -gt 0 ] && [ $((now_ts - checked_ts)) -le "$HEALTH_STATUS_TTL" ]; then
        if [ "$health_value" = "healthy" ]; then
            echo " ${GREEN}[Healthy]${NC}"
        elif [ "$health_value" = "unhealthy" ]; then
            echo " ${RED}[Unhealthy]${NC}"
        else
            echo " ${YELLOW}[Health: ${health_value}]${NC}"
        fi
    else
        echo " ${YELLOW}[Health: stale]${NC}"
    fi
}


backend_port_for_project() {
    local project_name=$1
    service_port_for_name "$project_name Backend"
}


find_service_by_name() {
    local search=$1
    local matches=()

    # Check if search is a number (port)
    if [[ "$search" =~ ^[0-9]+$ ]]; then
        # Search by port
        for service in "${services[@]}"; do
            parse_service_entry "$service" name url docs || continue
            # Extract port from URL
            local port
            port=$(port_from_url "$url")

            # Check for exact match first
            if [ "$port" = "$search" ]; then
                matches+=("$name")
            # Check if port ends with the search pattern (e.g., "100" matches "8100", "9100")
            elif [[ "$port" =~ $search$ ]]; then
                matches+=("$name")
            fi
        done
    else
        # Search by name (existing logic)
        for service in "${services[@]}"; do
            parse_service_entry "$service" name url docs || continue
            if [[ "${name,,}" == *"${search,,}"* ]]; then
                matches+=("$name")
            fi
        done
    fi

    if [ ${#matches[@]} -eq 0 ]; then
        echo ""
    elif [ ${#matches[@]} -eq 1 ]; then
        echo "${matches[0]}"
    else
        echo -e "${YELLOW}Multiple matches found:${NC}" >&2
        printf '  - %s\n' "${matches[@]}" >&2
        echo -n "Please be more specific: " >&2
        read -r specific
        find_service_by_name "$specific"
    fi
}

# Enhanced cleanup function

kill_job_pids() {
    local signal="${1:--TERM}"
    local normalized_signal="${signal#-}"
    if [ -z "$normalized_signal" ]; then
        normalized_signal="TERM"
    fi

    _kill_pid_tree() {
        local pid=$1
        local sig=$2
        [ -n "$pid" ] || return 0
        [[ "$pid" =~ ^[0-9]+$ ]] || return 0

        if command -v pgrep >/dev/null 2>&1; then
            local child_pid
            while IFS= read -r child_pid; do
                [ -n "$child_pid" ] || continue
                _kill_pid_tree "$child_pid" "$sig"
            done < <(pgrep -P "$pid" 2>/dev/null || true)
        fi

        kill "-$sig" "$pid" 2>/dev/null || true
    }

    local job_pids
    job_pids=$(jobs -p)
    if [ -n "$job_pids" ]; then
        local pid
        while IFS= read -r pid; do
            [ -n "$pid" ] || continue
            _kill_pid_tree "$pid" "$normalized_signal"
        done <<< "$job_pids"
    fi
}

cleanup_add_port() {
    local -n port_seen_ref=$1
    local -n port_list_ref=$2
    local port=$3

    if [[ "$port" =~ ^[0-9]+$ ]] && [ -z "${port_seen_ref[$port]:-}" ]; then
        port_seen_ref[$port]=1
        port_list_ref+=("$port")
    fi
}

cleanup_add_spaced_ports() {
    local base=$3
    local spacing=$4
    local count=$5

    if ! [[ "$base" =~ ^[0-9]+$ ]] || ! [[ "$spacing" =~ ^[0-9]+$ ]]; then
        return 0
    fi
    if [ "$count" -lt 1 ]; then
        return 0
    fi

    local i
    for ((i=0; i<count; i++)); do
        cleanup_add_port "$1" "$2" $((base + i * spacing))
    done
}

cleanup_port_slot_count() {
    local count=0

    if declare -F list_tree_paths >/dev/null 2>&1; then
        while IFS= read -r tree_dir; do
            [ -n "$tree_dir" ] && ((count++))
        done < <(list_tree_paths "${BASE_DIR:-.}" "${TREES_DIR_NAME:-trees}")
    fi

    local backend_count=0
    if [ ${#service_info[@]} -gt 0 ]; then
        local name
        local pid="" port="" log="" type="" dir=""
        for name in "${!service_info[@]}"; do
            if service_info_fields "$name" pid port log type dir; then
                if [ "$type" = "backend" ]; then
                    ((backend_count++))
                fi
            fi
        done
    fi

    if [ "$backend_count" -gt "$count" ]; then
        count=$backend_count
    fi
    if [ "$count" -lt 1 ]; then
        count=1
    fi

    echo "$count"
}

cleanup_collect_port_candidates() {
    local -A port_seen=()
    local -a ports=()
    local slot_count
    slot_count=$(cleanup_port_slot_count)

    cleanup_add_spaced_ports port_seen ports "${BACKEND_PORT_BASE:-}" "${PORT_SPACING:-}" "$slot_count"
    cleanup_add_spaced_ports port_seen ports "${FRONTEND_PORT_BASE:-}" "${PORT_SPACING:-}" "$slot_count"

    if [ "${PER_TREE_REQUIREMENTS:-false}" = true ]; then
        cleanup_add_spaced_ports port_seen ports "${DB_PORT_BASE:-}" "${PORT_SPACING:-}" "$slot_count"
        cleanup_add_spaced_ports port_seen ports "${REDIS_PORT_BASE:-}" "${PORT_SPACING:-}" "$slot_count"
    fi

    cleanup_add_port port_seen ports "${DB_PORT:-}"
    cleanup_add_port port_seen ports "${REDIS_PORT:-}"

    if [ "${SUPABASE_ALL_TREES:-false}" = true ] || [ "${SUPABASE_MAIN_ENABLE:-false}" = true ]; then
        cleanup_add_spaced_ports port_seen ports "${SUPABASE_PUBLIC_PORT_BASE:-}" "${PORT_SPACING:-}" "$slot_count"
        cleanup_add_spaced_ports port_seen ports "${SUPABASE_DB_PORT_BASE:-}" "${PORT_SPACING:-}" "$slot_count"
    fi

    local name
    local pid="" port="" log="" type="" dir=""
    for name in "${!service_info[@]}"; do
        if service_info_fields "$name" pid port log type dir; then
            cleanup_add_port port_seen ports "$port"
        fi
    done

    for name in "${!actual_ports[@]}"; do
        cleanup_add_port port_seen ports "${actual_ports[$name]}"
    done

    local ports_dir="${BASE_DIR:-.}/.envctl-workspaces"
    if [ -d "$ports_dir" ]; then
        local ports_file line port_blob
        for ports_file in "$ports_dir"/*.ports; do
            [ -f "$ports_file" ] || continue
            while IFS= read -r line; do
                [ -n "$line" ] || continue
                port_blob="${line#*:}"
                port_blob="${port_blob//|/,}"
                local -a parts=()
                local part
                IFS=',' read -r -a parts <<< "$port_blob"
                for part in "${parts[@]}"; do
                    cleanup_add_port port_seen ports "$part"
                done
            done < "$ports_file"
        done
    fi

    printf '%s\n' "${ports[@]}"
}

get_pids_for_port() {
    local port=$1
    if ! command -v lsof >/dev/null 2>&1; then
        return 0
    fi
    lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true
}

cleanup_kill_port_ranges() {
    if [ "${CLEANUP_KILL_PORT_RANGES:-false}" != true ]; then
        return 0
    fi

    local -a ports=()
    while IFS= read -r port; do
        [ -n "$port" ] && ports+=("$port")
    done < <(cleanup_collect_port_candidates)

    if [ ${#ports[@]} -eq 0 ]; then
        return 0
    fi

    echo -e "${YELLOW}Stopping processes bound to configured port ranges...${NC}"
    local port
    for port in "${ports[@]}"; do
        if [ "$(type -t force_kill_port)" = "function" ]; then
            force_kill_port "$port" >/dev/null 2>&1 || true
        else
            local pids
            pids=$(get_pids_for_port "$port")
            if [ -n "$pids" ]; then
                echo "$pids" | xargs kill -9 2>/dev/null || true
            fi
        fi
    done
}

# Function to find service by partial name or port

cleanup() {
    local _cleanup_exit_code=$?
    # If a signal triggered this, ensure we exit with 128+signal (POSIX convention)
    # rather than inheriting whatever $? happened to be at signal delivery time.
    if [ -n "${RUN_SH_SIGNAL_RECEIVED:-}" ]; then
        case "$RUN_SH_SIGNAL_RECEIVED" in
            INT)  _cleanup_exit_code=130 ;;
            TERM) _cleanup_exit_code=143 ;;
        esac
    fi
    if [ "${CLEANUP_COMPLETED:-false}" = true ] || [ "${CLEANUP_IN_PROGRESS:-false}" = true ]; then
        return 0
    fi
    CLEANUP_IN_PROGRESS=true
    if [ "${SKIP_CLEANUP}" = true ]; then
        CLEANUP_IN_PROGRESS=false
        return 0
    fi
    echo -e "\n${YELLOW}Stopping all services...${NC}"

    # Always terminate background jobs first (parallel startup workers, helper jobs),
    # even when no service PIDs have been registered yet.
    kill_job_pids TERM

    if [ ${#pids[@]} -eq 0 ] && [ ${#service_info[@]} -gt 0 ]; then
        declare -A pid_seen=()
        for key in "${!service_info[@]}"; do
            service_info_fields "$key" pid port log type dir || continue
            if [ -n "$pid" ] && [ -z "${pid_seen[$pid]:-}" ]; then
                pid_seen[$pid]=1
                if kill -0 "$pid" 2>/dev/null; then
                    pids+=("$pid")
                fi
            fi
        done
    fi

    # Handle empty service case — still run cleanup below
    if [ ${#pids[@]} -eq 0 ]; then
        echo -e "${GREEN}No services to stop${NC}"
    fi

  if [ ${#pids[@]} -gt 0 ]; then
    # Show shutdown progress
    echo -e "${YELLOW}Graceful shutdown in progress...${NC}"

    # First try graceful shutdown
    local total_services=${#pids[@]}
    local stopped=0

    # Kill all child processes gracefully
    kill_job_pids TERM

    # Kill specific PIDs with progress indicator
    for pid in "${pids[@]}"; do
        if kill -TERM "$pid" 2>/dev/null; then
            ((stopped++))
            local progress=$((stopped * 100 / total_services))
            printf "\rShutdown progress: ["
            printf "%*s" $((progress / 5)) | tr ' ' '#'
            printf "%*s" $((20 - progress / 5)) | tr ' ' '-'
            printf "] %d%%" "$progress"
        fi
    done
    echo

    # Also kill any orphaned processes scoped to this project
    local _cleanup_pattern="${BASE_DIR:-__no_match__}"
    pkill -f "uvicorn.*${_cleanup_pattern}" 2>/dev/null || true
    pkill -f "npm run dev.*${_cleanup_pattern}" 2>/dev/null || true
    pkill -f "vite.*${_cleanup_pattern}" 2>/dev/null || true

    # Give time to stop gracefully
    local wait_count=0
    while [ $wait_count -lt $GRACEFUL_SHUTDOWN_TIMEOUT ]; do
        sleep 1
        ((wait_count++))
        # Check if any processes are still running
        local still_running=0
        for pid in "${pids[@]}"; do
            if kill -0 "$pid" 2>/dev/null; then
                ((still_running++))
            fi
        done
        if [ $still_running -eq 0 ]; then
            break
        fi
        printf "\rWaiting for graceful shutdown: %d/%d seconds" "$wait_count" "$GRACEFUL_SHUTDOWN_TIMEOUT"
    done
    echo

    # Force kill if needed
    kill_job_pids KILL
    for pid in "${pids[@]}"; do
        kill -9 "$pid" 2>/dev/null || true
    done

    # Final cleanup of any remaining processes scoped to this project
    pkill -9 -f "uvicorn.*${_cleanup_pattern}" 2>/dev/null || true
    pkill -9 -f "npm run dev.*${_cleanup_pattern}" 2>/dev/null || true
    pkill -9 -f "vite.*${_cleanup_pattern}" 2>/dev/null || true

  fi # end if pids > 0

    # Ensure any remaining background jobs are terminated regardless of service PID state.
    kill_job_pids KILL

    cleanup_kill_port_ranges

    # Actually handle database preservation
    if [ "${CLEANUP_STOP_INFRA:-false}" = true ] && [ "$CLEANUP_DB_MODE" != "preserve" ]; then
        local remove_volumes=false
        if [ "$CLEANUP_DB_MODE" = "remove-volumes" ] || [ "$REMOVE_DB_VOLUMES" = true ]; then
            remove_volumes=true
        fi
        if [ "${CLEANUP_SCOPE_STATE_ONLY:-false}" = true ] && [ "$(type -t cleanup_state_requirements)" = "function" ]; then
            if [ "$remove_volumes" = true ]; then
                echo "Removing state-scoped requirement containers and volumes..."
            else
                echo "Removing state-scoped requirement containers..."
            fi
            cleanup_state_requirements "$remove_volumes"
        elif per_tree_requirements_enabled; then
            if [ "$remove_volumes" = true ]; then
                echo "Removing per-tree database containers and volumes..."
            else
                echo "Removing per-tree database containers..."
            fi
            cleanup_tree_requirements "$remove_volumes"
        else
            if [ "$remove_volumes" = true ]; then
                echo "Removing database containers and volumes..."
                docker rm -f -v "${DB_CONTAINER_NAME:-}" "${REDIS_CONTAINER_NAME:-}" 2>/dev/null || true
            else
                echo "Removing database containers..."
                docker rm -f "${DB_CONTAINER_NAME:-}" "${REDIS_CONTAINER_NAME:-}" 2>/dev/null || true
            fi
        fi
    elif [ "${CLEANUP_STOP_INFRA:-false}" = true ]; then
        echo "Database containers preserved as requested"
    else
        echo "Infrastructure containers preserved as requested"
    fi

    # Generate error report if there were failures
    if [ ${#failed_services[@]} -gt 0 ]; then
        generate_error_report
    fi

    # Clean up temporary files and locks
    rm -f "$SCRIPT_DIR"/.${DB_NAME}.lock 2>/dev/null || true
    rm -f /tmp/${DB_NAME}-*.tmp 2>/dev/null || true
    # Preserve LAST_STATE_FILE on signal interrupt so --resume works
    if [ "$_cleanup_exit_code" -eq 0 ]; then
        local pointer_dir=""
        pointer_dir=$(state_pointer_dir)
        if [ -n "${LAST_STATE_FILE:-}" ]; then
            rm -f "$LAST_STATE_FILE" 2>/dev/null || true
        fi
        rm -f "${pointer_dir}/.last_state.main" 2>/dev/null || true
        if ls "${pointer_dir}"/.last_state.trees.* >/dev/null 2>&1; then
            rm -f "${pointer_dir}"/.last_state.trees.* 2>/dev/null || true
        fi
    fi
    if [ "$(type -t port_state_clear)" = "function" ]; then
        port_state_clear
    fi
    if [ "$(type -t port_release_all)" = "function" ]; then
        port_release_all
    fi
    if [ -n "${RUN_SH_PARALLEL_FRAGMENT_DIR:-}" ]; then
        rm -rf "$RUN_SH_PARALLEL_FRAGMENT_DIR" 2>/dev/null || true
    fi

    # Log cleanup process
    echo -e "${GREEN}✓ All services stopped.${NC}" | tee -a "$LOGS_DIR/cleanup.log"
    echo "Cleanup completed at $(date)" >> "$LOGS_DIR/cleanup.log"

    CLEANUP_COMPLETED=true
    CLEANUP_IN_PROGRESS=false
    trap - INT TERM EXIT
    maybe_stop_docker

    exit "$_cleanup_exit_code"
}

cleanup_blast_all() {
    echo -e "\n${RED}!!! INITIATING BLAST-ALL NUCLEAR CLEANUP !!!${NC}"

    echo -e "${YELLOW}Hunting OS processes...${NC}"
    local os_targets=(
        "vite"
        "uvicorn.*app\.main"
        "bun\s+run\s+dev"
        "npm\s+run\s+dev"
        "celery"
    )
    for target in "${os_targets[@]}"; do
        if pkill -0 -f "$target" 2>/dev/null; then
            echo "  Killing match: $target"
            pkill -9 -f "$target" 2>/dev/null || true
        fi
    done

    echo -e "${YELLOW}Sweeping common development port ranges...${NC}"
    local lsof_pids
    local docker_filter='(com\.docker|Docker Desktop|vpnkit|dockerd|containerd)'
    local -A kill_pid_ports=()
    local -A docker_pid_ports=()
    for port in {8000..8100} {5432..5450} {6379..6400} {5678..5700}; do
        lsof_pids=$(lsof -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null) || true
        if [ -n "$lsof_pids" ]; then
            local kill_pids=()
            local keep_pids=()
            local pid=""
            while IFS= read -r pid; do
                [ -n "$pid" ] || continue
                local proc_cmd=""
                proc_cmd=$(ps -p "$pid" -o command= 2>/dev/null || true)
                if [ -n "$proc_cmd" ] && echo "$proc_cmd" | grep -Eiq "$docker_filter"; then
                    keep_pids+=("$pid")
                else
                    kill_pids+=("$pid")
                fi
            done <<< "$lsof_pids"

            if [ ${#kill_pids[@]} -gt 0 ]; then
                local kill_pid=""
                for kill_pid in "${kill_pids[@]}"; do
                    local existing_kill_ports="${kill_pid_ports[$kill_pid]:-}"
                    if [ -z "$existing_kill_ports" ]; then
                        kill_pid_ports["$kill_pid"]="$port"
                    else
                        case ",${existing_kill_ports}," in
                            *",${port},"*)
                                ;;
                            *)
                                kill_pid_ports["$kill_pid"]="${existing_kill_ports},${port}"
                                ;;
                        esac
                    fi
                done
            fi
            if [ ${#keep_pids[@]} -gt 0 ]; then
                local keep_pid=""
                for keep_pid in "${keep_pids[@]}"; do
                    local existing_ports="${docker_pid_ports[$keep_pid]:-}"
                    if [ -z "$existing_ports" ]; then
                        docker_pid_ports["$keep_pid"]="$port"
                    else
                        case ",${existing_ports}," in
                            *",${port},"*)
                                ;;
                            *)
                                docker_pid_ports["$keep_pid"]="${existing_ports},${port}"
                                ;;
                        esac
                    fi
                done
            fi
        fi
    done
    if [ ${#kill_pid_ports[@]} -gt 0 ]; then
        local kill_summary=""
        local kill_pid=""
        for kill_pid in "${!kill_pid_ports[@]}"; do
            kill_summary+="${kill_pid}|${kill_pid_ports[$kill_pid]}"$'\n'
        done
        while IFS='|' read -r kill_pid ports_csv; do
            [ -n "$kill_pid" ] || continue
            echo "  Killing orphaned PID ${kill_pid} across ports: ${ports_csv}"
            kill -9 "$kill_pid" 2>/dev/null || true
        done < <(printf '%s' "$kill_summary" | sort -t'|' -k1,1n)
    fi
    if [ ${#docker_pid_ports[@]} -gt 0 ]; then
        local docker_skip_summary=""
        local docker_pid=""
        for docker_pid in "${!docker_pid_ports[@]}"; do
            docker_skip_summary+="${docker_pid}|${docker_pid_ports[$docker_pid]}"$'\n'
        done
        while IFS='|' read -r docker_pid ports_csv; do
            [ -n "$docker_pid" ] || continue
            echo "  Skipping Docker-managed PID ${docker_pid} across ports: ${ports_csv}"
        done < <(printf '%s' "$docker_skip_summary" | sort -t'|' -k1,1n)
    fi

    echo -e "${YELLOW}Annihilating ecosystem Docker containers...${NC}"
    local keep_worktree_storage=false
    case "${RUN_SH_COMMAND_BLAST_KEEP_WORKTREE_VOLUMES:-false}" in
        1|true|TRUE|yes|YES|y|Y|on|ON)
            keep_worktree_storage=true
            ;;
    esac

    local remove_main_storage="${RUN_SH_COMMAND_BLAST_REMOVE_MAIN_VOLUMES:-}"
    case "$remove_main_storage" in
        1|true|TRUE|yes|YES|y|Y|on|ON)
            remove_main_storage=true
            ;;
        0|false|FALSE|no|NO|n|N|off|OFF)
            remove_main_storage=false
            ;;
        *)
            remove_main_storage=""
            ;;
    esac
    if [ -z "$remove_main_storage" ] && [ -t 0 ] && [ "$(type -t prompt_yes_no)" = "function" ]; then
        if prompt_yes_no "Delete MAIN project Docker storage volumes as well? (y/N): "; then
            remove_main_storage=true
        else
            remove_main_storage=false
        fi
    fi
    if [ -z "$remove_main_storage" ]; then
        remove_main_storage=false
    fi

    if [ "$keep_worktree_storage" = true ]; then
        echo "  Worktree Docker volumes: keep (override enabled)"
    else
        echo "  Worktree Docker volumes: remove (default)"
    fi
    if [ "$remove_main_storage" = true ]; then
        echo "  Main Docker volumes: remove"
    else
        echo "  Main Docker volumes: keep"
    fi

    local main_supabase_project=""
    if [ -n "${BASE_DIR:-}" ] && [ "$(type -t supabase_compose_project_name)" = "function" ]; then
        main_supabase_project=$(supabase_compose_project_name "$BASE_DIR" 2>/dev/null || true)
    fi
    local main_redis_container="${REDIS_CONTAINER_NAME:-${DOCKER_PROJECT_NAME:-envctl}-redis}"
    local main_db_container="${DB_CONTAINER_NAME:-${DOCKER_PROJECT_NAME:-envctl}-postgres}"

    local docker_ready=false
    if [ "$(type -t docker_probe)" = "function" ]; then
        if docker_probe info >/dev/null 2>&1; then
            docker_ready=true
        fi
    elif docker info >/dev/null 2>&1; then
        docker_ready=true
    fi

    if [ "$docker_ready" = true ]; then
        local docker_containers
        local volume_candidates=""
        docker_containers=$(docker ps -a --format "{{.ID}}|{{.Image}}|{{.Names}}" 2>/dev/null || true)
        if [ -n "$docker_containers" ]; then
            while IFS= read -r container; do
                [ -n "$container" ] || continue
                local cid="${container%%|*}"
                local rest="${container#*|}"
                local image="${rest%%|*}"
                local name="${rest#*|}"

                if [[ "$name" == *"supabase"* ]] || [[ "$name" == *"n8n"* ]] || [[ "$name" == *"redis"* ]] || [[ "$image" == *"postgres"* ]] || [[ "$image" == *"redis"* ]] || [[ "$image" == *"n8nio"* ]] || [[ "$image" == *"supabase"* ]]; then
                    local is_main_container=false
                    if [ "$name" = "$main_redis_container" ] || [ "$name" = "$main_db_container" ]; then
                        is_main_container=true
                    elif [ -n "$main_supabase_project" ] && [[ "$name" == "${main_supabase_project}-"* ]]; then
                        is_main_container=true
                    fi

                    local remove_container_storage=false
                    if [ "$is_main_container" = true ]; then
                        if [ "$remove_main_storage" = true ]; then
                            remove_container_storage=true
                        fi
                    else
                        if [ "$keep_worktree_storage" != true ]; then
                            remove_container_storage=true
                        fi
                    fi

                    echo "  Nuking container: $name ($image)"
                    if [ "$remove_container_storage" = true ]; then
                        local container_volumes=""
                        container_volumes=$(docker inspect -f '{{range .Mounts}}{{if eq .Type "volume"}}{{println .Name}}{{end}}{{end}}' "$cid" 2>/dev/null || true)
                        if [ -n "$container_volumes" ]; then
                            local volume_name=""
                            while IFS= read -r volume_name; do
                                [ -n "$volume_name" ] || continue
                                if ! printf '%s\n' "$volume_candidates" | grep -Fxq "$volume_name"; then
                                    if [ -z "$volume_candidates" ]; then
                                        volume_candidates="$volume_name"
                                    else
                                        volume_candidates="${volume_candidates}"$'\n'"$volume_name"
                                    fi
                                fi
                            done <<< "$container_volumes"
                        fi
                        docker rm -f -v "$cid" 2>/dev/null || true
                    else
                        docker rm -f "$cid" 2>/dev/null || true
                    fi
                fi
            done <<< "$docker_containers"

            if [ -n "$volume_candidates" ]; then
                local volume_name=""
                while IFS= read -r volume_name; do
                    [ -n "$volume_name" ] || continue
                    echo "  Nuking volume: $volume_name"
                    if docker volume rm "$volume_name" >/dev/null 2>&1; then
                        echo "    ✓ removed volume"
                    else
                        echo "    ⚠ volume not removed (in use or already deleted)"
                    fi
                done <<< "$volume_candidates"
            fi
        fi
    else
        echo -e "${YELLOW}  Docker daemon unavailable; skipping Docker container cleanup.${NC}"
    fi

    echo -e "${YELLOW}Purging leftover state pointers and locks...${NC}"
    local pointer_dir=""
    pointer_dir=$(state_pointer_dir)
    rm -f "${pointer_dir}/.last_state" 2>/dev/null || true
    rm -f "${pointer_dir}"/.last_state.* 2>/dev/null || true
    if [ "$(type -t port_reservation_dir)" = "function" ]; then
        local reservation_dir=""
        reservation_dir=$(port_reservation_dir)
        [ -n "$reservation_dir" ] && rm -rf "$reservation_dir" 2>/dev/null || true
    fi
    # Best-effort cleanup for legacy locations created before runtime-dir migration.
    rm -rf "$BASE_DIR/.run-sh-port-reservations" 2>/dev/null || true
    rm -rf "$BASE_DIR/utils/.run-sh-port-reservations" 2>/dev/null || true
    find "$BASE_DIR" -maxdepth 4 -name ".last_state" -type f -delete 2>/dev/null || true

    echo -e "${GREEN}✓ Ecosystem blasted.${NC}\n"
}

# Find the last saved state file path

state_file_from_pointer() {
    local pointer_file=$1
    [ -n "$pointer_file" ] || return 1
    [ -f "$pointer_file" ] || return 1
    local state_file
    state_file=$(cat "$pointer_file" 2>/dev/null || true)
    [ -n "$state_file" ] || return 1
    [ -f "$state_file" ] || return 1
    printf '%s\n' "$state_file"
    return 0
}

state_pointer_dir() {
    local runtime_dir=""
    if [ "$(type -t run_sh_runtime_dir)" = "function" ]; then
        runtime_dir=$(run_sh_runtime_dir)
    else
        runtime_dir="${RUN_SH_RUNTIME_DIR:-/tmp/envctl-runtime}"
        mkdir -p "$runtime_dir" 2>/dev/null || true
    fi
    printf '%s\n' "${runtime_dir%/}"
}

collect_all_state_pointers() {
    local logs_dir
    logs_dir=$(state_pointer_dir)
    [ -d "$logs_dir" ] || return 0
    [ -f "$logs_dir/.last_state" ] && echo "$logs_dir/.last_state"
    [ -f "$logs_dir/.last_state.main" ] && echo "$logs_dir/.last_state.main"
    local pointer
    while IFS= read -r pointer; do
        [ -n "$pointer" ] && [ -f "$pointer" ] && echo "$pointer"
    done < <(ls "$logs_dir"/.last_state.trees.* 2>/dev/null || true)
}

collect_dashboard_state_files() {
    local logs_dir
    logs_dir=$(state_pointer_dir)
    [ -d "$logs_dir" ] || return 0

    local -a pointers=()
    local pointer=""
    if [ -n "${LAST_STATE_FILE:-}" ] && [ -f "${LAST_STATE_FILE:-}" ]; then
        pointers+=("${LAST_STATE_FILE}")
    fi
    [ -f "$logs_dir/.last_state.main" ] && pointers+=("$logs_dir/.last_state.main")
    while IFS= read -r pointer; do
        [ -n "$pointer" ] && pointers+=("$pointer")
    done < <(ls -t "$logs_dir"/.last_state.trees.* 2>/dev/null || true)
    [ -f "$logs_dir/.last_state" ] && pointers+=("$logs_dir/.last_state")

    local -A seen_states=()
    local state_file=""
    for pointer in "${pointers[@]}"; do
        if state_file=$(state_file_from_pointer "$pointer"); then
            if [ -z "${seen_states["$state_file"]:-}" ]; then
                seen_states["$state_file"]=1
                printf '%s\n' "$state_file"
            fi
        fi
    done
}

find_last_state_file() {
    local logs_dir
    logs_dir=$(state_pointer_dir)
    local state_file=""
    local requested_mode="${TREES_MODE:-}"

    state_file_matches_requested_mode() {
        local candidate=$1
        [ -n "$candidate" ] || return 1
        [ -f "$candidate" ] || return 1
        case "$requested_mode" in
            true)
                grep -qE "export TREES_MODE=['\"]?true['\"]?" "$candidate"
                ;;
            false)
                grep -qE "export TREES_MODE=['\"]?false['\"]?" "$candidate"
                ;;
            *)
                return 0
                ;;
        esac
    }

    if state_file=$(state_file_from_pointer "${LAST_STATE_FILE:-}"); then
        if state_file_matches_requested_mode "$state_file"; then
            printf '%s\n' "$state_file"
            return 0
        fi
    fi

    if [ "${TREES_MODE:-false}" = true ]; then
        local -a parsed_targets=()
        if command -v parse_command_targets >/dev/null 2>&1; then
            parse_command_targets parsed_targets "${RUN_SH_COMMAND_TARGETS[@]}"
        else
            parsed_targets=("${RUN_SH_COMMAND_TARGETS[@]}")
        fi

        local target project pointer
        local -A seen_projects=()
        for target in "${parsed_targets[@]}"; do
            case "$target" in
                __PROJECT__:*)
                    project="${target#__PROJECT__:}"
                    ;;
                project:*)
                    project="${target#project:}"
                    ;;
                *)
                    project=""
                    ;;
            esac
            [ -n "$project" ] || continue
            if [ -n "${seen_projects["$project"]:-}" ]; then
                continue
            fi
            seen_projects["$project"]=1
            pointer="$logs_dir/.last_state.trees.$project"
            if state_file=$(state_file_from_pointer "$pointer"); then
                if state_file_matches_requested_mode "$state_file"; then
                    printf '%s\n' "$state_file"
                    return 0
                fi
            fi
        done

        while IFS= read -r pointer; do
            [ -n "$pointer" ] || continue
            if state_file=$(state_file_from_pointer "$pointer"); then
                if state_file_matches_requested_mode "$state_file"; then
                    printf '%s\n' "$state_file"
                    return 0
                fi
            fi
        done < <(ls -t "$logs_dir"/.last_state.trees.* 2>/dev/null || true)
    else
        if state_file=$(state_file_from_pointer "$logs_dir/.last_state.main"); then
            if state_file_matches_requested_mode "$state_file"; then
                printf '%s\n' "$state_file"
                return 0
            fi
        fi
    fi

    if state_file=$(state_file_from_pointer "$logs_dir/.last_state"); then
        if state_file_matches_requested_mode "$state_file"; then
            printf '%s\n' "$state_file"
            return 0
        fi
    fi

    return 1
}

load_state_for_dashboard() {
    local -a merged_services=()
    local -a merged_pids=()
    local -A merged_service_info=()
    local -A merged_service_ports=()
    local -A merged_actual_ports=()
    local -A seen_service_names=()
    local -A seen_pids=()
    local loaded_any=false

    local state_file=""
    while IFS= read -r state_file; do
        [ -n "$state_file" ] || continue
        [ -f "$state_file" ] || continue

        loaded_any=true
        local tmp
        tmp=$(mktemp)
        (
            # shellcheck disable=SC1090
            source "$state_file"
            local svc=""
            for svc in "${services[@]}"; do
                printf 'SERVICE\t%s\n' "$svc"
            done
            local key=""
            for key in "${!service_info[@]}"; do
                printf 'INFO\t%s\t%s\n' "$key" "${service_info["$key"]}"
            done
            for key in "${!service_ports[@]}"; do
                printf 'SPORT\t%s\t%s\n' "$key" "${service_ports["$key"]}"
            done
            for key in "${!actual_ports[@]}"; do
                printf 'APORT\t%s\t%s\n' "$key" "${actual_ports["$key"]}"
            done
            local pid=""
            for pid in "${pids[@]}"; do
                printf 'PID\t%s\n' "$pid"
            done
        ) > "$tmp"

        local tag="" v1="" v2=""
        while IFS=$'\t' read -r tag v1 v2; do
            case "$tag" in
                SERVICE)
                    [ -n "$v1" ] || continue
                    local service_name="${v1%%|*}"
                    [ -n "$service_name" ] || service_name="$v1"
                    if [ -z "${seen_service_names["$service_name"]:-}" ]; then
                        seen_service_names["$service_name"]=1
                        merged_services+=("$v1")
                    fi
                    ;;
                INFO)
                    [ -n "$v1" ] || continue
                    if [ -z "${merged_service_info["$v1"]:-}" ]; then
                        merged_service_info["$v1"]="$v2"
                    fi
                    ;;
                SPORT)
                    [ -n "$v1" ] || continue
                    merged_service_ports["$v1"]="$v2"
                    ;;
                APORT)
                    [ -n "$v1" ] || continue
                    merged_actual_ports["$v1"]="$v2"
                    ;;
                PID)
                    [ -n "$v1" ] || continue
                    if [ -z "${seen_pids["$v1"]:-}" ]; then
                        seen_pids["$v1"]=1
                        merged_pids+=("$v1")
                    fi
                    ;;
            esac
        done < "$tmp"
        rm -f "$tmp"
    done < <(collect_dashboard_state_files)

    if [ "$loaded_any" != true ]; then
        return 1
    fi

    services=("${merged_services[@]}")
    pids=("${merged_pids[@]}")

    local key=""
    for key in "${!service_info[@]}"; do
        unset 'service_info[$key]'
    done
    for key in "${!merged_service_info[@]}"; do
        service_info["$key"]="${merged_service_info[$key]}"
    done

    for key in "${!service_ports[@]}"; do
        unset 'service_ports[$key]'
    done
    for key in "${!merged_service_ports[@]}"; do
        service_ports["$key"]="${merged_service_ports[$key]}"
    done

    for key in "${!actual_ports[@]}"; do
        unset 'actual_ports[$key]'
    done
    for key in "${!merged_actual_ports[@]}"; do
        actual_ports["$key"]="${merged_actual_ports[$key]}"
    done

    return 0
}


last_state_is_trees() {
    local state_file
    if ! state_file=$(find_last_state_file); then
        return 1
    fi
    grep -qE "export TREES_MODE=['\"]?true['\"]?" "$state_file"
}


last_state_is_main() {
    local state_file
    if ! state_file=$(find_last_state_file); then
        return 1
    fi
    grep -qE "export TREES_MODE=['\"]?false['\"]?" "$state_file"
}

resume_project_name_is_main() {
    local project_name=${1:-}
    [ -n "$project_name" ] || return 1
    local lowered=""
    lowered=$(printf '%s' "$project_name" | tr '[:upper:]' '[:lower:]')
    [ "$lowered" = "main" ]
}


resume_selected_projects_from_targets() {
    if [ ${#RUN_SH_COMMAND_TARGETS[@]} -eq 0 ]; then
        return 0
    fi

    local -a parsed_targets=()
    if command -v parse_command_targets >/dev/null 2>&1; then
        parse_command_targets parsed_targets "${RUN_SH_COMMAND_TARGETS[@]}"
    else
        parsed_targets=("${RUN_SH_COMMAND_TARGETS[@]}")
    fi

    local -a selected_projects=()
    local target
    for target in "${parsed_targets[@]}"; do
        case "$target" in
            __ALL__|all)
                return 0
                ;;
            __PROJECT__:*)
                selected_projects+=("${target#__PROJECT__:}")
                ;;
            project:*)
                selected_projects+=("${target#project:}")
                ;;
        esac
    done

    if [ ${#selected_projects[@]} -eq 0 ]; then
        return 0
    fi

    local -A seen=()
    local project_name
    for project_name in "${selected_projects[@]}"; do
        [ -n "$project_name" ] || continue
        if resume_project_name_is_main "$project_name"; then
            project_name="Main"
        fi
        if [ -z "${seen[$project_name]:-}" ]; then
            seen["$project_name"]=1
            echo "$project_name"
        fi
    done
}

resume_selected_targets_include_main() {
    local project_name=""
    while IFS= read -r project_name; do
        [ -n "$project_name" ] || continue
        if resume_project_name_is_main "$project_name"; then
            return 0
        fi
    done < <(resume_selected_projects_from_targets)
    return 1
}

state_load_dashboard_selection() {
    if ! load_state_for_dashboard; then
        return 1
    fi

    local state_file=""
    if ! state_file=$(find_last_state_file 2>/dev/null); then
        while IFS= read -r state_file; do
            [ -n "$state_file" ] && break
        done < <(collect_dashboard_state_files)
    fi

    if [ -n "$state_file" ]; then
        LOGS_DIR="$(dirname "$state_file")"
        STATE_FILE="$state_file"
    else
        local runtime_root=""
        runtime_root=$(state_pointer_dir 2>/dev/null || true)
        LOGS_DIR="${runtime_root:-${LOGS_DIR:-}}"
        STATE_FILE=""
    fi

    SKIP_CLEANUP=true
    return 0
}

resume_apply_project_filter() {
    if [ "${TREES_MODE:-false}" != true ]; then
        return 0
    fi

    local -a selected_projects=()
    local project_name
    while IFS= read -r project_name; do
        [ -n "$project_name" ] && selected_projects+=("$project_name")
    done < <(resume_selected_projects_from_targets)

    if [ ${#selected_projects[@]} -eq 0 ]; then
        return 0
    fi

    local -A keep_projects=()
    for project_name in "${selected_projects[@]}"; do
        keep_projects["$project_name"]=1
    done

    local -a filtered_services=()
    local -A filtered_service_info=()
    local -A filtered_service_ports=()
    local -A filtered_actual_ports=()
    local -a filtered_pids=()
    local -A seen_pids=()
    local -A matched_projects=()

    local service name url docs pid port log type dir svc_project
    for service in "${services[@]}"; do
        parse_service_entry "$service" name url docs || continue
        svc_project=$(project_name_from_service_name "$name")
        if [ -z "${keep_projects[$svc_project]:-}" ]; then
            continue
        fi

        matched_projects["$svc_project"]=1
        filtered_services+=("$service")

        if [ -n "${service_info[$name]:-}" ]; then
            filtered_service_info["$name"]="${service_info[$name]}"
            IFS='|' read -r pid port log type dir <<< "${service_info[$name]}"
            if [ -n "$pid" ] && [ -z "${seen_pids[$pid]:-}" ]; then
                seen_pids["$pid"]=1
                filtered_pids+=("$pid")
            fi
        fi

        if [ -n "${service_ports[$name]:-}" ]; then
            filtered_service_ports["$name"]="${service_ports[$name]}"
        fi
        if [ -n "${actual_ports[$name]:-}" ]; then
            filtered_actual_ports["$name"]="${actual_ports[$name]}"
        fi
    done

    if [ ${#filtered_services[@]} -eq 0 ]; then
        echo -e "${RED}No services found for selected resume worktrees: $(IFS=','; echo "${selected_projects[*]}").${NC}"
        return 1
    fi

    services=("${filtered_services[@]}")

    unset service_info
    if ! declare -g -A service_info=() 2>/dev/null; then
        declare -A service_info=()
    fi
    local key
    for key in "${!filtered_service_info[@]}"; do
        service_info["$key"]="${filtered_service_info[$key]}"
    done

    unset service_ports
    if ! declare -g -A service_ports=() 2>/dev/null; then
        declare -A service_ports=()
    fi
    for key in "${!filtered_service_ports[@]}"; do
        service_ports["$key"]="${filtered_service_ports[$key]}"
    done

    unset actual_ports
    if ! declare -g -A actual_ports=() 2>/dev/null; then
        declare -A actual_ports=()
    fi
    for key in "${!filtered_actual_ports[@]}"; do
        actual_ports["$key"]="${filtered_actual_ports[$key]}"
    done

    pids=("${filtered_pids[@]}")

    local -a missing_projects=()
    for project_name in "${selected_projects[@]}"; do
        if [ -z "${matched_projects[$project_name]:-}" ]; then
            missing_projects+=("$project_name")
        fi
    done

    echo -e "${CYAN}Resuming selected worktrees: $(IFS=','; echo "${selected_projects[*]}").${NC}"
    if [ ${#missing_projects[@]} -gt 0 ]; then
        echo -e "${YELLOW}Selected worktrees not found in saved state: $(IFS=','; echo "${missing_projects[*]}").${NC}"
    fi

    return 0
}

# Resume from a saved state

resume_apply_status_defaults() {
    local fast_resume="${RUN_SH_RESUME_FAST_STATUS:-true}"
    case "$fast_resume" in
        1|true|TRUE|yes|YES|y|Y|on|ON)
            ;;
        *)
            return 0
            ;;
    esac

    if [ -z "${RUN_SH_STATUS_MODE:-}" ]; then
        RUN_SH_STATUS_MODE="${RUN_SH_RESUME_STATUS_MODE:-lite}"
    fi
    if [ -z "${RUN_SH_STATUS_CACHE_TTL:-}" ]; then
        RUN_SH_STATUS_CACHE_TTL=30
    fi
    if [ -z "${RUN_SH_PID_TTL:-}" ]; then
        RUN_SH_PID_TTL=10
    fi
    if [ -z "${RUN_SH_N8N_HEALTH_TTL:-}" ]; then
        RUN_SH_N8N_HEALTH_TTL=5
    fi
    if [ -z "${RUN_SH_N8N_HEALTH_PARALLEL:-}" ]; then
        RUN_SH_N8N_HEALTH_PARALLEL=16
    fi
    if [ -z "${RUN_SH_HEALTH_PARALLEL:-}" ]; then
        RUN_SH_HEALTH_PARALLEL=16
    fi
    if [ -z "${RUN_SH_LITE_RESOLVE_PIDS:-}" ]; then
        RUN_SH_LITE_RESOLVE_PIDS=true
    fi
    if [ -z "${RUN_SH_LITE_SHOW_PR:-}" ]; then
        RUN_SH_LITE_SHOW_PR=true
    fi
}

state_guess_project_root_from_name() {
    local project_name=$1

    if [ -z "$project_name" ] || [ "$project_name" = "Main" ]; then
        printf '%s\n' "${BASE_DIR%/}"
        return 0
    fi

    local trees_root="${BASE_DIR%/}/${TREES_DIR_NAME:-trees}"
    if [ ! -d "$trees_root" ]; then
        return 1
    fi

    local feature="$project_name"
    local iter=""
    if [[ "$project_name" =~ ^(.+)_([0-9]+)$ ]]; then
        feature="${BASH_REMATCH[1]}"
        iter="${BASH_REMATCH[2]}"
    fi

    local candidate=""
    if [ -n "$iter" ]; then
        candidate="${trees_root%/}/${feature}/${iter}"
        if [ -d "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    fi

    candidate="${trees_root%/}/${project_name}"
    if [ -d "$candidate" ]; then
        printf '%s\n' "$candidate"
        return 0
    fi

    candidate="${trees_root%/}/${project_name}/1"
    if [ -d "$candidate" ]; then
        printf '%s\n' "$candidate"
        return 0
    fi

    return 1
}

state_guess_service_dir_from_name() {
    local service_name=$1
    local service_type=$2
    local project_name=""

    if [ "$(type -t project_name_from_service_name)" = "function" ]; then
        project_name=$(project_name_from_service_name "$service_name")
    fi

    local project_root=""
    project_root=$(state_guess_project_root_from_name "$project_name" 2>/dev/null || true)
    if [ -z "$project_root" ]; then
        return 1
    fi

    case "$service_type" in
        backend)
            printf '%s/%s\n' "${project_root%/}" "${BACKEND_DIR_NAME:-backend}"
            ;;
        frontend)
            printf '%s/%s\n' "${project_root%/}" "${FRONTEND_DIR_NAME:-frontend}"
            ;;
        *)
            return 1
            ;;
    esac
}

state_recover_service_info_if_missing() {
    if [ ${#services[@]} -eq 0 ]; then
        return 0
    fi

    if ! declare -p service_info >/dev/null 2>&1; then
        if ! declare -g -A service_info=() 2>/dev/null; then
            declare -A service_info=()
        fi
    fi

    if ! declare -p service_ports >/dev/null 2>&1; then
        if ! declare -g -A service_ports=() 2>/dev/null; then
            declare -A service_ports=()
        fi
    fi
    if ! declare -p actual_ports >/dev/null 2>&1; then
        if ! declare -g -A actual_ports=() 2>/dev/null; then
            declare -A actual_ports=()
        fi
    fi

    local recovered=0
    local service name url docs
    for service in "${services[@]}"; do
        parse_service_entry "$service" name url docs || continue
        [ -n "$name" ] || continue

        local port=""
        port=$(port_from_url "$url")

        local existing="${service_info[$name]:-}"
        local pid=""
        local saved_port=""
        local log=""
        local type=""
        local dir=""
        if [ -n "$existing" ]; then
            IFS='|' read -r pid saved_port log type dir <<< "$existing"
        fi

        if [ -z "$saved_port" ]; then
            saved_port="$port"
        fi
        if [ -z "$type" ] && [ "$(type -t service_type_from_name)" = "function" ]; then
            type=$(service_type_from_name "$name")
        fi
        if [ -z "$pid" ] && [ -n "$saved_port" ]; then
            pid=$(lsof -nP -iTCP:"$saved_port" -sTCP:LISTEN -t 2>/dev/null | head -n 1 || true)
        fi
        if [ -z "$dir" ]; then
            dir=$(state_guess_service_dir_from_name "$name" "$type" 2>/dev/null || true)
        fi

        local updated="${pid}|${saved_port}|${log}|${type}|${dir}"
        if [ "$existing" != "$updated" ]; then
            recovered=$((recovered + 1))
        fi

        service_info["$name"]="$updated"
        if [ -n "$saved_port" ]; then
            service_ports["$saved_port"]="$name"
            actual_ports["$name"]="$saved_port"
        fi
    done

    if [ "$recovered" -gt 0 ]; then
        echo -e "${YELLOW}Recovered missing service metadata for ${recovered} services.${NC}"
    fi
}

resume_from_state() {
    local resumed_from_dashboard=false
    if [ "${TREES_MODE:-false}" = true ] && resume_selected_targets_include_main; then
        if ! state_load_dashboard_selection; then
            echo -e "${RED}No saved state found. Use 'quit' to save a resumable session.${NC}"
            exit 1
        fi
        resumed_from_dashboard=true
    else
        local state_file
        if ! state_file=$(find_last_state_file); then
            echo -e "${RED}No saved state found. Use 'quit' to save a resumable session.${NC}"
            exit 1
        fi

        LOGS_DIR="$(dirname "$state_file")"
        STATE_FILE="$state_file"
        SKIP_CLEANUP=true

        # shellcheck disable=SC1090
        source "$STATE_FILE"
        if [ -n "${RUN_LOGS_DIR:-}" ]; then
            local resolved_logs_dir=""
            resolved_logs_dir=$(state_absolute_dir "$RUN_LOGS_DIR" 2>/dev/null || true)
            if [ -n "$resolved_logs_dir" ]; then
                LOGS_DIR="$resolved_logs_dir"
            else
                LOGS_DIR="$RUN_LOGS_DIR"
            fi
        fi
    fi

    if ! resume_apply_project_filter; then
        exit 1
    fi

    state_recover_service_info_if_missing
    resume_apply_status_defaults

    if [ "$resumed_from_dashboard" = true ]; then
        echo -e "${GREEN}Resumed merged session from dashboard state pointers.${NC}"
    else
        echo -e "${GREEN}Resumed session from: $STATE_FILE${NC}"
    fi

    local missing_backends=()
    local missing_frontends=()
    local missing_total=0
    for service in "${services[@]}"; do
        parse_service_entry "$service" name url docs || continue
        if service_info_fields "$name" pid port log type dir; then
            if ! kill -0 "$pid" 2>/dev/null; then
                if [ "$type" = "backend" ]; then
                    missing_backends+=("$name")
                else
                    missing_frontends+=("$name")
                fi
                ((missing_total++))
            fi
        fi
    done

    if [ $missing_total -gt 0 ]; then
        local should_restart=true
        if [ "$INTERACTIVE_MODE" = true ] && [ -t 0 ] && [ -t 1 ]; then
            echo -e "${YELLOW}Found ${missing_total} services not running in the saved session.${NC}"
            if ! prompt_yes_no "Restart them now? (y/N): "; then
                should_restart=false
            fi
        fi
        if [ "$should_restart" = true ]; then
            for svc in "${missing_backends[@]}"; do
                restart_service "$svc"
            done
            for svc in "${missing_frontends[@]}"; do
                restart_service "$svc"
            done
        fi
    fi

    if [ "$INTERACTIVE_MODE" = true ]; then
        interactive_mode
        echo -e "${GREEN}Services continue running in background.${NC}"
        echo -e "${CYAN}To stop them later, use: kill $(echo ${pids[@]})${NC}"
        exit 0
    fi

    show_status
    exit 0
}

# Load saved state for non-interactive command execution (no restarts).
load_state_for_command() {
    if [ "${TREES_MODE:-false}" = true ] && resume_selected_targets_include_main; then
        if ! state_load_dashboard_selection; then
            echo -e "${RED}No saved state found. Use 'quit' to save a resumable session.${NC}"
            return 1
        fi
    else
        local state_file
        if ! state_file=$(find_last_state_file); then
            echo -e "${RED}No saved state found. Use 'quit' to save a resumable session.${NC}"
            return 1
        fi

        LOGS_DIR="$(dirname "$state_file")"
        STATE_FILE="$state_file"
        SKIP_CLEANUP=true

        # Validate state file before sourcing: must live under an expected runtime
        # root (new /tmp runtime paths or legacy repo logs) and carry the header.
        local logs_base="${BASE_DIR%/}/logs"
        local runtime_root=""
        runtime_root=$(state_pointer_dir 2>/dev/null || true)
        local state_path_allowed=false
        case "$STATE_FILE" in
            "$logs_base"/*)
                state_path_allowed=true
                ;;
        esac
        if [ "$state_path_allowed" != true ] && [ -n "$runtime_root" ]; then
            case "$STATE_FILE" in
                "${runtime_root%/}/states/"*|\
                "${runtime_root%/}/runs/"*)
                    state_path_allowed=true
                    ;;
            esac
        fi
        if [ "$state_path_allowed" != true ]; then
            echo -e "${RED}State file is outside expected runtime directories: $STATE_FILE${NC}" >&2
            return 1
        fi
        local header=""
        header=$(head -2 "$STATE_FILE" 2>/dev/null || true)
        if ! echo "$header" | grep -q "# envctl State File"; then
            echo -e "${RED}State file missing expected header — refusing to load: $STATE_FILE${NC}" >&2
            return 1
        fi

        # shellcheck disable=SC1090
        source "$STATE_FILE"
        if [ -n "${RUN_LOGS_DIR:-}" ]; then
            local resolved_logs_dir=""
            resolved_logs_dir=$(state_absolute_dir "$RUN_LOGS_DIR" 2>/dev/null || true)
            if [ -n "$resolved_logs_dir" ]; then
                LOGS_DIR="$resolved_logs_dir"
            else
                LOGS_DIR="$RUN_LOGS_DIR"
            fi
        fi
    fi

    # Promote state variables to globals (state files use declare, which is local
    # when sourced inside this function).
    if declare -p services >/dev/null 2>&1; then
        local -a loaded_services=("${services[@]}")
        if declare -g -a services=("${loaded_services[@]}") 2>/dev/null; then
            :
        else
            services=("${loaded_services[@]}")
        fi
    fi

    if declare -p service_info >/dev/null 2>&1; then
        local -A loaded_service_info=()
        local key
        for key in "${!service_info[@]}"; do
            loaded_service_info["$key"]="${service_info[$key]}"
        done
        local service_info_decl="declare -g -A service_info=("
        for key in "${!loaded_service_info[@]}"; do
            service_info_decl+="[$(printf '%q' "$key")]=$(printf '%q' "${loaded_service_info[$key]}") "
        done
        service_info_decl+=")"
        if eval "$service_info_decl" 2>/dev/null; then
            :
        else
            declare -A service_info
            for key in "${!loaded_service_info[@]}"; do
                service_info["$key"]="${loaded_service_info[$key]}"
            done
        fi
    fi

    if declare -p service_ports >/dev/null 2>&1; then
        local -A loaded_service_ports=()
        local port_key
        for port_key in "${!service_ports[@]}"; do
            loaded_service_ports["$port_key"]="${service_ports[$port_key]}"
        done
        local service_ports_decl="declare -g -A service_ports=("
        for port_key in "${!loaded_service_ports[@]}"; do
            service_ports_decl+="[$(printf '%q' "$port_key")]=$(printf '%q' "${loaded_service_ports[$port_key]}") "
        done
        service_ports_decl+=")"
        if eval "$service_ports_decl" 2>/dev/null; then
            :
        else
            declare -A service_ports
            for port_key in "${!loaded_service_ports[@]}"; do
                service_ports["$port_key"]="${loaded_service_ports[$port_key]}"
            done
        fi
    fi

    state_recover_service_info_if_missing

    return 0
}

# Load last saved state into attach-only map

load_attach_state() {
    local state_file
    if ! state_file=$(find_last_state_file); then
        return 1
    fi
    local tmp
    tmp=$(mktemp)
    (
        # shellcheck disable=SC1090
        source "$state_file"
        for key in "${!service_info[@]}"; do
            echo "$key|${service_info[$key]}"
        done
    ) > "$tmp"

    while IFS='|' read -r name pid port log type dir; do
        [ -z "$name" ] && continue
        ATTACH_SERVICE_INFO["$name"]="$pid|$port|$log|$type|$dir"
    done < "$tmp"
    rm -f "$tmp"
    return 0
}

# Function to save current state

state_absolute_path() {
    local path=${1:-}
    [ -n "$path" ] || return 1

    local candidate="$path"
    if [[ "$candidate" != /* ]] && [ -n "${BASE_DIR:-}" ]; then
        candidate="${BASE_DIR%/}/$candidate"
    fi

    local dir base
    dir=$(dirname "$candidate")
    base=$(basename "$candidate")
    (
        cd "$dir" 2>/dev/null || return 1
        printf '%s/%s\n' "$(pwd)" "$base"
    )
}

state_absolute_dir() {
    local dir_path=${1:-}
    [ -n "$dir_path" ] || return 1
    local candidate="$dir_path"
    if [[ "$candidate" != /* ]] && [ -n "${BASE_DIR:-}" ]; then
        candidate="${BASE_DIR%/}/$candidate"
    fi
    (
        cd "$candidate" 2>/dev/null || return 1
        pwd
    )
}

save_state() {
    local state_path="$STATE_FILE"
    local abs_state_path=""
    abs_state_path=$(state_absolute_path "$state_path" 2>/dev/null || true)
    if [ -n "$abs_state_path" ]; then
        state_path="$abs_state_path"
        STATE_FILE="$abs_state_path"
    fi

    local state_dir=""
    state_dir=$(dirname "$state_path")
    mkdir -p "$state_dir" 2>/dev/null || true

    local run_logs_dir="${LOGS_DIR:-}"
    local abs_run_logs_dir=""
    if [ -n "$run_logs_dir" ]; then
        abs_run_logs_dir=$(state_absolute_dir "$run_logs_dir" 2>/dev/null || true)
        if [ -n "$abs_run_logs_dir" ]; then
            run_logs_dir="$abs_run_logs_dir"
        fi
    fi

    echo "Saving state to: $state_path"
    {
        echo "#!/bin/bash"
        echo "# envctl State File"
        echo "# Generated at: $(date)"
        printf "export TIMESTAMP=%q\n" "$TIMESTAMP"
        printf "export RUN_LOGS_DIR=%q\n" "$run_logs_dir"
        printf "export TREES_MODE='%s'\n" "$TREES_MODE"
        printf "export FRESH_INSTALL='%s'\n" "$FRESH_INSTALL"
        printf "export BACKEND_DIR_NAME=%q\n" "$BACKEND_DIR_NAME"
        printf "export FRONTEND_DIR_NAME=%q\n" "$FRONTEND_DIR_NAME"
        printf "export TREES_DIR_NAME=%q\n" "$TREES_DIR_NAME"
        echo ""
        echo "# Running Services"
        echo "declare -a services=("
        for service in "${services[@]}"; do
            printf "  %q\n" "$service"
        done
        echo ")"
        echo ""
        echo "# Service Info"
        echo "declare -A service_info=("
        for key in "${!service_info[@]}"; do
            printf "  [%q]=%q\n" "$key" "${service_info[$key]}"
        done
        echo ")"
        echo ""
        echo "# Service Ports"
        echo "declare -A service_ports=("
        for port in "${!service_ports[@]}"; do
            printf "  [%q]=%q\n" "$port" "${service_ports[$port]}"
        done
        echo ")"
        echo ""
        echo "# Actual Ports (after retries)"
        echo "declare -A actual_ports=("
        for key in "${!actual_ports[@]}"; do
            printf "  [%q]=%q\n" "$key" "${actual_ports[$key]}"
        done
        echo ")"
        echo ""
        echo "# PIDs"
        echo "declare -a pids=("
        for pid in "${pids[@]}"; do
            printf "  %q\n" "$pid"
        done
        echo ")"
    } > "$state_path"
}

state_projects_from_services() {
    local -A seen=()
    local service name url docs project
    for service in "${services[@]}"; do
        parse_service_entry "$service" name url docs || continue
        project=$(project_name_from_service_name "$name")
        [ -n "$project" ] || continue
        if [ -z "${seen[$project]:-}" ]; then
            seen["$project"]=1
            echo "$project"
        fi
    done
}

write_last_state_pointers() {
    local logs_dir
    logs_dir=$(state_pointer_dir)
    mkdir -p "$logs_dir"
    local state_path="$STATE_FILE"
    local abs_state_path=""
    abs_state_path=$(state_absolute_path "$state_path" 2>/dev/null || true)
    if [ -n "$abs_state_path" ]; then
        state_path="$abs_state_path"
        STATE_FILE="$abs_state_path"
    fi

    if [ -n "${LAST_STATE_FILE:-}" ]; then
        printf '%s\n' "$state_path" > "$LAST_STATE_FILE"
    fi

    if [ "${TREES_MODE:-false}" = true ]; then
        local project pointer
        while IFS= read -r project; do
            [ -n "$project" ] || continue
            pointer="$logs_dir/.last_state.trees.$project"
            printf '%s\n' "$state_path" > "$pointer"
        done < <(state_projects_from_services)
    else
        printf '%s\n' "$state_path" > "$logs_dir/.last_state.main"
    fi
}

resume_hint_command() {
    if [ "${TREES_MODE:-false}" = true ]; then
        local -a projects=()
        local project
        while IFS= read -r project; do
            [ -n "$project" ] && projects+=("$project")
        done < <(state_projects_from_services)

        if [ ${#projects[@]} -eq 1 ]; then
            printf 'envctl trees=true --resume --project %s\n' "${projects[0]}"
            return 0
        fi
        if [ ${#projects[@]} -gt 1 ]; then
            local csv
            csv=$(IFS=','; echo "${projects[*]}")
            printf 'envctl trees=true --resume --projects %s\n' "$csv"
            return 0
        fi
        printf 'envctl trees=true --resume\n'
        return 0
    fi

    printf 'envctl --main --resume\n'
}

# Function to generate error report

generate_error_report() {
    local error_report="$LOGS_DIR/error_report.txt"
    echo "Generating error report: $error_report"
    {
        echo "# envctl Error Report"
        echo "# Generated at: $(date)"
        echo ""
        echo "## Failed Services:"
        for failed in "${failed_services[@]}"; do
            IFS='|' read -r name log <<< "$failed"
            echo "- $name"
            echo "  Log: $log"
            if [ -f "$log" ]; then
                echo "  Last 10 lines:"
                tail -10 "$log" | sed 's/^/    /'
            fi
            echo ""
        done
        echo ""
        echo "## Port Allocation:"
        for key in "${!actual_ports[@]}"; do
            echo "- $key: ${actual_ports[$key]}"
        done
        if [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
            local debug_log=""
            if [ "$(type -t debug_log_path)" = "function" ]; then
                debug_log=$(debug_log_path)
            elif [ -n "${RUN_SH_DEBUG_LOG:-}" ]; then
                debug_log="$RUN_SH_DEBUG_LOG"
            else
                debug_log="$LOGS_DIR/run_debug.log"
            fi
            if [ -n "$debug_log" ]; then
                echo ""
                echo "## Debug Log:"
                echo "- $debug_log"
                local tail_lines="${RUN_SH_DEBUG_ERROR_TAIL_LINES:-}"
                if [ -f "$debug_log" ] && [[ "$tail_lines" =~ ^[0-9]+$ ]] && [ "$tail_lines" -gt 0 ]; then
                    echo "  Last ${tail_lines} lines:"
                    tail -n "$tail_lines" "$debug_log" | sed 's/^/    /'
                fi
            fi
        fi
    } > "$error_report"
}

# Function to create recovery script

create_recovery_script() {
    local recovery_script="$LOGS_DIR/recover.sh"
    local recovery_dir=""
    recovery_dir=$(dirname "$recovery_script")
    mkdir -p "$recovery_dir" 2>/dev/null || true
    local debug_log_path_value=""
    local state_file_value="$STATE_FILE"
    local abs_state_path=""
    abs_state_path=$(state_absolute_path "$state_file_value" 2>/dev/null || true)
    if [ -n "$abs_state_path" ]; then
        state_file_value="$abs_state_path"
    fi
    if [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
        if [ "$(type -t debug_log_path)" = "function" ]; then
            debug_log_path_value=$(debug_log_path)
        fi
    fi
    cat > "$recovery_script" << 'EOF'
#!/bin/bash
# Auto-generated recovery script
echo "Recovering envctl services from saved state..."

# Base directory for the original run script
BASE_DIR="__BASE_DIR__"

# Get the directory of this script
RECOVERY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEBUG_LOG_PATH="__DEBUG_LOG__"
STATE_FILE_PATH="__STATE_FILE__"

if [ -n "$DEBUG_LOG_PATH" ] && [ -f "$DEBUG_LOG_PATH" ]; then
    echo "Debug log: $DEBUG_LOG_PATH"
fi

# Source the state file
if [ -n "$STATE_FILE_PATH" ] && [ -f "$STATE_FILE_PATH" ]; then
    source "$STATE_FILE_PATH"
elif [ -f "$RECOVERY_DIR/.state" ]; then
    source "$RECOVERY_DIR/.state"
else
    echo "Error: State file not found at $STATE_FILE_PATH or $RECOVERY_DIR/.state"
    exit 1
fi

RUN_SCRIPT="${BASE_DIR}/utils/run.sh"
if [ ! -x "$RUN_SCRIPT" ]; then
    RUN_SCRIPT="${BASE_DIR}/run.sh"
fi
if [ ! -x "$RUN_SCRIPT" ]; then
    RUN_SCRIPT="${BASE_DIR}/utils/run-all-trees.sh"
fi
if [ ! -x "$RUN_SCRIPT" ]; then
    RUN_SCRIPT="${BASE_DIR}/run-all-trees.sh"
fi

echo "Found ${#services[@]} services to recover"

# Function to restart a service
restart_service() {
    local service_entry=$1
    IFS='|' read -r name url docs <<< "$service_entry"

    if [ -n "${service_info[$name]}" ]; then
        IFS='|' read -r pid port log type dir <<< "${service_info[$name]}"
        echo "Recovering $name ($type) on port $port..."

        # Check if directory still exists
        if [ ! -d "$dir" ]; then
            echo "Error: Directory $dir not found for $name"
            return 1
        fi

        # Restart based on type
        cd "$BASE_DIR"
        if [ "$type" = "backend" ]; then
            BACKEND_DIR_NAME="$BACKEND_DIR_NAME" "$RUN_SCRIPT" restart-single "$name" "$dir" "$type" "$port"
        else
            # For frontend, find backend port
            local backend_port=""
            local project_name="${name% Frontend}"
            for other_service in "${services[@]}"; do
                IFS='|' read -r other_name other_url other_docs <<< "$other_service"
                if [ "$other_name" = "$project_name Backend" ]; then
                    backend_port="${other_url##*:}"
                    backend_port="${backend_port%%/*}"
                    break
                fi
            done
            FRONTEND_DIR_NAME="$FRONTEND_DIR_NAME" "$RUN_SCRIPT" restart-single "$name" "$dir" "$type" "$port" "$backend_port"
        fi
    fi
}

# Restart all services
for service in "${services[@]}"; do
    restart_service "$service"
done

echo "Recovery complete!"
EOF
    sed_inplace "s|__BASE_DIR__|${BASE_DIR}|g" "$recovery_script"
    sed_inplace "s|__DEBUG_LOG__|${debug_log_path_value}|g" "$recovery_script"
    sed_inplace "s|__STATE_FILE__|${state_file_value}|g" "$recovery_script"
    chmod +x "$recovery_script"
    echo -e "${CYAN}Recovery script created: $recovery_script${NC}"
}
