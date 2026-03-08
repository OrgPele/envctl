#!/usr/bin/env bash

# TTY and interactive UI helpers.

UI_LIB_DIR="${UI_LIB_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
if ! command -v run_command >/dev/null 2>&1; then
    if [ -f "$UI_LIB_DIR/actions.sh" ]; then
        # shellcheck source=/dev/null
        source "$UI_LIB_DIR/actions.sh"
    fi
fi

prompt_yes_no() {
    local prompt=$1
    local reply=""
    if [ -t 0 ] && [ -t 1 ]; then
        read -r -p "$prompt" -n 1 reply
        echo
        if [[ "$reply" =~ ^[Yy]$ ]]; then
            return 0
        fi
    fi
    return 1
}

ui_can_interactive() {
    local tty="${TTY_DEVICE:-/dev/tty}"
    if [ -t 0 ] && [ -t 1 ]; then
        return 0
    fi
    if [ -r "$tty" ] && [ -w "$tty" ]; then
        if (stty -g < "$tty" >/dev/null 2>&1) 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}


read_char() {
    local timeout=$1
    local var_name=$2
    local tty="${TTY_DEVICE:-/dev/tty}"
    local read_failed=false
    if [ -r "$tty" ]; then
        if [ -n "$timeout" ]; then
            if ! IFS= read -rsn1 -t "$timeout" "$var_name" < "$tty" 2>/dev/null; then
                read_failed=true
            fi
        else
            if ! IFS= read -rsn1 "$var_name" < "$tty" 2>/dev/null; then
                read_failed=true
            fi
        fi
    else
        if [ -n "$timeout" ]; then
            if ! IFS= read -rsn1 -t "$timeout" "$var_name" 2>/dev/null; then
                read_failed=true
            fi
        else
            if ! IFS= read -rsn1 "$var_name" 2>/dev/null; then
                read_failed=true
            fi
        fi
    fi

    if [ "$read_failed" = true ]; then
        if [ -z "$timeout" ] && [ -r "$tty" ]; then
            TTY_READ_FAILED=true
            tty_restore_base
        fi
        return 1
    fi

    if [ "${TTY_READ_FAILED:-false}" = true ]; then
        TTY_READ_FAILED=false
    fi

    if [ -n "${KEY_DEBUG_LOG:-}" ]; then
        local value="${!var_name}"
        local hex=""
        if [ -n "$value" ]; then
            hex=$(printf '%s' "$value" | od -An -t x1 | tr -d ' \n')
        fi
        printf '%s read_char %s %q\n' "$(date +%s)" "$hex" "$value" >> "$KEY_DEBUG_LOG"
    fi
}


drain_pending_input() {
    local timeout=${KEY_DRAIN_TIMEOUT:-0.03}
    local max_reads=${KEY_DRAIN_READS:-6}
    local _key=""
    while [ "$max_reads" -gt 0 ]; do
        if ! read_char "$timeout" _key; then
            break
        fi
        max_reads=$((max_reads - 1))
    done
}


