#!/usr/bin/env bash

# Test runner helpers for test-all-trees.sh.

LIB_DIR="${LIB_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

if ! command -v summary_print_banner >/dev/null 2>&1; then
    if [ -f "$LIB_DIR/summary.sh" ]; then
        # shellcheck source=/dev/null
        source "$LIB_DIR/summary.sh"
    fi
fi

test_runner_print_usage() {
    cat <<'USAGE'
envctl Test Runner

Usage:
  ./test-all-trees.sh [options]

Options:
  trees=false / main=true
  tree=<n> or tree=<feature>/<iter>
  project=<name> (requires runtime map)
  projects=a,b,c (requires runtime map)
  runtime-map=/path/to/.runtime-map
  backend=false / frontend=false
  frontend-test-runner=<auto|npm|bun> (default: bun)
  parallel=false / sequential=true
  coverage=true
  --verbose / verbose=true
  --brief / --no-detailed
  --debug-verbose
  --help, -h
USAGE
}

test_runner_print_banner() {
    local line="══════════════════════════════════════════════════"
    local title="       🧪 envctl Test Runner 🧪             "
    summary_print_banner "$title" "$line" "$CYAN" 50 "$CYAN"
}

test_runner_init_config() {
    TREES_MODE=true
    RUN_COVERAGE=false
    RUN_BACKEND=true
    RUN_FRONTEND=true
    SPECIFIC_TREE=""
    SPECIFIC_PROJECT=""
    SPECIFIC_PROJECTS=()
    RUNTIME_MAP_PATH="${RUNTIME_MAP_PATH:-}"
    PARALLEL_MODE=true
    VERBOSE_MODE=false
    DETAILED_MODE=true
    DEBUG_VERBOSE=false
    FAILED_SUMMARY_MODE=true
    SHOW_HELP=false
    FRONTEND_TEST_RUNNER="${FRONTEND_TEST_RUNNER:-bun}"
}

test_runner_parse_args() {
    local arg
    for arg in "$@"; do
        case $arg in
            --help|-h|help)
                SHOW_HELP=true
                ;;
            trees=false|TREES=false)
                TREES_MODE=false
                ;;
            main=true|MAIN=true)
                TREES_MODE=false
                ;;
            coverage=true|COVERAGE=true)
                RUN_COVERAGE=true
                ;;
            backend=false|BACKEND=false)
                RUN_BACKEND=false
                ;;
            frontend=false|FRONTEND=false)
                RUN_FRONTEND=false
                ;;
            frontend-test-runner=*|FRONTEND_TEST_RUNNER=*|--frontend-test-runner=*)
                FRONTEND_TEST_RUNNER="${arg#*=}"
                ;;
            --frontend-test-runner)
                if [ -n "${2:-}" ] && [[ "${2:-}" != -* ]]; then
                    FRONTEND_TEST_RUNNER="$2"
                    shift
                fi
                ;;
            tree=*)
                SPECIFIC_TREE="${arg#tree=}"
                ;;
            project=*|PROJECT=*)
                SPECIFIC_PROJECT="${arg#*=}"
                ;;
            projects=*|PROJECTS=*)
                raw_projects="${arg#*=}"
                IFS=',' read -r -a SPECIFIC_PROJECTS <<< "$raw_projects"
                ;;
            parallel=true|PARALLEL=true)
                PARALLEL_MODE=true
                ;;
            parallel=false|PARALLEL=false|sequential=true|SEQUENTIAL=true)
                PARALLEL_MODE=false
                ;;
            verbose=true|--verbose=true|VERBOSE=true|v=true|-v|--verbose)
                VERBOSE_MODE=true
                ;;
            --debug-verbose)
                VERBOSE_MODE=true
                DEBUG_VERBOSE=true
                ;;
            detailed=true|DETAILED=true|--detailed|-d)
                DETAILED_MODE=true
                ;;
            detailed=false|DETAILED=false|--no-detailed|--brief)
                DETAILED_MODE=false
                ;;
            runtime-map=*|RUNTIME_MAP_PATH=*|--runtime-map=*)
                RUNTIME_MAP_PATH="${arg#*=}"
                ;;
        esac
    done
}

