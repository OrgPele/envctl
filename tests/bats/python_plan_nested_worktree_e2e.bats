#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  BIN="$REPO_ROOT/bin/envctl"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "python --plan discovers nested trees/<feature>/<iter> and assigns unique ports" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
    set -euo pipefail
    repo_tmp=$(mktemp -d)
    repo="$repo_tmp/repo"
    runtime="$repo_tmp/runtime"
    base=$((20000 + (RANDOM % 10000)))
    mkdir -p "$repo/.git"
    mkdir -p "$repo/trees/feature-a/1" "$repo/trees/feature-b/1"

    RUN_SH_RUNTIME_DIR="$runtime" \
    ENVCTL_BACKEND_PORT_BASE="$base" \
    ENVCTL_FRONTEND_PORT_BASE="$((base + 1000))" \
    ENVCTL_DB_PORT_BASE="$((base + 2000))" \
    ENVCTL_REDIS_PORT_BASE="$((base + 3000))" \
    ENVCTL_N8N_PORT_BASE="$((base + 4000))" \
    ENVCTL_RUNTIME_TRUTH_MODE=best_effort \
    ENVCTL_REQUIREMENTS_STRICT=false \
    ENVCTL_REQUIREMENT_LISTENER_TIMEOUT_SECONDS=0.1 \
    ENVCTL_REQUIREMENT_POSTGRES_CMD="sh -lc true" \
    ENVCTL_REQUIREMENT_REDIS_CMD="sh -lc true" \
    ENVCTL_REQUIREMENT_N8N_CMD="sh -lc true" \
    ENVCTL_REQUIREMENT_SUPABASE_CMD="sh -lc true" \
    ENVCTL_BACKEND_START_CMD="sh -lc true" \
    ENVCTL_FRONTEND_START_CMD="sh -lc true" \
    PYTHON_BIN="$1" \
    "$2" --repo "$repo" --plan feature-a,feature-b --no-parallel-trees --batch >/tmp/envctl_nested_plan.out

    RUNTIME_DIR="$runtime" PYTHONPATH="$3/python" "$1" - <<"PY"
import json
import os
import pathlib

runtime = pathlib.Path(os.environ["RUNTIME_DIR"]) / "python-engine"
manifest = json.loads((runtime / "ports_manifest.json").read_text(encoding="utf-8"))
projects = manifest["projects"]
names = [p["project"] for p in projects]
assert names == ["feature-a-1", "feature-b-1"], names
for key in ("backend", "frontend", "db", "redis", "n8n"):
    values = [proj["ports"][key]["final"] for proj in projects]
    assert len(values) == len(set(values)), (key, values)
print("ok")
PY

    RUN_SH_RUNTIME_DIR="$runtime" \
    PYTHON_BIN="$1" \
    "$2" --repo "$repo" --stop-all >/tmp/envctl_nested_plan_stop.out
  ' _ "$PYTHON_BIN" "$BIN" "$REPO_ROOT"

  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}
