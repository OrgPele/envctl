#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "python runtime projection URLs match actual listener ports after retries/rebounds" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
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
ENVCTL_TEST_CONFLICT_BACKEND=1 \
ENVCTL_TEST_CONFLICT_FRONTEND=1 \
ENVCTL_TEST_FRONTEND_REBOUND_DELTA=2 \
"$2" --repo "$repo" --plan feature-a >/tmp/envctl_listener_projection.out

RUNTIME_DIR="$runtime" PYTHONPATH="$3/python" "$1" - <<"PY"
import json
import os
import pathlib

runtime = pathlib.Path(os.environ["RUNTIME_DIR"]) / "python-engine"
runtime_map = json.loads((runtime / "runtime_map.json").read_text(encoding="utf-8"))
projection = runtime_map["projection"]
service_to_actual = runtime_map["service_to_actual_port"]

for project, urls in projection.items():
    backend_name = f"{project} Backend"
    frontend_name = f"{project} Frontend"
    backend_port = service_to_actual[backend_name]
    frontend_port = service_to_actual[frontend_name]
    backend_status = urls.get("backend_status")
    frontend_status = urls.get("frontend_status")
    if backend_status == "simulated":
        assert urls["backend_url"] is None, urls
    else:
        assert urls["backend_url"] == f"http://localhost:{backend_port}", urls
    if frontend_status == "simulated":
        assert urls["frontend_url"] is None, urls
    else:
        assert urls["frontend_url"] == f"http://localhost:{frontend_port}", urls
print("ok")
PY
  ' _ "$PYTHON_BIN" "$BIN" "$REPO_ROOT"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}
