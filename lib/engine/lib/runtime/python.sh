#!/usr/bin/env bash

python_error() {
    local msg=$1
    if [ -n "${RED:-}" ] || [ -n "${NC:-}" ]; then
        printf '%b\n' "${RED}${msg}${NC}"
    else
        printf '%s\n' "$msg"
    fi
}

python_is_supported() {
    local py=$1
    "$py" - <<'PY' >/dev/null 2>&1
import sys
major, minor = sys.version_info[:2]
sys.exit(0 if major == 3 and 12 <= minor <= 14 else 1)
PY
}

select_python() {
    local requested_cmd="${PYTHON_CMD:-}"
    if [ -n "$requested_cmd" ]; then
        if command -v "$requested_cmd" >/dev/null 2>&1; then
            echo "$requested_cmd"
            return 0
        fi
        python_error "PYTHON_CMD not found: $requested_cmd"
        return 1
    fi

    local requested="${PYTHON_BIN:-}"
    if [ -n "$requested" ]; then
        if command -v "$requested" >/dev/null 2>&1; then
            if python_is_supported "$requested"; then
                echo "$requested"
                return 0
            fi
            python_error "PYTHON_BIN must be Python 3.12-3.14 (got: $requested)."
            return 1
        fi
        python_error "PYTHON_BIN not found: $requested"
        return 1
    fi

    if command -v python3.14 >/dev/null 2>&1 && python_is_supported python3.14; then
        echo "python3.14"
        return 0
    fi

    if command -v python3.13 >/dev/null 2>&1 && python_is_supported python3.13; then
        echo "python3.13"
        return 0
    fi

    if command -v python3.12 >/dev/null 2>&1 && python_is_supported python3.12; then
        echo "python3.12"
        return 0
    fi

    if command -v python3 >/dev/null 2>&1 && python_is_supported python3; then
        echo "python3"
        return 0
    fi

    if command -v python >/dev/null 2>&1 && python_is_supported python; then
        echo "python"
        return 0
    fi

    return 1
}

ensure_python_bin() {
    if PYTHON_BIN=$(select_python); then
        return 0
    fi
    python_error "Python 3.12-3.14 is required. Install a supported interpreter, set PYTHON_BIN accordingly, or set PYTHON_CMD to use a different version."
    return 1
}
