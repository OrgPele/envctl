#!/usr/bin/env bash

# Shared summary formatting helpers.

summary_print_line() {
    local line=${1:-=}
    local width=${2:-50}
    local color=${3:-}
    local output="$line"

    if [ ${#line} -le 1 ]; then
        output=$(printf '%*s' "$width" '' | tr ' ' "$line")
    fi

    if [ -n "$color" ]; then
        printf '%b\n' "${color}${output}${NC:-}"
    else
        printf '%s\n' "$output"
    fi
}

summary_print_banner() {
    local title=$1
    local line=${2:-=}
    local title_color=${3:-${CYAN:-}}
    local width=${4:-50}
    local line_color=${5:-$title_color}

    summary_print_line "$line" "$width" "$line_color"
    if [ -n "$title_color" ]; then
        printf '%b\n' "${title_color}${title}${NC:-}"
    else
        printf '%s\n' "$title"
    fi
    summary_print_line "$line" "$width" "$line_color"
}

summary_print_section() {
    local title=$1
    local line=${2:--}
    local title_color=${3:-${CYAN:-}}
    local width=${4:-50}
    local line_color=${5:-$title_color}

    if [ -n "$title_color" ]; then
        printf '%b\n' "${title_color}${title}${NC:-}"
    else
        printf '%s\n' "$title"
    fi
    summary_print_line "$line" "$width" "$line_color"
}

summary_print_label_value() {
    local label=$1
    local value=$2
    local label_color=${3:-${BLUE:-}}

    if [ -n "$label_color" ]; then
        printf '%b\n' "${label_color}${label}:${NC:-} $value"
    else
        printf '%s\n' "${label}: $value"
    fi
}
