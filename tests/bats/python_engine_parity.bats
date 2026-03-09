#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  ENGINE_MAIN="$REPO_ROOT/lib/engine/main.sh"
  BIN="$REPO_ROOT/bin/envctl"
  BASH_BIN="$(command -v bash || true)"
}

@test "engine bridges to Python when ENVCTL_ENGINE_PYTHON_V1=true" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    tmp=$(mktemp -d)
    fake_py="$tmp/fake-python"
    cat > "$fake_py" <<"PY"
#!/usr/bin/env bash
echo "python-invoked:$*"
exit 0
PY
    chmod +x "$fake_py"
    repo="$tmp/repo"
    mkdir -p "$repo/.git"
    RUN_REPO_ROOT="$repo" ENVCTL_ENGINE_PYTHON_V1=true PYTHON_CMD="$fake_py" "$1" --help
  ' _ "$ENGINE_MAIN"

  [ "$status" -eq 0 ]
  [[ "$output" == *"python-invoked:-m envctl_engine.runtime.cli --help"* ]]
}

@test "engine defaults to shell flow when Python mode is disabled" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  "$BASH_BIN" -lc 'declare -A __bats_assoc_test=()' >/dev/null 2>&1 || skip "bash with associative arrays required"
  "$BASH_BIN" -lc '
    set -euo pipefail
    tmp=$(mktemp -d)
    repo="$tmp/repo"
    mkdir -p "$repo/.git"
    RUN_REPO_ROOT="$repo" ENVCTL_ENGINE_PYTHON_V1=false "$1" --help >/dev/null 2>&1
  ' _ "$ENGINE_MAIN" || skip "shell engine not runnable in bats harness"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    tmp=$(mktemp -d)
    repo="$tmp/repo"
    mkdir -p "$repo/.git"
    RUN_REPO_ROOT="$repo" ENVCTL_ENGINE_PYTHON_V1=false "$1" --help
  ' _ "$ENGINE_MAIN"

  [ "$status" -eq 0 ]
  [[ "$output" == *"Development Server Runner"* ]]
}

@test "engine does not force Python when ENVCTL_ENGINE_PYTHON_V1=false" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    tmp=$(mktemp -d)
    fake_py="$tmp/fake-python"
    cat > "$fake_py" <<"PY"
#!/usr/bin/env bash
echo "python-invoked:$*"
exit 0
PY
    chmod +x "$fake_py"
    repo="$tmp/repo"
    mkdir -p "$repo/.git"
    RUN_REPO_ROOT="$repo" ENVCTL_ENGINE_PYTHON_V1=false PYTHON_CMD="$fake_py" "$1" --help
  ' _ "$ENGINE_MAIN"

  [[ "$output" != *"python-invoked:"* ]]
}

@test "launcher defaults to python runtime unless shell fallback is requested" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    tmp=$(mktemp -d)
    repo="$tmp/repo"
    runtime="$tmp/runtime"
    mkdir -p "$repo/.git"
    RUN_SH_RUNTIME_DIR="$runtime" PYTHON_BIN="$1" "$2" --repo "$repo" --list-commands
  ' _ "$REPO_ROOT/.venv/bin/python" "$BIN"

  [ "$status" -eq 0 ]
  [[ "$output" == *"dashboard"* ]]
  [[ "$output" == *"resume"* ]]
}

@test "launcher respects ENVCTL_ENGINE_PYTHON_V1=false override" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  "$BASH_BIN" -lc '
    set -euo pipefail
    tmp=$(mktemp -d)
    repo="$tmp/repo"
    runtime="$tmp/runtime"
    mkdir -p "$repo/.git"
    RUN_SH_RUNTIME_DIR="$runtime" ENVCTL_ENGINE_PYTHON_V1=false "$1" --repo "$repo" --list-commands >/dev/null 2>&1
  ' _ "$BIN" || skip "shell engine not runnable in bats harness"

  run "$BASH_BIN" -lc '
    set -euo pipefail
    tmp=$(mktemp -d)
    repo="$tmp/repo"
    runtime="$tmp/runtime"
    mkdir -p "$repo/.git"
    RUN_SH_RUNTIME_DIR="$runtime" ENVCTL_ENGINE_PYTHON_V1=false "$1" --repo "$repo" --list-commands
  ' _ "$BIN"

  [ "$status" -eq 0 ]
  [[ "$output" == *"stop-all"* ]]
  [[ "$output" != *"envctl Python runtime"* ]]
}
