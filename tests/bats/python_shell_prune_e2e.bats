#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
}

@test "shell prune contract passes for repository ledger" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"
  run bash -lc '
    set +e
    PYTHONPATH="$1/python" "$2" "$1/scripts/verify_shell_prune_contract.py" --repo "$1" --max-unmigrated 0 --max-partial-keep 999 --max-intentional-keep 999
    rc=$?
    set -e
    echo "__RC__:$rc"
  ' _ "$REPO_ROOT" "$PYTHON_BIN"
  [[ "$output" == *"shell_prune.unmigrated_count: 0"* ]] && {
    [[ "$output" == *"shell_prune.passed: true"* ]]
    [[ "$output" == *"__RC__:0"* ]]
    return 0
  }
  [[ "$output" == *"shell_prune.passed: false"* ]]
  [[ "$output" == *"unmigrated entries exceed budget"* ]]
  [[ "$output" == *"__RC__:1"* ]]
}

@test "shell prune contract fails when ledger is missing" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"
  run bash -lc '
    set -euo pipefail
    tmp=$(mktemp -d)
    repo="$tmp/repo"
    mkdir -p "$repo/.git"
    set +e
    out=$(PYTHONPATH="$1/python" "$2" "$1/scripts/verify_shell_prune_contract.py" --repo "$repo" 2>&1)
    rc=$?
    set -e
    echo "$out"
    [ "$rc" -eq 1 ] || exit 1
    [[ "$out" == *"shell ownership ledger missing"* ]] || exit 1
    echo "ok"
  ' _ "$REPO_ROOT" "$PYTHON_BIN"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}

@test "shell prune contract enforces strict partial-keep budget by default" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"
  run bash -lc '
    set -euo pipefail
    tmp=$(mktemp -d)
    repo="$tmp/repo"
    mkdir -p "$repo/lib/engine/lib" "$repo/contracts"
    printf "source \"\${LIB_DIR}/demo.sh\"\n" > "$repo/lib/engine/main.sh"
    printf "demo_func() { :; }\n" > "$repo/lib/engine/lib/demo.sh"
    printf "{\"generated_at\":\"2026-02-25\",\"commands\":{\"doctor\":\"python_complete\"},\"modes\":{}}" > "$repo/contracts/python_engine_parity_manifest.json"
    cat > "$repo/contracts/envctl-shell-ownership-ledger.json" <<"JSON"
{
  "version": 1,
  "generated_at": "2026-02-25T00:00:00Z",
  "entries": [
    {
      "shell_module": "lib/engine/lib/demo.sh",
      "shell_function": "demo_func",
      "python_owner_module": "python/envctl_engine/engine_runtime.py",
      "python_owner_symbol": "PythonEngineRuntime._doctor",
      "status": "python_partial_keep_temporarily",
      "evidence_tests": ["tests/python/test_missing_evidence.py"],
      "delete_wave": "wave-1",
      "notes": "test",
      "commands": []
    }
  ],
  "command_mappings": [
    {
      "command": "doctor",
      "python_owner_module": "python/envctl_engine/engine_runtime.py",
      "python_owner_symbol": "PythonEngineRuntime._doctor",
      "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"]
    }
  ],
  "compat_shim_allowlist": ["lib/envctl.sh", "lib/engine/main.sh", "scripts/install.sh"]
}
JSON
    set +e
    out=$(PYTHONPATH="$1/python" "$2" "$1/scripts/verify_shell_prune_contract.py" --repo "$repo" 2>&1)
    rc=$?
    set -e
    echo "$out"
    [ "$rc" -eq 1 ] || exit 1
    [[ "$out" == *"partial_keep entries exceed budget"* ]] || exit 1
    echo "ok"
  ' _ "$REPO_ROOT" "$PYTHON_BIN"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}

@test "unmigrated report enforces strict partial-keep budget by default" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"
  run bash -lc '
    set -euo pipefail
    tmp=$(mktemp -d)
    repo="$tmp/repo"
    mkdir -p "$repo/lib/engine/lib" "$repo/contracts"
    printf "source \"\${LIB_DIR}/demo.sh\"\n" > "$repo/lib/engine/main.sh"
    printf "demo_func() { :; }\n" > "$repo/lib/engine/lib/demo.sh"
    printf "{\"generated_at\":\"2026-02-25\",\"commands\":{\"doctor\":\"python_complete\"},\"modes\":{}}" > "$repo/contracts/python_engine_parity_manifest.json"
    cat > "$repo/contracts/envctl-shell-ownership-ledger.json" <<"JSON"
{
  "version": 1,
  "generated_at": "2026-02-25T00:00:00Z",
  "entries": [
    {
      "shell_module": "lib/engine/lib/demo.sh",
      "shell_function": "demo_func",
      "python_owner_module": "python/envctl_engine/engine_runtime.py",
      "python_owner_symbol": "PythonEngineRuntime._doctor",
      "status": "python_partial_keep_temporarily",
      "evidence_tests": ["tests/python/test_missing_evidence.py"],
      "delete_wave": "wave-1",
      "notes": "test",
      "commands": []
    }
  ],
  "command_mappings": [
    {
      "command": "doctor",
      "python_owner_module": "python/envctl_engine/engine_runtime.py",
      "python_owner_symbol": "PythonEngineRuntime._doctor",
      "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"]
    }
  ],
  "compat_shim_allowlist": ["lib/envctl.sh", "lib/engine/main.sh", "scripts/install.sh"]
}
JSON
    set +e
    out=$(PYTHONPATH="$1/python" "$2" "$1/scripts/report_unmigrated_shell.py" --repo "$repo" 2>&1)
    rc=$?
    set -e
    echo "$out"
    [ "$rc" -eq 1 ] || exit 1
    [[ "$out" == *"shell_migration_status: fail"* ]] || exit 1
    [[ "$out" == *"partial_keep_count: 1"* ]] || exit 1
    [[ "$out" == *"partial_keep entries exceed budget"* ]] || exit 1
    echo "ok"
  ' _ "$REPO_ROOT" "$PYTHON_BIN"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}

