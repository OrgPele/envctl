#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "python --plan creates missing worktrees to satisfy selected planning counts" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    repo_tmp=$(mktemp -d)
    repo="$repo_tmp/repo"
    runtime="$repo_tmp/runtime"
    mkdir -p "$repo/.git"
    mkdir -p "$repo/docs/planning/implementations"
    printf "# task\n" > "$repo/docs/planning/implementations/task.md"

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
    BACKEND_PORT_BASE=18200 \
    FRONTEND_PORT_BASE=19200 \
    DB_PORT=16432 \
    REDIS_PORT=17379 \
    N8N_PORT_BASE=16678 \
    ENVCTL_REQUIREMENTS_STRICT=false \
    ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK=true \
    PYTHON_BIN="$1" \
    ENVCTL_BACKEND_START_CMD="bash $repo/bin/start_service.sh" \
    ENVCTL_FRONTEND_START_CMD="bash $repo/bin/start_service.sh" \
    ENVCTL_REQUIREMENT_POSTGRES_CMD="bash $repo/bin/start_listener.sh" \
    ENVCTL_REQUIREMENT_REDIS_CMD="bash $repo/bin/start_listener.sh" \
    ENVCTL_REQUIREMENT_N8N_CMD="bash $repo/bin/start_listener.sh" \
    ENVCTL_REQUIREMENT_SUPABASE_CMD="bash $repo/bin/start_listener.sh" \
    "$2" --repo "$repo" --plan implementations/task,implementations/task >/tmp/envctl_plan_setup.out

    RUNTIME_DIR="$runtime" REPO_DIR="$repo" PYTHONPATH="$3/python" "$1" - <<"PY"
import json
import os
import pathlib

runtime = pathlib.Path(os.environ["RUNTIME_DIR"]) / "python-engine"
repo = pathlib.Path(os.environ["REPO_DIR"])
manifest = json.loads((runtime / "ports_manifest.json").read_text(encoding="utf-8"))
projects = [p["project"] for p in manifest["projects"]]
assert projects == ["implementations_task-1", "implementations_task-2"], projects
assert (repo / "trees" / "implementations_task" / "1").is_dir()
assert (repo / "trees" / "implementations_task" / "2").is_dir()
print("ok")
PY
  ' _ "$PYTHON_BIN" "$BIN" "$REPO_ROOT"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}
