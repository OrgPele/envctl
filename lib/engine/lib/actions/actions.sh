#!/usr/bin/env bash

# Shared command execution for interactive and non-interactive modes.

actions_trim() {
    local value=${1:-}
    if command -v trim >/dev/null 2>&1; then
        trim "$value"
        return 0
    fi
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    printf '%s' "$value"
}

actions_is_truthy() {
    local value
    value=$(actions_trim "${1:-}")
    case "$value" in
        1|true|TRUE|yes|YES|y|Y)
            return 0
            ;;
    esac
    return 1
}

list_commands() {
    cat <<'COMMANDS'
start
plan
resume
dashboard
config
doctor
debug-pack
debug-report
debug-last
delete-worktree
blast-worktree
stop
restart
stop-all
blast-all
test
pr
commit
analyze
migrate
logs
clear-logs
health
errors
list-commands
list-targets
list-trees
show-config
show-state
explain-startup
help
COMMANDS
}

list_command_targets() {
    echo "all"
    echo "untested"
    if command -v get_project_names >/dev/null 2>&1; then
        get_project_names | sed 's/^/project:/'
    fi
    if command -v get_service_names >/dev/null 2>&1; then
        get_service_names | sed 's/^/service:/'
    fi
}

parse_command_targets() {
    local -n out=$1
    shift
    out=()

    local raw
    for raw in "$@"; do
        local value
        value=$(actions_trim "$raw")
        [ -n "$value" ] || continue
        case "$value" in
            __ALL__|__UNTESTED__|__PROJECT__:*|__SERVICE__:*)
                out+=("$value")
                ;;
            all)
                out+=("__ALL__")
                ;;
            untested)
                out+=("__UNTESTED__")
                ;;
            project:*)
                out+=("__PROJECT__:${value#project:}")
                ;;
            service:*)
                out+=("__SERVICE__:${value#service:}")
                ;;
            *)
                out+=("$value")
                ;;
        esac
    done
}

