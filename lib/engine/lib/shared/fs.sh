#!/usr/bin/env bash

safe_cd() {
    local target=$1
    if [ -z "$target" ]; then
        return 1
    fi
    cd "$target" 2>/dev/null || return 1
    return 0
}

mktemp_file() {
    local prefix=${1:-tmp}
    local tmpdir=${TMPDIR:-/tmp}
    mktemp "${tmpdir%/}/${prefix}.XXXXXX"
}

mktemp_dir() {
    local prefix=${1:-tmp}
    local tmpdir=${TMPDIR:-/tmp}
    mktemp -d "${tmpdir%/}/${prefix}.XXXXXX"
}

sed_inplace() {
    if [[ "${OSTYPE:-}" == "darwin"* ]]; then
        sed -i '' "$@"
    else
        sed -i "$@"
    fi
}
