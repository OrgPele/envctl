#!/usr/bin/env bash

# Debug trace logging helpers for run.sh.

debug_enabled() {
    case "${RUN_SH_DEBUG:-false}" in
        true|TRUE|1|yes|YES)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

debug_log_path() {
    if [ -n "${RUN_SH_DEBUG_LOG:-}" ]; then
        echo "$RUN_SH_DEBUG_LOG"
        return 0
    fi
    if [ -n "${LOGS_DIR:-}" ]; then
        echo "${LOGS_DIR%/}/run_debug.log"
        return 0
    fi
    local runtime_dir=""
    if [ "$(type -t run_sh_runtime_dir)" = "function" ]; then
        runtime_dir=$(run_sh_runtime_dir)
    else
        runtime_dir="${RUN_SH_RUNTIME_DIR:-/tmp/envctl-runtime}"
        mkdir -p "$runtime_dir" 2>/dev/null || true
    fi
    echo "${runtime_dir%/}/run_debug.log"
}

debug_log_init_prelog() {
    if ! debug_enabled; then
        return 0
    fi
    if [ -n "${LOGS_DIR:-}" ]; then
        return 0
    fi
    if [ -n "${DEBUG_LOG_PRELOG:-}" ] && [ -f "$DEBUG_LOG_PRELOG" ]; then
        return 0
    fi
    local prelog=""
    if command -v mktemp >/dev/null 2>&1; then
        prelog=$(mktemp "/tmp/envctl-run-prelog.XXXXXX" 2>/dev/null || true)
    fi
    if [ -z "$prelog" ]; then
        prelog="/tmp/envctl-run-prelog.$$"
        : > "$prelog"
    fi
    DEBUG_LOG_PRELOG="$prelog"
}

debug_log_finalize() {
    if ! debug_enabled; then
        return 0
    fi
    local log_path
    log_path=$(debug_log_path)
    mkdir -p "$(dirname "$log_path")"
    touch "$log_path"
    if [ -n "${DEBUG_LOG_PRELOG:-}" ] && [ -f "$DEBUG_LOG_PRELOG" ]; then
        cat "$DEBUG_LOG_PRELOG" >> "$log_path"
        rm -f "$DEBUG_LOG_PRELOG"
        DEBUG_LOG_PRELOG=""
    fi
}

debug_log_line() {
    if ! debug_enabled; then
        return 0
    fi
    local level=$1
    shift || true
    local message="$*"
    if [ -z "$level" ]; then
        level="INFO"
    fi
    local target=""
    if [ -n "${DEBUG_LOG_PRELOG:-}" ] && [ -f "$DEBUG_LOG_PRELOG" ] && [ -z "${LOGS_DIR:-}" ]; then
        target="$DEBUG_LOG_PRELOG"
    else
        target=$(debug_log_path)
        mkdir -p "$(dirname "$target")"
    fi
    printf '%s|%s|%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$level" "$message" >> "$target"
}

debug_trace_on() {
    if ! debug_enabled; then
        return 0
    fi
    if [ "${RUN_SH_DEBUG_XTRACE:-true}" != true ]; then
        return 0
    fi
    if [ -n "${DEBUG_XTRACE_FD:-}" ]; then
        return 0
    fi
    local log_path
    log_path=$(debug_log_path)
    mkdir -p "$(dirname "$log_path")"
    exec {DEBUG_XTRACE_FD}>>"$log_path"
    export BASH_XTRACEFD="$DEBUG_XTRACE_FD"
    export PS4='+ [ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)][pid=$$][func=${FUNCNAME[0]:-main}][line=${LINENO}] '
    set -x
}

debug_trace_off() {
    if ! debug_enabled; then
        return 0
    fi
    set +x
    if [ -n "${DEBUG_XTRACE_FD:-}" ]; then
        exec {DEBUG_XTRACE_FD}>&-
        unset DEBUG_XTRACE_FD
    fi
    unset BASH_XTRACEFD
    DEBUG_TRACE_SUSPEND_COUNT=0
}

debug_trace_suppress_begin() {
    if ! debug_enabled; then
        return 0
    fi
    if [ "${RUN_SH_DEBUG_ALLOW_SECRETS:-false}" = true ]; then
        return 0
    fi
    if [[ $- != *x* ]]; then
        return 0
    fi
    DEBUG_TRACE_SUSPEND_COUNT=$(( ${DEBUG_TRACE_SUSPEND_COUNT:-0} + 1 ))
    if [ "$DEBUG_TRACE_SUSPEND_COUNT" -eq 1 ]; then
        set +x
    fi
}

debug_trace_suppress_end() {
    if ! debug_enabled; then
        return 0
    fi
    if [ "${RUN_SH_DEBUG_ALLOW_SECRETS:-false}" = true ]; then
        return 0
    fi
    if [ "${DEBUG_TRACE_SUSPEND_COUNT:-0}" -le 0 ]; then
        return 0
    fi
    DEBUG_TRACE_SUSPEND_COUNT=$((DEBUG_TRACE_SUSPEND_COUNT - 1))
    if [ "$DEBUG_TRACE_SUSPEND_COUNT" -eq 0 ]; then
        set -x
    fi
}

