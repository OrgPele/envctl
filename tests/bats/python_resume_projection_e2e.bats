#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "python resume and restart keep runtime map URLs aligned to final ports" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    repo_tmp=$(mktemp -d)
    repo="$repo_tmp/repo"
    runtime="$repo_tmp/runtime"
    mkdir -p "$repo/.git" "$repo/trees/feature-a-1"

    ENVCTL_REQUIREMENTS_STRICT=false \
    ENVCTL_BACKEND_START_CMD="$1 -m http.server {port} --bind 127.0.0.1" \
    ENVCTL_FRONTEND_START_CMD="$1 -m http.server {port} --bind 127.0.0.1" \
    RUN_SH_RUNTIME_DIR="$runtime" PYTHON_BIN="$1" "$2" --repo "$repo" --plan feature-a >/tmp/envctl_plan.out
    ENVCTL_REQUIREMENTS_STRICT=false \
    ENVCTL_BACKEND_START_CMD="$1 -m http.server {port} --bind 127.0.0.1" \
    ENVCTL_FRONTEND_START_CMD="$1 -m http.server {port} --bind 127.0.0.1" \
    RUN_SH_RUNTIME_DIR="$runtime" PYTHON_BIN="$1" "$2" --repo "$repo" --resume >/tmp/envctl_resume.out
    ENVCTL_REQUIREMENTS_STRICT=false \
    ENVCTL_BACKEND_START_CMD="$1 -m http.server {port} --bind 127.0.0.1" \
    ENVCTL_FRONTEND_START_CMD="$1 -m http.server {port} --bind 127.0.0.1" \
    RUN_SH_RUNTIME_DIR="$runtime" PYTHON_BIN="$1" "$2" --repo "$repo" restart >/tmp/envctl_restart.out

    RUNTIME_DIR="$runtime" PYTHONPATH="$3/python" "$1" - <<"PY"
import json
import os
import pathlib

runtime = pathlib.Path(os.environ["RUNTIME_DIR"]) / "python-engine"
run_state = json.loads((runtime / "run_state.json").read_text(encoding="utf-8"))
runtime_map = json.loads((runtime / "runtime_map.json").read_text(encoding="utf-8"))

service_to_actual = runtime_map["service_to_actual_port"]
projection = runtime_map["projection"]

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
        assert urls["backend_url"].endswith(f":{backend_port}"), urls
    if frontend_status == "simulated":
        assert urls["frontend_url"] is None, urls
    else:
        assert urls["frontend_url"].endswith(f":{frontend_port}"), urls

assert run_state["schema_version"] == 1
print("ok")
PY
  ' _ "$PYTHON_BIN" "$BIN" "$REPO_ROOT"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}
