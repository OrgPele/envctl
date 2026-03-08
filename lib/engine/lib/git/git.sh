#!/usr/bin/env bash

hash_stdin() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 1 | awk '{print $1}'
        return 0
    fi
    if command -v sha1sum >/dev/null 2>&1; then
        sha1sum | awk '{print $1}'
        return 0
    fi
    if command -v md5 >/dev/null 2>&1; then
        md5 | awk '{print $NF}'
        return 0
    fi
    wc -c | tr -d ' '
}

if [ -z "${GIT_STATE_CACHE+x}" ]; then
    declare -A GIT_STATE_CACHE=()
fi
if [ -z "${GIT_STATE_CACHE_TS+x}" ]; then
    declare -A GIT_STATE_CACHE_TS=()
fi

git_state_cache_ttl() {
    local ttl="${RUN_SH_STATUS_CACHE_TTL:-0}"
    if [[ "$ttl" =~ ^[0-9]+$ ]] && [ "$ttl" -gt 0 ]; then
        echo "$ttl"
        return 0
    fi
    echo 0
}

git_state_for_dir() {
    local dir=$1
    if [ -z "$dir" ]; then
        return 1
    fi
    local ttl
    ttl=$(git_state_cache_ttl)
    if [ "$ttl" -gt 0 ]; then
        local cached_ts="${GIT_STATE_CACHE_TS[$dir]:-0}"
        local now
        now=$(date +%s)
        if [ "$cached_ts" -gt 0 ] && [ $((now - cached_ts)) -le "$ttl" ]; then
            local cached="${GIT_STATE_CACHE[$dir]:-}"
            if [ -n "$cached" ]; then
                echo "$cached"
                return 0
            fi
        fi
    fi
    if ! git -C "$dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        return 1
    fi
    local head=""
    head=$(git -C "$dir" rev-parse HEAD 2>/dev/null || true)
    local status=""
    status=$(git -C "$dir" status --porcelain=1 2>/dev/null || true)
    local status_hash=""
    status_hash=$(printf '%s' "$status" | hash_stdin)
    local status_lines=""
    status_lines=$(printf '%s\n' "$status" | sed '/^$/d' | wc -l | tr -d ' ')
    local output="${head}|${status_hash}|${status_lines}"
    if [ "$ttl" -gt 0 ]; then
        GIT_STATE_CACHE["$dir"]="$output"
        GIT_STATE_CACHE_TS["$dir"]="$(date +%s)"
    fi
    echo "$output"
}

extract_repo_slug() {
    local url=$1
    url="${url%.git}"
    if [[ "$url" =~ github\.com[:/](.+/.+)$ ]]; then
        echo "${BASH_REMATCH[1]}"
        return 0
    fi
    return 1
}
