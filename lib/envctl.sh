#!/usr/bin/env bash

set -euo pipefail

ENVCTL_ROOT_DIR="${ENVCTL_ROOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)}"

ENVCTL_SELECTED_ENGINE=""
ENVCTL_SELECTED_ADAPTER=""
ENVCTL_SELECTED_WORKSPACE=""

trim() {
    local s="${1:-}"
    s="${s#"${s%%[![:space:]]*}"}"
    s="${s%"${s##*[![:space:]]}"}"
    printf '%s' "$s"
}

envctl_print_usage() {
    cat <<'USAGE'
Usage:
  envctl [--repo <path>] [engine args...]
  envctl doctor [--repo <path>]
  envctl install [--shell-file <path>] [--dry-run]
  envctl uninstall [--shell-file <path>] [--dry-run]
  envctl --help

Examples:
  envctl
  envctl --main
  envctl --repo /Users/kfiramar/projects/my-project --resume
  envctl doctor --repo /Users/kfiramar/projects/my-project
USAGE
}

envctl_error() {
    printf '%s\n' "$*" >&2
}

envctl_dir_realpath() {
    local dir=${1:-}
    if [ -z "$dir" ]; then
        return 1
    fi
    if [ ! -d "$dir" ]; then
        return 1
    fi
    (
        cd "$dir" >/dev/null 2>&1 || exit 1
        pwd -P
    )
}

envctl_file_realpath() {
    local file=${1:-}
    if [ -z "$file" ]; then
        return 1
    fi
    local parent="$(dirname "$file")"
    parent="$(envctl_dir_realpath "$parent")" || return 1
    printf '%s/%s\n' "$parent" "$(basename "$file")"
}

envctl_is_repo_root() {
    local dir=${1:-}
    [ -n "$dir" ] || return 1
    if [ -d "$dir/.git" ] || [ -f "$dir/.git" ]; then
        return 0
    fi
    return 1
}

envctl_find_repo_root_from_pwd() {
    local cur
    cur="$(pwd -P)"
    while true; do
        if envctl_is_repo_root "$cur"; then
            printf '%s\n' "$cur"
            return 0
        fi
        if [ "$cur" = "/" ]; then
            return 1
        fi
        cur="$(dirname "$cur")"
    done
}

envctl_resolve_repo_root() {
    local repo_arg=${1:-}
    if [ -n "$repo_arg" ]; then
        local repo_root
        repo_root="$(envctl_dir_realpath "$repo_arg")" || {
            envctl_error "Invalid --repo path: $repo_arg"
            return 1
        }
        if ! envctl_is_repo_root "$repo_root"; then
            envctl_error "Invalid repo root: $repo_root (expected a git repository with .git)"
            return 1
        fi
        printf '%s\n' "$repo_root"
        return 0
    fi

    if envctl_find_repo_root_from_pwd >/dev/null 2>&1; then
        envctl_find_repo_root_from_pwd
        return 0
    fi

    envctl_error "Could not resolve repository root. Use --repo <path>."
    return 1
}

envctl_select_engine() {
    ENVCTL_SELECTED_ENGINE=""
    ENVCTL_SELECTED_ADAPTER=""
    ENVCTL_SELECTED_WORKSPACE=""

    ENVCTL_SELECTED_ENGINE="${ENVCTL_ROOT_DIR%/}/lib/engine/main.sh"
    if [ ! -x "$ENVCTL_SELECTED_ENGINE" ]; then
        envctl_error "Missing engine: $ENVCTL_SELECTED_ENGINE"
        return 1
    fi
    return 0
}

envctl_run_doctor() {
    local repo_arg=${1:-}
    local binary_path
    binary_path="$(envctl_file_realpath "$0" 2>/dev/null || printf '%s' "$0")"

    local repo_root
    repo_root="$(envctl_resolve_repo_root "$repo_arg")" || return 1

    if ! envctl_select_engine "$repo_root" doctor; then
        envctl_error "Could not resolve engine for repo: $repo_root"
        return 1
    fi

    printf 'Launcher: envctl\n'
    printf 'Binary Path: %s\n' "$binary_path"
    printf 'Repo Root: %s\n' "$repo_root"

    printf 'Engine Path: %s (reachable)\n' "$ENVCTL_SELECTED_ENGINE"
    return 0
}

envctl_install_script() {
    local mode=${1:-}
    shift || true

    local installer="${ENVCTL_ROOT_DIR%/}/scripts/install.sh"
    if [ ! -x "$installer" ]; then
        envctl_error "Missing installer: $installer"
        return 1
    fi

    ENVCTL_ROOT_DIR="$ENVCTL_ROOT_DIR" "$installer" "$mode" "$@"
}

envctl_forward_to_engine() {
    local repo_root=${1:-}
    shift || true

    if ! envctl_select_engine "$repo_root" run; then
        envctl_error "Could not resolve engine for repo: $repo_root"
        return 1
    fi

    export RUN_LAUNCHER_NAME="envctl"
    export RUN_LAUNCHER_CONTEXT="envctl"
    export RUN_REPO_ROOT="$repo_root"
    export RUN_ENGINE_PATH="$ENVCTL_SELECTED_ENGINE"
    export RUN_LAUNCHER_ADAPTER="$ENVCTL_SELECTED_ADAPTER"
    if [ -z "${ENVCTL_ENGINE_PYTHON_V1:-}" ]; then
        if [ "${ENVCTL_ENGINE_SHELL_FALLBACK:-false}" = true ]; then
            export ENVCTL_ENGINE_PYTHON_V1=false
        else
            export ENVCTL_ENGINE_PYTHON_V1=true
        fi
    fi
    if [ -n "$ENVCTL_SELECTED_WORKSPACE" ]; then
        export RUN_ADAPTER_WORKSPACE_DIR="$ENVCTL_SELECTED_WORKSPACE"
    fi

    exec "$ENVCTL_SELECTED_ENGINE" "$@"
}

envctl_main() {
    local repo_arg=""
    local -a args=()

    while [ $# -gt 0 ]; do
        case "$1" in
            --repo)
                repo_arg="$(trim "${2:-}")"
                if [ -z "$repo_arg" ]; then
                    envctl_error "Missing value for --repo"
                    return 1
                fi
                shift 2
                ;;
            --repo=*)
                repo_arg="$(trim "${1#*=}")"
                if [ -z "$repo_arg" ]; then
                    envctl_error "Missing value for --repo"
                    return 1
                fi
                shift
                ;;
            --help|-h)
                envctl_print_usage
                return 0
                ;;
            *)
                args+=("$1")
                shift
                ;;
        esac
    done

    local cmd=""
    if [ ${#args[@]} -gt 0 ]; then
        cmd="${args[0]}"
    fi

    case "$cmd" in
        doctor)
            envctl_run_doctor "$repo_arg"
            ;;
        install)
            envctl_install_script install "${args[@]:1}"
            ;;
        uninstall)
            envctl_install_script uninstall "${args[@]:1}"
            ;;
        *)
            local repo_root
            repo_root="$(envctl_resolve_repo_root "$repo_arg")" || return 1
            envctl_forward_to_engine "$repo_root" "${args[@]}"
            ;;
    esac
}
