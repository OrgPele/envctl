#!/usr/bin/env bash

trim() {
    local value=$1
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    printf '%s' "$value"
}

split_csv() {
    local csv=$1
    local -n out=$2
    out=()
    if [ -n "$csv" ]; then
        IFS=',' read -r -a out <<< "$csv"
    fi
}

parse_bool() {
    local value
    value=$(trim "${1:-}")
    case "$value" in
        1|true|TRUE|yes|YES|y|Y)
            printf 'true'
            return 0
            ;;
        0|false|FALSE|no|NO|n|N|"")
            printf 'false'
            return 0
            ;;
    esac
    return 1
}

is_truthy() {
    local value
    value=$(trim "${1:-}")
    case "$value" in
        1|true|TRUE|yes|YES|y|Y)
            return 0
            ;;
    esac
    return 1
}
