#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python_engine_version_is_supported() {
    local py_bin=$1
    "$py_bin" - <<'PY' >/dev/null 2>&1
import sys
major, minor = sys.version_info[:2]
sys.exit(0 if major == 3 and 12 <= minor <= 14 else 1)
PY
}

python_engine_select_bin() {
    if [ -n "${PYTHON_CMD:-}" ]; then
        if command -v "${PYTHON_CMD}" >/dev/null 2>&1; then
            printf '%s\n' "${PYTHON_CMD}"
            return 0
        fi
        echo "PYTHON_CMD not found: ${PYTHON_CMD}" >&2
        return 1
    fi
    if [ -n "${PYTHON_BIN:-}" ]; then
        if command -v "${PYTHON_BIN}" >/dev/null 2>&1 && python_engine_version_is_supported "${PYTHON_BIN}"; then
            printf '%s\n' "${PYTHON_BIN}"
            return 0
        fi
        echo "PYTHON_BIN must resolve to Python 3.12-3.14: ${PYTHON_BIN}" >&2
        return 1
    fi

    local envctl_root=""
    envctl_root="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"
    local repo_venv_python="${envctl_root}/.venv/bin/python"
    if [ -x "${repo_venv_python}" ] && python_engine_version_is_supported "${repo_venv_python}"; then
        printf '%s\n' "${repo_venv_python}"
        return 0
    fi
    if command -v python3.14 >/dev/null 2>&1 && python_engine_version_is_supported python3.14; then
        echo "python3.14"
        return 0
    fi
    if command -v python3.13 >/dev/null 2>&1 && python_engine_version_is_supported python3.13; then
        echo "python3.13"
        return 0
    fi
    if command -v python3.12 >/dev/null 2>&1 && python_engine_version_is_supported python3.12; then
        echo "python3.12"
        return 0
    fi
    if command -v python3 >/dev/null 2>&1 && python_engine_version_is_supported python3; then
        echo "python3"
        return 0
    fi
    if command -v python >/dev/null 2>&1 && python_engine_version_is_supported python; then
        echo "python"
        return 0
    fi
    echo "Python 3.12-3.14 is required for ENVCTL_ENGINE_PYTHON_V1=true" >&2
    return 1
}

exec_python_engine_if_enabled() {
    [ "${ENVCTL_ENGINE_PYTHON_V1:-false}" = true ] || return 1

    local py_bin=""
    py_bin="$(python_engine_select_bin)" || return 2

    local envctl_root=""
    envctl_root="$(cd "${SCRIPT_DIR}/../.." && pwd -P)"
    local python_root="${envctl_root}/python"
    if [ ! -d "${python_root}/envctl_engine" ]; then
        echo "Python engine package not found: ${python_root}/envctl_engine" >&2
        return 2
    fi

    if [ -n "${PYTHONPATH:-}" ]; then
        export PYTHONPATH="${python_root}:${PYTHONPATH}"
    else
        export PYTHONPATH="${python_root}"
    fi
    exec "${py_bin}" -m envctl_engine.runtime.cli "$@"
}

shell_engine_should_print_usage() {
    if [ "$#" -eq 0 ]; then
        return 0
    fi
    local arg=""
    for arg in "$@"; do
        case "$arg" in
            --help|-h|--list-commands|--list-targets)
                return 0
                ;;
        esac
    done
    return 1
}

exec_shell_engine() {
    local repo_root="${RUN_REPO_ROOT:-}"
    local -a candidates=()
    if [ -n "$repo_root" ]; then
        candidates+=("${repo_root}/utils/run.sh")
        candidates+=("${repo_root}/run.sh")
        candidates+=("${repo_root}/utils/run-all-trees.sh")
        candidates+=("${repo_root}/run-all-trees.sh")
    fi

    local candidate=""
    for candidate in "${candidates[@]}"; do
        if [ -x "$candidate" ]; then
            exec "$candidate" "$@"
        fi
    done

    if ! shell_engine_should_print_usage "$@"; then
        echo "Shell engine script not found for repo: ${repo_root:-unknown}. Set ENVCTL_ENGINE_PYTHON_V1=true to use the Python runtime." >&2
        return 2
    fi

    local lib_dir="${SCRIPT_DIR}/lib"
    if [ -f "${lib_dir}/run_all_trees_cli.sh" ]; then
        source "${lib_dir}/run_all_trees_cli.sh"
    fi

    if command -v run_all_trees_cli_print_usage >/dev/null 2>&1; then
        run_all_trees_cli_print_usage
        return 0
    fi

    echo "Shell engine usage unavailable; missing run_all_trees_cli.sh." >&2
    return 2
}

if [ "${ENVCTL_ENGINE_PYTHON_V1:-false}" = true ]; then
    if ! exec_python_engine_if_enabled "$@"; then
        echo "Python engine failed to start. Ensure Python 3.12-3.14 is available." >&2
        exit 2
    fi
fi

if ! exec_shell_engine "$@"; then
    exit 2
fi
