#!/usr/bin/env bash

# Core helpers: logging, colors, error handling.

supports_color() {
    [ -t 1 ] || return 1
    [ -z "${NO_COLOR:-}" ] || return 1
    [ "${TERM:-}" != "dumb" ] || return 1
    return 0
}

_init_colors() {
    if supports_color; then
        RED='\033[0;31m'
        GREEN='\033[0;32m'
        YELLOW='\033[1;33m'
        BLUE='\033[0;34m'
        CYAN='\033[0;36m'
        MAGENTA='\033[0;35m'
        WHITE='\033[0;37m'
        GRAY='\033[0;90m'
        BOLD='\033[1m'
        NC='\033[0m'
    else
        RED=''
        GREEN=''
        YELLOW=''
        BLUE=''
        CYAN=''
        MAGENTA=''
        WHITE=''
        GRAY=''
        BOLD=''
        NC=''
    fi
}

_init_colors

run_sh_runtime_dir() {
    local dir="${RUN_SH_RUNTIME_DIR:-/tmp/envctl-runtime}"
    if [[ "$dir" != /* ]] && [ -n "${BASE_DIR:-}" ]; then
        dir="${BASE_DIR%/}/$dir"
    fi
    mkdir -p "$dir" 2>/dev/null || true
    printf '%s\n' "$dir"
}

if ! declare -p RUN_SH_PROFILE_STARTS >/dev/null 2>&1; then
    declare -Ag RUN_SH_PROFILE_STARTS=()
fi
if ! declare -p RUN_SH_PROFILE_KPI_MARKS >/dev/null 2>&1; then
    declare -Ag RUN_SH_PROFILE_KPI_MARKS=()
fi

log_info() {
    printf '%b\n' "${CYAN}$*${NC}"
}

log_warn() {
    printf '%b\n' "${YELLOW}$*${NC}" >&2
}

log_error() {
    printf '%b\n' "${RED}$*${NC}" >&2
}

die() {
    local msg=$1
    local code=${2:-1}
    log_error "$msg"
    exit "$code"
}

ensure_assoc_array() {
    local name=$1
    [ -n "$name" ] || return 1
    local decl=""
    decl=$(declare -p "$name" 2>/dev/null || true)
    if [[ "$decl" == "declare -A"* ]]; then
        return 0
    fi
    unset "$name"
    if declare -g -A "$name" 2>/dev/null; then
        return 0
    fi
    declare -A "$name"
}

ensure_assoc_array RUN_SH_PROFILE_STARTS
ensure_assoc_array RUN_SH_PROFILE_COUNTERS
ensure_assoc_array RUN_SH_PROFILE_KPI_MARKS

profile_enabled() {
    [ "${RUN_SH_PROFILE:-false}" = true ]
}

profile_log_path() {
    if [ -n "${RUN_SH_PROFILE_LOG:-}" ]; then
        echo "$RUN_SH_PROFILE_LOG"
        return 0
    fi
    if [ -n "${LOGS_DIR:-}" ]; then
        echo "${LOGS_DIR%/}/run_profile.log"
        return 0
    fi
    local runtime_dir=""
    if [ "$(type -t run_sh_runtime_dir)" = "function" ]; then
        runtime_dir=$(run_sh_runtime_dir)
    else
        runtime_dir="${RUN_SH_RUNTIME_DIR:-/tmp/envctl-runtime}"
        mkdir -p "$runtime_dir" 2>/dev/null || true
    fi
    echo "${runtime_dir%/}/run_profile.log"
}

profile_now_ms() {
    local ns=""
    # On macOS, date +%s%N outputs a literal 'N'; try gdate first
    if [[ "${OSTYPE:-}" == darwin* ]] && command -v gdate >/dev/null 2>&1; then
        ns=$(gdate +%s%N 2>/dev/null || true)
    else
        ns=$(date +%s%N 2>/dev/null || true)
    fi
    if [[ "$ns" =~ ^[0-9]+$ ]] && [ ${#ns} -gt 10 ]; then
        echo $((ns / 1000000))
        return 0
    fi
    local sec=""
    sec=$(date +%s 2>/dev/null || true)
    if [[ "$sec" =~ ^[0-9]+$ ]]; then
        echo $((sec * 1000))
        return 0
    fi
    echo 0
}

profile_set_run_start() {
    if ! profile_enabled; then
        return 0
    fi
    if [ -z "${RUN_SH_PROFILE_RUN_START_MS:-}" ]; then
        RUN_SH_PROFILE_RUN_START_MS="$(profile_now_ms)"
    fi
}

profile_start() {
    local phase=$1
    [ -n "$phase" ] || return 1
    if ! profile_enabled; then
        return 0
    fi
    if ! ensure_assoc_array RUN_SH_PROFILE_STARTS >/dev/null 2>&1; then
        return 0
    fi
    RUN_SH_PROFILE_STARTS["$phase"]="$(profile_now_ms)"
}

profile_end() {
    local phase=$1
    [ -n "$phase" ] || return 1
    if ! profile_enabled; then
        return 0
    fi
    if ! ensure_assoc_array RUN_SH_PROFILE_STARTS >/dev/null 2>&1; then
        return 0
    fi
    local start="${RUN_SH_PROFILE_STARTS[$phase]:-}"
    if [ -z "$start" ]; then
        return 0
    fi
    if ! [[ "$start" =~ ^[0-9]+$ ]]; then
        return 0
    fi
    local end
    end=$(profile_now_ms)
    if ! [[ "$end" =~ ^[0-9]+$ ]]; then
        return 0
    fi
    local duration=$((end - start))
    if [ "$duration" -lt 0 ]; then
        duration=0
    fi
    local log_path
    log_path=$(profile_log_path)
    mkdir -p "$(dirname "$log_path")"
    printf '%s|%s\n' "$phase" "$duration" >> "$log_path"
}

profile_mark_kpi() {
    local key=$1
    local note=${2:-}
    [ -n "$key" ] || return 1
    if ! profile_enabled; then
        return 0
    fi
    if ! ensure_assoc_array RUN_SH_PROFILE_KPI_MARKS >/dev/null 2>&1; then
        return 0
    fi
    profile_set_run_start
    if [ -n "${RUN_SH_PROFILE_KPI_MARKS[$key]:-}" ]; then
        return 0
    fi
    local now
    now=$(profile_now_ms)
    local start_ms="${RUN_SH_PROFILE_RUN_START_MS:-$now}"
    local duration=$((now - start_ms))
    local log_path
    log_path=$(profile_log_path)
    mkdir -p "$(dirname "$log_path")"
    printf 'kpi.%s|%s|%s\n' "$key" "$duration" "$note" >> "$log_path"
    RUN_SH_PROFILE_KPI_MARKS["$key"]=1
}

profile_mark_kpi_at() {
    local key=$1
    local timestamp_ms=$2
    local note=${3:-}
    [ -n "$key" ] || return 1
    if ! profile_enabled; then
        return 0
    fi
    if ! ensure_assoc_array RUN_SH_PROFILE_KPI_MARKS >/dev/null 2>&1; then
        return 0
    fi
    profile_set_run_start
    if [ -n "${RUN_SH_PROFILE_KPI_MARKS[$key]:-}" ]; then
        return 0
    fi
    if ! [[ "$timestamp_ms" =~ ^[0-9]+$ ]]; then
        return 1
    fi
    local start_ms="${RUN_SH_PROFILE_RUN_START_MS:-$timestamp_ms}"
    local duration=$((timestamp_ms - start_ms))
    if [ "$duration" -lt 0 ]; then
        duration=0
    fi
    local log_path
    log_path=$(profile_log_path)
    mkdir -p "$(dirname "$log_path")"
    printf 'kpi.%s|%s|%s\n' "$key" "$duration" "$note" >> "$log_path"
    RUN_SH_PROFILE_KPI_MARKS["$key"]=1
}

profile_counter_increment() {
    local key=$1
    [ -n "$key" ] || return 1
    if ! profile_enabled; then
        return 0
    fi
    if [ "${RUN_SH_PROFILE_VERBOSE:-false}" != true ]; then
        return 0
    fi
    if ! ensure_assoc_array RUN_SH_PROFILE_COUNTERS >/dev/null 2>&1; then
        return 0
    fi
    local current=${RUN_SH_PROFILE_COUNTERS[$key]:-0}
    RUN_SH_PROFILE_COUNTERS["$key"]=$((current + 1))
}

profile_dump_counters() {
    if ! profile_enabled; then
        return 0
    fi
    if [ "${RUN_SH_PROFILE_VERBOSE:-false}" != true ]; then
        return 0
    fi
    if ! ensure_assoc_array RUN_SH_PROFILE_COUNTERS >/dev/null 2>&1; then
        return 0
    fi
    local log_path
    log_path=$(profile_log_path)
    mkdir -p "$(dirname "$log_path")"
    local key
    for key in "${!RUN_SH_PROFILE_COUNTERS[@]}"; do
        printf 'counter.%s|%s\n' "$key" "${RUN_SH_PROFILE_COUNTERS[$key]}" >> "$log_path"
    done
}