@test "shell prune contract enforces strict intentional-keep budget by default" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"
  run bash -lc '
    set -euo pipefail
    tmp=$(mktemp -d)
    repo="$tmp/repo"
    mkdir -p "$repo/lib/engine/lib" "$repo/contracts"
    printf "source \"\${LIB_DIR}/demo.sh\"\n" > "$repo/lib/engine/main.sh"
    printf "demo_func() { :; }\n" > "$repo/lib/engine/lib/demo.sh"
    printf "{\"generated_at\":\"2026-02-25\",\"commands\":{\"doctor\":\"python_complete\"},\"modes\":{}}" > "$repo/contracts/python_engine_parity_manifest.json"
    cat > "$repo/contracts/envctl-shell-ownership-ledger.json" <<"JSON"
{
  "version": 1,
  "generated_at": "2026-02-25T00:00:00Z",
  "entries": [
    {
      "shell_module": "lib/engine/lib/demo.sh",
      "shell_function": "demo_func",
      "python_owner_module": "python/envctl_engine/engine_runtime.py",
      "python_owner_symbol": "PythonEngineRuntime._doctor",
      "status": "shell_intentional_keep",
      "evidence_tests": ["tests/python/test_missing_evidence.py"],
      "delete_wave": "wave-1",
      "notes": "test",
      "commands": []
    }
  ],
  "command_mappings": [
    {
      "command": "doctor",
      "python_owner_module": "python/envctl_engine/engine_runtime.py",
      "python_owner_symbol": "PythonEngineRuntime._doctor",
      "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"]
    }
  ],
  "compat_shim_allowlist": ["lib/envctl.sh", "lib/engine/main.sh", "scripts/install.sh"]
}
JSON
    set +e
    out=$(PYTHONPATH="$1/python" "$2" "$1/scripts/verify_shell_prune_contract.py" --repo "$repo" 2>&1)
    rc=$?
    set -e
    echo "$out"
    [ "$rc" -eq 1 ] || exit 1
    [[ "$out" == *"intentional_keep entries exceed budget"* ]] || exit 1
    echo "ok"
  ' _ "$REPO_ROOT" "$PYTHON_BIN"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}

@test "unmigrated report enforces strict intentional-keep budget by default" {
  [ -x "$PYTHON_BIN" ] || skip "project venv python not found"
  run bash -lc '
    set -euo pipefail
    tmp=$(mktemp -d)
    repo="$tmp/repo"
    mkdir -p "$repo/lib/engine/lib" "$repo/contracts"
    printf "source \"\${LIB_DIR}/demo.sh\"\n" > "$repo/lib/engine/main.sh"
    printf "demo_func() { :; }\n" > "$repo/lib/engine/lib/demo.sh"
    printf "{\"generated_at\":\"2026-02-25\",\"commands\":{\"doctor\":\"python_complete\"},\"modes\":{}}" > "$repo/contracts/python_engine_parity_manifest.json"
    cat > "$repo/contracts/envctl-shell-ownership-ledger.json" <<"JSON"
{
  "version": 1,
  "generated_at": "2026-02-25T00:00:00Z",
  "entries": [
    {
      "shell_module": "lib/engine/lib/demo.sh",
      "shell_function": "demo_func",
      "python_owner_module": "python/envctl_engine/engine_runtime.py",
      "python_owner_symbol": "PythonEngineRuntime._doctor",
      "status": "shell_intentional_keep",
      "evidence_tests": ["tests/python/test_missing_evidence.py"],
      "delete_wave": "wave-1",
      "notes": "test",
      "commands": []
    }
  ],
  "command_mappings": [
    {
      "command": "doctor",
      "python_owner_module": "python/envctl_engine/engine_runtime.py",
      "python_owner_symbol": "PythonEngineRuntime._doctor",
      "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"]
    }
  ],
  "compat_shim_allowlist": ["lib/envctl.sh", "lib/engine/main.sh", "scripts/install.sh"]
}
JSON
    set +e
    out=$(PYTHONPATH="$1/python" "$2" "$1/scripts/report_unmigrated_shell.py" --repo "$repo" 2>&1)
    rc=$?
    set -e
    echo "$out"
    [ "$rc" -eq 1 ] || exit 1
    [[ "$out" == *"shell_migration_status: fail"* ]] || exit 1
    [[ "$out" == *"intentional_keep_count: 1"* ]] || exit 1
    [[ "$out" == *"intentional_keep entries exceed budget"* ]] || exit 1
    echo "ok"
  ' _ "$REPO_ROOT" "$PYTHON_BIN"
  [ "$status" -eq 0 ]
  [[ "$output" == *"ok"* ]]
}
