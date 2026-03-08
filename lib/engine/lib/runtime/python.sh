#!/usr/bin/env bash

python_error() {
    local msg=$1
    if [ -n "${RED:-}" ] || [ -n "${NC:-}" ]; then
        printf '%b\n' "${RED}${msg}${NC}"
    else
        printf '%s\n' "$msg"
    fi
}

python_is_312() {
    local py=$1
    "$py" - <<'PY' >/dev/null 2>&1
import sys
sys.exit(0 if (sys.version_info.major, sys.version_info.minor) == (3, 12) else 1)
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
            if python_is_312 "$requested"; then
                echo "$requested"
                return 0
            fi
            python_error "PYTHON_BIN must be Python 3.12 (got: $requested)."
            return 1
        fi
        python_error "PYTHON_BIN not found: $requested"
        return 1
    fi

    if command -v python3.12 >/dev/null 2>&1 && python_is_312 python3.12; then
        echo "python3.12"
        return 0
    fi

    if command -v python3 >/dev/null 2>&1 && python_is_312 python3; then
        echo "python3"
        return 0
    fi

    return 1
}

ensure_python_bin() {
    if PYTHON_BIN=$(select_python); then
        return 0
    fi
    python_error "Python 3.12 is required. Install python3.12, set PYTHON_BIN to a 3.12 interpreter, or set PYTHON_CMD to use a different version."
    return 1
}