read_key() {
    local esc=$'\x1b'
    local key=""
    local seq=""
    local next=""
    local max_reads=${KEY_SEQ_MAX_READS}

    if [ "${SIGINT_REQUESTED:-false}" = true ]; then
        echo -n "esc"
        return 0
    fi
    if [ "${TTY_READ_FAILED:-false}" = true ]; then
        echo -n "esc"
        return 0
    fi

    if ! read_char "" key; then
        if [ "${TTY_READ_FAILED:-false}" = true ]; then
            echo -n "esc"
            return 0
        fi
        echo -n "noop"
        return 0
    fi

    if [ "$key" = $'\x03' ]; then
        SIGINT_REQUESTED=true
        echo -n "esc"
        return 0
    fi

    if [ "$key" = $'\r' ] || [ "$key" = $'\n' ]; then
        if [ -n "${KEY_DEBUG_LOG:-}" ]; then
            printf '%s read_key enter\n' "$(date +%s)" >> "$KEY_DEBUG_LOG"
        fi
        echo -n "enter"
        return 0
    fi
    if [ "$key" != "$esc" ]; then
        if [ -n "${KEY_DEBUG_LOG:-}" ]; then
            printf '%s read_key char %q\n' "$(date +%s)" "$key" >> "$KEY_DEBUG_LOG"
        fi
        echo -n "$key"
        return 0
    fi

    if ! read_char "$KEY_ESC_WAIT_TIMEOUT" next; then
        if [ -n "${KEY_DEBUG_LOG:-}" ]; then
            printf '%s read_key esc-timeout\n' "$(date +%s)" >> "$KEY_DEBUG_LOG"
        fi
        drain_pending_input
        echo -n "esc"
        return 0
    fi
    if [ "$next" != "[" ] && [ "$next" != "O" ]; then
        if [ -n "${KEY_DEBUG_LOG:-}" ]; then
            printf '%s read_key esc-other %q\n' "$(date +%s)" "$next" >> "$KEY_DEBUG_LOG"
        fi
        drain_pending_input
        echo -n "esc"
        return 0
    fi
    seq="$next"
    while [ "$max_reads" -gt 0 ]; do
        if ! read_char "$KEY_ESC_IDLE_TIMEOUT" next; then
            break
        fi
        seq+="$next"
        max_reads=$((max_reads - 1))
        case "$next" in
            [A-Za-z~])
                break
                ;;
        esac
    done

    if [ -n "${KEY_DEBUG_LOG:-}" ]; then
        local hex=""
        if [ -n "$seq" ]; then
            hex=$(printf '%s' "$seq" | od -An -t x1 | tr -d ' \n')
        fi
        printf '%s read_key esc %s %q\n' "$(date +%s)" "$hex" "$seq" >> "$KEY_DEBUG_LOG"
    fi

    case "$seq" in
        *A)
            if [ -n "${KEY_DEBUG_LOG:-}" ]; then
                printf '%s read_key match up\n' "$(date +%s)" >> "$KEY_DEBUG_LOG"
            fi
            echo -n "[A"
            return 0
            ;;
        *B)
            if [ -n "${KEY_DEBUG_LOG:-}" ]; then
                printf '%s read_key match down\n' "$(date +%s)" >> "$KEY_DEBUG_LOG"
            fi
            echo -n "[B"
            return 0
            ;;
        *C)
            if [ -n "${KEY_DEBUG_LOG:-}" ]; then
                printf '%s read_key match right\n' "$(date +%s)" >> "$KEY_DEBUG_LOG"
            fi
            echo -n "[C"
            return 0
            ;;
        *D)
            if [ -n "${KEY_DEBUG_LOG:-}" ]; then
                printf '%s read_key match left\n' "$(date +%s)" >> "$KEY_DEBUG_LOG"
            fi
            echo -n "[D"
            return 0
            ;;
    esac

    if [ -n "${KEY_DEBUG_LOG:-}" ]; then
        printf '%s read_key esc-unhandled %q\n' "$(date +%s)" "$seq" >> "$KEY_DEBUG_LOG"
    fi
    drain_pending_input
    echo -n "noop"
}


