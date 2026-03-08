#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "python parallel trees startup emits parallel execution mode event" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    repo_tmp=$(mktemp -d)
    repo="$repo_tmp/repo"
    runtime="$repo_tmp/runtime"
    mkdir -p "$repo/.git" "$repo/trees/feature-a/1" "$repo/trees/feature-b/1"

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
duration = float(os.environ.get("ENVCTL_TEST_LISTENER_DURATION_SECONDS", "20"))
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", port))
sock.listen(1)
time.sleep(duration)
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
duration = float(os.environ.get("ENVCTL_TEST_LISTENER_DURATION_SECONDS", "20"))
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", port))
sock.listen(1)
time.sleep(duration)
PY
exit 0
SH
    chmod +x "$repo/bin/start_listener.sh"

    RUN_SH_RUNTIME_DIR="$runtime" \
    PYTHON_BIN="$1" \
    ENVCTL_BACKEND_START_CMD="bash $repo/bin/start_service.sh" \
    ENVCTL_FRONTEND_START_CMD="bash $repo/bin/start_service.sh" \
    ENVCTL_REQUIREMENT_POSTGRES_CMD="bash $repo/bin/start_listener.sh" \
    ENVCTL_REQUIREMENT_REDIS_CMD="bash $repo/bin/start_listener.sh" \
    ENVCTL_REQUIREMENT_N8N_CMD="bash $repo/bin/start_listener.sh" \
    ENVCTL_REQUIREMENT_SUPABASE_CMD="bash $repo/bin/start_listener.sh" \
    "$2" --repo "$repo" --plan feature-a,feature-b --parallel-trees --parallel-trees-max 2 --batch >/tmp/envctl_parallel_mode.out 2>&1

    RUN_SH_RUNTIME_DIR="$runtime" PYTHONPATH="$3/python" "$1" - <<'\''PY'\''
import json
import os
from pathlib import Path

runtime = Path(os.environ["RUN_SH_RUNTIME_DIR"]) / "python-engine"
events_path = runtime / "events.jsonl"
events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
matches = [event for event in events if event.get("event") == "startup.execution"]
assert matches, events
latest = matches[-1]
assert latest.get("mode") == "parallel", latest
assert int(latest.get("workers", 0)) == 2, latest
print("ok")
PY
  ' _ "$PYTHON_BIN" "$BIN" "$REPO_ROOT"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}

@test "python no-parallel flag forces sequential execution mode event" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    repo_tmp=$(mktemp -d)
    repo="$repo_tmp/repo"
    runtime="$repo_tmp/runtime"
    mkdir -p "$repo/.git" "$repo/trees/feature-a/1" "$repo/trees/feature-b/1"

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
duration = float(os.environ.get("ENVCTL_TEST_LISTENER_DURATION_SECONDS", "20"))
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", port))
sock.listen(1)
time.sleep(duration)
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
duration = float(os.environ.get("ENVCTL_TEST_LISTENER_DURATION_SECONDS", "20"))
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", port))
sock.listen(1)
time.sleep(duration)
PY
exit 0
SH
    chmod +x "$repo/bin/start_listener.sh"

    RUN_SH_RUNTIME_DIR="$runtime" \
    RUN_SH_OPT_PARALLEL_TREES=true \
    PYTHON_BIN="$1" \
    ENVCTL_BACKEND_START_CMD="bash $repo/bin/start_service.sh" \
    ENVCTL_FRONTEND_START_CMD="bash $repo/bin/start_service.sh" \
    ENVCTL_REQUIREMENT_POSTGRES_CMD="bash $repo/bin/start_listener.sh" \
    ENVCTL_REQUIREMENT_REDIS_CMD="bash $repo/bin/start_listener.sh" \
    ENVCTL_REQUIREMENT_N8N_CMD="bash $repo/bin/start_listener.sh" \
    ENVCTL_REQUIREMENT_SUPABASE_CMD="bash $repo/bin/start_listener.sh" \
    "$2" --repo "$repo" --plan feature-a,feature-b --no-parallel-trees --batch >/tmp/envctl_no_parallel_mode.out 2>&1

    RUN_SH_RUNTIME_DIR="$runtime" PYTHONPATH="$3/python" "$1" - <<'\''PY'\''
import json
import os
from pathlib import Path

runtime = Path(os.environ["RUN_SH_RUNTIME_DIR"]) / "python-engine"
events_path = runtime / "events.jsonl"
events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
matches = [event for event in events if event.get("event") == "startup.execution"]
assert matches, events
latest = matches[-1]
assert latest.get("mode") == "sequential", latest
assert int(latest.get("workers", 0)) == 1, latest
print("ok")
PY
  ' _ "$PYTHON_BIN" "$BIN" "$REPO_ROOT"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}
