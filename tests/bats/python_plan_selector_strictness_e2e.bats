#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "python --plan with invalid planning selection fails strictly without fallback" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    repo_tmp=$(mktemp -d)
    repo="$repo_tmp/repo"
    runtime="$repo_tmp/runtime"
    mkdir -p "$repo/.git"
    mkdir -p "$repo/trees/feature-a/1"
    mkdir -p "$repo/todo/plans/implementations"
    printf "# task\n" > "$repo/todo/plans/implementations/task.md"
    cat >"$repo/.envctl" <<'"'"'EOF'"'"'
# >>> envctl managed startup config >>>
ENVCTL_DEFAULT_MODE=trees

MAIN_STARTUP_ENABLE=false
MAIN_BACKEND_ENABLE=true
MAIN_FRONTEND_ENABLE=false
TREES_STARTUP_ENABLE=false
TREES_BACKEND_ENABLE=true
TREES_FRONTEND_ENABLE=false
# <<< envctl managed startup config <<<
EOF

    mkdir -p "$repo/bin"
    cat >"$repo/bin/start_service.sh" <<'"'"'SH'"'"'
#!/usr/bin/env bash
set -euo pipefail
python_bin="${PYTHON_BIN:-python3}"
port="${PORT:-0}"
exec "$python_bin" - <<'"'"'PY'"'"'
import os
import socket
import time

port = int(os.environ.get("PORT", "0"))
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", port))
sock.listen(1)
time.sleep(5)
PY
SH
    chmod +x "$repo/bin/start_service.sh"

    cat >"$repo/bin/start_listener.sh" <<'"'"'SH'"'"'
#!/usr/bin/env bash
set -euo pipefail
python_bin="${PYTHON_BIN:-python3}"
nohup "$python_bin" - <<'"'"'PY'"'"' >/dev/null 2>&1 &
import os
import socket
import time

port = int(os.environ.get("PORT", "0"))
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", port))
sock.listen(1)
time.sleep(5)
PY
exit 0
SH
    chmod +x "$repo/bin/start_listener.sh"

    set +e
    RUN_SH_RUNTIME_DIR="$runtime" \
    PYTHON_BIN="$1" \
    ENVCTL_BACKEND_START_CMD="bash $repo/bin/start_service.sh" \
    ENVCTL_FRONTEND_START_CMD="bash $repo/bin/start_service.sh" \
    ENVCTL_REQUIREMENT_POSTGRES_CMD="bash $repo/bin/start_listener.sh" \
    ENVCTL_REQUIREMENT_REDIS_CMD="bash $repo/bin/start_listener.sh" \
    ENVCTL_REQUIREMENT_N8N_CMD="bash $repo/bin/start_listener.sh" \
    ENVCTL_REQUIREMENT_SUPABASE_CMD="bash $repo/bin/start_listener.sh" \
    "$2" --repo "$repo" --plan implementations/missing >"$repo_tmp/out" 2>&1
    rc=$?
    set -e
    cat "$repo_tmp/out"
    exit "$rc"
  ' _ "$PYTHON_BIN" "$BIN"

  [ "$status" -ne 0 ]
  [[ "$output" == *"Planning file not found"* ]]
  [[ "$output" != *"Starting project"* ]]
}
