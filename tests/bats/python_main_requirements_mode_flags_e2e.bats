#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "python --main-services-local enables supabase/n8n and disables postgres in main mode" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    repo_tmp=$(mktemp -d)
    repo="$repo_tmp/repo"
    runtime="$repo_tmp/runtime"
    mkdir -p "$repo/.git"

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

    RUN_SH_RUNTIME_DIR="$runtime" \
    ENVCTL_REQUIREMENTS_STRICT=false \
    PYTHON_BIN="$1" \
    ENVCTL_BACKEND_START_CMD="bash $repo/bin/start_service.sh" \
    ENVCTL_FRONTEND_START_CMD="bash $repo/bin/start_service.sh" \
    ENVCTL_REQUIREMENT_POSTGRES_CMD="bash $repo/bin/start_listener.sh" \
    ENVCTL_REQUIREMENT_REDIS_CMD="bash $repo/bin/start_listener.sh" \
    ENVCTL_REQUIREMENT_N8N_CMD="bash $repo/bin/start_listener.sh" \
    ENVCTL_REQUIREMENT_SUPABASE_CMD="bash $repo/bin/start_listener.sh" \
    "$2" --repo "$repo" --main --main-services-local --batch >/tmp/envctl_main_local.out 2>&1

    RUN_SH_RUNTIME_DIR="$runtime" PYTHONPATH="$3/python" "$1" - <<'\''PY'\''
import json
import os
from pathlib import Path

runtime = Path(os.environ["RUN_SH_RUNTIME_DIR"])
state = json.loads((runtime / "python-engine" / "run_state.json").read_text(encoding="utf-8"))
req = state["requirements"]["Main"]
assert req["db"]["enabled"] is False, req
assert req["supabase"]["enabled"] is True, req
assert req["n8n"]["enabled"] is True, req
assert req["redis"]["enabled"] is True, req
print("ok")
PY
  ' _ "$PYTHON_BIN" "$BIN" "$REPO_ROOT"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}

@test "python --main-services-remote disables supabase and n8n overrides in main mode" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    repo_tmp=$(mktemp -d)
    repo="$repo_tmp/repo"
    runtime="$repo_tmp/runtime"
    mkdir -p "$repo/.git"

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

    RUN_SH_RUNTIME_DIR="$runtime" \
    SUPABASE_MAIN_ENABLE=true \
    N8N_MAIN_ENABLE=true \
    PYTHON_BIN="$1" \
    ENVCTL_BACKEND_START_CMD="bash $repo/bin/start_service.sh" \
    ENVCTL_FRONTEND_START_CMD="bash $repo/bin/start_service.sh" \
    ENVCTL_REQUIREMENT_POSTGRES_CMD="bash $repo/bin/start_listener.sh" \
    ENVCTL_REQUIREMENT_REDIS_CMD="bash $repo/bin/start_listener.sh" \
    ENVCTL_REQUIREMENT_N8N_CMD="bash $repo/bin/start_listener.sh" \
    ENVCTL_REQUIREMENT_SUPABASE_CMD="bash $repo/bin/start_listener.sh" \
    "$2" --repo "$repo" --main --main-services-remote --batch >/tmp/envctl_main_remote.out 2>&1

    RUN_SH_RUNTIME_DIR="$runtime" PYTHONPATH="$3/python" "$1" - <<'\''PY'\''
import json
import os
from pathlib import Path

runtime = Path(os.environ["RUN_SH_RUNTIME_DIR"])
state = json.loads((runtime / "python-engine" / "run_state.json").read_text(encoding="utf-8"))
req = state["requirements"]["Main"]
assert req["supabase"]["enabled"] is False, req
assert req["n8n"]["enabled"] is False, req
print("ok")
PY
  ' _ "$PYTHON_BIN" "$BIN" "$REPO_ROOT"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}

@test "python conflicting main requirement mode flags fail fast" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    repo_tmp=$(mktemp -d)
    repo="$repo_tmp/repo"
    runtime="$repo_tmp/runtime"
    mkdir -p "$repo/.git"

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
    "$2" --repo "$repo" --main --main-services-local --main-services-remote --batch >"$repo_tmp/out" 2>&1
    rc=$?
    set -e
    cat "$repo_tmp/out"
    exit "$rc"
  ' _ "$PYTHON_BIN" "$BIN"

  [ "$status" -ne 0 ]
  [[ "$output" == *"Conflicting main requirements flags"* ]]
}
