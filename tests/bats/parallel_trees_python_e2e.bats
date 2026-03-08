#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BASH_BIN="$(command -v bash || true)"
  BIN="$REPO_ROOT/bin/envctl"
}

@test "python planner assigns unique ports for 3 trees" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    REPO_ROOT="$1"
    if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
      PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
    else
      PYTHON_BIN="$(command -v python3.12 || command -v python3)"
    fi
    PYTHONPATH="$REPO_ROOT/python" "$PYTHON_BIN" - <<"PY"
from envctl_engine.ports import PortPlanner

planner = PortPlanner(backend_base=8000, frontend_base=9000, spacing=20)
plans = [planner.plan_project(f"tree-{idx}", index=idx) for idx in range(3)]
backend_ports = [plan["backend"].final for plan in plans]
frontend_ports = [plan["frontend"].final for plan in plans]

assert len(set(backend_ports)) == 3
assert len(set(frontend_ports)) == 3
print("ok")
PY
  ' _ "$REPO_ROOT"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}

@test "python state loader rejects malformed state files" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    REPO_ROOT="$1"
    if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
      PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
    else
      PYTHON_BIN="$(command -v python3.12 || command -v python3)"
    fi
    PYTHONPATH="$REPO_ROOT/python" "$PYTHON_BIN" - <<"PY"
import json
import tempfile
from pathlib import Path

from envctl_engine.state import StateValidationError, load_state

with tempfile.TemporaryDirectory() as tmpdir:
    state_path = Path(tmpdir) / "bad.json"
    state_path.write_text(json.dumps({"run_id": "run-1"}), encoding="utf-8")
    try:
        load_state(str(state_path), allowed_root=tmpdir)
    except StateValidationError:
        print("rejected")
    else:
        raise SystemExit("expected StateValidationError")
PY
  ' _ "$REPO_ROOT"

  [ "$status" -eq 0 ]
  [ "$output" = "rejected" ]
}

@test "python engine writes required runtime artifacts" {
  [ -n "$BASH_BIN" ] || skip "bash not found"
  run "$BASH_BIN" -lc '
    set -euo pipefail
    repo_tmp=$(mktemp -d)
    repo="$repo_tmp/repo"
    runtime="$repo_tmp/runtime"
    mkdir -p "$repo/.git" "$repo/trees/feature-a-1"
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

    backend_base=$((42000 + RANDOM % 2000))
    frontend_base=$((backend_base + 1000))
    db_port=$((backend_base + 2000))
    redis_port=$((backend_base + 3000))
    n8n_base=$((backend_base + 4000))

    RUN_SH_RUNTIME_DIR="$runtime" \
    BACKEND_PORT_BASE="$backend_base" \
    FRONTEND_PORT_BASE="$frontend_base" \
    DB_PORT="$db_port" \
    REDIS_PORT="$redis_port" \
    N8N_PORT_BASE="$n8n_base" \
    PYTHON_BIN="$1" \
    ENVCTL_BACKEND_START_CMD="bash $repo/bin/start_service.sh" \
    ENVCTL_FRONTEND_START_CMD="bash $repo/bin/start_service.sh" \
    ENVCTL_REQUIREMENT_POSTGRES_CMD="bash $repo/bin/start_listener.sh" \
    ENVCTL_REQUIREMENT_REDIS_CMD="bash $repo/bin/start_listener.sh" \
    ENVCTL_REQUIREMENT_N8N_CMD="bash $repo/bin/start_listener.sh" \
    ENVCTL_REQUIREMENT_SUPABASE_CMD="bash $repo/bin/start_listener.sh" \
    "$2" --repo "$repo" --plan feature-a >/dev/null
    test -f "$runtime/python-engine/run_state.json"
    test -f "$runtime/python-engine/runtime_map.json"
    test -f "$runtime/python-engine/ports_manifest.json"
    test -f "$runtime/python-engine/error_report.json"
    test -f "$runtime/python-engine/events.jsonl"
    test -f "$runtime/python-engine/shell_prune_report.json"
    RUN_SH_RUNTIME_DIR="$runtime" "$1" - <<'"'"'PY'"'"'
import json
import os
from pathlib import Path

runtime = Path(os.environ["RUN_SH_RUNTIME_DIR"]) / "python-engine"
state = json.loads((runtime / "run_state.json").read_text(encoding="utf-8"))
pointers = state.get("pointers", {})
path = Path(str(pointers.get("shell_prune_report", "")))
if path.name != "shell_prune_report.json":
    raise SystemExit("missing shell_prune_report pointer")
if not path.is_file():
    raise SystemExit("shell_prune_report pointer path missing")
PY
    echo "ok"
  ' _ "$REPO_ROOT/.venv/bin/python" "$BIN"

  [ "$status" -eq 0 ]
  [ "$output" = "ok" ]
}
