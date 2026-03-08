#!/usr/bin/env bash

# Config loader helpers (env > config > defaults).

config_apply_if_unset() {
    local key=$1
    local value=$2
    [ -n "$key" ] || return 0
    if [ -z "${!key+x}" ]; then
        export "$key=$value"
    fi
}

load_config_file() {
    local file=$1
    [ -f "$file" ] || return 0

    if command -v python3 >/dev/null 2>&1; then
        while IFS=$'\t' read -r key value; do
            [ -n "$key" ] || continue
            config_apply_if_unset "$key" "$value"
        done < <(python3 - "$file" <<'PY'
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as handle:
    for raw in handle:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        print(f"{key}\t{value}")
PY
        )
        return 0
    fi

    while IFS= read -r line; do
        [ -z "$line" ] && continue
        case "$line" in
            \#*) continue ;;
        esac
        line=$(trim "$line")
        if [[ "$line" == export* ]]; then
            line=${line#export }
            line=$(trim "$line")
        fi
        if [[ "$line" != *=* ]]; then
            continue
        fi
        local key=${line%%=*}
        local value=${line#*=}
        key=$(trim "$key")
        value=$(trim "$value")
        value=${value%\"}
        value=${value#\"}
        value=${value%\'}
        value=${value#\'}
        config_apply_if_unset "$key" "$value"
    done < "$file"
}

load_envctl_config() {
    local base_dir=${1:-${BASE_DIR:-}}
    local config_file="${ENVCTL_CONFIG_FILE:-}"

    if [ -z "$config_file" ] && [ -n "$base_dir" ]; then
        if [ -f "$base_dir/.envctl" ]; then
            config_file="$base_dir/.envctl"
        elif [ -f "$base_dir/.envctl.sh" ]; then
            config_file="$base_dir/.envctl.sh"
        elif [ -f "$base_dir/.supportopia-config" ]; then
            # Legacy fallback
            config_file="$base_dir/.supportopia-config"
        fi
    fi
    if [ -z "$config_file" ]; then
        return 0
    fi

    # If it is .envctl.sh, we just source it
    if [[ "$config_file" == *".envctl.sh" ]]; then
        # shellcheck source=/dev/null
        source "$config_file"
    else
        load_config_file "$config_file"
    fi
}