test_runner_apply_env_overrides() {
    if [ "${TREES:-}" = "false" ]; then
        TREES_MODE=false
    fi
    if [ "${MAIN:-}" = "true" ]; then
        TREES_MODE=false
    fi
    if [ "${COVERAGE:-false}" = "true" ]; then
        RUN_COVERAGE=true
    fi
    if [ "${PARALLEL:-}" = "false" ] || [ "${SEQUENTIAL:-}" = "true" ]; then
        PARALLEL_MODE=false
    fi
    if [ "${VERBOSE:-false}" = "true" ]; then
        VERBOSE_MODE=true
    fi
    if [ "${DETAILED:-}" = "false" ]; then
        DETAILED_MODE=false
    elif [ "${DETAILED:-}" = "true" ]; then
        DETAILED_MODE=true
    fi
    if [ -z "$RUNTIME_MAP_PATH" ] && [ -n "${RUNTIME_MAP:-}" ]; then
        RUNTIME_MAP_PATH="${RUNTIME_MAP}"
    fi
}

test_runner_prepare_results_dir() {
    local timestamp
    timestamp=$(date +"%Y%m%d_%H%M%S")
    RESULTS_DIR="$BASE_DIR/test-results/run_$timestamp"
    mkdir -p "$RESULTS_DIR"
    printf '\n'
    summary_print_label_value "📁 Results directory" "$RESULTS_DIR" "$BLUE"
}

test_runner_normalize_runtime_map_path() {
    local path=$1
    if [ -z "$path" ]; then
        return 1
    fi
    if [ -f "$path" ]; then
        echo "$path"
        return 0
    fi
    if [ -f "$BASE_DIR/$path" ]; then
        echo "$BASE_DIR/$path"
        return 0
    fi
    return 1
}

