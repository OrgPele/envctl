#!/usr/bin/env bash

# Resolve script and base directories, then load core helpers.

if [ -z "${SCRIPT_DIR:-}" ]; then
    # Walk BASH_SOURCE to find the first caller that isn't loader.sh itself
    _loader_caller=""
    for _loader_src in "${BASH_SOURCE[@]}"; do
        if [ "$(basename "$_loader_src")" != "loader.sh" ]; then
            _loader_caller="$_loader_src"
            break
        fi
    done
    if [ -n "$_loader_caller" ]; then
        SCRIPT_DIR="$(cd "$(dirname "$_loader_caller")" && pwd)"
    else
        SCRIPT_DIR="$(pwd)"
    fi
    unset _loader_caller _loader_src
fi

if [ -n "${RUN_REPO_ROOT:-}" ]; then
    BASE_DIR="$RUN_REPO_ROOT"
elif [ -z "${BASE_DIR:-}" ]; then
    if [ "$(basename "$SCRIPT_DIR")" = "utils" ]; then
        BASE_DIR="$(dirname "$SCRIPT_DIR")"
    else
        BASE_DIR="$SCRIPT_DIR"
    fi
fi

LIB_DIR="${LIB_DIR:-$SCRIPT_DIR/lib}"

safe_source() {
    local file=$1
    [ -f "$file" ] || return 1
    # shellcheck source=/dev/null
    source "$file"
}

safe_source "$LIB_DIR/core.sh" || true
safe_source "$LIB_DIR/debug.sh" || true
safe_source "$LIB_DIR/cli.sh" || true
safe_source "$LIB_DIR/summary.sh" || true
safe_source "$LIB_DIR/run_cache.sh" || true
safe_source "$LIB_DIR/config_loader.sh" || true
safe_source "$LIB_DIR/fs.sh" || true
safe_source "$LIB_DIR/python.sh" || true
