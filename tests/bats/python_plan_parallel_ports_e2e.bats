#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "python --plan assigns unique app and infra ports across 3 trees" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    repo_tmp=$(mktemp -d)
    repo="$repo_tmp/repo"
    runtime="$repo_tmp/runtime"
    mkdir -p "$repo/.git" "$repo/trees/feature-a-1" "$repo/trees/feature-a-2" "$repo/trees/feature-b-1"

    RUN_SH_RUNTIME_DIR="$runtime" \
    ENVCTL_REQUIREMENTS_STRICT=false \
    ENVCTL_BACKEND_START_CMD="$1 -m http.server {port} --bind 127.0.0.1" \
    ENVCTL_FRONTEND_START_CMD="$1 -m http.server {port} --bind 127.0.0.1" \
    PYTHON_BIN="$1" \
    "$2" --repo "$repo" --plan feature-a,feature-b

    RUNTIME_DIR="$runtime" PYTHONPATH="$3/python" "$1" - <<"PY"
import json
import os
import pathlib

runtime = pathlib.Path(os.environ["RUNTIME_DIR"]) / "python-engine"
manifest = json.loads((runtime / "ports_manifest.json").read_text(encoding="utf-8"))

projects = manifest["projects"]
assert len(projects) == 3, projects
for key in ("backend", "frontend", "db", "redis", "n8n"):
    values = [proj["ports"][key]["final"] for proj in projects]
    assert len(values) == len(set(values)), (key, values)
print("ok")
PY
  ' _ "$PYTHON_BIN" "$BIN" "$REPO_ROOT"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}
