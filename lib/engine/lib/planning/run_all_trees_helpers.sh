#!/usr/bin/env bash

# Helpers for run.sh.

LIB_DIR="${LIB_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

if ! command -v summary_print_banner >/dev/null 2>&1; then
    if [ -f "$LIB_DIR/summary.sh" ]; then
        # shellcheck source=/dev/null
        source "$LIB_DIR/summary.sh"
    fi
fi

if ! command -v run_command >/dev/null 2>&1; then
    if [ -f "$LIB_DIR/actions.sh" ]; then
        # shellcheck source=/dev/null
        source "$LIB_DIR/actions.sh"
    fi
fi

check_required_tools() {
    local missing=()

    if ! command -v lsof &> /dev/null; then
        missing+=("lsof")
    fi

    if ! command -v jq &> /dev/null; then
        missing+=("jq")
    fi

    if [ -z "$TIMEOUT_BIN" ]; then
        if command -v timeout &> /dev/null; then
            TIMEOUT_BIN="timeout"
        elif command -v gtimeout &> /dev/null; then
            TIMEOUT_BIN="gtimeout"
        else
            missing+=("timeout")
        fi
    elif ! command -v "$TIMEOUT_BIN" &> /dev/null; then
        missing+=("timeout")
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        echo -e "${RED}Missing required tools: ${missing[*]}${NC}"
        echo "Install hints:"
        if printf '%s\n' "${missing[@]}" | grep -q '^lsof$'; then
            echo "  - macOS: preinstalled (try: xcode-select --install)"
            echo "  - Ubuntu: sudo apt-get install lsof"
        fi
        if printf '%s\n' "${missing[@]}" | grep -q '^jq$'; then
            echo "  - macOS: brew install jq"
            echo "  - Ubuntu: sudo apt-get install jq"
        fi
        if printf '%s\n' "${missing[@]}" | grep -q '^timeout$'; then
            echo "  - macOS: brew install coreutils (then use gtimeout or set TIMEOUT_BIN)"
            echo "  - Ubuntu: sudo apt-get install coreutils"
        fi
        exit 1
    fi
}

slugify() {
    echo "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g'
}

slugify_underscore() {
    echo "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/_/g; s/^_+|_+$//g; s/_+/_/g'
}

cleanup_empty_feature_root() {
    local tree_root=$1
    [ -n "$tree_root" ] || return 0
    [ -d "$tree_root" ] || return 0

    local resolved_root=""
    resolved_root=$(cd "$tree_root" && pwd -P 2>/dev/null) || return 0
    local base_root="${BASE_DIR:-.}/${TREES_DIR_NAME:-trees}"
    if [ -d "$base_root" ]; then
        base_root=$(cd "$base_root" && pwd -P 2>/dev/null || true)
    fi
    if [ -n "$base_root" ] && [ "$resolved_root" = "$base_root" ]; then
        return 0
    fi

    local entry=""
    entry=$(find "$resolved_root" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null || true)
    [ -z "$entry" ] || return 0

    if rmdir "$resolved_root" 2>/dev/null; then
        echo -e "${GREEN}✓ Removed empty feature root: ${resolved_root#$BASE_DIR/}${NC}"
    fi
}