read_command() {
    local cmd=""
    local tty="${TTY_DEVICE:-/dev/tty}"
    local tty_state=""
    local read_ok=true
    local eof_sentinel="${READ_COMMAND_EOF_SENTINEL:-__RUN_SH_READ_EOF__}"

    if [ -r "$tty" ]; then
        tty_flush_input
        tty_state=$(stty -g < "$tty" 2>/dev/null || true)
        stty -isig < "$tty" 2>/dev/null || true
        if ! IFS= read -r cmd < "$tty"; then
            read_ok=false
        fi
        if [ -n "$tty_state" ]; then
            stty "$tty_state" < "$tty" 2>/dev/null || true
        fi
    else
        if ! IFS= read -r cmd; then
            read_ok=false
        fi
    fi

    if [ "$read_ok" != true ]; then
        echo "$eof_sentinel"
        return 0
    fi

    if [[ "$cmd" == *$'\x03'* ]]; then
        SIGINT_REQUESTED=true
        cmd=${cmd//$'\x03'/}
    fi
    cmd=${cmd//$'\r'/}
    cmd=${cmd//$'\x1b'/}
    cmd=$(printf '%s' "$cmd" | sed -E 's/\[[0-9;]*[[:alpha:]~]//g; s/O[ABCD]//g; s/\[[0-9;]*//g')
    cmd=$(trim "$cmd")

    case "$cmd" in
        '[A'|'[B'|'[C'|'[D'|'OA'|'OB'|'OC'|'OD')
            echo ""
            return 0
            ;;
    esac

    echo "$cmd"
}


tty_raw_on() {
    local tty="${TTY_DEVICE:-/dev/tty}"
    if [ -r "$tty" ]; then
        tty_prepare_prompt
        local state
        state=$(stty -g < "$tty" 2>/dev/null || true)
        if [ -z "$state" ]; then
            return 1
        fi
        stty -icanon -echo -isig -ixon min 1 time 0 < "$tty" 2>/dev/null || return 1
        if [ -n "${KEY_DEBUG_LOG:-}" ]; then
            printf '%s tty_raw_on %s\n' "$(date +%s)" "$state" >> "$KEY_DEBUG_LOG"
        fi
        echo "$state"
        return 0
    fi
    return 1
}


tty_raw_off() {
    local state=$1
    local tty="${TTY_DEVICE:-/dev/tty}"
    if [ -n "$state" ] && [ -r "$tty" ]; then
        stty "$state" < "$tty" 2>/dev/null || true
        if [ -n "${KEY_DEBUG_LOG:-}" ]; then
            printf '%s tty_raw_off %s\n' "$(date +%s)" "$state" >> "$KEY_DEBUG_LOG"
        fi
    fi
}


tty_restore_base() {
    if [ -n "$TTY_BASE_STATE" ] && [ -r "$TTY_DEVICE" ]; then
        stty "$TTY_BASE_STATE" < "$TTY_DEVICE" 2>/dev/null || true
    fi
}


tty_flush_input() {
    local tty="${TTY_DEVICE:-/dev/tty}"
    local _key=""
    local timeout=${TTY_FLUSH_TIMEOUT:-0.03}
    if [ -r "$tty" ]; then
        while read_char "$timeout" _key; do
            : # drain pending bytes
        done
    else
        while read_char "$timeout" _key; do
            :
        done
    fi
}


menu_cleanup() {
    local tty_state=$1
    tput rmkx >&2 2>/dev/null || true
    tput cnorm >&2 2>/dev/null || true
    tty_flush_input
    tty_raw_off "$tty_state"
}


menu_setup() {
    tput smkx >&2 2>/dev/null || true
}


request_sigint_quit() {
    SIGINT_REQUESTED=true
    tty_restore_base
}


tty_prepare_prompt() {
    local tty="${TTY_DEVICE:-/dev/tty}"
    if [ ! -r "$tty" ]; then
        return 0
    fi

    if [ -n "$TTY_BASE_STATE" ]; then
        stty "$TTY_BASE_STATE" < "$tty" 2>/dev/null || true
    fi

    local stty_dump
    stty_dump=$(stty -a < "$tty" 2>/dev/null || true)
    if [ -n "${KEY_DEBUG_LOG:-}" ]; then
        printf '%s tty_prepare_prompt %q\n' "$(date +%s)" "$stty_dump" >> "$KEY_DEBUG_LOG"
    fi
    if echo "$stty_dump" | grep -q -- '-icanon' || echo "$stty_dump" | grep -q -- '-echo' || echo "$stty_dump" | grep -q -- '-isig' || echo "$stty_dump" | grep -q -- '-ixon'; then
        stty sane < "$tty" 2>/dev/null || true
        TTY_BASE_STATE=$(stty -g < "$tty" 2>/dev/null || true)
    fi
}

select_menu() (
    local prompt=$1
    local options_name=$2
    local values_name=${3:-}
    local -n options_ref="$options_name"
    local has_values=false
    if [ -n "$values_name" ]; then
        local -n values_ref="$values_name"
        has_values=true
    fi

    if [ ${#options_ref[@]} -eq 0 ]; then
        echo ""
        return 1
    fi

    local selected=0
    local total=${#options_ref[@]}
    local redraw=false
    local tty_state=""
    tty_state=$(tty_raw_on 2>/dev/null || true)
    menu_setup
    tty_flush_input
    trap 'menu_cleanup "'"$tty_state"'"' EXIT

    tput civis >&2 2>/dev/null || true
    echo -e "${CYAN}$prompt (↑/↓ to move, Enter to select, q to cancel):${NC}" >&2

    for i in "${!options_ref[@]}"; do
        if [ "$i" -eq "$selected" ]; then
            echo -e "  ${GREEN}▶${NC} ${CYAN}${options_ref[$i]}${NC}" >&2
        else
            echo -e "    ${options_ref[$i]}" >&2
        fi
    done

    while true; do
        key=$(read_key)

        case "$key" in
            noop)
                continue
                ;;
            esc|q|Q)
                tput cnorm >&2 2>/dev/null || true
                echo "" >&2
                echo ""
                return 1
                ;;
            '[A'|'OA')
                ((selected = (selected - 1 + total) % total))
                redraw=true
                ;;
            '[B'|'OB')
                ((selected = (selected + 1) % total))
                redraw=true
                ;;
            ''|enter)
                tput cnorm >&2 2>/dev/null || true
                echo "" >&2
                if [ "$has_values" = true ]; then
                    echo "${values_ref[$selected]}"
                else
                    echo "${options_ref[$selected]}"
                fi
                return 0
                ;;
        esac

        if [ "$redraw" = true ]; then
            printf "\033[%dA" "$total" >&2
            for i in "${!options_ref[@]}"; do
                printf "\r\033[K" >&2
                if [ "$i" -eq "$selected" ]; then
                    echo -e "  ${GREEN}▶${NC} ${CYAN}${options_ref[$i]}${NC}" >&2
                else
                    echo -e "    ${options_ref[$i]}" >&2
                fi
            done
            redraw=false
        fi
    done
)