validate_command_targets() {
    local -a targets=("$@")
    local -a errors=()
    local -a project_names=()
    local -a service_names=()
    local project_loaded=false
    local service_loaded=false

    if command -v get_project_names >/dev/null 2>&1; then
        mapfile -t project_names < <(get_project_names)
        project_loaded=true
    fi
    if command -v get_service_names >/dev/null 2>&1; then
        mapfile -t service_names < <(get_service_names)
        service_loaded=true
    fi

    local target
    for target in "${targets[@]}"; do
        case "$target" in
            __PROJECT__:*)
                if [ "$project_loaded" = true ]; then
                    local project_name="${target#__PROJECT__:}"
                    if [ -n "$project_name" ] && ! printf '%s\n' "${project_names[@]}" | grep -Fxq "$project_name"; then
                        errors+=("Unknown project: $project_name")
                    fi
                fi
                ;;
            __SERVICE__:*)
                if [ "$service_loaded" = true ]; then
                    local service_name="${target#__SERVICE__:}"
                    if [ -n "$service_name" ] && ! printf '%s\n' "${service_names[@]}" | grep -Fxq "$service_name"; then
                        errors+=("Unknown service: $service_name")
                    fi
                fi
                ;;
        esac
    done

    if [ ${#errors[@]} -gt 0 ]; then
        local err
        for err in "${errors[@]}"; do
            if command -v log_error >/dev/null 2>&1; then
                log_error "$err"
            else
                printf '%s\n' "$err" >&2
            fi
        done
        return 1
    fi

    return 0
}

doctor_check_port() {
    local port=$1
    local listeners
    listeners=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
    if [ -n "$listeners" ]; then
        echo -e "${YELLOW}Port ${port} is in use:${NC}"
        echo "$listeners"
        echo "Repair: lsof -nP -iTCP:${port} -sTCP:LISTEN"
        return 1
    fi
    echo -e "${GREEN}Port ${port} is free.${NC}"
    return 0
}

doctor_collect_state_pointers() {
    collect_all_state_pointers
}

doctor_check_state_orphans() {
    local state_file=$1
    local missing=0
    local pid
    while IFS= read -r pid; do
        [ -n "$pid" ] || continue
        if ! kill -0 "$pid" 2>/dev/null; then
            echo -e "${YELLOW}Stale PID in state ${state_file}: ${pid}${NC}"
            missing=1
        fi
    done < <(bash -c 'source "$1" 2>/dev/null || exit 0; printf "%s\n" "${pids[@]}"' _ "$state_file" 2>/dev/null || true)
    return $missing
}

run_doctor() {
    local issues=0
    local logs_dir=""
    if command -v state_pointer_dir >/dev/null 2>&1; then
        logs_dir=$(state_pointer_dir)
    fi
    if [ -z "$logs_dir" ]; then
        logs_dir="${RUN_SH_RUNTIME_DIR:-/tmp/envctl-runtime}"
    fi

    echo -e "${CYAN}envctl Doctor${NC}"
    echo -e "${CYAN}=================${NC}"

    echo -e "
${BLUE}Ports${NC}"
    local port
    for port in 5432 54321 8000 9000; do
        if ! doctor_check_port "$port"; then
            issues=$((issues + 1))
        fi
    done

    echo -e "
${BLUE}OpenCode lock files${NC}"
    local lock_dir="$HOME/.openclaw/agents/opencode/sessions"
    local lock_found=false
    local lock_file
    for lock_file in "$lock_dir"/*.jsonl.lock; do
        [ -e "$lock_file" ] || continue
        lock_found=true
        issues=$((issues + 1))
        echo -e "${YELLOW}Lock present:${NC} $lock_file"
        sed 's/^/  /' "$lock_file" 2>/dev/null || true
    done
    if [ "$lock_found" = false ]; then
        echo -e "${GREEN}No lock files found.${NC}"
    else
        echo "Repair: ~/.openclaw/workspace-opencode/skills/kfir-code/bin/recover_opencode_locks.sh agent:opencode:main 60 true"
    fi

    echo -e "
${BLUE}State pointers${NC}"
    local pointers=()
    local ptr
    while IFS= read -r ptr; do
        [ -n "$ptr" ] && pointers+=("$ptr")
    done < <(doctor_collect_state_pointers)

    if [ ${#pointers[@]} -eq 0 ]; then
        echo -e "${YELLOW}No state pointers found under ${logs_dir}.${NC}"
        echo "Repair: start an interactive run and quit with q to persist state"
    fi

    local valid_states=0
    local state_file
    for ptr in "${pointers[@]}"; do
        state_file=$(cat "$ptr" 2>/dev/null || true)
        if [ -n "$state_file" ] && [ -f "$state_file" ]; then
            echo -e "${GREEN}OK:${NC} ${ptr} -> ${state_file}"
            valid_states=$((valid_states + 1))
            if doctor_check_state_orphans "$state_file"; then
                :
            else
                issues=$((issues + 1))
                echo "Repair: envctl --resume --command restart --all --load-state --skip-startup"
            fi
        else
            issues=$((issues + 1))
            echo -e "${YELLOW}Broken pointer:${NC} ${ptr} -> ${state_file}"
            echo "Repair: rm -f "${ptr}""
        fi
    done

    echo -e "
${BLUE}Potential orphan dev processes${NC}"
    local orphan_lines
    orphan_lines=$(ps -ax -o pid=,command= | grep -E 'uvicorn app.main:app|vite --port|npm run dev|bun run dev' | grep -v 'grep -E' || true)
    if [ -n "$orphan_lines" ] && [ "$valid_states" -eq 0 ]; then
        issues=$((issues + 1))
        echo -e "${YELLOW}Dev processes running without valid state pointers:${NC}"
        echo "$orphan_lines"
        echo "Repair: envctl --force --batch"
    else
        echo -e "${GREEN}No obvious orphan process issue detected.${NC}"
    fi

    echo -e "
${CYAN}Doctor summary:${NC} issues=${issues}"
    if [ "$issues" -gt 0 ]; then
        return 1
    fi
    return 0
}

dashboard_extract_host_ports() {
    local ports_field=${1:-}
    [ -n "$ports_field" ] || return 0

    local csv=""
    local port=""
    while IFS= read -r port; do
        [ -n "$port" ] || continue
        case ",${csv}," in
            *",${port},"*)
                continue
                ;;
        esac
        if [ -z "$csv" ]; then
            csv="$port"
        else
            csv="${csv},${port}"
        fi
    done < <(printf '%s\n' "$ports_field" | grep -oE ':[0-9]+->' | sed -E 's/^:([0-9]+)->$/\1/')

    [ -n "$csv" ] && printf '%s\n' "$csv"
}

dashboard_is_data_container() {
    local name_lc=${1:-}
    local image_lc=${2:-}
    case "$image_lc" in
        *redis*|*postgres*|*postgis*|*mysql*|*mariadb*|*mongo*)
            return 0
            ;;
    esac
    case "$name_lc" in
        *redis*|*postgres*|*supabase-db*|*database*|*db-1)
            return 0
            ;;
    esac
    return 1
}

dashboard_connection_targets() {
    local name=${1:-}
    local image=${2:-}
    local ports_field=${3:-}
    local name_lc
    name_lc=$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]')
    local image_lc
    image_lc=$(printf '%s' "$image" | tr '[:upper:]' '[:lower:]')
    local host_ports_csv=""
    host_ports_csv=$(dashboard_extract_host_ports "$ports_field")
    if [ -z "$host_ports_csv" ]; then
        echo "internal-only"
        return 0
    fi

    local targets=""
    local port=""
    IFS=',' read -r -a _ports <<< "$host_ports_csv"
    for port in "${_ports[@]}"; do
        [ -n "$port" ] || continue
        local target="localhost:${port}"
        if ! dashboard_is_data_container "$name_lc" "$image_lc"; then
            case "$name_lc" in
                *n8n*|*backend*|*frontend*|*-api-*|api-*|*-api|*web*|*ui*|*kong*|*auth*|*proxy*)
                    target="http://localhost:${port}"
                    ;;
                *)
                    case "$port" in
                        80|3000|5173|8080|9000|9001|9020|9040)
                            target="http://localhost:${port}"
                            ;;
                        443)
                            target="https://localhost:${port}"
                            ;;
                    esac
                    ;;
            esac
        fi
        if [ -z "$targets" ]; then
            targets="$target"
        else
            targets="${targets},${target}"
        fi
    done

    printf '%s\n' "$targets"
}

dashboard_http_endpoint_candidates() {
    local name_lc=${1:-}
    local image_lc=${2:-}
    if dashboard_is_data_container "$name_lc" "$image_lc"; then
        return 0
    fi
    case "$name_lc" in
        *backend*|*-api-*|api-*|*-api)
            printf '%s\n' "/api/v1/health" "/health" "/docs"
            ;;
        *frontend*|*web*|*ui*|*vite*)
            printf '%s\n' "/healthz" "/"
            ;;
        *n8n*)
            printf '%s\n' "/healthz"
            ;;
        *kong*|*auth*|*proxy*)
            printf '%s\n' "/health"
            ;;
        *)
            printf '%s\n' "/healthz" "/health"
            ;;
    esac
}

dashboard_http_probe_status() {
    local name=${1:-}
    local image=${2:-}
    local connect_targets=${3:-}
    if ! command -v curl >/dev/null 2>&1; then
        echo "n/a (curl unavailable)"
        return 0
    fi

    local name_lc
    name_lc=$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]')
    local image_lc
    image_lc=$(printf '%s' "$image" | tr '[:upper:]' '[:lower:]')
    local target=""
    IFS=',' read -r -a _targets <<< "$connect_targets"
    for target in "${_targets[@]}"; do
        [ -n "$target" ] || continue
        case "$target" in
            http://*|https://*)
                local endpoint=""
                while IFS= read -r endpoint; do
                    [ -n "$endpoint" ] || continue
                    local code=""
                    code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 1 --max-time 2 "${target}${endpoint}" || true)
                    if [[ "$code" =~ ^2[0-9][0-9]$ ]] || [[ "$code" =~ ^3[0-9][0-9]$ ]]; then
                        echo "ok (${code} ${endpoint})"
                        return 0
                    fi
                done < <(dashboard_http_endpoint_candidates "$name_lc" "$image_lc")
                echo "down (${code:-000})"
                return 0
                ;;
        esac
    done

    echo "n/a"
}

dashboard_show_docker_containers() {
    echo -e "${CYAN}Running Docker Containers:${NC}"
    echo -e "${CYAN}========================================${NC}"

    if ! command -v docker >/dev/null 2>&1; then
        echo -e "${YELLOW}Docker CLI not found.${NC}"
        echo
        return 0
    fi

    if [ "$(type -t docker_probe)" = "function" ]; then
        if ! docker_probe info >/dev/null 2>&1; then
            local socket_state="unknown"
            if [ "$(type -t docker_socket_state)" = "function" ]; then
                socket_state=$(docker_socket_state)
            fi
            echo -e "${YELLOW}Docker daemon unavailable (socket:${socket_state}).${NC}"
            echo
            return 0
        fi
    else
        if ! docker info >/dev/null 2>&1; then
            echo -e "${YELLOW}Docker daemon unavailable.${NC}"
            echo
            return 0
        fi
    fi

    local ps_rows=""
    if [ "$(type -t docker_cmd)" = "function" ]; then
        ps_rows=$(docker_cmd ps --format '{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || true)
    else
        ps_rows=$(docker ps --format '{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || true)
    fi

    if [ -z "$ps_rows" ]; then
        echo -e "${YELLOW}No running Docker containers.${NC}"
        echo
        return 0
    fi

    local total=0
    local healthy=0
    local unhealthy=0
    local running=0
    local other=0
    local row=""

    local -A container_connect_targets=()
    local -a container_names_ordered=()
    local -A container_details=()

    while IFS= read -r row; do
        [ -n "$row" ] || continue
        local cid="" name="" image="" status="" ports=""
        IFS=$'\t' read -r cid name image status ports <<< "$row"
        [ -n "$name" ] || continue
        total=$((total + 1))
        container_names_ordered+=("$name")

        local icon="${YELLOW}~${NC}"
        local health="unknown"
        case "$status" in
            *"(healthy)"*)
                icon="${GREEN}✓${NC}"
                health="healthy"
                healthy=$((healthy + 1))
                ;;
            *"(unhealthy)"*)
                icon="${RED}✗${NC}"
                health="unhealthy"
                unhealthy=$((unhealthy + 1))
                ;;
            Up*)
                icon="${GREEN}✓${NC}"
                health="running"
                running=$((running + 1))
                ;;
            *)
                other=$((other + 1))
                ;;
        esac

        local connect_targets=""
        connect_targets=$(dashboard_connection_targets "$name" "$image" "$ports")
        container_connect_targets["$name"]="$connect_targets"

        local details="  ${icon} ${name}\n"
        details+="    image: ${image}\n"
        details+="    status: ${status}\n"
        details+="    health: ${health}\n"
        if [ -n "$ports" ]; then
            details+="    ports: ${ports}\n"
        else
            details+="    ports: internal-only\n"
        fi
        details+="    connect: ${connect_targets}\n"
        container_details["$name"]="$details"
    done <<< "$ps_rows"

    local tmp_dir
    tmp_dir=$(mktemp -d)
    local -a job_pids=()
    local -A service_files=()

    local name=""
    for name in "${container_names_ordered[@]}"; do
        local targets="${container_connect_targets[$name]:-}"
        local out_file="${tmp_dir}/${name}.probe"
        service_files["$name"]="$out_file"

        (
            dashboard_http_probe_status "$name" "" "$targets" > "$out_file"
        ) &
        job_pids+=("$!")
    done

    # Wait for all background probes to finish
    local pid
    for pid in "${job_pids[@]}"; do
        wait "$pid" 2>/dev/null || true
    done

    for name in "${container_names_ordered[@]}"; do
        local details="${container_details[$name]}"
        local out_file="${service_files[$name]}"
        local probe_status="n/a"
        if [ -f "$out_file" ]; then
            probe_status=$(cat "$out_file")
        fi

        # Print details plus the probe_status and shell command
        echo -e "${details}    http: ${probe_status}\n    shell: docker exec -it ${name} sh"
    done

    rm -rf "$tmp_dir"

    echo
    echo -e "${CYAN}Docker Summary:${NC} total=${total}, healthy=${healthy}, unhealthy=${unhealthy}, running(no healthcheck)=${running}, other=${other}"
    echo
}

run_dashboard() {
    local previous_run_hints_mode="${RUN_SH_STATUS_SHOW_RUN_HINTS-__unset__}"
    local previous_run_all_hints_mode="${RUN_SH_STATUS_SHOW_RUN_ALL_HINTS-__unset__}"

    if [ ${#services[@]} -eq 0 ] && [ ${#service_info[@]} -eq 0 ]; then
        if [ "$(type -t load_state_for_dashboard)" = "function" ]; then
            load_state_for_dashboard >/dev/null 2>&1 || true
        elif [ "$(type -t load_state_for_command)" = "function" ]; then
            load_state_for_command >/dev/null 2>&1 || true
        fi
    fi

    if [ ${#services[@]} -gt 0 ] || [ ${#service_info[@]} -gt 0 ]; then
        # Keep dashboard health rendering identical to run/resume interactive mode.
        RUN_SH_STATUS_SHOW_RUN_HINTS=true
        if [ "${RUN_SH_COMMAND_DASHBOARD_INTERACTIVE:-false}" = true ] && [ "${INTERACTIVE_MODE:-false}" = true ]; then
            RUN_SH_STATUS_SHOW_RUN_ALL_HINTS=false
        fi
        show_status false
    else
        echo -e "${YELLOW}No tracked app services available in state.${NC}"
        echo
    fi

    if [ "$previous_run_hints_mode" = "__unset__" ]; then
        unset RUN_SH_STATUS_SHOW_RUN_HINTS
    else
        RUN_SH_STATUS_SHOW_RUN_HINTS="$previous_run_hints_mode"
    fi
    if [ "$previous_run_all_hints_mode" = "__unset__" ]; then
        unset RUN_SH_STATUS_SHOW_RUN_ALL_HINTS
    else
        RUN_SH_STATUS_SHOW_RUN_ALL_HINTS="$previous_run_all_hints_mode"
    fi
}

list_worktree_paths_for_delete() {
    if [ "$(type -t list_tree_paths)" != "function" ]; then
        return 1
    fi

    local base_dir="${BASE_DIR:-.}"
    local trees_dir_name="${TREES_DIR_NAME:-trees}"
    local -a paths=()
    local path
    while IFS= read -r path; do
        [ -n "$path" ] || continue
        path="${path%/}"
        [ -d "$path" ] || continue
        if [ -n "${BASE_DIR:-}" ] && [ "$path" = "${BASE_DIR%/}" ]; then
            continue
        fi
        paths+=("$path")
    done < <(list_tree_paths "$base_dir" "$trees_dir_name")

    if [ ${#paths[@]} -eq 0 ]; then
        return 0
    fi

    local -A seen=()
    local -a unique_paths=()
    for path in "${paths[@]}"; do
        if [ -n "${seen[$path]:-}" ]; then
            continue
        fi
        seen[$path]=1
        unique_paths+=("$path")
    done
    printf '%s\n' "${unique_paths[@]}" | sort
}

worktree_delete_label_for_path() {
    local path=$1
    local rel="$path"
    if [ -n "${BASE_DIR:-}" ]; then
        rel="${path#${BASE_DIR%/}/}"
    fi

    local identity=""
    if [ "$(type -t worktree_identity_from_dir)" = "function" ]; then
        identity=$(worktree_identity_from_dir "$path" "${BASE_DIR:-}" "${TREES_DIR_NAME:-trees}" 2>/dev/null || true)
    fi

    if [ -n "$identity" ]; then
        local feature="${identity%%|*}"
        local iter="${identity#*|}"
        printf '%s\n' "${feature}_${iter} (${rel})"
        return 0
    fi

    printf '%s\n' "$rel"
}

run_worktree_delete_command() {
    if [ "$(type -t delete_worktrees_for_paths)" != "function" ]; then
        echo -e "${RED:-}Worktree deletion helpers are unavailable.${NC:-}"
        return 1
    fi

    local -a worktree_paths=()
    while IFS= read -r path; do
        [ -n "$path" ] && worktree_paths+=("$path")
    done < <(list_worktree_paths_for_delete)

    if [ ${#worktree_paths[@]} -eq 0 ]; then
        echo -e "${YELLOW:-}No worktrees found to delete.${NC:-}"
        return 0
    fi

    local delete_mode=""
    local target
    for target in "$@"; do
        case "$target" in
            __ALL__)
                delete_mode="all"
                ;;
        esac
    done

    if [ -z "$delete_mode" ]; then
        if [ "$(type -t select_menu)" != "function" ]; then
            echo -e "${RED:-}Interactive menu helpers are unavailable.${NC:-}"
            return 1
        fi
        local can_interactive=false
        if [ "$(type -t ui_can_interactive)" = "function" ]; then
            if ui_can_interactive; then
                can_interactive=true
            fi
        elif [ -t 0 ] && [ -t 1 ]; then
            can_interactive=true
        fi
        if [ "$can_interactive" != true ]; then
            echo -e "${RED:-}Worktree deletion requires an interactive TTY.${NC:-}"
            echo -e "${YELLOW:-}Tip: run 'envctl delete-worktree --all' to skip the selector menu.${NC:-}"
            return 1
        fi

        local -a mode_options=(
            "Delete one worktree"
            "Delete all worktrees"
            "Cancel"
        )
        local -a mode_values=(
            "one"
            "all"
            "cancel"
        )
        local selected_mode=""
        selected_mode=$(select_menu "Worktree cleanup" mode_options mode_values) || {
            echo -e "${YELLOW:-}Deletion cancelled.${NC:-}"
            return 0
        }
        case "$selected_mode" in
            all)
                delete_mode="all"
                ;;
            one)
                delete_mode="one"
                ;;
            *)
                echo -e "${YELLOW:-}Deletion cancelled.${NC:-}"
                return 0
                ;;
        esac
    fi

    case "$delete_mode" in
        all)
            delete_worktrees_for_paths "all worktrees" "${worktree_paths[@]}"
            return $?
            ;;
        one)
            local -a path_options=()
            local -a path_values=()
            local path=""
            for path in "${worktree_paths[@]}"; do
                path_options+=("$(worktree_delete_label_for_path "$path")")
                path_values+=("$path")
            done
            local selected_path=""
            selected_path=$(select_menu "Select worktree to delete" path_options path_values) || {
                echo -e "${YELLOW:-}Deletion cancelled.${NC:-}"
                return 0
            }
            if [ -z "$selected_path" ]; then
                echo -e "${YELLOW:-}Deletion cancelled.${NC:-}"
                return 0
            fi
            delete_worktrees_for_paths "selected worktree" "$selected_path"
            return $?
            ;;
        *)
            echo -e "${RED:-}Unknown worktree delete mode: ${delete_mode}${NC:-}"
            return 1
            ;;
    esac
}

run_command() {
    local cmd_raw=$1
    shift || true
    local -a targets=("$@")

    local cmd
    cmd=$(actions_trim "$cmd_raw")
    cmd="${cmd,,}"

    case "$cmd" in
        delete-worktree|delete-worktrees|remove-worktrees|blast-worktree|blast-worktrees)
            run_worktree_delete_command "${targets[@]}"
            return $?
            ;;
        s|stop)
            SKIP_CLEANUP=false
            CLEANUP_DB_MODE="preserve"
            CLEANUP_STOP_INFRA=false
            REMOVE_DB_VOLUMES=false
            CLEANUP_KILL_PORT_RANGES=false
            CLEANUP_SCOPE_STATE_ONLY=false
            echo -e "${YELLOW}Stopping app services (databases preserved)...${NC}"
            cleanup
            if [ "$cmd_raw" = "stop" ]; then
                return 3
            fi
            return 0
            ;;
        stop-all|stopall)
            if [ ${#services[@]} -eq 0 ] && [ ${#service_info[@]} -eq 0 ] && [ "$(type -t load_state_for_command)" = "function" ]; then
                load_state_for_command >/dev/null 2>&1 || true
            fi
            SKIP_CLEANUP=false
            CLEANUP_DB_MODE="all"
            CLEANUP_STOP_INFRA=true
            REMOVE_DB_VOLUMES=false
            CLEANUP_KILL_PORT_RANGES="${RUN_SH_STOP_ALL_KILL_PORT_RANGES:-false}"
            CLEANUP_SCOPE_STATE_ONLY=true
            local remove_volumes="${RUN_SH_COMMAND_STOP_ALL_REMOVE_VOLUMES:-}"
            if [ "${INTERACTIVE_MODE:-false}" = true ] && [ -z "$remove_volumes" ]; then
                if prompt_yes_no "Remove database containers and volumes? (y/N): "; then
                    remove_volumes=true
                fi
            fi
            if actions_is_truthy "$remove_volumes"; then
                CLEANUP_DB_MODE="remove-volumes"
                REMOVE_DB_VOLUMES=true
            fi
            echo -e "${YELLOW}Stopping all services and databases...${NC}"
            cleanup
            return 0
            ;;
        blast-all)
            SKIP_CLEANUP=true
            cleanup_blast_all
            return 0
            ;;
        r|restart)
            if [ ${#targets[@]} -eq 0 ]; then
                echo -e "${RED}No restart target selected.${NC}"
                return 1
            fi
            local restart_all=false
            local target
            for target in "${targets[@]}"; do
                case "$target" in
                    __ALL__)
                        restart_all=true
                        ;;
                    __PROJECT__:*)
                        local project_name="${target#__PROJECT__:}"
                        [ -n "$project_name" ] && restart_project "$project_name"
                        ;;
                    __SERVICE__:*)
                        local service_name="${target#__SERVICE__:}"
                        [ -n "$service_name" ] && restart_service "$service_name"
                        ;;
                    *)
                        [ -n "$target" ] && restart_service "$target"
                        ;;
                esac
            done
            if [ "$restart_all" = true ]; then
                local services_copy=("${services[@]}")
                local reload_count=0
                local total_services=${#services_copy[@]}
                local service
                for service in "${services_copy[@]}"; do
                    parse_service_entry "$service" name url docs || continue
                    ((reload_count++))
                    echo -e "\n${CYAN}[$reload_count/$total_services] Restarting $name...${NC}"
                    restart_service "$name"
                    sleep 1
                done
                echo -e "\n${GREEN}✓ All services restarted${NC}"
            fi
            if command -v write_runtime_map >/dev/null 2>&1; then
                write_runtime_map
            fi
            return 0
            ;;
        t|test|tests)
            if [ ${#targets[@]} -eq 0 ]; then
                echo -e "${RED}No test target selected.${NC}"
                return 1
            fi
            local test_script="$BASE_DIR/utils/test-all-trees.sh"
            if [ ! -f "$test_script" ]; then
                echo -e "${RED}test-all-trees.sh not found at $test_script${NC}"
                return 3
            fi
            if command -v write_runtime_map >/dev/null 2>&1; then
                write_runtime_map
            fi
            local runtime_map
            runtime_map=$(runtime_map_path 2>/dev/null || true)
            local -a test_args=()
            if [ -n "$runtime_map" ] && [ -f "$runtime_map" ]; then
                test_args+=("runtime-map=$runtime_map")
            fi
            if [ -n "${FRONTEND_TEST_RUNNER:-}" ]; then
                test_args+=("frontend-test-runner=$FRONTEND_TEST_RUNNER")
            fi

            local use_all=false
            local use_untested=false
            local -a selected_projects=()
            local target
            for target in "${targets[@]}"; do
                case "$target" in
                    __ALL__)
                        use_all=true
                        ;;
                    __UNTESTED__)
                        use_untested=true
                        ;;
                    __PROJECT__:*)
                        selected_projects+=("${target#__PROJECT__:}")
                        ;;
                    *)
                        ;;
                esac
            done

            if [ "$use_all" = true ]; then
                (cd "$BASE_DIR" && bash "$test_script" "${test_args[@]}")
                return 0
            fi

            if [ "$use_untested" = true ]; then
                local untested_projects=()
                while IFS= read -r project; do
                    [ -n "$project" ] && untested_projects+=("$project")
                done < <(list_untested_projects)
                if [ ${#untested_projects[@]} -eq 0 ]; then
                    echo -e "${YELLOW}No untested projects available.${NC}"
                    return 3
                fi
                selected_projects+=("${untested_projects[@]}")
            fi

            if [ ${#selected_projects[@]} -gt 0 ]; then
                local unique_projects=()
                local seen="|"
                local proj
                for proj in "${selected_projects[@]}"; do
                    [ -n "$proj" ] || continue
                    if [[ "$seen" != *"|$proj|"* ]]; then
                        unique_projects+=("$proj")
                        seen+="$proj|"
                    fi
                done
                if [ ${#unique_projects[@]} -gt 0 ]; then
                    local projects_arg
                    projects_arg=$(IFS=','; echo "${unique_projects[*]}")
                    test_args+=("projects=$projects_arg")
                fi
            fi

            (cd "$BASE_DIR" && bash "$test_script" "${test_args[@]}")
            return 0
            ;;
        p|pr|prs)
            if [ ${#targets[@]} -eq 0 ]; then
                echo -e "${RED}No PR target selected.${NC}"
                return 1
            fi
            local -a pr_paths=()
            local show_summary=false
            local target
            for target in "${targets[@]}"; do
                case "$target" in
                    __ALL__)
                        show_summary=true
                        local project
                        while IFS= read -r project; do
                            [ -z "$project" ] && continue
                            local root
                            root=$(project_root_from_project_name "$project" 2>/dev/null || true)
                            if [ -n "$root" ]; then
                                pr_paths+=("$root")
                            else
                                echo -e "${YELLOW}No worktree root found for ${project}${NC}"
                            fi
                        done < <(get_project_names)
                        ;;
                    __PROJECT__:*)
                        local project_name="${target#__PROJECT__:}"
                        local root
                        root=$(project_root_from_project_name "$project_name" 2>/dev/null || true)
                        if [ -n "$root" ]; then
                            pr_paths+=("$root")
                        else
                            echo -e "${YELLOW}No worktree root found for ${project_name}${NC}"
                        fi
                        ;;
                    __SERVICE__:*)
                        local service_name="${target#__SERVICE__:}"
                        local project_name
                        project_name=$(project_name_from_service_name "$service_name")
                        if [ -n "$project_name" ]; then
                            local root
                            root=$(project_root_from_project_name "$project_name" 2>/dev/null || true)
                            if [ -n "$root" ]; then
                                pr_paths+=("$root")
                            else
                                echo -e "${YELLOW}No worktree root found for ${project_name}${NC}"
                            fi
                        fi
                        ;;
                esac
            done

            if [ ${#pr_paths[@]} -gt 0 ]; then
                local base_branch=""
                if [ -n "${RUN_SH_COMMAND_PR_BASE:-}" ]; then
                    base_branch="$RUN_SH_COMMAND_PR_BASE"
                elif [ "${INTERACTIVE_MODE:-false}" = true ]; then
                    base_branch=$(prompt_pr_base_branch)
                else
                    base_branch=$(default_pr_base_branch)
                fi
                if [ -z "$base_branch" ]; then
                    echo -e "${YELLOW}No base branch selected; skipping PR creation.${NC}"
                    return 3
                fi
                PR_BASE_BRANCH="$base_branch" create_prs_for_paths "selected projects" "$show_summary" "${pr_paths[@]}"
            else
                echo -e "${YELLOW}No valid worktree paths found for PR creation.${NC}"
            fi
            return 0
            ;;
        c|commit)
            if [ ${#targets[@]} -eq 0 ]; then
                echo -e "${RED}No commit target selected.${NC}"
                return 1
            fi
            local -a commit_paths_list=()
            local target
            for target in "${targets[@]}"; do
                case "$target" in
                    __ALL__)
                        local project
                        while IFS= read -r project; do
                            [ -z "$project" ] && continue
                            local root
                            root=$(project_root_from_project_name "$project" 2>/dev/null || true)
                            if [ -n "$root" ]; then
                                commit_paths_list+=("$root")
                            else
                                echo -e "${YELLOW}No worktree root found for ${project}${NC}"
                            fi
                        done < <(get_project_names)
                        ;;
                    __PROJECT__:*)
                        local project_name="${target#__PROJECT__:}"
                        local root
                        root=$(project_root_from_project_name "$project_name" 2>/dev/null || true)
                        if [ -n "$root" ]; then
                            commit_paths_list+=("$root")
                        else
                            echo -e "${YELLOW}No worktree root found for ${project_name}${NC}"
                        fi
                        ;;
                    __SERVICE__:*)
                        local service_name="${target#__SERVICE__:}"
                        local project_name
                        project_name=$(project_name_from_service_name "$service_name")
                        if [ -n "$project_name" ]; then
                            local root
                            root=$(project_root_from_project_name "$project_name" 2>/dev/null || true)
                            if [ -n "$root" ]; then
                                commit_paths_list+=("$root")
                            else
                                echo -e "${YELLOW}No worktree root found for ${project_name}${NC}"
                            fi
                        fi
                        ;;
                esac
            done

            if [ ${#commit_paths_list[@]} -gt 0 ]; then
                if [ -n "${RUN_SH_COMMAND_COMMIT_MESSAGE:-}" ]; then
                    COMMIT_MESSAGE_OVERRIDE="$RUN_SH_COMMAND_COMMIT_MESSAGE"
                    COMMIT_MESSAGE_FILE_OVERRIDE=""
                elif [ -n "${RUN_SH_COMMAND_COMMIT_MESSAGE_FILE:-}" ]; then
                    COMMIT_MESSAGE_OVERRIDE=""
                    COMMIT_MESSAGE_FILE_OVERRIDE="$RUN_SH_COMMAND_COMMIT_MESSAGE_FILE"
                fi
                commit_paths "selected projects" "${commit_paths_list[@]}"
                COMMIT_MESSAGE_OVERRIDE=""
                COMMIT_MESSAGE_FILE_OVERRIDE=""
            else
                echo -e "${YELLOW}No valid worktree paths found for commit.${NC}"
            fi
            return 0
            ;;
        a|analyze)
            if [ ${#targets[@]} -eq 0 ]; then
                echo -e "${RED}No analysis target selected.${NC}"
                return 1
            fi
            local selection="${targets[0]}"
            if [ ${#targets[@]} -gt 1 ]; then
                echo -e "${YELLOW}Multiple analysis targets provided; using ${selection}.${NC}"
            fi
            resolve_analysis_selection "$selection"
            local mode="${RUN_SH_COMMAND_ANALYZE_MODE:-}"
            if [ -z "$mode" ]; then
                if analysis_selection_has_multiple_iterations && [ "${INTERACTIVE_MODE:-false}" = true ]; then
                    mode=$(select_analyze_mode "Select analysis mode") || return 3
                    mode=$(actions_trim "$mode")
                else
                    mode="single"
                fi
            fi
            run_tree_change_analysis "$selection" "$mode"
            return 0
            ;;
        m|migrate|migration|migrations)
            if [ ${#targets[@]} -eq 0 ]; then
                echo -e "${RED}No migration target selected.${NC}"
                return 1
            fi
            local -a project_entries=()
            local target
            for target in "${targets[@]}"; do
                case "$target" in
                    __ALL__)
                        local project
                        while IFS= read -r project; do
                            [ -z "$project" ] && continue
                            local root
                            root=$(project_root_from_project_name "$project" 2>/dev/null || true)
                            if [ -n "$root" ]; then
                                project_entries+=("${project}|${root}")
                            else
                                echo -e "${YELLOW}No worktree root found for ${project}${NC}"
                            fi
                        done < <(get_project_names)
                        ;;
                    __PROJECT__:*)
                        local project_name="${target#__PROJECT__:}"
                        local root
                        root=$(project_root_from_project_name "$project_name" 2>/dev/null || true)
                        if [ -n "$root" ]; then
                            project_entries+=("${project_name}|${root}")
                        else
                            echo -e "${YELLOW}No worktree root found for ${project_name}${NC}"
                        fi
                        ;;
                    __SERVICE__:*)
                        local service_name="${target#__SERVICE__:}"
                        local project_name
                        project_name=$(project_name_from_service_name "$service_name")
                        if [ -n "$project_name" ]; then
                            local root
                            root=$(project_root_from_project_name "$project_name" 2>/dev/null || true)
                            if [ -n "$root" ]; then
                                project_entries+=("${project_name}|${root}")
                            else
                                echo -e "${YELLOW}No worktree root found for ${project_name}${NC}"
                            fi
                        fi
                        ;;
                esac
            done

            if [ ${#project_entries[@]} -eq 0 ]; then
                echo -e "${YELLOW}No valid project roots found for migrations.${NC}"
                return 3
            fi

            local total=${#project_entries[@]}
            local index=0
            local entry
            for entry in "${project_entries[@]}"; do
                ((index++))
                local project_name="${entry%%|*}"
                local root="${entry#*|}"
                local backend_dir
                backend_dir=$(find_backend_dir "$root" 2>/dev/null || true)
                if [ -z "$backend_dir" ] || [ ! -d "$backend_dir" ]; then
                    echo -e "${RED}Backend directory not found for ${project_name}${NC}"
                    continue
                fi
                local python_path="$backend_dir/venv/bin/python"
                if [ ! -x "$python_path" ]; then
                    echo -e "${RED}Backend venv not found at ${python_path}${NC}"
                    continue
                fi
                echo -e "${CYAN}[$index/$total] Running Alembic migrations for ${project_name}...${NC}"
                if command -v migration_db_hint >/dev/null 2>&1; then
                    migration_db_hint "$project_name" "$backend_dir" "$python_path"
                fi
                (cd "$backend_dir" && "$python_path" -m alembic upgrade head)
            done
            return 0
            ;;
        l|logs)
            if [ ${#targets[@]} -eq 0 ]; then
                echo -e "${RED}No log target selected.${NC}"
                return 1
            fi
            local target
            for target in "${targets[@]}"; do
                if [[ "$target" == "__PROJECT__:"* ]]; then
                    local project_name="${target#__PROJECT__:}"
                    local matches=()
                    mapfile -t matches < <(services_for_project "$project_name")
                    if [ ${#matches[@]} -gt 0 ]; then
                        if [ "${INTERACTIVE_MODE:-false}" = true ]; then
                            tail_multiple_logs "${matches[@]}"
                        else
                            tail_multiple_logs_noninteractive "${matches[@]}"
                        fi
                    else
                        echo -e "${RED}No services found for project '$project_name'${NC}"
                    fi
                else
                    local service_name="$target"
                    if [[ "$service_name" == "__SERVICE__:"* ]]; then
                        service_name="${service_name#__SERVICE__:}"
                    fi
                    if [ "${INTERACTIVE_MODE:-false}" = true ]; then
                        tail_logs "$service_name"
                    else
                        tail_logs_noninteractive "$service_name"
                    fi
                fi
            done
            return 3
            ;;
        h|health)
            check_health
            return 0
            ;;
        dashboard|dash)
            if [ "${RUN_SH_COMMAND_DASHBOARD_INTERACTIVE:-false}" = true ] && [ "${INTERACTIVE_MODE:-false}" = true ]; then
                echo -e "\n${CYAN:-}========================================${NC:-}"
                echo -e "${CYAN:-}Development Environment - Interactive Mode${NC:-}"
                echo -e "${CYAN:-}========================================${NC:-}"
                RUN_SH_INTERACTIVE_SKIP_HEADER=true
            fi
            run_dashboard
            if [ "${RUN_SH_COMMAND_DASHBOARD_INTERACTIVE:-false}" = true ] && [ "${INTERACTIVE_MODE:-false}" = true ]; then
                if [ "$(type -t interactive_mode)" = "function" ]; then
                    RUN_SH_INTERACTIVE_SKIP_FIRST_RENDER=true
                    interactive_mode
                fi
            fi
            return 0
            ;;
        e|errors)
            if [ ${#targets[@]} -eq 0 ]; then
                show_errors
                return 0
            fi
            local target
            for target in "${targets[@]}"; do
                if [[ "$target" == "__PROJECT__:"* ]]; then
                    local project_name="${target#__PROJECT__:}"
                    local matches=()
                    mapfile -t matches < <(services_for_project "$project_name")
                    if [ ${#matches[@]} -gt 0 ]; then
                        show_errors "${matches[@]}"
                    else
                        echo -e "${RED}No services found for project '$project_name'${NC}"
                    fi
                elif [ "$target" = "__ALL__" ]; then
                    show_errors
                else
                    local service_name="$target"
                    if [[ "$service_name" == "__SERVICE__:"* ]]; then
                        service_name="${service_name#__SERVICE__:}"
                    fi
                    show_errors "$service_name"
                fi
            done
            return 0
            ;;
        d|doctor)
            run_doctor
            return $?
            ;;
        q|quit)
            SKIP_CLEANUP=true
            save_state
            create_recovery_script
            if command -v write_last_state_pointers >/dev/null 2>&1; then
                write_last_state_pointers
            elif [ -n "${LAST_STATE_FILE:-}" ]; then
                echo "$STATE_FILE" > "$LAST_STATE_FILE"
            fi
            echo -e "${CYAN}Saved session state: $STATE_FILE${NC}"
            if command -v resume_hint_command >/dev/null 2>&1; then
                local resume_cmd
                resume_cmd=$(resume_hint_command)
                if [ -n "$resume_cmd" ]; then
                    echo -e "${CYAN}Resume with: ${resume_cmd}${NC}"
                fi
            fi
            echo -e "${YELLOW}Exiting interactive mode (services continue running)${NC}"
            trap - INT
            return 2
            ;;
        *)
            echo -e "${RED}Invalid command: $cmd_raw${NC}"
            return 0
            ;;
    esac
}