sanitize_project_name() {
    local name=$1
    name=${name// /_}
    name=${name//\//_}
    name=${name//\\\\/_}
    echo "$name"
}

check_runtime_health() {
    local port=$1
    local endpoint=$2
    if [ -z "$port" ]; then
        echo "missing|port not set"
        return 0
    fi
    local url="http://localhost:${port}${endpoint}"
    if curl -s -f -m 2 "$url" >/dev/null 2>&1; then
        echo "healthy|"
    else
        echo "unhealthy|health check failed (${url})"
    fi
}

evaluate_runtime_health() {
    local max_parallel="${RUN_SH_HEALTH_PARALLEL:-0}"
    if [ -n "$max_parallel" ] && [ "$max_parallel" -gt 1 ]; then
        evaluate_runtime_health_parallel "$max_parallel"
        return 0
    fi

    runtime_backend_health=()
    runtime_frontend_health=()
    runtime_backend_reason=()
    runtime_frontend_reason=()

    local project
    for project in "${runtime_projects[@]}"; do
        local backend_port="${runtime_backend_ports[$project]:-}"
        local frontend_port="${runtime_frontend_ports[$project]:-}"
        local status=""
        local reason=""

        IFS='|' read -r status reason <<< "$(check_runtime_health "$backend_port" "/api/v1/health")"
        runtime_backend_health["$project"]="$status"
        runtime_backend_reason["$project"]="$reason"

        IFS='|' read -r status reason <<< "$(check_runtime_health "$frontend_port" "/healthz")"
        runtime_frontend_health["$project"]="$status"
        runtime_frontend_reason["$project"]="$reason"
    done
}

evaluate_runtime_health_parallel() {
    local max_parallel=$1
    runtime_backend_health=()
    runtime_frontend_health=()
    runtime_backend_reason=()
    runtime_frontend_reason=()

    local tmp_dir
    tmp_dir=$(mktemp -d)
    local -A project_files=()
    local -a job_pids=()

    local project
    for project in "${runtime_projects[@]}"; do
        local safe
        safe=$(sanitize_project_name "$project")
        local out_file="${tmp_dir}/${safe}.health"
        project_files["$project"]="$out_file"

        (
            local backend_port="${runtime_backend_ports[$project]:-}"
            local frontend_port="${runtime_frontend_ports[$project]:-}"
            local status="" reason=""

            IFS='|' read -r status reason <<< "$(check_runtime_health "$backend_port" "/api/v1/health")"
            printf 'backend|%s|%s\n' "$status" "$reason" > "$out_file"

            IFS='|' read -r status reason <<< "$(check_runtime_health "$frontend_port" "/healthz")"
            printf 'frontend|%s|%s\n' "$status" "$reason" >> "$out_file"
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

    for project in "${runtime_projects[@]}"; do
        local out_file="${project_files[$project]:-}"
        if [ -z "$out_file" ] || [ ! -f "$out_file" ]; then
            continue
        fi
        local line kind status reason
        while IFS='|' read -r kind status reason; do
            case "$kind" in
                backend)
                    runtime_backend_health["$project"]="$status"
                    runtime_backend_reason["$project"]="$reason"
                    ;;
                frontend)
                    runtime_frontend_health["$project"]="$status"
                    runtime_frontend_reason["$project"]="$reason"
                    ;;
            esac
        done < "$out_file"
    done
    rm -rf "$tmp_dir"
}

test_project() {
    local name=$1
    local dir=$2
    local safe_name
    safe_name=$(sanitize_project_name "$name")

    # Convert to absolute path
    dir="$(cd "$dir" 2>/dev/null && pwd)" || dir="$dir"

    local project_log_dir="$RESULTS_DIR/${safe_name}"

    mkdir -p "$project_log_dir"

    # Only show header in sequential mode
    if [ "$PARALLEL_MODE" = false ]; then
        echo -e "\n${CYAN}=== Testing $name ===${NC}"
    fi

    local backend_result=0
    local frontend_result=0
    local has_backend=false
    local has_frontend=false
    local backend_dir=""
    local frontend_dir=""
    local backend_log=""
    local frontend_log=""
    local backend_pid=""
    local frontend_pid=""
    local backend_result_file=""
    local frontend_result_file=""
    local backend_duration_file=""
    local frontend_duration_file=""
    local backend_port="${runtime_backend_ports[$name]:-}"
    local frontend_port="${runtime_frontend_ports[$name]:-}"
    local backend_health="${runtime_backend_health[$name]:-}"
    local frontend_health="${runtime_frontend_health[$name]:-}"
    local backend_reason="${runtime_backend_reason[$name]:-}"
    local frontend_reason="${runtime_frontend_reason[$name]:-}"

    # Find backend/frontend directories first so we can run tests concurrently
    if [ "$RUN_BACKEND" = true ]; then
        backend_dir=$(find_backend_dir "$dir")
        if [ -n "$backend_dir" ]; then
            has_backend=true
            backend_log="$project_log_dir/backend_test.log"

            # Log detected directory
            if [ "$backend_dir" != "$dir/$BACKEND_DIR_NAME" ]; then
                echo -e "${BLUE}Found backend directory: $(basename "$backend_dir")${NC}"
            fi
        else
            if [ "$PARALLEL_MODE" = false ]; then
                echo -e "${YELLOW}No backend directory found${NC}"
            fi
        fi
    fi

    if [ "$RUN_FRONTEND" = true ]; then
        frontend_dir=$(find_frontend_dir "$dir")
        local debug_log=""
        if [ "$DEBUG_VERBOSE" = true ]; then
            debug_log="$project_log_dir/debug.log"
            echo "DEBUG: Looking for frontend in $dir" >> "$debug_log"
            echo "DEBUG: find_frontend_dir returned: '$frontend_dir'" >> "$debug_log"
        fi

        if [ -n "$frontend_dir" ]; then
            has_frontend=true
            frontend_log="$project_log_dir/frontend_test.log"
            if [ -n "$debug_log" ]; then
                echo "DEBUG: Frontend found at: $frontend_dir" >> "$debug_log"
            fi

            # Log detected directory
            if [ "$PARALLEL_MODE" = false ] && [ "$frontend_dir" != "$dir/$FRONTEND_DIR_NAME" ]; then
                echo -e "${BLUE}Found frontend directory: $(basename "$frontend_dir")${NC}"
            fi
        else
            if [ -n "$debug_log" ]; then
                echo "DEBUG: No frontend directory found for $name" >> "$debug_log"
            fi
            if [ "$PARALLEL_MODE" = false ]; then
                echo -e "${YELLOW}No frontend directory found${NC}"
            fi
        fi
    fi

    # Kick off tests concurrently when possible
    if [ "$has_backend" = true ]; then
        backend_result_file=$(mktemp "${TMPDIR:-/tmp}/envctl_backend_result_${safe_name}.XXXXXX")
        backend_duration_file=$(mktemp "${TMPDIR:-/tmp}/envctl_backend_duration_${safe_name}.XXXXXX")
        (
            local start_time end_time rc
            start_time=$(date +%s)
            run_backend_tests "$name" "$backend_dir" "$backend_log"
            rc=$?
            end_time=$(date +%s)
            echo "$rc" > "$backend_result_file"
            echo $((end_time - start_time)) > "$backend_duration_file"
        ) &
        backend_pid=$!
    fi
    if [ "$has_frontend" = true ]; then
        frontend_result_file=$(mktemp "${TMPDIR:-/tmp}/envctl_frontend_result_${safe_name}.XXXXXX")
        frontend_duration_file=$(mktemp "${TMPDIR:-/tmp}/envctl_frontend_duration_${safe_name}.XXXXXX")
        (
            local start_time end_time rc
            start_time=$(date +%s)
            run_frontend_tests "$name" "$frontend_dir" "$frontend_log" "$backend_port" "$backend_health" "$frontend_health" "$frontend_reason"
            rc=$?
            end_time=$(date +%s)
            echo "$rc" > "$frontend_result_file"
            echo $((end_time - start_time)) > "$frontend_duration_file"
        ) &
        frontend_pid=$!
    fi

    # Wait for backend tests
    if [ -n "$backend_pid" ]; then
        wait "$backend_pid"
        if [ -f "$backend_result_file" ]; then
            backend_result=$(cat "$backend_result_file")
        else
            backend_result=$?
        fi
        if [ -f "$backend_duration_file" ]; then
            backend_durations["$name"]=$(cat "$backend_duration_file")
        fi
        [ -n "$backend_result_file" ] && rm -f "$backend_result_file"
        [ -n "$backend_duration_file" ] && rm -f "$backend_duration_file"
        read b_passed b_failed < <(extract_test_counts "$backend_log")
        backend_passed_counts["$name"]=$b_passed
        backend_failed_counts["$name"]=$b_failed

        if [ "$PARALLEL_MODE" = false ]; then
            local backend_duration_str=""
            if [ -n "${backend_durations[$name]:-}" ]; then
                backend_duration_str=" in $(format_duration ${backend_durations[$name]})"
            fi
            if [ $backend_result -eq 0 ]; then
                echo -e "${GREEN}✓ Backend tests passed${NC} (${GREEN}$b_passed passed${NC})${backend_duration_str}"
            elif [ $backend_result -eq 2 ]; then
                echo -e "${YELLOW}⚠ Backend tests skipped (no test runner found)${NC}"
            else
                echo -e "${RED}✗ Backend tests failed${NC} (${GREEN}$b_passed passed${NC}, ${RED}$b_failed failed${NC})${backend_duration_str}"
                echo -e "${YELLOW}Check logs at: $backend_log${NC}"
            fi
        fi
    fi

    # Wait for frontend tests
    if [ -n "$frontend_pid" ]; then
        wait "$frontend_pid"
        if [ -f "$frontend_result_file" ]; then
            frontend_result=$(cat "$frontend_result_file")
        else
            frontend_result=$?
        fi
        if [ -f "$frontend_duration_file" ]; then
            frontend_durations["$name"]=$(cat "$frontend_duration_file")
        fi
        [ -n "$frontend_result_file" ] && rm -f "$frontend_result_file"
        [ -n "$frontend_duration_file" ] && rm -f "$frontend_duration_file"
        read f_passed f_failed < <(extract_test_counts "$frontend_log")
        frontend_passed_counts["$name"]=$f_passed
        frontend_failed_counts["$name"]=$f_failed

        if [ "$PARALLEL_MODE" = false ]; then
            local frontend_duration_str=""
            if [ -n "${frontend_durations[$name]:-}" ]; then
                frontend_duration_str=" in $(format_duration ${frontend_durations[$name]})"
            fi
            if [ $frontend_result -eq 0 ]; then
                echo -e "${GREEN}✓ Frontend tests passed${NC} (${GREEN}$f_passed passed${NC})${frontend_duration_str}"
            elif [ $frontend_result -eq 2 ]; then
                echo -e "${YELLOW}⚠ Frontend tests skipped (no test runner found)${NC}"
            elif [ $frontend_result -eq 3 ]; then
                echo -e "${YELLOW}⚠ Frontend tests skipped (frontend unhealthy)${NC}"
            else
                echo -e "${RED}✗ Frontend tests failed${NC} (${GREEN}${f_passed:-0} passed${NC}, ${RED}${f_failed:-0} failed${NC})${frontend_duration_str}"
                echo -e "${YELLOW}Check logs at: $frontend_log${NC}"
            fi
        fi
    fi

    if [ -n "$backend_result_file" ]; then
        rm -f "$backend_result_file" "$backend_duration_file"
    fi
    if [ -n "$frontend_result_file" ]; then
        rm -f "$frontend_result_file" "$frontend_duration_file"
    fi

    # Determine overall result
    if [ "$has_backend" = false ] && [ "$has_frontend" = false ]; then
        echo -e "${YELLOW}⚠ No testable projects found in $name${NC}"
        skipped_tests+=("$name")
        return 2
    fi

    if [ -z "${backend_result:-}" ]; then
        backend_result=0
    fi
    if [ -z "${frontend_result:-}" ]; then
        frontend_result=0
    fi

    # Count skipped as success if no actual failures
    if [ $backend_result -eq 2 ]; then
        backend_result=0
    fi
    if [ $frontend_result -eq 2 ] || [ $frontend_result -eq 3 ]; then
        frontend_result=0
    fi

    if [ $backend_result -eq 0 ] && [ $frontend_result -eq 0 ]; then
        if [ "$PARALLEL_MODE" = false ]; then
            echo -e "${GREEN}✓ All tests passed for $name${NC}"
        fi
        passed_tests+=("$name")
        return 0
    else
        if [ "$PARALLEL_MODE" = false ]; then
            echo -e "${RED}✗ Tests failed for $name${NC}"
        fi
        failed_tests+=("$name")
        return 1
    fi
}

test_project_parallel() {
    local name=$1
    local dir=$2
    local safe_name
    safe_name=$(sanitize_project_name "$name")

    # Record start time
    test_start_times["$name"]=$(date +%s)

    (
        start_time=$(date +%s)
        test_project "$name" "$dir" > "$RESULTS_DIR/.${safe_name}_output" 2>&1
        result=$?
        end_time=$(date +%s)
        duration=$((end_time - start_time))

        # Save result and duration
        echo $result > "$RESULTS_DIR/.${safe_name}_result"
        echo $duration > "$RESULTS_DIR/.${safe_name}_duration"

        # Save backend and frontend durations if they exist
        # Note: These arrays are populated in test_project function
        if [ -f "$RESULTS_DIR/${safe_name}/backend_test.log" ] && [ -n "${backend_durations[$name]:-}" ]; then
            echo ${backend_durations[$name]} > "$RESULTS_DIR/.${safe_name}_backend_duration"
        fi
        if [ -f "$RESULTS_DIR/${safe_name}/frontend_test.log" ] && [ -n "${frontend_durations[$name]:-}" ]; then
            echo ${frontend_durations[$name]} > "$RESULTS_DIR/.${safe_name}_frontend_duration"
        fi
    ) &

    test_pids+=($!)
}

cache_project_results() {
    local name=$1
    [ -n "$name" ] || return 0
    if [ "${parsed_projects[$name]:-}" = "1" ]; then
        return 0
    fi
    parsed_projects["$name"]=1

    local safe_name
    safe_name=$(sanitize_project_name "$name")
    local log_dir="$RESULTS_DIR/${safe_name}"
    local backend_log="${log_dir}/backend_test.log"
    local frontend_log="${log_dir}/frontend_test.log"
    local backend_list_count=0
    local frontend_list_count=0

    if [ -f "$backend_log" ]; then
        read b_passed b_failed < <(extract_test_counts "$backend_log")
        backend_passed_counts["$name"]=$b_passed
        backend_failed_counts["$name"]=$b_failed

        if [ "$DETAILED_MODE" = true ] || [ "$FAILED_SUMMARY_MODE" = true ] || [ "$VERBOSE_MODE" = true ]; then
            backend_failed_tests["$name"]=$(extract_failed_test_names "$backend_log")
            backend_list_count=$(count_list_entries "${backend_failed_tests[$name]:-}")
            if [ "$backend_list_count" -gt 0 ]; then
                backend_failed_counts["$name"]=$backend_list_count
            fi
        fi

        if [ "$backend_list_count" -gt 0 ] && { [ "$VERBOSE_MODE" = true ] || [ "$FAILED_SUMMARY_MODE" = true ]; }; then
            extract_pytest_errors "$backend_log" "$name"
        fi
    fi

    if [ -f "$frontend_log" ]; then
        read f_passed f_failed < <(extract_test_counts "$frontend_log")
        frontend_passed_counts["$name"]=$f_passed
        frontend_failed_counts["$name"]=$f_failed

        local capture_errors=false
        if [ "$VERBOSE_MODE" = true ] || [ "$FAILED_SUMMARY_MODE" = true ]; then
            capture_errors=true
        fi
        if [ "$DETAILED_MODE" = true ] || [ "$FAILED_SUMMARY_MODE" = true ] || [ "$VERBOSE_MODE" = true ]; then
            extract_frontend_failures "$frontend_log" "$name" "$capture_errors"
        else
            extract_frontend_failures "$frontend_log" "$name" "false"
        fi

        frontend_list_count=$(count_list_entries "${frontend_failed_tests[$name]:-}")
        if [ "$frontend_list_count" -gt 0 ]; then
            frontend_failed_counts["$name"]=$frontend_list_count
        fi
    fi
}

show_progress() {
    local current=$1
    local total=$2
    local width=50
    local percentage=$((current * 100 / total))
    local completed=$((width * current / total))

    printf "\rProgress: ["
    printf "%${completed}s" | tr ' ' '='
    printf "%$((width - completed))s" | tr ' ' ' '
    printf "] %d%% (%d/%d)" $percentage $current $total
}