append_menu_option() {
    local -n options_ref=$1
    local -n values_ref=$2
    local label=$3
    local value=$4

    if [ -n "$label" ]; then
        options_ref+=("$label")
        values_ref+=("$value")
    fi
}


append_service_options() {
    local -n options_ref=$1
    local -n values_ref=$2

    for service in "${services[@]}"; do
        parse_service_entry "$service" name url docs || continue
        options_ref+=("$name")
        values_ref+=("$name")
    done
}


append_project_options() {
    local -n options_ref=$1
    local -n values_ref=$2
    local suffix=${3:-" (all)"}
    local value_prefix=${4:-"__PROJECT__:"}
    local require_trees=${5:-false}

    if [ "$require_trees" = true ] && [ "$TREES_MODE" != true ]; then
        return 0
    fi

    local project
    while IFS= read -r project; do
        [ -z "$project" ] && continue
        local label="$project"
        if [ -n "$suffix" ]; then
            label+="$suffix"
        fi
        options_ref+=("$label")
        values_ref+=("${value_prefix}${project}")
    done < <(get_project_names)
}

# Function to select service interactively with arrow keys
select_service() (
    local prompt=${1:-"Select service"}
    local include_all=${2:-false}
    local options=()
    local values=()

    if [ "$include_all" = true ]; then
        append_menu_option options values "All services" "__ALL__"
    fi
    append_service_options options values

    select_menu "$prompt" options values
)

# Function to select a restart target (service, project group, or all)
select_restart_target() (
    local prompt=${1:-"Restart"}
    local options=()
    local values=()

    append_menu_option options values "All services" "__ALL__"
    append_project_options options values " (all)" "__PROJECT__:" true
    append_service_options options values

    select_menu "$prompt" options values
)

select_pr_target() (
    local prompt=${1:-"Create PR for"}
    local options=()
    local values=()

    append_menu_option options values "All projects" "__ALL__"
    append_project_options options values "" "__PROJECT__:" false

    select_menu "$prompt" options values
)


