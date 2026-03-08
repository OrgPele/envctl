#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "release gate fails when docs important flags are unsupported by parser" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"

  run bash -lc '
set -euo pipefail
repo_tmp=$(mktemp -d)
repo="$repo_tmp/repo"
mkdir -p "$repo/.git" "$repo/docs"
cat > "$repo/docs/important-flags.md" <<DOC
# Important Flags
| Flag | Purpose |
| --- | --- |
| \`--definitely-not-supported\` | test |
DOC

PYTHONPATH="$1/python" "$2" - <<PY
from pathlib import Path
from envctl_engine.release_gate import evaluate_shipability

repo = Path("$repo")
result = evaluate_shipability(
    repo_root=repo,
    required_paths=[],
    required_scopes=[],
    check_tests=False,
    enforce_parity_sync=False,
    enforce_shell_prune_contract=False,
    enforce_documented_flag_parity=True,
)
print("passed=", result.passed)
for err in result.errors:
    print(err)
if result.passed:
    raise SystemExit(1)
if not any("unsupported by parser" in err for err in result.errors):
    raise SystemExit(2)
PY
  ' _ "$REPO_ROOT" "$PYTHON_BIN"

  [ "$status" -eq 0 ]
  [[ "$output" == *"passed= False"* ]]
  [[ "$output" == *"unsupported by parser"* ]]
}