resolve_main_backend_env_file() {
    local candidate=""
    if [ -n "$MAIN_ENV_FILE" ]; then
        candidate="$MAIN_ENV_FILE"
        if [[ "$candidate" != /* ]]; then
            candidate="$BASE_DIR/$candidate"
        fi
        if [ -f "$candidate" ]; then
            echo "$candidate"
            return 0
        fi
    fi

    candidate="$BASE_DIR/backend/.env.main"
    if [ -f "$candidate" ]; then
        echo "$candidate"
        return 0
    fi

    candidate="$BASE_DIR/.env.main"
    if [ -f "$candidate" ]; then
        echo "$candidate"
        return 0
    fi

    candidate="$BASE_DIR/backend/.env.cloud"
    if [ -f "$candidate" ]; then
        echo "$candidate"
        return 0
    fi

    candidate="$BASE_DIR/.env.cloud"
    if [ -f "$candidate" ]; then
        echo "$candidate"
        return 0
    fi

    return 1
}

resolve_main_frontend_env_file() {
    local candidate=""
    if [ -n "$MAIN_FRONTEND_ENV_FILE" ]; then
        candidate="$MAIN_FRONTEND_ENV_FILE"
        if [[ "$candidate" != /* ]]; then
            candidate="$BASE_DIR/$candidate"
        fi
        if [ -f "$candidate" ]; then
            echo "$candidate"
            return 0
        fi
    fi

    candidate="$BASE_DIR/frontend/.env.main"
    if [ -f "$candidate" ]; then
        echo "$candidate"
        return 0
    fi

    return 1
}

run_all_trees_init_tty() {
    TTY_DEVICE="${TTY_DEVICE:-/dev/tty}"
    TTY_BASE_STATE=""
    KEY_ESC_WAIT_TIMEOUT="${KEY_ESC_WAIT_TIMEOUT:-0.2}"
    KEY_ESC_IDLE_TIMEOUT="${KEY_ESC_IDLE_TIMEOUT:-0.05}"
    KEY_SEQ_MAX_READS="${KEY_SEQ_MAX_READS:-8}"
    KEY_DEBUG=false

    if [ -r "$TTY_DEVICE" ] && [ -t 0 ]; then
        TTY_BASE_STATE=$(stty -g < "$TTY_DEVICE" 2>/dev/null || true)
    fi
}

run_all_trees_init_tty_debug_log() {
    if [ "$KEY_DEBUG" = true ] && [ -z "${KEY_DEBUG_LOG:-}" ]; then
        KEY_DEBUG_LOG="$LOGS_DIR/tty-debug.log"
    fi
    if [ -n "${KEY_DEBUG_LOG:-}" ]; then
        mkdir -p "$(dirname "$KEY_DEBUG_LOG")"
        printf 'tty debug %s\n' "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" > "$KEY_DEBUG_LOG"
        printf 'tty device %s\n' "${TTY_DEVICE:-/dev/tty}" >> "$KEY_DEBUG_LOG"
    fi
}

run_all_trees_run_docker_interactive() {
    if [ "$INTERACTIVE_MODE" != true ]; then
        return 1
    fi

    if [ "$(type -t ui_can_interactive)" = "function" ] && ! ui_can_interactive; then
        echo -e "${YELLOW}No interactive TTY detected; running Docker mode without interactive loop.${NC}"
        return 1
    fi

    echo -e "${CYAN}Starting Docker Compose (detached)...${NC}"
    if ! docker_compose_up true; then
        echo -e "${RED}Docker Compose failed to start.${NC}"
        return 2
    fi
    interactive_mode_docker
    echo -e "${GREEN}Containers continue running in background.${NC}"
    return 0
}

run_all_trees_run_interactive() {
    if [ "$INTERACTIVE_MODE" != true ]; then
        return 1
    fi

    if [ "$(type -t ui_can_interactive)" = "function" ] && ! ui_can_interactive; then
        echo -e "${YELLOW}No interactive TTY detected; skipping interactive loop.${NC}"
        if [ ${#failed_services[@]} -gt 0 ]; then
            run_all_trees_print_logs_path_once
        fi
        return 1
    fi

    if [ ${#failed_services[@]} -gt 0 ]; then
        run_all_trees_print_logs_path_once
    fi
    interactive_mode
    echo -e "${GREEN}Services continue running in background.${NC}"
    local pid_list=""
    if [ ${#pids[@]} -gt 0 ]; then
        pid_list=$(printf '%s ' "${pids[@]}")
        pid_list=${pid_list% }
    fi
    echo -e "${CYAN}To stop them later, use:${NC} kill ${pid_list}"
    return 0
}

run_all_trees_ensure_command_context() {
    RED="${RED:-\033[0;31m}"
    GREEN="${GREEN:-\033[0;32m}"
    YELLOW="${YELLOW:-\033[1;33m}"
    BLUE="${BLUE:-\033[0;34m}"
    CYAN="${CYAN:-\033[0;36m}"
    NC="${NC:-\033[0m}"

    if [ -z "${LOGS_DIR:-}" ]; then
        local runtime_dir=""
        if [ "$(type -t run_sh_runtime_dir)" = "function" ]; then
            runtime_dir=$(run_sh_runtime_dir)
        else
            runtime_dir="${RUN_SH_RUNTIME_DIR:-/tmp/envctl-runtime}"
            mkdir -p "$runtime_dir" 2>/dev/null || true
        fi
        local runs_dir="${RUN_SH_RUNS_DIR:-${runtime_dir%/}/runs}"
        mkdir -p "$runs_dir" 2>/dev/null || true
        LOGS_DIR="$runs_dir"
    fi
    if [ -z "${LAST_STATE_FILE:-}" ]; then
        local runtime_dir=""
        if [ "$(type -t run_sh_runtime_dir)" = "function" ]; then
            runtime_dir=$(run_sh_runtime_dir)
        else
            runtime_dir="${RUN_SH_RUNTIME_DIR:-/tmp/envctl-runtime}"
            mkdir -p "$runtime_dir" 2>/dev/null || true
        fi
        LAST_STATE_FILE="${runtime_dir%/}/.last_state"
    fi

    BACKEND_PORT_BASE="${BACKEND_PORT_BASE:-8000}"
    FRONTEND_PORT_BASE="${FRONTEND_PORT_BASE:-9000}"
    DB_PORT_BASE="${DB_PORT_BASE:-5432}"
    REDIS_PORT_BASE="${REDIS_PORT_BASE:-6379}"
    DB_PORT="${DB_PORT:-$DB_PORT_BASE}"
    REDIS_PORT="${REDIS_PORT:-$REDIS_PORT_BASE}"
    DB_USER="${DB_USER:-postgres}"
    DB_PASSWORD="${DB_PASSWORD:-postgres}"
    DB_NAME="${DB_NAME:-postgres}"
    PR_STATUS_TTL="${PR_STATUS_TTL:-30}"
    HEALTH_STATUS_TTL="${HEALTH_STATUS_TTL:-120}"
    HAS_GH="${HAS_GH:-false}"

    if ! declare -p pids >/dev/null 2>&1; then
        declare -ag pids=()
    fi
    if ! declare -p services >/dev/null 2>&1; then
        declare -ag services=()
    fi
    if ! declare -p failed_services >/dev/null 2>&1; then
        declare -ag failed_services=()
    fi
    if ! declare -p service_info >/dev/null 2>&1; then
        declare -Ag service_info=()
    fi
    if ! declare -p service_ports >/dev/null 2>&1; then
        declare -Ag service_ports=()
    fi
    if ! declare -p actual_ports >/dev/null 2>&1; then
        declare -Ag actual_ports=()
    fi
    if ! declare -p ATTACH_SERVICE_INFO >/dev/null 2>&1; then
        declare -Ag ATTACH_SERVICE_INFO=()
    fi
    if ! declare -p PR_STATUS_CACHE >/dev/null 2>&1; then
        declare -Ag PR_STATUS_CACHE=()
    fi
    if ! declare -p PR_STATUS_CACHE_TS >/dev/null 2>&1; then
        declare -Ag PR_STATUS_CACHE_TS=()
    fi
    if ! declare -p HEALTH_STATUS >/dev/null 2>&1; then
        declare -Ag HEALTH_STATUS=()
    fi
    if ! declare -p HEALTH_STATUS_TS >/dev/null 2>&1; then
        declare -Ag HEALTH_STATUS_TS=()
    fi
}

run_all_trees_run_command() {
    run_all_trees_ensure_command_context

    if [ "${RUN_SH_COMMAND_LIST_COMMANDS:-false}" = true ]; then
        if command -v list_commands >/dev/null 2>&1; then
            list_commands
            return 0
        fi
        echo -e "${RED}Command list unavailable.${NC}"
        return 1
    fi

    if [ "${RUN_SH_COMMAND_LIST_TARGETS:-false}" = true ]; then
        if command -v list_command_targets >/dev/null 2>&1; then
            list_command_targets
            return 0
        fi
        echo -e "${RED}Command targets unavailable.${NC}"
        return 1
    fi

    if [ -z "${RUN_SH_COMMAND:-}" ]; then
        return 1
    fi

    local original_interactive="${INTERACTIVE_MODE:-true}"
    local command_interactive=false
    if [ "$original_interactive" = true ] && [ "${RUN_SH_COMMAND_DASHBOARD_INTERACTIVE:-false}" = true ]; then
        case "${RUN_SH_COMMAND:-}" in
            dashboard|dash)
                command_interactive=true
                ;;
        esac
    fi
    if [ "$command_interactive" = true ]; then
        INTERACTIVE_MODE=true
    else
        INTERACTIVE_MODE=false
    fi

    if [ "${RUN_SH_COMMAND_ONLY:-false}" = true ] && [ "${RUN_SH_COMMAND_RESUME:-false}" != true ]; then
        if command -v log_error >/dev/null 2>&1; then
            log_error "skip-startup requires --load-state."
        else
            echo "skip-startup requires --load-state." >&2
        fi
        INTERACTIVE_MODE="$original_interactive"
        return 1
    fi

    if { [ "${RUN_SH_COMMAND_RESUME:-false}" = true ] || [ "${RUN_SH_COMMAND_ONLY:-false}" = true ]; } && [ "${RUN_SH_COMMAND:-}" != "blast-all" ]; then
        if command -v load_state_for_command >/dev/null 2>&1; then
            if ! load_state_for_command; then
                if [ "${RUN_SH_COMMAND:-}" != "blast-all" ]; then
                    INTERACTIVE_MODE="$original_interactive"
                    return 1
                fi
            fi
        else
            if command -v log_error >/dev/null 2>&1; then
                log_error "load_state_for_command is unavailable."
            else
                echo "load_state_for_command is unavailable." >&2
            fi
            INTERACTIVE_MODE="$original_interactive"
            return 1
        fi
    fi

    local -a parsed_targets=()
    if command -v parse_command_targets >/dev/null 2>&1; then
        parse_command_targets parsed_targets "${RUN_SH_COMMAND_TARGETS[@]}"
    else
        parsed_targets=("${RUN_SH_COMMAND_TARGETS[@]}")
    fi

    if command -v validate_command_targets >/dev/null 2>&1; then
        if ! validate_command_targets "${parsed_targets[@]}"; then
            INTERACTIVE_MODE="$original_interactive"
            return 1
        fi
    fi

    if command -v run_command >/dev/null 2>&1; then
        run_command "$RUN_SH_COMMAND" "${parsed_targets[@]}"
        local rc=$?
        if [ "$rc" -eq 0 ] && [ -n "${STATE_FILE:-}" ] && [ "${RUN_SH_COMMAND_RESUME:-false}" = true ] && [ "$(type -t save_state)" = "function" ]; then
            if [ "${RUN_SH_COMMAND:-}" != "blast-all" ] && [ "${RUN_SH_COMMAND:-}" != "stop-all" ] && [ "${RUN_SH_COMMAND:-}" != "stop" ]; then
                save_state
                if [ "$(type -t write_last_state_pointers)" = "function" ]; then
                    write_last_state_pointers
                fi
            fi
        fi
        if command -v run_all_trees_write_dashboard >/dev/null 2>&1; then
            run_all_trees_write_dashboard
        fi
        INTERACTIVE_MODE="$original_interactive"
        return "$rc"
    fi

    echo -e "${RED}Command runner unavailable.${NC}"
    INTERACTIVE_MODE="$original_interactive"
    return 1
}

run_all_trees_handle_resume() {
    local has_project_filters=false
    if [ "$TREES_MODE" = true ] && [ ${#RUN_SH_COMMAND_TARGETS[@]} -gt 0 ]; then
        local -a parsed_targets=()
        if command -v parse_command_targets >/dev/null 2>&1; then
            parse_command_targets parsed_targets "${RUN_SH_COMMAND_TARGETS[@]}"
        else
            parsed_targets=("${RUN_SH_COMMAND_TARGETS[@]}")
        fi
        local target
        for target in "${parsed_targets[@]}"; do
            case "$target" in
                __PROJECT__:*|project:*)
                    has_project_filters=true
                    break
                    ;;
            esac
        done
    fi

    if [ "$RESUME_MODE" != true ] && [ "$AUTO_RESUME" = true ] && [ "$has_project_filters" != true ]; then
        if [ "$DOCKER_MODE" != true ] && [ "$INTERACTIVE_MODE" = true ] && \
           [ "$SETUP_WORKTREES" != true ] && [ "$PLANNING_ENVS" != true ] && \
           [ "$FRESH_INSTALL" != true ] && [ "$FORCE_PORTS" != true ]; then
            if find_last_state_file >/dev/null 2>&1; then
                if [ "$TREES_MODE" = true ] && last_state_is_trees; then
                    RESUME_MODE=true
                elif [ "$TREES_MODE" != true ] && last_state_is_main; then
                    RESUME_MODE=true
                else
                    RESUME_MODE=false
                fi
            fi
        fi
    fi

    if [ "$FORCE_MAIN_MODE" = true ] && [ "$RESUME_MODE" = true ] && last_state_is_trees; then
        RESUME_MODE=false
    fi

    if [ "$RESUME_MODE" = true ]; then
        resume_from_state
    fi
}

run_all_trees_is_main_project_name() {
    local project_name=${1:-}
    [ -n "$project_name" ] || return 1
    local lowered=""
    lowered=$(printf '%s' "$project_name" | tr '[:upper:]' '[:lower:]')
    [ "$lowered" = "main" ]
}

run_all_trees_apply_cli_project_filters() {
    RUN_SH_INCLUDE_MAIN_PROJECT=false

    if [ "${TREES_MODE:-false}" != true ]; then
        return 0
    fi
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
    local -A seen_projects=()
    local target=""
    local project_name=""
    for target in "${parsed_targets[@]}"; do
        project_name=""
        case "$target" in
            __PROJECT__:*)
                project_name="${target#__PROJECT__:}"
                ;;
            project:*)
                project_name="${target#project:}"
                ;;
            *)
                ;;
        esac
        [ -n "$project_name" ] || continue
        if run_all_trees_is_main_project_name "$project_name"; then
            project_name="Main"
        fi
        if [ -z "${seen_projects[$project_name]:-}" ]; then
            selected_projects+=("$project_name")
            seen_projects["$project_name"]=1
        fi
    done

    if [ ${#selected_projects[@]} -eq 0 ]; then
        return 0
    fi

    local -a resolved_paths=()
    local -A seen_paths=()
    local -a unresolved_projects=()
    local include_main_project=false

    for project_name in "${selected_projects[@]}"; do
        if run_all_trees_is_main_project_name "$project_name"; then
            include_main_project=true
            continue
        fi

        local project_root=""
        if [ "$(type -t state_guess_project_root_from_name)" = "function" ]; then
            project_root=$(state_guess_project_root_from_name "$project_name" 2>/dev/null || true)
        fi
        if [ -z "$project_root" ] && [ -d "${BASE_DIR%/}/${TREES_DIR_NAME:-trees}/${project_name}" ]; then
            project_root="${BASE_DIR%/}/${TREES_DIR_NAME:-trees}/${project_name}"
        fi

        if [ -z "$project_root" ] || [ ! -d "$project_root" ]; then
            unresolved_projects+=("$project_name")
            continue
        fi

        local is_tree_iteration=false
        if [ "$(type -t worktree_identity_from_dir)" = "function" ]; then
            if worktree_identity_from_dir "$project_root" "$BASE_DIR" "${TREES_DIR_NAME:-trees}" >/dev/null 2>&1; then
                is_tree_iteration=true
            fi
        elif [[ "$(basename "$project_root")" =~ ^[0-9]+$ ]]; then
            is_tree_iteration=true
        fi

        if [ "$is_tree_iteration" = true ]; then
            project_root="${project_root%/}"
            if [ -z "${seen_paths[$project_root]:-}" ]; then
                resolved_paths+=("$project_root")
                seen_paths["$project_root"]=1
            fi
            continue
        fi

        local -a iter_paths=()
        if [ "$(type -t list_numeric_dirs)" = "function" ]; then
            while IFS= read -r path; do
                [ -n "$path" ] && iter_paths+=("${path%/}")
            done < <(list_numeric_dirs "$project_root")
        else
            while IFS= read -r path; do
                [ -n "$path" ] && iter_paths+=("${path%/}")
            done < <(find "$project_root" -mindepth 1 -maxdepth 1 -type d -name "[0-9]*" -print 2>/dev/null)
        fi

        if [ ${#iter_paths[@]} -eq 0 ]; then
            unresolved_projects+=("$project_name")
            continue
        fi

        local iter_path=""
        for iter_path in "${iter_paths[@]}"; do
            if [ -z "${seen_paths[$iter_path]:-}" ]; then
                resolved_paths+=("$iter_path")
                seen_paths["$iter_path"]=1
            fi
        done
    done

    RUN_SH_INCLUDE_MAIN_PROJECT=$include_main_project

    if [ ${#resolved_paths[@]} -eq 0 ]; then
        if [ "$include_main_project" != true ] || [ "${RESUME_MODE:-false}" != true ]; then
            echo -e "${RED}No tree paths found for requested project filter(s): $(IFS=','; echo "${selected_projects[*]}").${NC}"
            return 1
        fi
    fi

    if [ ${#unresolved_projects[@]} -gt 0 ]; then
        echo -e "${YELLOW}Skipping unknown project filter(s): $(IFS=','; echo "${unresolved_projects[*]}").${NC}"
    fi

    TREES_TARGET_PATHS=("${resolved_paths[@]}")
    echo -e "${CYAN}Applying trees startup filter: $(IFS=','; echo "${selected_projects[*]}").${NC}"
    return 0
}

run_all_trees_handle_docker_mode() {
    if [ "$DOCKER_MODE" != true ]; then
        return 1
    fi

    RUN_ALL_TREES_EXIT_STATUS=0
    SKIP_CLEANUP=true

    if [ ! -f "$DOCKER_COMPOSE_FILE" ]; then
        if [ "$TREES_MODE" != true ]; then
            echo -e "${RED}Docker compose file not found: $DOCKER_COMPOSE_FILE${NC}"
            RUN_ALL_TREES_EXIT_STATUS=1
            return 0
        fi
    fi

    check_required_tools
    check_docker

    if [ "$TREES_MODE" = true ]; then
        if ! resolve_docker_trees; then
            RUN_ALL_TREES_EXIT_STATUS=1
            return 0
        fi
    else
        if ! resolve_docker_ports; then
            RUN_ALL_TREES_EXIT_STATUS=1
            return 0
        fi
        DOCKER_KNOWN_SERVICES=("${DOCKER_UP_SERVICES[@]}")
    fi

    if run_all_trees_run_docker_interactive; then
        RUN_ALL_TREES_EXIT_STATUS=0
        return 0
    else
        local rc=$?
        if [ "$rc" -eq 2 ]; then
            RUN_ALL_TREES_EXIT_STATUS=1
            return 0
        fi
    fi

    echo -e "${CYAN}Starting Docker Compose...${NC}"
    docker_compose_up false
    RUN_ALL_TREES_EXIT_STATUS=$?
    return 0
}

run_all_trees_prepare_requirements() {
    check_required_tools
    check_docker
    enable_requirements_seed_from_base
    if ! ensure_python_bin; then
        return 1
    fi
    return 0
}

run_all_trees_export_setup_envs() {
    export BACKEND_DIR_NAME FRONTEND_DIR_NAME TREES_DIR_NAME
    export BACKEND_PORT_BASE FRONTEND_PORT_BASE PORT_SPACING
    export DB_PORT REDIS_PORT DB_USER DB_PASSWORD DB_NAME
}

run_all_trees_resolve_main_environment() {
    main_dir=$(cd "$BASE_DIR" && pwd -P)
    main_uses_supabase=false
    main_skip_local_db=false
    local requirements_mode="${MAIN_REQUIREMENTS_MODE:-}"

    if [ "$requirements_mode" = "local" ]; then
        SUPABASE_MAIN_ENABLE=true
        N8N_MAIN_ENABLE=true
    elif [ "$requirements_mode" = "remote" ]; then
        SUPABASE_MAIN_ENABLE=false
        N8N_MAIN_ENABLE=false
    fi

    if [ "$MAIN_MODE" != true ]; then
        if [ -n "$MAIN_ENV_FILE" ] || [ -n "$MAIN_FRONTEND_ENV_FILE" ]; then
            echo -e "${YELLOW}Main env overrides set but MAIN mode is off; ignoring MAIN_ENV_FILE/MAIN_FRONTEND_ENV_FILE.${NC}"
        fi
        unset MAIN_ENV_FILE MAIN_FRONTEND_ENV_FILE
        MAIN_ENV_FILE_PATH=""
        MAIN_FRONTEND_ENV_FILE_PATH=""
        return 0
    fi

    if [ "$MAIN_MODE" = true ] && [ "$TREES_MODE" != true ] && tree_uses_supabase "$main_dir"; then
        main_uses_supabase=true
    fi

    if [ "$MAIN_MODE" = true ]; then
        MAIN_ENV_FILE_PATH=$(resolve_main_backend_env_file || true)
        MAIN_FRONTEND_ENV_FILE_PATH=$(resolve_main_frontend_env_file || true)
        if [ -n "$MAIN_ENV_FILE" ] && [ -z "$MAIN_ENV_FILE_PATH" ]; then
            echo -e "${YELLOW}Main env override not found: $MAIN_ENV_FILE; falling back to default .env/local DB settings.${NC}"
        fi
        if [ -n "$MAIN_FRONTEND_ENV_FILE" ] && [ -z "$MAIN_FRONTEND_ENV_FILE_PATH" ]; then
            echo -e "${YELLOW}Main frontend env override not found: $MAIN_FRONTEND_ENV_FILE; falling back to default frontend env settings.${NC}"
        fi
        if [ -n "$MAIN_ENV_FILE_PATH" ] && [ "$requirements_mode" != "local" ]; then
            main_skip_local_db=true
            if [ "$main_uses_supabase" = true ]; then
                main_uses_supabase=false
                echo -e "${YELLOW}Main env override detected; skipping local Supabase stack for Main.${NC}"
            fi
        fi
        if [ "$requirements_mode" = "local" ]; then
            if [ -n "$MAIN_ENV_FILE_PATH" ] || [ -n "$MAIN_FRONTEND_ENV_FILE_PATH" ]; then
                echo -e "${YELLOW}Main local requirements enabled; ignoring MAIN_ENV_FILE overrides.${NC}"
            fi
            MAIN_ENV_FILE_PATH=""
            MAIN_FRONTEND_ENV_FILE_PATH=""
        fi
        if [ -n "$MAIN_FRONTEND_ENV_FILE_PATH" ]; then
            FRONTEND_ENV_FILE_OVERRIDE="$MAIN_FRONTEND_ENV_FILE_PATH"
        fi
    fi
}

run_all_trees_handle_setup_worktrees() {
    local setup_script=""
    local tree_root=""

    if [ "$DOCKER_MODE" = true ]; then
        echo -e "${RED}setup-worktrees is not supported in Docker mode.${NC}"
        return 1
    fi

    if [ -z "$SETUP_WORKTREES_FEATURE" ]; then
        echo -e "${RED}Missing feature name for setup-worktrees.${NC}"
        echo "Usage: --setup-worktrees <FEATURE> <COUNT> or --setup-worktree <FEATURE> <ITER>"
        return 1
    fi

    if [ "$SETUP_WORKTREES_MODE" = "multi" ] && [ -z "$SETUP_WORKTREES_COUNT" ]; then
        echo -e "${RED}Missing count for setup-worktrees.${NC}"
        echo "Usage: --setup-worktrees <FEATURE> <COUNT>"
        return 1
    fi

    if [ "$SETUP_WORKTREES_MODE" = "single" ] && [ -z "$SETUP_WORKTREES_ITER" ]; then
        echo -e "${RED}Missing iteration for setup-worktree.${NC}"
        echo "Usage: --setup-worktree <FEATURE> <ITER>"
        return 1
    fi

    setup_script="$BASE_DIR/utils/setup-worktrees.sh"
    if [ ! -f "$setup_script" ]; then
        echo -e "${RED}setup-worktrees.sh not found at $setup_script${NC}"
        return 1
    fi

    tree_root=$(preferred_tree_root_for_feature "$SETUP_WORKTREES_FEATURE")
    local -A existing_iters=()
    if [ -d "$tree_root" ]; then
        while IFS= read -r iter_name; do
            [ -n "$iter_name" ] && existing_iters["$iter_name"]=1
        done < <(list_numeric_dir_names "$tree_root")
    fi

    echo -e "${CYAN}Setting up worktrees for ${SETUP_WORKTREES_FEATURE}...${NC}"
    run_all_trees_export_setup_envs

    local -a setup_args=()
    if [ "$SETUP_WORKTREES_MODE" = "single" ]; then
        setup_args=(--single "$SETUP_WORKTREES_FEATURE" "$SETUP_WORKTREES_ITER")
        if [ "${SETUP_WORKTREE_EXISTING:-false}" = true ]; then
            setup_args+=(--existing)
        fi
        if [ "${SETUP_WORKTREE_RECREATE:-false}" = true ]; then
            setup_args+=(--recreate)
        fi
    else
        setup_args=("$SETUP_WORKTREES_FEATURE" "$SETUP_WORKTREES_COUNT")
    fi

    "$setup_script" "${setup_args[@]}"

    if [ $? -ne 0 ]; then
        echo -e "${RED}setup-worktrees.sh failed.${NC}"
        return 1
    fi

    TREES_MODE=true
    TREES_FEATURE_FILTER="$SETUP_WORKTREES_FEATURE"
    TREES_ROOTS=("$tree_root")

    TREES_TARGETS=()
    if [ -d "$tree_root" ]; then
        while IFS= read -r iter_name; do
            if [ -n "$iter_name" ] && [ -z "${existing_iters[$iter_name]:-}" ]; then
                TREES_TARGETS+=("$iter_name")
            fi
        done < <(list_numeric_dir_names "$tree_root")
    fi

    if [ ${#TREES_TARGETS[@]} -eq 0 ] && [ "$SETUP_WORKTREES_MODE" = "single" ]; then
        TREES_TARGETS+=("$SETUP_WORKTREES_ITER")
    fi

    if [ -n "${SETUP_INCLUDE_WORKTREES_RAW:-}" ]; then
        local -a extra_iters=()
        local extra_iter=""
        IFS=',' read -r -a extra_iters <<< "$SETUP_INCLUDE_WORKTREES_RAW"

        local -A target_seen=()
        local target_iter=""
        for target_iter in "${TREES_TARGETS[@]}"; do
            [ -n "$target_iter" ] && target_seen["$target_iter"]=1
        done

        local -a missing_extra_iters=()
        for extra_iter in "${extra_iters[@]}"; do
            extra_iter="${extra_iter#"${extra_iter%%[![:space:]]*}"}"
            extra_iter="${extra_iter%"${extra_iter##*[![:space:]]}"}"
            [ -n "$extra_iter" ] || continue

            if [ ! -d "$tree_root/$extra_iter" ]; then
                missing_extra_iters+=("$extra_iter")
                continue
            fi

            if [ -z "${target_seen[$extra_iter]:-}" ]; then
                TREES_TARGETS+=("$extra_iter")
                target_seen["$extra_iter"]=1
            fi
        done

        if [ ${#missing_extra_iters[@]} -gt 0 ]; then
            echo -e "${YELLOW}Skipping non-existent additional worktrees: $(IFS=','; echo "${missing_extra_iters[*]}").${NC}"
        fi
    fi

    return 0
}

run_all_trees_handle_planning_envs() {
    if [ "$PLANNING_ENVS" != true ]; then
        return 1
    fi

    if [ "$DOCKER_MODE" = true ]; then
        echo -e "${RED}The --plan option is not supported in Docker mode.${NC}"
        return 3
    fi

    MAIN_MODE=false
    local -a local_plans=()
    local -A desired_counts=()
    local plan_entry=""
    local plan_file=""
    local count=""
    local planning_output=""
    if ! planning_output=$(resolve_planning_files "$PLANNING_SELECTION_RAW"); then
        return 3
    fi
    while IFS= read -r plan_entry; do
        [ -z "$plan_entry" ] && continue
        plan_file="$plan_entry"
        count=""
        if [[ "$plan_entry" == *"|"* ]]; then
            plan_file="${plan_entry%%|*}"
            count="${plan_entry#*|}"
        fi
        [ -z "$plan_file" ] && continue
        local_plans+=("$plan_file")
        if [[ "$count" =~ ^[0-9]+$ ]]; then
            desired_counts["$plan_file"]="$count"
        else
            desired_counts["$plan_file"]=$(( ${desired_counts["$plan_file"]:-0} + 1 ))
        fi
    done <<< "$planning_output"

    if [ ${#local_plans[@]} -eq 0 ]; then
        echo -e "${RED}No planning files selected.${NC}"
        return 3
    fi

    local -A unique_seen=()
    local -a unique_plans=()
    for plan_file in "${local_plans[@]}"; do
        if [ -z "${unique_seen[$plan_file]:-}" ]; then
            unique_plans+=("$plan_file")
            unique_seen["$plan_file"]=1
        fi
    done

    local setup_script="$BASE_DIR/utils/setup-worktrees.sh"
    if [ ! -f "$setup_script" ]; then
        echo -e "${RED}setup-worktrees.sh not found at $setup_script${NC}"
        return 3
    fi

    run_all_trees_export_setup_envs

    TREES_MODE=true
    USE_FEATURE_LABELS=true
    TREES_ROOTS=()
    TREES_TARGET_PATHS=()

    local -A added_paths=()
    local feature_name=""
    local tree_root=""
    for plan_file in "${unique_plans[@]}"; do
        feature_name=$(planning_feature_name "$plan_file")
        tree_root=$(preferred_tree_root_for_feature "$feature_name")

        local -A existing_iters=()
        if [ -d "$tree_root" ]; then
            while IFS= read -r iter_name; do
                [ -n "$iter_name" ] && existing_iters["$iter_name"]=1
            done < <(list_numeric_dir_names "$tree_root")
        fi

        local existing_count=${#existing_iters[@]}
        local initial_existing_count=$existing_count
        local desired_count=${desired_counts["$plan_file"]:-0}
        if [ "$desired_count" -eq 0 ] && [ "$existing_count" -eq 0 ]; then
            continue
        fi
        if [ "$existing_count" -gt "$desired_count" ]; then
            local delete_count=$((existing_count - desired_count))
            local delete_dirs=()
            if [ "$delete_count" -gt 0 ]; then
                mapfile -t sorted_iters < <(list_numeric_dir_names "$tree_root" | sort -nr)
                for iter in "${sorted_iters[@]}"; do
                    if [ ${#delete_dirs[@]} -ge "$delete_count" ]; then
                        break
                    fi
                    delete_dirs+=("${tree_root%/}/${iter}")
                done
            fi
            if [ ${#delete_dirs[@]} -gt 0 ]; then
                echo -e "${YELLOW}Selected count for ${plan_file} (${desired_count}) is below existing (${existing_count}).${NC}"
                if delete_worktrees_for_paths "${plan_file}" "${delete_dirs[@]}"; then
                    existing_iters=()
                    while IFS= read -r iter_name; do
                        [ -n "$iter_name" ] && existing_iters["$iter_name"]=1
                    done < <(list_numeric_dir_names "$tree_root")
                    existing_count=${#existing_iters[@]}
                else
                    desired_count=$existing_count
                fi
            else
                desired_count=$existing_count
            fi
        fi
        local create_count=$((desired_count - existing_count))

        if [ "$desired_count" -eq 0 ] && [ "$initial_existing_count" -gt 0 ] && [ "$existing_count" -eq 0 ]; then
            if [ "${PLANNING_KEEP_PLAN:-false}" != true ] && [ "$(type -t planning_move_to_done)" = "function" ]; then
                planning_move_to_done "$plan_file"
            fi
            cleanup_empty_feature_root "$tree_root"
        fi

        if [ "$create_count" -gt 0 ]; then
            echo -e "${CYAN}Setting up ${create_count} worktree(s) for ${plan_file} -> ${feature_name}...${NC}"
            local plan_path=""
            if [ "$(type -t planning_file_path)" = "function" ]; then
                plan_path=$(planning_file_path "$plan_file")
            else
                local planning_root="${ENVCTL_PLANNING_DIR:-docs/planning}"
                planning_root="${planning_root%/}"
                if [[ "$planning_root" = /* ]]; then
                    plan_path="${planning_root}/${plan_file}"
                else
                    plan_path="${BASE_DIR}/${planning_root}/${plan_file}"
                fi
            fi
            PLAN_FILE="$plan_path" "$setup_script" "$feature_name" "$create_count"
            if [ $? -ne 0 ]; then
                echo -e "${RED}setup-worktrees.sh failed for ${feature_name}.${NC}"
                return 3
            fi
        elif [ "$existing_count" -gt 0 ]; then
            echo -e "${CYAN}Using existing ${existing_count} worktree(s) for ${plan_file} -> ${feature_name}.${NC}"
        fi

        if feature_requests_supabase "$feature_name" "$plan_file"; then
            ensure_supabase_marker_for_root "$tree_root"
        fi

        if [ "$existing_count" -eq 0 ] && [ "$create_count" -le 0 ]; then
            continue
        fi

        if [ ! -d "$tree_root" ]; then
            echo -e "${RED}Unable to locate worktree root for ${feature_name}.${NC}"
            return 3
        fi

        local root_seen=false
        for root in "${TREES_ROOTS[@]}"; do
            if [ "$root" = "$tree_root" ]; then
                root_seen=true
                break
            fi
        done
        if [ "$root_seen" = false ]; then
            TREES_ROOTS+=("$tree_root")
        fi

        while IFS= read -r dir; do
            [ -n "$dir" ] || continue
            if [ -z "${added_paths[${dir%/}]:-}" ]; then
                TREES_TARGET_PATHS+=("${dir%/}")
                added_paths["${dir%/}"]=1
            fi
        done < <(list_numeric_dirs "$tree_root")
    done

    if [ ${#TREES_ROOTS[@]} -eq 0 ]; then
        echo -e "${YELLOW}No worktrees selected to run.${NC}"
        return 2
    fi

    if [ "$PLANNING_CREATE_PRS" = true ]; then
        base_branch=$(prompt_pr_base_branch)
        if [ -z "$base_branch" ]; then
            echo -e "${YELLOW}No base branch selected; skipping PR creation.${NC}"
        else
            PR_BASE_BRANCH="$base_branch" create_prs_for_planning_paths || true
        fi
        if [ "$PLANNING_PRS_ONLY" = true ]; then
            return 2
        fi
    fi

    return 0
}

run_all_trees_start_requirements() {
    if [ "$(type -t envctl_setup_infrastructure)" = "function" ]; then
        echo -e "${CYAN}Using custom envctl_setup_infrastructure hook...${NC}"
        envctl_setup_infrastructure
        return $?
    fi

    if [ "${ENVCTL_SKIP_DEFAULT_INFRASTRUCTURE:-false}" = "true" ]; then
        return 0
    fi

    if [ "$main_uses_supabase" = true ]; then
        echo -e "${CYAN}Using Supabase stack for main project requirements...${NC}"
        local main_db_port=""
        local main_db_locked=false
        local supabase_db_container=""
        if [ "$(type -t supabase_container_name)" = "function" ]; then
            supabase_db_container=$(supabase_container_name "$main_dir" "supabase-db" 2>/dev/null || true)
        fi
        if [ -n "$supabase_db_container" ]; then
            if [ "$(type -t lock_requirement_port_from_container)" = "function" ]; then
                local existing_db_port=""
                existing_db_port=$(lock_requirement_port_from_container "$supabase_db_container" "5432" "${main_dir}:supabase-db")
                if [ -n "$existing_db_port" ]; then
                    main_db_port="$existing_db_port"
                    main_db_locked=true
                fi
            elif [ "$(type -t container_host_port)" = "function" ]; then
                local existing_db_port=""
                existing_db_port=$(container_host_port "$supabase_db_container" "5432")
                if [ -n "$existing_db_port" ]; then
                    main_db_port="$existing_db_port"
                    main_db_locked=true
                    if [ -n "${service_ports+x}" ]; then
                        service_ports["$existing_db_port"]="${main_dir}:supabase-db"
                    fi
                    if [ "$(type -t port_state_record)" = "function" ]; then
                        port_state_record "$existing_db_port" "${main_dir}:supabase-db" "reserved" || true
                    fi
                fi
            fi
        fi
        if [ "$main_db_locked" = false ]; then
            main_db_port=$(reserve_requirement_port "$DB_PORT_BASE" "" "" "${main_dir}:supabase-db")
        fi
        register_supabase_tree_config "$main_dir" "$main_db_port"
        if ! start_tree_supabase "$main_dir" "$main_db_port"; then
            echo -e "${RED}Failed to start Supabase for main project. Exiting.${NC}"
            return 1
        fi
        apply_supabase_env_for_tree "$main_dir"
        if [ "$(type -t tree_uses_n8n)" = "function" ] && tree_uses_n8n "$main_dir"; then
            local n8n_port=""
            if [ "$(type -t tree_n8n_port_for_dir)" = "function" ]; then
                local resolved_port=""
                resolved_port=$(tree_n8n_port_for_dir "$main_dir" "" n8n_port 2>/dev/null || true)
                if [ -z "$n8n_port" ] && [ -n "$resolved_port" ]; then
                    n8n_port="$resolved_port"
                fi
            fi
            if [ -z "$n8n_port" ]; then
                n8n_port="${N8N_PORT_BASE:-5678}"
            fi
            if [ "$(type -t apply_n8n_env_for_tree)" = "function" ]; then
                apply_n8n_env_for_tree "$main_dir" "$n8n_port"
            fi
            if [ "$(type -t start_tree_n8n)" = "function" ]; then
                if ! start_tree_n8n "$main_dir" "$n8n_port"; then
                    echo -e "${RED}Failed to start n8n for main project. Exiting.${NC}"
                    return 1
                fi
            fi
        fi
        select_redis_port_for_main
        if ! start_redis; then
            echo -e "${RED}Failed to start Redis. Exiting.${NC}"
            return 1
        fi
        return 0
    fi

    if per_tree_requirements_enabled; then
        echo -e "${CYAN}Per-tree requirements enabled; skipping shared PostgreSQL/Redis.${NC}"
        return 0
    fi

    if [ "$MAIN_MODE" = true ] && [ "$main_skip_local_db" = true ]; then
        echo -e "${YELLOW}Main env override active; skipping local PostgreSQL for Main.${NC}"
    else
        if ! start_postgres; then
            echo -e "${RED}Failed to start PostgreSQL. Exiting.${NC}"
            return 1
        fi
    fi

    select_redis_port_for_main
    if ! start_redis; then
        echo -e "${RED}Failed to start Redis. Exiting.${NC}"
        return 1
    fi
    return 0
}

run_all_trees_print_running_services() {
    if [ ${#services[@]} -eq 0 ]; then
        return 1
    fi

    echo -e "\n${GREEN}✓ Running services:${NC}"
    for service in "${services[@]}"; do
        parse_service_entry "$service" name url docs || continue
        actual_port=${actual_ports["$name"]:-}
        if [ -n "$actual_port" ]; then
            url=$(echo "$url" | sed -E "s/:[0-9]+/:$actual_port/")
        fi
        echo -e "  ${BLUE}$name:${NC} $url"
    done
    return 0
}

run_all_trees_print_failed_services() {
    if [ ${#failed_services[@]} -eq 0 ]; then
        return 1
    fi

    run_all_trees_print_logs_path_once

    echo -e "\n${RED}✗ Failed services:${NC}"
    for failed in "${failed_services[@]}"; do
        IFS='|' read -r name log <<< "$failed"
        echo -e "  ${RED}$name${NC} - Check log: $log"
    done
    return 0
}

run_all_trees_print_logs_path_once() {
    if [ "${RUN_ALL_TREES_LOG_PATH_PRINTED:-false}" = true ]; then
        return 0
    fi
    RUN_ALL_TREES_LOG_PATH_PRINTED=true
    local logs_path="$LOGS_DIR"
    if command -v realpath >/dev/null 2>&1; then
        logs_path=$(realpath "$LOGS_DIR" 2>/dev/null || echo "$LOGS_DIR")
    fi
    echo -e "\n${CYAN}Logs directory:${NC} ${logs_path}"
}

run_all_trees_print_logs_summary() {
    printf '\n'
    summary_print_label_value "📁 Logs Directory" "$LOGS_DIR" "$CYAN"
    if [ "$(type -t run_all_trees_dashboard_path)" = "function" ]; then
        local dashboard_path=""
        dashboard_path=$(run_all_trees_dashboard_path)
        if [ -n "$dashboard_path" ]; then
            summary_print_label_value "Dashboard" "$dashboard_path" "$CYAN"
        fi
    fi
    if [ "$(type -t run_all_trees_root_dashboard_path)" = "function" ]; then
        local root_dashboard=""
        root_dashboard=$(run_all_trees_root_dashboard_path)
        if [ -n "$root_dashboard" ]; then
            summary_print_label_value "Dashboard (root)" "$root_dashboard" "$CYAN"
        fi
    fi
    if [ "$(type -t debug_enabled)" = "function" ] && debug_enabled; then
        local debug_log=""
        if [ "$(type -t debug_log_path)" = "function" ]; then
            debug_log=$(debug_log_path)
        elif [ -n "${RUN_SH_DEBUG_LOG:-}" ]; then
            debug_log="$RUN_SH_DEBUG_LOG"
        else
            debug_log="$LOGS_DIR/run_debug.log"
        fi
        summary_print_label_value "Debug Log" "$debug_log" "$CYAN"
    fi
    echo -e "${CYAN}View logs with:${NC}"
    echo -e "  ${BLUE}List all:${NC} ./view-logs.sh list"
    echo -e "  ${BLUE}All logs:${NC} ./view-logs.sh all"
    echo -e "  ${BLUE}Specific tree:${NC} ./view-logs.sh <tree_name>"
    echo -e "  ${BLUE}Errors only:${NC} ./view-logs.sh errors"

    if [ -f "$LOGS_DIR/recover.sh" ]; then
        echo -e "\n${CYAN}Recovery script available:${NC}"
        echo -e "  ${BLUE}Recover session:${NC} $LOGS_DIR/recover.sh"
    fi

    echo -e "\n${YELLOW}Press Ctrl+C to stop all services${NC}"
    echo -e "==================================================\n"
}

run_all_trees_dashboard_path() {
    if [ -z "${LOGS_DIR:-}" ]; then
        return 1
    fi
    if [ "$TREES_MODE" = true ]; then
        echo "$LOGS_DIR/dashboard_trees.txt"
    else
        echo "$LOGS_DIR/dashboard_main.txt"
    fi
}

run_all_trees_root_dashboard_path() {
    local runtime_dir=""
    if [ "$(type -t run_sh_runtime_dir)" = "function" ]; then
        runtime_dir=$(run_sh_runtime_dir)
    else
        runtime_dir="${RUN_SH_RUNTIME_DIR:-/tmp/envctl-runtime}"
        mkdir -p "$runtime_dir" 2>/dev/null || true
    fi
    if [ "$TREES_MODE" = true ]; then
        echo "${runtime_dir%/}/dashboard_trees.txt"
    else
        echo "${runtime_dir%/}/dashboard_main.txt"
    fi
}

run_all_trees_write_dashboard() {
    if [ -z "${LOGS_DIR:-}" ]; then
        return 0
    fi
    if [ ${#services[@]} -eq 0 ] && [ ${#failed_services[@]} -eq 0 ]; then
        return 0
    fi

    local dashboard_path=""
    dashboard_path=$(run_all_trees_dashboard_path) || dashboard_path=""
    local root_dashboard=""
    root_dashboard=$(run_all_trees_root_dashboard_path) || root_dashboard=""
    local -a dashboard_paths=()
    if [ -n "$dashboard_path" ]; then
        dashboard_paths+=("$dashboard_path")
    fi
    if [ -n "$root_dashboard" ]; then
        dashboard_paths+=("$root_dashboard")
    fi
    if [ ${#dashboard_paths[@]} -eq 0 ]; then
        return 0
    fi
    local seen="|"
    local path
    for path in "${dashboard_paths[@]}"; do
        if [[ "$seen" == *"|$path|"* ]]; then
            continue
        fi
        seen+="${path}|"
        mkdir -p "$(dirname "$path")"
    done

    local mode_label="MAIN"
    if [ "$TREES_MODE" = true ]; then
        mode_label="TREES"
    fi
    local -A service_urls=()
    local service
    for service in "${services[@]}"; do
        parse_service_entry "$service" name url docs || continue
        service_urls["$name"]="$url"
    done

    local dashboard_content=""
    dashboard_content="$(
        {
            echo "envctl Dashboard"
            echo "Mode: $mode_label"
            echo ""

            if [ ${#services[@]} -eq 0 ]; then
                echo "No running services."
            else
                if [ "$TREES_MODE" = true ]; then
                    local -A project_services=()
                    local -a project_order=()
                    local -A seen_projects=()
                    for service in "${services[@]}"; do
                        parse_service_entry "$service" name url docs || continue
                        local project_name
                        project_name=$(project_name_from_service_name "$name")
                        [ -n "$project_name" ] || project_name="unknown"
                        if [ -z "${seen_projects[$project_name]:-}" ]; then
                            project_order+=("$project_name")
                            seen_projects["$project_name"]=1
                        fi
                        project_services["$project_name"]+="${name}"$'\n'
                    done

                    local project_name
                    for project_name in "${project_order[@]}"; do
                        echo "Project: $project_name"
                        local svc
                        while IFS= read -r svc; do
                            [ -n "$svc" ] || continue
                            local pid="" port="" log="" type="" dir=""
                            if service_info_fields "$svc" pid port log type dir; then
                                if [ -z "$type" ] && command -v service_type_from_name >/dev/null 2>&1; then
                                    type=$(service_type_from_name "$svc")
                                fi
                                local log_display
                                log_display=$(format_log_path "$log")
                                local url="${service_urls[$svc]:-}"
                                echo "  - ${svc} [${type:-service}] url=${url} pid=${pid} log=${log_display}"
                            else
                                local url="${service_urls[$svc]:-}"
                                echo "  - ${svc} url=${url}"
                            fi
                        done < <(printf '%s' "${project_services[$project_name]}")

                        if [ "$(type -t tree_uses_n8n)" = "function" ]; then
                            local project_root=""
                            project_root=$(project_root_from_project_name "$project_name" 2>/dev/null || true)
                            if [ -n "$project_root" ] && tree_uses_n8n "$project_root"; then
                                local n8n_port=""
                                local project_root_real=""
                                project_root_real=$(cd "$project_root" && pwd -P 2>/dev/null || true)
                                if [ -n "$project_root_real" ]; then
                                    n8n_port="${N8N_TREE_PORTS[$project_root_real]:-}"
                                fi
                                if [ -z "$n8n_port" ] && [ "$(type -t read_env_value)" = "function" ]; then
                                    n8n_port=$(read_env_value "${project_root%/}/.env" "N8N_PORT")
                                fi
                                if [ -n "$n8n_port" ]; then
                                    echo "  - n8n url=http://localhost:${n8n_port}"
                                fi
                            fi
                        fi
                        echo ""
                    done
                else
                    echo "Services:"
                    for service in "${services[@]}"; do
                        parse_service_entry "$service" name url docs || continue
                        local pid="" port="" log="" type="" dir=""
                        if service_info_fields "$name" pid port log type dir; then
                            if [ -z "$type" ] && command -v service_type_from_name >/dev/null 2>&1; then
                                type=$(service_type_from_name "$name")
                            fi
                            local log_display
                            log_display=$(format_log_path "$log")
                            echo "  - ${name} [${type:-service}] url=${url} pid=${pid} log=${log_display}"
                        else
                            echo "  - ${name} url=${url}"
                        fi
                    done
                    if [ -n "${N8N_PORT:-}" ]; then
                        echo ""
                        echo "Infrastructure:"
                        echo "  - n8n url=http://localhost:${N8N_PORT}"
                    fi
                fi
            fi

            if [ ${#failed_services[@]} -gt 0 ]; then
                echo ""
                echo "Failed Services:"
                local failed
                for failed in "${failed_services[@]}"; do
                    local name="" log=""
                    IFS='|' read -r name log <<< "$failed"
                    [ -n "$name" ] || continue
                    local log_display
                    log_display=$(format_log_path "$log")
                    echo "  - ${name} log=${log_display}"
                done
            fi
        } )"

    local tmp_dashboard=""
    tmp_dashboard=$(mktemp "${TMPDIR:-/tmp}/envctl-dashboard.XXXXXX") || return 0
    printf '%s\n' "$dashboard_content" > "$tmp_dashboard"

    for path in "${dashboard_paths[@]}"; do
        if [ -f "$path" ] && cmp -s "$tmp_dashboard" "$path"; then
            continue
        fi
        cp "$tmp_dashboard" "$path"
    done
    rm -f "$tmp_dashboard" 2>/dev/null || true
    return 0
}

run_all_trees_print_noninteractive_summary() {
    printf '\n'
    summary_print_banner "Development Environment" "=" "$CYAN" 50 ""

    run_all_trees_print_running_services || true
    run_all_trees_print_failed_services || true

    if [ ${#services[@]} -eq 0 ]; then
        echo -e "\n${RED}No services started successfully${NC}"
        return 1
    fi

    run_all_trees_write_dashboard
    run_all_trees_print_logs_summary
    return 0
}

run_all_trees_prepare_tree_paths() {
    if [ "$(type -t profile_start)" = "function" ]; then
        profile_start "tree_discovery"
    fi
    tree_paths=()
    if [ ${#TREES_TARGET_PATHS[@]} -gt 0 ]; then
        tree_paths=("${TREES_TARGET_PATHS[@]}")
    else
        while IFS= read -r path; do
            [ -n "$path" ] && tree_paths+=("${path%/}")
        done < <(list_tree_paths "$BASE_DIR" "$TREES_DIR_NAME")

        if [ ${#TREES_ROOTS[@]} -gt 0 ]; then
            filtered_paths=()
            for path in "${tree_paths[@]}"; do
                for root in "${TREES_ROOTS[@]}"; do
                    if [[ "${path%/}" == "${root%/}"/* ]]; then
                        filtered_paths+=("$path")
                        break
                    fi
                done
            done
            tree_paths=("${filtered_paths[@]}")
        fi
    fi

    if [ ${#tree_paths[@]} -eq 0 ]; then
        echo -e "${RED}No tree directories found to run${NC}"
        if [ "$(type -t profile_end)" = "function" ]; then
            profile_end "tree_discovery"
        fi
        return 1
    fi
    if [ "$(type -t debug_log_line)" = "function" ] && [ "${RUN_SH_DEBUG_VERBOSE:-false}" = true ]; then
        debug_log_line "TRACE" "tree_discovery.count=${#tree_paths[@]}"
        local joined=""
        joined=$(printf '%s ' "${tree_paths[@]}" | sed 's/ $//')
        if [ -n "$joined" ]; then
            debug_log_line "TRACE" "tree_discovery.paths=${joined}"
        fi
    fi
    if [ "$(type -t profile_end)" = "function" ]; then
        profile_end "tree_discovery"
    fi
    return 0
}

tree_target_matches() {
    local tree_dir=$1
    local name=$2

    if [ ${#TREES_TARGET_PATHS[@]} -gt 0 ]; then
        local match=false
        local target
        for target in "${TREES_TARGET_PATHS[@]}"; do
            if [ "${tree_dir%/}" = "$target" ]; then
                match=true
                break
            fi
        done
        [ "$match" = true ] || return 1
    fi

    if [ ${#TREES_TARGETS[@]} -gt 0 ]; then
        local match=false
        local target
        for target in "${TREES_TARGETS[@]}"; do
            if [ "$name" = "$target" ]; then
                match=true
                break
            fi
        done
        [ "$match" = true ] || return 1
    fi

    return 0
}

start_tree_job_with_offset() {
    local tree_dir=$1
    local feature_label=$2
    local iter_count=$3
    local force_feature_label=$4
    local assigned_port_offset=$5
    local name
    name=$(basename "$tree_dir")

    local project_label="$name"
    if [ -n "$feature_label" ] && { [ "$USE_FEATURE_LABELS" = true ] || [ "$force_feature_label" = true ]; }; then
        project_label="$feature_label"
        if [ "$iter_count" -gt 1 ]; then
            project_label="${feature_label}_${name}"
        fi
    fi

    local env_file="${tree_dir%/}/.env"
    local backend_port=""
    local frontend_port=""
    backend_port=$(read_env_value "$env_file" "BACKEND_PORT")
    frontend_port=$(read_env_value "$env_file" "FRONTEND_PORT")

    if [ -z "$backend_port" ] || [ -z "$frontend_port" ]; then
        local ports_from_cfg=""
        ports_from_cfg=$(read_ports_from_worktree_config "${tree_dir%/}")
        if [ -n "$ports_from_cfg" ]; then
            local cfg_backend=""
            local cfg_frontend=""
            local cfg_db=""
            local cfg_redis=""
            IFS='|' read -r cfg_backend cfg_frontend cfg_db cfg_redis <<< "$ports_from_cfg"
            [ -z "$backend_port" ] && backend_port="$cfg_backend"
            [ -z "$frontend_port" ] && frontend_port="$cfg_frontend"
        fi
    fi

    # Treat base ports from checked-in config as defaults when an explicit tree offset is assigned.
    if [[ "$assigned_port_offset" =~ ^-?[0-9]+$ ]] && [ "$assigned_port_offset" -ne 0 ]; then
        if [[ "$backend_port" =~ ^[0-9]+$ ]] && [ "$backend_port" -eq "$BACKEND_PORT_BASE" ]; then
            backend_port=""
        fi
        if [[ "$frontend_port" =~ ^[0-9]+$ ]] && [ "$frontend_port" -eq "$FRONTEND_PORT_BASE" ]; then
            frontend_port=""
        fi
    fi

    if [ -z "$backend_port" ]; then
        backend_port=$((BACKEND_PORT_BASE + assigned_port_offset))
    fi
    if [ -z "$frontend_port" ]; then
        frontend_port=$((FRONTEND_PORT_BASE + assigned_port_offset))
    fi

    start_project_with_attach "$project_label" "${tree_dir%/}" "$backend_port" "$frontend_port" "$assigned_port_offset"
}

run_all_trees_parallel_worker_write_fragment() {
    local fragment_file=$1
    local status=$2
    local ready_at_ms=${3:-}

    : > "$fragment_file"
    printf 'STATUS\t%s\n' "$status" >> "$fragment_file"
    if [ -n "$ready_at_ms" ]; then
        printf 'READY_AT_MS\t%s\n' "$ready_at_ms" >> "$fragment_file"
    fi

    local pid
    for pid in "${pids[@]}"; do
        printf 'PID\t%s\n' "$pid" >> "$fragment_file"
    done

    local service_entry
    for service_entry in "${services[@]}"; do
        printf 'SERVICE\t%s\n' "$service_entry" >> "$fragment_file"
    done

    local service_name
    for service_name in "${!service_info[@]}"; do
        printf 'SERVICE_INFO\t%s\t%s\n' "$service_name" "${service_info[$service_name]}" >> "$fragment_file"
    done

    local port
    for port in "${!service_ports[@]}"; do
        printf 'SERVICE_PORT\t%s\t%s\n' "$port" "${service_ports[$port]}" >> "$fragment_file"
    done

    local actual_name
    for actual_name in "${!actual_ports[@]}"; do
        printf 'ACTUAL_PORT\t%s\t%s\n' "$actual_name" "${actual_ports[$actual_name]}" >> "$fragment_file"
    done

    local failed
    for failed in "${failed_services[@]}"; do
        printf 'FAILED\t%s\n' "$failed" >> "$fragment_file"
    done
}

run_all_trees_parallel_worker() {
    local fragment_file=$1
    local tree_dir=$2
    local feature_label=$3
    local iter_count=$4
    local force_feature_label=$5
    local assigned_port_offset=$6

    local -a pids=()
    local -a services=()
    local -a failed_services=()
    local -A service_info=()
    local -A service_ports=()
    local -A actual_ports=()

    RUN_SH_PARALLEL_WORKER=true
    RUN_SH_PORT_RESERVATION_SESSION="${BASHPID:-$$}"
    start_tree_job_with_offset "$tree_dir" "$feature_label" "$iter_count" "$force_feature_label" "$assigned_port_offset"
    local status=$?

    local ready_at_ms=""
    if [ "$status" -eq 0 ] && [ ${#failed_services[@]} -eq 0 ] && [ ${#services[@]} -gt 0 ]; then
        if [ "$(type -t profile_now_ms)" = "function" ]; then
            ready_at_ms=$(profile_now_ms)
        fi
    fi

    run_all_trees_parallel_worker_write_fragment "$fragment_file" "$status" "$ready_at_ms"
    return "$status"
}

dedupe_array_in_place() {
    local -n arr_ref=$1
    local -A seen=()
    local -a unique=()
    local item=""
    for item in "${arr_ref[@]}"; do
        [ -n "$item" ] || continue
        if [ -n "${seen[$item]:-}" ]; then
            continue
        fi
        seen[$item]=1
        unique+=("$item")
    done
    arr_ref=("${unique[@]}")
}

run_all_trees_merge_worker_fragment() {
    local fragment_file=$1
    local ready_out_var=$2
    local status_out_var=$3
    local ready_at_ms=""
    local status=0

    [ -f "$fragment_file" ] || {
        printf -v "$ready_out_var" '%s' ""
        printf -v "$status_out_var" '%s' "1"
        return 1
    }

    local kind=""
    local value1=""
    local value2=""
    while IFS=$'\t' read -r kind value1 value2; do
        case "$kind" in
            STATUS)
                status=$value1
                ;;
            READY_AT_MS)
                ready_at_ms=$value1
                ;;
            PID)
                [ -n "$value1" ] && pids+=("$value1")
                ;;
            SERVICE)
                [ -n "$value1" ] && services+=("$value1")
                ;;
            SERVICE_INFO)
                [ -n "$value1" ] && service_info["$value1"]="$value2"
                ;;
            SERVICE_PORT)
                [ -n "$value1" ] && service_ports["$value1"]="$value2"
                ;;
            ACTUAL_PORT)
                [ -n "$value1" ] && actual_ports["$value1"]="$value2"
                ;;
            FAILED)
                [ -n "$value1" ] && failed_services+=("$value1")
                ;;
        esac
    done < "$fragment_file"

    printf -v "$ready_out_var" '%s' "$ready_at_ms"
    printf -v "$status_out_var" '%s' "$status"
    dedupe_array_in_place pids
    dedupe_array_in_place services
    dedupe_array_in_place failed_services
    return 0
}

run_all_trees_collect_finished_parallel_worker() {
    local -n pids_ref=$1
    local -n fragments_ref=$2
    local -n names_ref=$3
    local -n started_ref=$4
    local first_ready_var=$5
    local had_failures_var=$6

    local worker_timeout_sec="${RUN_SH_PARALLEL_WORKER_TIMEOUT_SEC:-1800}"
    if ! [[ "$worker_timeout_sec" =~ ^[0-9]+$ ]]; then
        worker_timeout_sec=1800
    fi

    while true; do
        local idx
        local now
        now=$(date +%s 2>/dev/null || echo 0)
        for idx in "${!pids_ref[@]}"; do
            local pid="${pids_ref[$idx]}"
            local fragment_file="${fragments_ref[$idx]}"
            local worker_name="${names_ref[$idx]}"
            local started_at="${started_ref[$idx]:-0}"

            if [[ "$started_at" =~ ^[0-9]+$ ]] && [ "$worker_timeout_sec" -gt 0 ]; then
                local elapsed=$((now - started_at))
                if [ "$elapsed" -ge "$worker_timeout_sec" ]; then
                    printf -v "$had_failures_var" '%s' "true"
                    kill -TERM "$pid" 2>/dev/null || true
                    sleep 1
                    kill -KILL "$pid" 2>/dev/null || true
                    wait "$pid" >/dev/null 2>&1 || true
                    failed_services+=("${worker_name} Startup|parallel worker timeout after ${worker_timeout_sec}s (fragment=${fragment_file})")
                    rm -f "$fragment_file" 2>/dev/null || true
                    unset 'pids_ref[idx]'
                    unset 'fragments_ref[idx]'
                    unset 'names_ref[idx]'
                    unset 'started_ref[idx]'
                    pids_ref=("${pids_ref[@]}")
                    fragments_ref=("${fragments_ref[@]}")
                    names_ref=("${names_ref[@]}")
                    started_ref=("${started_ref[@]}")
                    return 0
                fi
            fi

            if kill -0 "$pid" 2>/dev/null; then
                continue
            fi

            local wait_rc=0
            wait "$pid" || wait_rc=$?

            local ready_at_ms=""
            local worker_status=0
            local merge_rc=0
            local failures_before=${#failed_services[@]}
            if ! run_all_trees_merge_worker_fragment "$fragment_file" ready_at_ms worker_status; then
                merge_rc=1
            else
                local current_first="${!first_ready_var:-}"
                if [ -n "$ready_at_ms" ] && { [ -z "$current_first" ] || [ "$ready_at_ms" -lt "$current_first" ]; }; then
                    printf -v "$first_ready_var" '%s' "$ready_at_ms"
                fi
            fi

            local failures_after=${#failed_services[@]}
            if [ "$wait_rc" -ne 0 ] || [ "$worker_status" -ne 0 ] || [ "$merge_rc" -ne 0 ]; then
                printf -v "$had_failures_var" '%s' "true"
                if [ "$failures_after" -le "$failures_before" ]; then
                    local reason="status_nonzero"
                    if [ "$merge_rc" -ne 0 ]; then
                        reason="fragment_missing_or_invalid"
                    elif [ "$wait_rc" -ne 0 ] && [ "$worker_status" -eq 0 ]; then
                        reason="worker_wait_failed"
                    fi
                    failed_services+=("${worker_name} Startup|parallel worker failed (${reason}; wait_rc=${wait_rc}; worker_status=${worker_status}; fragment=${fragment_file})")
                fi
            fi

            rm -f "$fragment_file" 2>/dev/null || true
            unset 'pids_ref[idx]'
            unset 'fragments_ref[idx]'
            unset 'names_ref[idx]'
            unset 'started_ref[idx]'
            pids_ref=("${pids_ref[@]}")
            fragments_ref=("${fragments_ref[@]}")
            names_ref=("${names_ref[@]}")
            started_ref=("${started_ref[@]}")
            return 0
        done
        sleep 0.1
    done
}

run_all_trees_start_tree_projects_parallel() {
    local -a jobs=("$@")
    [ ${#jobs[@]} -gt 0 ] || return 0

    local max_jobs="${RUN_SH_OPT_PARALLEL_TREES_MAX:-4}"
    if ! [[ "$max_jobs" =~ ^[0-9]+$ ]] || [ "$max_jobs" -lt 1 ]; then
        max_jobs=4
    fi

    local fragment_dir="$LOGS_DIR/tree-start-fragments"
    mkdir -p "$fragment_dir"
    RUN_SH_PARALLEL_FRAGMENT_DIR="$fragment_dir"

    local -a worker_pids=()
    local -a worker_fragments=()
    local -a worker_names=()
    local -a worker_started_at=()
    local first_ready_ms=""
    local had_failures=false
    local entry=""
    local worker_index=0

    for entry in "${jobs[@]}"; do
        local tree_dir=""
        local feature_label=""
        local iter_count=""
        local force_feature_label=""
        local assigned_offset=""
        IFS=$'\t' read -r tree_dir feature_label iter_count force_feature_label assigned_offset <<< "$entry"
        local worker_name
        worker_name=$(basename "$tree_dir")
        local fragment_file="$fragment_dir/worker_${worker_index}_${worker_name}.state"
        worker_index=$((worker_index + 1))

        run_all_trees_parallel_worker "$fragment_file" "$tree_dir" "$feature_label" "$iter_count" "$force_feature_label" "$assigned_offset" &
        worker_pids+=("$!")
        worker_fragments+=("$fragment_file")
        worker_names+=("$worker_name")
        worker_started_at+=("$(date +%s 2>/dev/null || echo 0)")

        while [ ${#worker_pids[@]} -ge "$max_jobs" ]; do
            run_all_trees_collect_finished_parallel_worker worker_pids worker_fragments worker_names worker_started_at first_ready_ms had_failures
        done
    done

    while [ ${#worker_pids[@]} -gt 0 ]; do
        run_all_trees_collect_finished_parallel_worker worker_pids worker_fragments worker_names worker_started_at first_ready_ms had_failures
    done

    if [ -n "$first_ready_ms" ] && [ "$(type -t profile_mark_kpi_at)" = "function" ]; then
        profile_mark_kpi_at "ttftr_ms" "$first_ready_ms" "mode=parallel"
    fi

    rmdir "$fragment_dir" >/dev/null 2>&1 || true
    unset RUN_SH_PARALLEL_FRAGMENT_DIR

    [ "$had_failures" = false ]
}

run_all_trees_start_tree_projects() {
    echo -e "${CYAN}Running in TREES mode${NC}\n"

    if ! run_all_trees_prepare_tree_paths; then
        return 1
    fi

    if [ ${#ATTACH_SERVICE_INFO[@]} -eq 0 ] && [ "$AUTO_RESUME" = true ]; then
        if load_attach_state; then
            ATTACH_STATE_ENABLED=true
        fi
    fi

    local parallel_max="${RUN_SH_OPT_PARALLEL_TREES_MAX:-4}"
    local parallel_requested="${RUN_SH_OPT_PARALLEL_TREES:-false}"
    local parallel_explicit="${RUN_SH_OPT_PARALLEL_TREES_EXPLICIT:-false}"
    if ! [[ "$parallel_max" =~ ^[0-9]+$ ]]; then
        parallel_max=4
    fi

    port_offset=0
    local -A feature_counts=()
    local tree_dir=""
    local identity=""
    for tree_dir in "${tree_paths[@]}"; do
        identity=$(worktree_identity_from_dir "$tree_dir" "$BASE_DIR" "$TREES_DIR_NAME" 2>/dev/null || true)
        if [ -n "$identity" ]; then
            local feature_name="${identity%%|*}"
            feature_counts["$feature_name"]=$(( ${feature_counts["$feature_name"]:-0} + 1 ))
        fi
    done

    local -a jobs=()
    for tree_dir in "${tree_paths[@]}"; do
        identity=$(worktree_identity_from_dir "$tree_dir" "$BASE_DIR" "$TREES_DIR_NAME" 2>/dev/null || true)
        local feature_label=""
        local iter_count=1
        local force_feature_label=false

        if [ -n "$identity" ]; then
            local iter_name=""
            IFS='|' read -r feature_label iter_name <<< "$identity"
            iter_count=${feature_counts[$feature_label]:-1}
            if [ -n "$TREES_FEATURE_FILTER" ] && [ "$feature_label" != "$TREES_FEATURE_FILTER" ]; then
                continue
            fi
            if [[ "$tree_dir" == "$BASE_DIR/$TREES_DIR_NAME/$feature_label/"* ]]; then
                force_feature_label=true
            fi
        fi

        local name
        name=$(basename "$tree_dir")
        if ! tree_target_matches "$tree_dir" "$name"; then
            ((port_offset += PORT_SPACING))
            continue
        fi

        jobs+=("${tree_dir}"$'\t'"${feature_label}"$'\t'"${iter_count}"$'\t'"${force_feature_label}"$'\t'"${port_offset}")
        ((port_offset += PORT_SPACING))
    done

    local use_parallel=false
    local auto_parallel=false
    if [ "$parallel_explicit" != true ] && [ "${#jobs[@]}" -gt 1 ]; then
        auto_parallel=true
    fi

    if [ "$parallel_requested" = true ] && [ "$parallel_max" -gt 1 ]; then
        use_parallel=true
    elif [ "$auto_parallel" = true ] && [ "$parallel_max" -gt 1 ]; then
        use_parallel=true
    fi

    if [ "$use_parallel" = true ]; then
        echo -e "${CYAN}Tree startup mode: parallel (max workers: ${parallel_max})${NC}"
    else
        if [ "$parallel_requested" = true ] && [ "$parallel_max" -le 1 ]; then
            echo -e "${YELLOW}Tree startup mode: sequential (parallel requested but max workers=${parallel_max})${NC}"
        elif [ "$auto_parallel" = true ] && [ "$parallel_max" -le 1 ]; then
            echo -e "${YELLOW}Tree startup mode: sequential (auto-parallel skipped; max workers=${parallel_max})${NC}"
        else
            echo -e "${CYAN}Tree startup mode: sequential${NC}"
        fi
    fi

    local had_failures=false
    if [ "$use_parallel" = true ]; then
        if ! run_all_trees_start_tree_projects_parallel "${jobs[@]}"; then
            had_failures=true
        fi
    else
        local entry=""
        for entry in "${jobs[@]}"; do
            local start_tree_dir_path=""
            local start_feature_label=""
            local start_iter_count="1"
            local start_force_feature_label=false
            local start_assigned_offset=0
            IFS=$'\t' read -r start_tree_dir_path start_feature_label start_iter_count start_force_feature_label start_assigned_offset <<< "$entry"
            if ! start_tree_dir "$start_tree_dir_path" "$start_feature_label" "$start_iter_count" "$start_force_feature_label" "$start_assigned_offset"; then
                had_failures=true
            fi
        done
    fi

    [ "$had_failures" = false ]
}

envctl_define_flat_services() {
    local i=1
    local has_services=false
    while true; do
        local var_name="ENVCTL_SERVICE_${i}"
        local val="${!var_name:-}"
        if [ -z "$val" ]; then
            break
        fi
        has_services=true
        local s_name s_dir s_type s_port s_bport s_log
        IFS='|' read -r s_name s_dir s_type s_port s_bport s_log <<< "$val"

        [ -z "$s_name" ] && s_name="Service $i"
        [ -z "$s_dir" ] && s_dir="."
        [ -z "$s_type" ] && s_type="backend"

        s_name=$(trim "$s_name")
        s_dir=$(trim "$s_dir")
        s_type=$(trim "$s_type")
        s_port=$(trim "$s_port")
        s_bport=$(trim "$s_bport")
        s_log=$(trim "$s_log")

        if [[ "$s_dir" != /* ]]; then
            s_dir="$BASE_DIR/$s_dir"
        fi
        if [ -z "$s_log" ]; then
            s_log="$LOGS_DIR/svc_${i}"
        elif [[ "$s_log" != /* ]]; then
            s_log="$LOGS_DIR/$s_log"
        fi

        start_service_with_retry "$s_name" "$s_dir" "$s_type" "$s_port" "$s_bport" "$s_log"
        i=$((i+1))
    done

    if [ "$has_services" = true ]; then
        return 0
    fi
    return 1
}

run_all_trees_start_main_project() {
    echo -e "${CYAN}Running in MAIN mode${NC}\n"
    prev_backend_env_override="$BACKEND_ENV_FILE_OVERRIDE"
    prev_frontend_env_override="$FRONTEND_ENV_FILE_OVERRIDE"
    prev_skip_local_db_env="$SKIP_LOCAL_DB_ENV"
    if [ -n "$MAIN_ENV_FILE_PATH" ]; then
        echo -e "${GREEN}Main backend env override applied: $MAIN_ENV_FILE_PATH${NC}"
        BACKEND_ENV_FILE_OVERRIDE="$MAIN_ENV_FILE_PATH"
        SKIP_LOCAL_DB_ENV=true
    else
        echo -e "${CYAN}Using default backend env (.env) and local DB settings for Main.${NC}"
    fi
    if [ -n "$MAIN_FRONTEND_ENV_FILE_PATH" ]; then
        echo -e "${GREEN}Main frontend env override applied: $MAIN_FRONTEND_ENV_FILE_PATH${NC}"
    fi
    local start_rc=0
    if [ "$(type -t envctl_define_services)" = "function" ]; then
        echo -e "${CYAN}Using custom envctl_define_services hook...${NC}"
        envctl_define_services
        start_rc=$?
    elif envctl_define_flat_services; then
        echo -e "${CYAN}Loaded services from declarative configuration...${NC}"
        start_rc=0
    elif [ "$main_uses_supabase" = true ]; then
        old_db_port="$DB_PORT"
        supabase_db_port="${SUPABASE_TREE_DB_PORTS[$main_dir]:-}"
        if [ -n "$supabase_db_port" ]; then
            DB_PORT="$supabase_db_port"
        fi
        with_tree_db_overrides "$main_dir" start_project "Main" "$BASE_DIR" "$BACKEND_PORT_BASE" "$FRONTEND_PORT_BASE"
        start_rc=$?
        DB_PORT="$old_db_port"
    else
        start_project "Main" "$BASE_DIR" "$BACKEND_PORT_BASE" "$FRONTEND_PORT_BASE"
        start_rc=$?
    fi
    keep_main_overrides=false
    if [ -n "$MAIN_ENV_FILE_PATH" ] || [ -n "$MAIN_FRONTEND_ENV_FILE_PATH" ]; then
        keep_main_overrides=true
    fi
    if [ "$keep_main_overrides" = false ]; then
        BACKEND_ENV_FILE_OVERRIDE="$prev_backend_env_override"
        FRONTEND_ENV_FILE_OVERRIDE="$prev_frontend_env_override"
        SKIP_LOCAL_DB_ENV="$prev_skip_local_db_env"
    fi
    return "$start_rc"
}

run_all_trees_start_projects() {
    if [ "$TREES_MODE" = true ]; then
        run_all_trees_start_tree_projects
    else
        run_all_trees_start_main_project
    fi
}

start_tree_dir() {
    local tree_dir=$1
    local feature_label=$2
    local iter_count=$3
    local force_feature_label=$4
    local assigned_port_offset=${5:-$port_offset}
    local name
    name=$(basename "$tree_dir")

    if ! tree_target_matches "$tree_dir" "$name"; then
        ((port_offset += PORT_SPACING))
        return
    fi

    start_tree_job_with_offset "$tree_dir" "$feature_label" "$iter_count" "$force_feature_label" "$assigned_port_offset"
    ((port_offset += PORT_SPACING))
}