select_test_target() (
    local prompt=${1:-"Run tests for"}
    local options=()
    local values=()

    local projects=()
    local project
    while IFS= read -r project; do
        [ -n "$project" ] && projects+=("$project")
    done < <(get_project_names)

    local untested_projects=()
    local total_projects=${#projects[@]}
    if [ "$total_projects" -gt 0 ] && has_passing_tests; then
        for project in "${projects[@]}"; do
            if [ "$(project_tests_status "$project")" = "none" ]; then
                untested_projects+=("$project")
            fi
        done
        if [ ${#untested_projects[@]} -gt 0 ] && [ ${#untested_projects[@]} -lt "$total_projects" ]; then
            append_menu_option options values "Run untested projects" "__UNTESTED__"
        fi
    fi

    if [ ${#projects[@]} -gt 1 ]; then
        append_menu_option options values "All projects" "__ALL__"
    fi

    for project in "${projects[@]}"; do
        options+=("$project")
        values+=("__PROJECT__:$project")
    done

    select_menu "$prompt" options values
)

select_analyze_mode() (
    local prompt=${1:-"Select analysis mode"}
    local options=(
        "Single implementation (current tree)"
        "Grouped by service (all iterations)"
    )
    local values=("single" "grouped")

    select_menu "$prompt" options values
)

# Function to select a grouped target (all, project, or service)
select_grouped_target() (
    local prompt=${1:-"Select target"}
    local options=()
    local values=()

    append_menu_option options values "All services" "__ALL__"
    append_project_options options values " (all)" "__PROJECT__:" false
    append_service_options options values

    select_menu "$prompt" options values
)

# Function to select a grouped project target (all projects or project)
select_project_target() (
    local prompt=${1:-"Select target"}
    local options=()
    local values=()

    append_menu_option options values "All projects" "__ALL__"
    append_project_options options values " (all)" "__PROJECT__:" false

    select_menu "$prompt" options values
)

resolve_backend_env_file() (
    local backend_dir=$1
    local env_file=""

    if [ -n "${BACKEND_ENV_FILE_OVERRIDE:-}" ] && [ -f "$BACKEND_ENV_FILE_OVERRIDE" ]; then
        env_file="$BACKEND_ENV_FILE_OVERRIDE"
    elif [ -f "$backend_dir/.env" ]; then
        env_file="$backend_dir/.env"
    fi

    if [ -n "$env_file" ]; then
        echo "$(cd "$(dirname "$env_file")" && pwd)/$(basename "$env_file")"
    fi
)

migration_db_hint() {
    local project_name=$1
    local backend_dir=$2
    local python_path=$3

    local env_file=""
    env_file=$(resolve_backend_env_file "$backend_dir")
    if [ -n "$env_file" ]; then
        echo -e "${BLUE}Env file: ${env_file}${NC}"
    fi

    local db_url_redacted=""
    db_url_redacted=$(
        cd "$backend_dir" && "$python_path" - <<'PY' 2>/dev/null
from __future__ import annotations

import sys

try:
    from app.core.config import settings
    from app.db.url import redact_database_url
except Exception:
    sys.exit(1)

try:
    print(redact_database_url(str(settings.DATABASE_URL)))
except Exception:
    sys.exit(2)
PY
    ) || true

    if [ -n "$db_url_redacted" ]; then
        echo -e "${BLUE}Database URL (redacted): ${db_url_redacted}${NC}"
    else
        echo -e "${YELLOW}Unable to resolve DATABASE_URL for ${project_name}. Ensure migrations run in the same environment as the app.${NC}"
    fi
}

# Restart both backend and frontend for a project

ui_docker_handle_command() {
    local cmd=$1
    case "$cmd" in
        s|stop)
            echo -e
            CLEANUP_KILL_PORT_RANGES=false
            echo -e "${YELLOW}Stopping app services (databases preserved)...${NC}"
            docker_stop_services
            return 0
            ;;
        r|restart)
            local selected
            selected=$(docker_select_service "Restart" true) || return 3
            selected=$(trim "$selected")
            [ -n "$selected" ] || return 3
            docker_restart_service "$selected"
            return 0
            ;;
        b|build|rebuild)
            local selected
            selected=$(docker_select_build_target) || return 3
            [ -n "$selected" ] || return 3
            docker_rebuild_services "$selected"
            return 0
            ;;
        l|logs)
            local selected
            selected=$(docker_select_service "Tail logs for" true) || return 3
            selected=$(trim "$selected")
            [ -n "$selected" ] || return 3
            docker_tail_logs "$selected"
            return 3
            ;;
        h|health)
            docker_check_health
            return 0
            ;;
        e|errors)
            docker_show_errors
            return 0
            ;;
        q|quit)
            echo -e "${YELLOW}Exiting Docker mode (containers continue running)${NC}"
            trap - INT
            return 2
            ;;
        stop-all|stopall)
            local remove_volumes=false
            if prompt_yes_no "Remove database containers and volumes? (y/N): "; then
                remove_volumes=true
            fi
            CLEANUP_KILL_PORT_RANGES=true
            echo -e "${YELLOW}Stopping all services and databases...${NC}"
            docker_stop_all "$remove_volumes"
            cleanup_kill_port_ranges
            return 0
            ;;
        *)
            echo -e "${RED}Invalid command: $cmd${NC}"
            return 0
            ;;
    esac
}

