#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "python runtime state is isolated across repositories sharing one runtime root" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
set -euo pipefail
repo_tmp=$(mktemp -d)
repo_a="$repo_tmp/repo-a"
repo_b="$repo_tmp/repo-b"
runtime="$repo_tmp/runtime"

mkdir -p "$repo_a/.git" "$repo_b/.git"
mkdir -p "$repo_a/trees/feature-a/1"

mkdir -p "$repo_a/bin"
cat >"$repo_a/bin/start_service.sh" <<'"'"'SH'"'"'
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
chmod +x "$repo_a/bin/start_service.sh"

cat >"$repo_a/bin/start_listener.sh" <<'"'"'SH'"'"'
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
chmod +x "$repo_a/bin/start_listener.sh"

RUN_SH_RUNTIME_DIR="$runtime" \
PYTHON_BIN="$1" \
ENVCTL_BACKEND_START_CMD="bash $repo_a/bin/start_service.sh" \
ENVCTL_FRONTEND_START_CMD="bash $repo_a/bin/start_service.sh" \
ENVCTL_REQUIREMENT_POSTGRES_CMD="bash $repo_a/bin/start_listener.sh" \
ENVCTL_REQUIREMENT_REDIS_CMD="bash $repo_a/bin/start_listener.sh" \
ENVCTL_REQUIREMENT_N8N_CMD="bash $repo_a/bin/start_listener.sh" \
ENVCTL_REQUIREMENT_SUPABASE_CMD="bash $repo_a/bin/start_listener.sh" \
"$2" --repo "$repo_a" --plan feature-a >/tmp/repo_a_start.out

out_b=$(RUN_SH_RUNTIME_DIR="$runtime" PYTHON_BIN="$1" "$2" --repo "$repo_b" --resume || true)
echo "$out_b"
[[ "$out_b" == *"No previous state found to resume."* ]]

scope_dirs=$(find "$runtime/python-engine" -mindepth 1 -maxdepth 1 -type d -name "repo-*" | wc -l | tr -d " ")
if [ "$scope_dirs" -lt 1 ]; then
  echo "missing scoped runtime directories"
  exit 1
fi
  ' _ "$PYTHON_BIN" "$BIN"

  [ "$status" -eq 0 ]
  [[ "$output" == *"No previous state found to resume."* ]]
}