debug_capture_env() {
    if ! debug_enabled; then
        return 0
    fi
    local mode="${RUN_SH_DEBUG_ENV_MODE:-redact}"
    if [ "$mode" = "none" ]; then
        debug_log_line "INFO" "env.snapshot skipped"
        return 0
    fi

    local log_path
    log_path=$(debug_log_path)
    mkdir -p "$(dirname "$log_path")"

    local redact_regex="${RUN_SH_DEBUG_ENV_REDACT_REGEX:-(TOKEN|SECRET|PASSWORD|KEY|AUTH|COOKIE|SESSION|PRIVATE)}"
    local allowlist="${RUN_SH_DEBUG_ENV_ALLOWLIST:-RUN_SH_,BACKEND_,FRONTEND_,SUPABASE_,N8N_}"
    allowlist="${allowlist// /,}"
    IFS=',' read -r -a allow_entries <<< "$allowlist"

    {
        echo "ENVIRONMENT SNAPSHOT (mode=${mode})"
        echo "redact_regex=${redact_regex}"
    } >> "$log_path"

    local prev_nocase
    prev_nocase=$(shopt -p nocasematch)
    shopt -s nocasematch

    while IFS= read -r line; do
        [ -n "$line" ] || continue
        local key="${line%%=*}"
        local value="${line#*=}"
        case "$mode" in
            allowlist)
                local allowed=false
                local entry=""
                for entry in "${allow_entries[@]}"; do
                    entry="${entry// /}"
                    [ -n "$entry" ] || continue
                    if [[ "$entry" == *"*" ]]; then
                        entry="${entry%\*}"
                    fi
                    if [[ "$key" == "$entry"* ]] || [ "$key" = "$entry" ]; then
                        allowed=true
                        break
                    fi
                done
                if [ "$allowed" = true ]; then
                    printf '%s=%s\n' "$key" "$value" >> "$log_path"
                fi
                ;;
            *)
                if [[ "$key" =~ $redact_regex ]]; then
                    value="***redacted***"
                fi
                printf '%s=%s\n' "$key" "$value" >> "$log_path"
                ;;
        esac
    done < <(env | sort)

    eval "$prev_nocase"
}

debug_capture_git_context() {
    if ! debug_enabled; then
        return 0
    fi
    local log_path
    log_path=$(debug_log_path)
    mkdir -p "$(dirname "$log_path")"

    {
        echo "GIT CONTEXT"
        if ! command -v git >/dev/null 2>&1; then
            echo "git unavailable"
        else
            local git_root=""
            if [ -n "${BASE_DIR:-}" ]; then
                git_root="$BASE_DIR"
            else
                git_root="$(pwd)"
            fi
            echo "git_root=${git_root}"
            git -C "$git_root" rev-parse --short HEAD 2>/dev/null | sed 's/^/commit=/' || true
            git -C "$git_root" status -sb 2>/dev/null | sed 's/^/status=/' || true
            git -C "$git_root" worktree list --porcelain 2>/dev/null | sed 's/^/worktree: /' || true
        fi
    } >> "$log_path"
}

debug_log_header() {
    if ! debug_enabled; then
        return 0
    fi
    local log_path
    log_path=$(debug_log_path)
    mkdir -p "$(dirname "$log_path")"

    {
        echo "RUN DEBUG HEADER"
        echo "timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "cwd=$(pwd)"
        echo "user=${USER:-}"
        echo "host=$(hostname 2>/dev/null || true)"
        echo "bash=${BASH_VERSION:-}"
        echo "uname=$(uname -a 2>/dev/null || true)"
        if [ -n "${ORIGINAL_ARGS[*]:-}" ]; then
            local args=""
            args=$(printf '%q ' "${ORIGINAL_ARGS[@]}" | sed 's/ $//')
            echo "args=${args}"
        fi
        echo "modes: trees=${TREES_MODE:-} main=${MAIN_MODE:-} docker=${DOCKER_MODE:-} interactive=${INTERACTIVE_MODE:-}"
        echo "ports: backend_base=${BACKEND_PORT_BASE:-} frontend_base=${FRONTEND_PORT_BASE:-} port_spacing=${PORT_SPACING:-} db_base=${DB_PORT_BASE:-} redis_base=${REDIS_PORT_BASE:-} supabase_public_base=${SUPABASE_PUBLIC_PORT_BASE:-} supabase_db_base=${SUPABASE_DB_PORT_BASE:-} n8n_base=${N8N_PORT_BASE:-}"
        local runtime_map_path_value=""
        if command -v runtime_map_path >/dev/null 2>&1; then
            runtime_map_path_value=$(runtime_map_path 2>/dev/null || true)
        fi
        echo "paths: logs_dir=${LOGS_DIR:-} state=${STATE_FILE:-} last_state=${LAST_STATE_FILE:-} runtime_map=${runtime_map_path_value}"
        echo "debug: stdio=${RUN_SH_DEBUG_STDIO:-} xtrace=${RUN_SH_DEBUG_XTRACE:-} interactive_trace=${RUN_SH_DEBUG_TRACE_INTERACTIVE:-} env_mode=${RUN_SH_DEBUG_ENV_MODE:-}"
    } >> "$log_path"
}