ui_interactive_handle_command() {
    local cmd=$1
    case "$cmd" in
        s|stop)
            run_command "$cmd"
            return $?
            ;;
        r|restart)
            local selected
            selected=$(select_restart_target "Restart") || return 3
            selected=$(trim "$selected")
            [ -n "$selected" ] || return 3
            run_command "restart" "$selected"
            return $?
            ;;
        t|test|tests)
            local selected
            selected=$(select_test_target "Run tests for") || return 3
            selected=$(trim "$selected")
            [ -n "$selected" ] || return 3
            run_command "test" "$selected"
            return $?
            ;;
        p|pr|prs)
            local selected
            selected=$(select_pr_target "Create PR for") || return 3
            selected=$(trim "$selected")
            [ -n "$selected" ] || return 3
            run_command "pr" "$selected"
            return $?
            ;;
        c|commit)
            local selected
            selected=$(select_pr_target "Commit changes for") || return 3
            selected=$(trim "$selected")
            [ -n "$selected" ] || return 3
            run_command "commit" "$selected"
            return $?
            ;;
        a|analyze)
            local selected
            selected=$(select_project_target "Analyze changes for") || return 3
            selected=$(trim "$selected")
            [ -n "$selected" ] || return 3
            run_command "analyze" "$selected"
            return $?
            ;;
        m|migrate|migration|migrations)
            local selected
            selected=$(select_project_target "Run migrations for") || return 3
            selected=$(trim "$selected")
            [ -n "$selected" ] || return 3
            run_command "migrate" "$selected"
            return $?
            ;;
        l|logs)
            local selected
            selected=$(select_grouped_target "Tail logs for") || return 3
            selected=$(trim "$selected")
            [ -n "$selected" ] || return 3
            run_command "logs" "$selected"
            return $?
            ;;
        h|health)
            run_command "health"
            return $?
            ;;
        e|errors)
            local selected
            selected=$(select_grouped_target "Errors for") || return 3
            selected=$(trim "$selected")
            [ -n "$selected" ] || return 3
            run_command "errors" "$selected"
            return $?
            ;;
        q|quit)
            run_command "quit"
            return $?
            ;;
        stop-all|stopall)
            run_command "stop-all"
            return $?
            ;;
        *)
            echo -e "${RED}Invalid command: $cmd${NC}"
            return 0
            ;;
    esac
}

