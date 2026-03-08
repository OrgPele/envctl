#!/usr/bin/env bash

if [ -z "${ENV_CACHE_VALUES+x}" ]; then
    declare -A ENV_CACHE_VALUES=()
fi
if [ -z "${ENV_CACHE_KEYS+x}" ]; then
    declare -A ENV_CACHE_KEYS=()
fi

env_cache_enabled() {
    if [ "${RUN_SH_FAST_STARTUP:-false}" != true ]; then
        return 1
    fi
    if [ "${RUN_SH_DISABLE_ENV_CACHE:-false}" = true ]; then
        return 1
    fi
    return 0
}

env_cache_dir() {
    if [ -n "${RUN_SH_ENV_CACHE_DIR:-}" ]; then
        echo "$RUN_SH_ENV_CACHE_DIR"
        return 0
    fi
    if [ -n "${LOGS_DIR:-}" ]; then
        echo "${LOGS_DIR%/}/.env-cache"
        return 0
    fi
    local runtime_dir=""
    if [ "$(type -t run_sh_runtime_dir)" = "function" ]; then
        runtime_dir=$(run_sh_runtime_dir)
    else
        runtime_dir="${RUN_SH_RUNTIME_DIR:-/tmp/envctl-runtime}"
        mkdir -p "$runtime_dir" 2>/dev/null || true
    fi
    echo "${runtime_dir%/}/env-cache"
}

env_cache_key() {
    local file=$1
    if command -v shasum >/dev/null 2>&1; then
        printf '%s' "$file" | shasum -a 1 | awk '{print $1}'
        return 0
    fi
    if command -v sha1sum >/dev/null 2>&1; then
        printf '%s' "$file" | sha1sum | awk '{print $1}'
        return 0
    fi
    if command -v md5 >/dev/null 2>&1; then
        printf '%s' "$file" | md5 | awk '{print $NF}'
        return 0
    fi
    printf '%s' "$file" | tr -c 'A-Za-z0-9' '_'
}

env_cache_file_for() {
    local file=$1
    local dir
    dir=$(env_cache_dir)
    mkdir -p "$dir"
    printf '%s/%s.envcache' "$dir" "$(env_cache_key "$file")"
}

env_cache_build() {
    local source_file=$1
    local cache_file=$2
    [ -f "$source_file" ] || return 1
    > "$cache_file"
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        case "$line" in
            \#*) continue ;;
        esac
        if [[ "$line" != *=* ]]; then
            continue
        fi
        local env_key=${line%%=*}
        local env_value=${line#*=}
        env_key=$(echo "$env_key" | xargs)
        # Strip matching outer quotes only (aligned with _read_env_value_raw)
        if [[ "$env_value" == '"'*'"' ]]; then
            env_value="${env_value#\"}"
            env_value="${env_value%\"}"
        elif [[ "$env_value" == "'"*"'" ]]; then
            env_value="${env_value#\'}"
            env_value="${env_value%\'}"
        fi
        printf '%s=%s\n' "$env_key" "$env_value" >> "$cache_file"
    done < "$source_file"
    return 0
}

_read_env_value_raw() {
    local file=$1
    local key=$2
    local line=""

    if [ -f "$file" ]; then
        line=$(grep -E "^${key}=" "$file" | tail -n 1)
    fi

    if [ -z "$line" ]; then
        return 0
    fi

    local value="${line#*=}"
    # Strip matching outer quotes only
    if [[ "$value" == '"'*'"' ]]; then
        value="${value#\"}"
        value="${value%\"}"
    elif [[ "$value" == "'"*"'" ]]; then
        value="${value#\'}"
        value="${value%\'}"
    fi
    echo "$value"
}

read_env_value() {
    if env_cache_enabled; then
        read_env_value_cached "$@"
        return $?
    fi
    _read_env_value_raw "$@"
}

read_env_value_cached() {
    local file=$1
    local key=$2

    if ! env_cache_enabled; then
        _read_env_value_raw "$file" "$key"
        return 0
    fi

    if [ -z "$file" ] || [ -z "$key" ]; then
        return 0
    fi

    local cache_key="${file}|${key}"
    if [ -n "${ENV_CACHE_VALUES[$cache_key]+x}" ]; then
        if [ "$(type -t profile_counter_increment)" = "function" ]; then
            profile_counter_increment "env.cache_hit"
        fi
        echo "${ENV_CACHE_VALUES[$cache_key]}"
        return 0
    fi

    if [ ! -f "$file" ]; then
        if [ "$(type -t profile_counter_increment)" = "function" ]; then
            profile_counter_increment "env.cache_miss"
        fi
        return 0
    fi

    local cache_file
    cache_file=$(env_cache_file_for "$file")

    if [ "${RUN_SH_REFRESH_CACHE:-false}" = true ] || [ ! -f "$cache_file" ]; then
        if [ "$(type -t profile_counter_increment)" = "function" ]; then
            profile_counter_increment "env.cache_miss"
        fi
        env_cache_build "$file" "$cache_file" || return 0
    fi

    if [ ! -f "$cache_file" ]; then
        if [ "$(type -t profile_counter_increment)" = "function" ]; then
            profile_counter_increment "env.cache_miss"
        fi
        return 0
    fi

    local line=""
    line=$(grep -E "^${key}=" "$cache_file" | tail -n 1)
    if [ -z "$line" ]; then
        if [ "$(type -t profile_counter_increment)" = "function" ]; then
            profile_counter_increment "env.cache_hit"
        fi
        return 0
    fi

    local value="${line#*=}"
    ENV_CACHE_VALUES["$cache_key"]="$value"
    if [ "$(type -t profile_counter_increment)" = "function" ]; then
        profile_counter_increment "env.cache_hit"
    fi
    echo "$value"
}

upsert_env_value() {
    local file=$1
    local key=$2
    local value=$3

    if [ ! -f "$file" ]; then
        printf '%s=%s\n' "$key" "$value" > "$file"
        return 0
    fi

    if grep -q "^${key}=" "$file"; then
        awk -v k="$key" -v v="$value" '
            BEGIN { FS="="; OFS="=" }
            $1 == k { print k, v; next }
            { print }
        ' "$file" > "$file.tmp" && mv "$file.tmp" "$file"
    else
        printf '%s=%s\n' "$key" "$value" >> "$file"
    fi
}

load_env_file_safe() {
    local file=$1
    [ -f "$file" ] || return 0

    if command -v python3 >/dev/null 2>&1; then
        local exports=""
        exports=$(python3 - "$file" <<'PY'
import re
import shlex
import sys

path = sys.argv[1]
_valid_key = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
with open(path, "r", encoding="utf-8") as handle:
    for raw in handle:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not _valid_key.match(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        print(f"export {key}={shlex.quote(value)}")
PY
        )
        if [ -n "$exports" ]; then
            eval "$exports"
        fi
        return 0
    fi

    # Fallback: naive parsing (best effort)
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        case "$line" in
            \#*) continue ;;
        esac
        if [[ "$line" != *=* ]]; then
            continue
        fi
        key=${line%%=*}
        value=${line#*=}
        key=$(echo "$key" | xargs)
        # Validate key: only allow alphanumeric and underscore
        if ! [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
            continue
        fi
        # Strip matching outer quotes only
        if [[ "$value" == '"'*'"' ]]; then
            value="${value#\"}"
            value="${value%\"}"
        elif [[ "$value" == "'"*"'" ]]; then
            value="${value#\'}"
            value="${value%\'}"
        fi
        export "$key"="$value"
    done < "$file"
}