interactive_mode_docker() {
    if ! ui_can_interactive; then
        echo -e "${YELLOW}Interactive Docker mode requires a TTY; skipping interactive loop.${NC}"
        return 0
    fi

    echo -e "\n${CYAN}========================================${NC}"
    echo -e "${CYAN}Development Environment - Docker Mode${NC}"
    echo -e "${CYAN}========================================${NC}"

    SIGINT_REQUESTED=false
    trap 'request_sigint_quit' INT

    while true; do
        local eof_sentinel="${READ_COMMAND_EOF_SENTINEL:-__RUN_SH_READ_EOF__}"
        if [ "${SIGINT_REQUESTED:-false}" = true ]; then
            SIGINT_REQUESTED=false
            cmd="q"
        else
            cleanup_docker_log_followers
            docker_show_status

            echo -e "${CYAN}Commands:${NC} (s)top | (r)estart | (b)uild | (l)ogs | (h)ealth | (e)rrors | (q)uit | stop-all"
            echo -n "Enter command: "
            tty_prepare_prompt
            cmd=$(read_command)
            if [ "$SIGINT_REQUESTED" = true ]; then
                SIGINT_REQUESTED=false
                cmd="q"
            fi
        fi

        case "$cmd" in
            "$eof_sentinel")
                echo -e "${YELLOW}No interactive TTY input available; leaving Docker interactive mode.${NC}"
                break
                ;;
            ''|enter)
                continue
                ;;
        esac

        ui_docker_handle_command "$cmd"
        local rc=$?
        if [ "$rc" -eq 2 ]; then
            break
        fi
        if [ "$rc" -eq 3 ]; then
            continue
        fi

        echo -e "\nPress Enter to continue..."
        read -r
    done
    trap - INT
}

# Interactive mode function

interactive_mode() {
    if ! ui_can_interactive; then
        echo -e "${YELLOW}Interactive mode requires a TTY; skipping interactive loop.${NC}"
        return 0
    fi

    local skip_header=false
    case "${RUN_SH_INTERACTIVE_SKIP_HEADER:-false}" in
        1|true|TRUE|yes|YES|y|Y|on|ON)
            skip_header=true
            ;;
    esac
    if [ "$skip_header" = true ]; then
        RUN_SH_INTERACTIVE_SKIP_HEADER=false
    else
        echo -e "\n${CYAN}========================================${NC}"
        echo -e "${CYAN}Development Environment - Interactive Mode${NC}"
        echo -e "${CYAN}========================================${NC}"
    fi

    SIGINT_REQUESTED=false
    trap 'request_sigint_quit' INT

    local skip_initial_render=false
    case "${RUN_SH_INTERACTIVE_SKIP_FIRST_RENDER:-false}" in
        1|true|TRUE|yes|YES|y|Y|on|ON)
            skip_initial_render=true
            ;;
    esac
    if [ "$skip_initial_render" = true ]; then
        RUN_SH_INTERACTIVE_SKIP_FIRST_RENDER=false
    fi

    while true; do
        local eof_sentinel="${READ_COMMAND_EOF_SENTINEL:-__RUN_SH_READ_EOF__}"
        if [ "${SIGINT_REQUESTED:-false}" = true ]; then
            SIGINT_REQUESTED=false
            cmd="q"
        else
            if [ "$skip_initial_render" = true ]; then
                skip_initial_render=false
            else
                show_status false
                if [ "$(type -t run_all_trees_write_dashboard)" = "function" ]; then
                    run_all_trees_write_dashboard
                fi
            fi

            echo -e "${CYAN}Commands:${NC} (s)top | (r)estart | (t)est | (p)r | (c)ommit | (a)nalyze | (m)igrate | (l)ogs | (h)ealth | (e)rrors | (q)uit | stop-all"
            echo -n "Enter command: "
            tty_prepare_prompt
            cmd=$(read_command)
            if [ "$SIGINT_REQUESTED" = true ]; then
                SIGINT_REQUESTED=false
                cmd="q"
            fi
        fi

        case "$cmd" in
            "$eof_sentinel")
                echo -e "${YELLOW}No interactive TTY input available; leaving interactive mode.${NC}"
                break
                ;;
            ''|enter)
                continue
                ;;
        esac

        ui_interactive_handle_command "$cmd"
        local rc=$?
        if [ "$rc" -eq 2 ]; then
            break
        fi
        if [ "$rc" -eq 3 ]; then
            continue
        fi

        echo -e "\nPress Enter to continue..."
        read -r
    done
    trap - INT
}
