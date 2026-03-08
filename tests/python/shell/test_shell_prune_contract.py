from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.shell.shell_prune import evaluate_shell_prune_contract, summarize_unmigrated_entries


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class ShellPruneContractTests(unittest.TestCase):
    def _mk_repo(self) -> Path:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        return repo

    def _write_manifest(self, repo: Path, *, commands: dict[str, str]) -> None:
        _write_json(
            repo / "docs/planning/python_engine_parity_manifest.json",
            {
                "generated_at": "2026-02-25",
                "commands": commands,
                "modes": {},
            },
        )

    def _write_main(self, repo: Path, *, source_line: str) -> None:
        main = repo / "lib/engine/main.sh"
        main.parent.mkdir(parents=True, exist_ok=True)
        main.write_text(source_line + "\n", encoding="utf-8")

    def _write_ledger(
        self,
        repo: Path,
        *,
        entries: list[dict[str, object]],
        command_mappings: list[dict[str, object]] | None = None,
    ) -> None:
        _write_json(
            repo / "docs/planning/refactoring/envctl-shell-ownership-ledger.json",
            {
                "version": 1,
                "generated_at": "2026-02-25T00:00:00Z",
                "entries": entries,
                "command_mappings": command_mappings or [],
                "compat_shim_allowlist": [
                    "lib/envctl.sh",
                    "lib/engine/main.sh",
                    "scripts/install.sh",
                ],
            },
        )

    def test_fails_when_delete_now_function_still_exists(self) -> None:
        repo = self._mk_repo()
        module_path = repo / "lib/engine/lib/demo.sh"
        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.write_text("demo_func() { :; }\n", encoding="utf-8")
        self._write_main(repo, source_line='source "${LIB_DIR}/demo.sh"')
        self._write_manifest(repo, commands={"doctor": "python_complete"})
        self._write_ledger(
            repo,
            entries=[
                {
                    "shell_module": "lib/engine/lib/demo.sh",
                    "shell_function": "demo_func",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "status": "python_verified_delete_now",
                    "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"],
                    "delete_wave": "wave-a",
                    "notes": "test",
                    "commands": ["doctor"],
                }
            ],
            command_mappings=[
                {
                    "command": "doctor",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"],
                }
            ],
        )

        result = evaluate_shell_prune_contract(repo, enforce_manifest_coverage=True)
        self.assertFalse(result.passed)
        self.assertTrue(any("python_verified_delete_now" in err for err in result.errors))

    def test_fails_when_python_complete_command_is_unmapped(self) -> None:
        repo = self._mk_repo()
        module_path = repo / "lib/engine/lib/demo.sh"
        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.write_text("demo_func() { :; }\n", encoding="utf-8")
        self._write_main(repo, source_line='source "${LIB_DIR}/demo.sh"')
        self._write_manifest(repo, commands={"doctor": "python_complete"})
        self._write_ledger(
            repo,
            entries=[
                {
                    "shell_module": "lib/engine/lib/demo.sh",
                    "shell_function": "demo_func",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "status": "python_partial_keep_temporarily",
                    "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"],
                    "delete_wave": "wave-a",
                    "notes": "test",
                    "commands": [],
                }
            ],
            command_mappings=[],
        )

        result = evaluate_shell_prune_contract(repo, enforce_manifest_coverage=True)
        self.assertFalse(result.passed)
        self.assertIn("doctor", result.missing_python_complete_commands)

    def test_fails_when_deleted_module_is_still_sourced(self) -> None:
        repo = self._mk_repo()
        self._write_main(repo, source_line='source "${LIB_DIR}/demo.sh"')
        self._write_manifest(repo, commands={"doctor": "python_complete"})
        self._write_ledger(
            repo,
            entries=[
                {
                    "shell_module": "lib/engine/lib/demo.sh",
                    "shell_function": "demo_func",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "status": "python_verified_delete_now",
                    "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"],
                    "delete_wave": "wave-a",
                    "notes": "test",
                    "commands": ["doctor"],
                }
            ],
            command_mappings=[
                {
                    "command": "doctor",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"],
                }
            ],
        )

        result = evaluate_shell_prune_contract(repo, enforce_manifest_coverage=True)
        self.assertFalse(result.passed)
        self.assertTrue(any("still sourced" in err for err in result.errors))

    def test_fails_when_unmigrated_exceeds_budget(self) -> None:
        repo = self._mk_repo()
        module_path = repo / "lib/engine/lib/demo.sh"
        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.write_text("demo_func() { :; }\n", encoding="utf-8")
        self._write_main(repo, source_line='source "${LIB_DIR}/demo.sh"')
        self._write_manifest(repo, commands={"doctor": "python_complete"})
        self._write_ledger(
            repo,
            entries=[
                {
                    "shell_module": "lib/engine/lib/demo.sh",
                    "shell_function": "demo_func",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "status": "unmigrated",
                    "evidence_tests": [],
                    "delete_wave": "wave-a",
                    "notes": "test",
                    "commands": [],
                }
            ],
            command_mappings=[
                {
                    "command": "doctor",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"],
                }
            ],
        )

        result = evaluate_shell_prune_contract(
            repo,
            enforce_manifest_coverage=True,
            max_unmigrated=0,
            phase="phase-1",
        )
        self.assertFalse(result.passed)
        self.assertTrue(any("unmigrated entries exceed budget" in err for err in result.errors))

    def test_warns_when_evidence_tests_missing_for_non_unmigrated(self) -> None:
        repo = self._mk_repo()
        module_path = repo / "lib/engine/lib/demo.sh"
        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.write_text("demo_func() { :; }\n", encoding="utf-8")
        self._write_main(repo, source_line='source "${LIB_DIR}/demo.sh"')
        self._write_manifest(repo, commands={"doctor": "python_complete"})
        self._write_ledger(
            repo,
            entries=[
                {
                    "shell_module": "lib/engine/lib/demo.sh",
                    "shell_function": "demo_func",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "status": "python_partial_keep_temporarily",
                    "evidence_tests": [],
                    "delete_wave": "wave-a",
                    "notes": "test",
                    "commands": ["doctor"],
                }
            ],
            command_mappings=[
                {
                    "command": "doctor",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"],
                }
            ],
        )

        result = evaluate_shell_prune_contract(repo, enforce_manifest_coverage=True)
        self.assertTrue(result.passed)
        self.assertTrue(any("non-unmigrated status without evidence_tests" in warning for warning in result.warnings))

    def test_budget_error_includes_phase_label(self) -> None:
        repo = self._mk_repo()
        module_path = repo / "lib/engine/lib/demo.sh"
        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.write_text("demo_func() { :; }\n", encoding="utf-8")
        self._write_main(repo, source_line='source "${LIB_DIR}/demo.sh"')
        self._write_manifest(repo, commands={"doctor": "python_complete"})
        self._write_ledger(
            repo,
            entries=[
                {
                    "shell_module": "lib/engine/lib/demo.sh",
                    "shell_function": "demo_func",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "status": "unmigrated",
                    "evidence_tests": [],
                    "delete_wave": "wave-a",
                    "notes": "test",
                    "commands": [],
                }
            ],
            command_mappings=[
                {
                    "command": "doctor",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"],
                }
            ],
        )

        result = evaluate_shell_prune_contract(
            repo,
            enforce_manifest_coverage=True,
            max_unmigrated=0,
            phase="wave-1",
        )
        self.assertFalse(result.passed)
        self.assertTrue(any("for phase wave-1" in err for err in result.errors))

    def test_fails_when_partial_keep_exceeds_budget(self) -> None:
        repo = self._mk_repo()
        module_path = repo / "lib/engine/lib/demo.sh"
        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.write_text("demo_func() { :; }\n", encoding="utf-8")
        self._write_main(repo, source_line='source "${LIB_DIR}/demo.sh"')
        self._write_manifest(repo, commands={"doctor": "python_complete"})
        self._write_ledger(
            repo,
            entries=[
                {
                    "shell_module": "lib/engine/lib/demo.sh",
                    "shell_function": "demo_func",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "status": "python_partial_keep_temporarily",
                    "evidence_tests": ["tests/python/test_missing_evidence.py"],
                    "delete_wave": "wave-a",
                    "notes": "test",
                    "commands": [],
                }
            ],
            command_mappings=[
                {
                    "command": "doctor",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"],
                }
            ],
        )

        result = evaluate_shell_prune_contract(
            repo,
            enforce_manifest_coverage=True,
            max_partial_keep=0,
            phase="cutover",
        )
        self.assertFalse(result.passed)
        self.assertTrue(any("partial_keep entries exceed budget" in err for err in result.errors))

    def test_partial_keep_with_existing_evidence_does_not_exceed_zero_budget_pre_cutover(self) -> None:
        repo = self._mk_repo()
        module_path = repo / "lib/engine/lib/demo.sh"
        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.write_text("demo_func() { :; }\n", encoding="utf-8")
        self._write_main(repo, source_line='source "${LIB_DIR}/demo.sh"')
        self._write_manifest(repo, commands={"doctor": "python_complete"})
        (repo / "tests/python").mkdir(parents=True, exist_ok=True)
        (repo / "tests/python/test_engine_runtime_command_parity.py").write_text("x = 1\n", encoding="utf-8")
        self._write_ledger(
            repo,
            entries=[
                {
                    "shell_module": "lib/engine/lib/demo.sh",
                    "shell_function": "demo_func",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "status": "python_partial_keep_temporarily",
                    "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"],
                    "delete_wave": "wave-a",
                    "notes": "test",
                    "commands": [],
                }
            ],
            command_mappings=[
                {
                    "command": "doctor",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"],
                }
            ],
        )

        result = evaluate_shell_prune_contract(
            repo,
            enforce_manifest_coverage=True,
            max_partial_keep=0,
            phase="wave-1",
        )
        self.assertTrue(result.passed)
        self.assertFalse(any("partial_keep entries exceed budget" in err for err in result.errors))

    def test_partial_keep_with_existing_evidence_exceeds_zero_budget_in_cutover(self) -> None:
        repo = self._mk_repo()
        module_path = repo / "lib/engine/lib/demo.sh"
        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.write_text("demo_func() { :; }\n", encoding="utf-8")
        self._write_main(repo, source_line='source "${LIB_DIR}/demo.sh"')
        self._write_manifest(repo, commands={"doctor": "python_complete"})
        (repo / "tests/python").mkdir(parents=True, exist_ok=True)
        (repo / "tests/python/test_engine_runtime_command_parity.py").write_text("x = 1\n", encoding="utf-8")
        self._write_ledger(
            repo,
            entries=[
                {
                    "shell_module": "lib/engine/lib/demo.sh",
                    "shell_function": "demo_func",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "status": "python_partial_keep_temporarily",
                    "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"],
                    "delete_wave": "wave-a",
                    "notes": "test",
                    "commands": [],
                }
            ],
            command_mappings=[
                {
                    "command": "doctor",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"],
                }
            ],
        )

        result = evaluate_shell_prune_contract(
            repo,
            enforce_manifest_coverage=True,
            max_partial_keep=0,
            phase="cutover",
        )
        self.assertFalse(result.passed)
        self.assertEqual(result.partial_keep_budget_actual, 1)
        self.assertTrue(any("partial_keep entries exceed budget" in err for err in result.errors))

    def test_summary_includes_partial_keep_entries(self) -> None:
        repo = self._mk_repo()
        module_path = repo / "lib/engine/lib/demo.sh"
        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.write_text("demo_func() { :; }\n", encoding="utf-8")
        self._write_main(repo, source_line='source "${LIB_DIR}/demo.sh"')
        self._write_manifest(repo, commands={"doctor": "python_complete"})
        self._write_ledger(
            repo,
            entries=[
                {
                    "shell_module": "lib/engine/lib/demo.sh",
                    "shell_function": "demo_func",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "status": "python_partial_keep_temporarily",
                    "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"],
                    "delete_wave": "wave-a",
                    "notes": "test",
                    "commands": [],
                }
            ],
            command_mappings=[
                {
                    "command": "doctor",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"],
                }
            ],
        )

        rows = summarize_unmigrated_entries(repo, limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "python_partial_keep_temporarily")

    def test_fails_when_intentional_keep_exceeds_budget(self) -> None:
        repo = self._mk_repo()
        module_path = repo / "lib/engine/lib/demo.sh"
        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.write_text("demo_func() { :; }\n", encoding="utf-8")
        self._write_main(repo, source_line='source "${LIB_DIR}/demo.sh"')
        self._write_manifest(repo, commands={"doctor": "python_complete"})
        self._write_ledger(
            repo,
            entries=[
                {
                    "shell_module": "lib/engine/lib/demo.sh",
                    "shell_function": "demo_func",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "status": "shell_intentional_keep",
                    "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"],
                    "delete_wave": "wave-a",
                    "notes": "fallback keep",
                    "commands": [],
                }
            ],
            command_mappings=[
                {
                    "command": "doctor",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"],
                }
            ],
        )

        result = evaluate_shell_prune_contract(
            repo,
            enforce_manifest_coverage=True,
            max_intentional_keep=0,
            phase="cutover",
        )
        self.assertFalse(result.passed)
        self.assertEqual(result.intentional_keep_budget_actual, 1)
        self.assertTrue(any("intentional_keep entries exceed budget" in err for err in result.errors))

    def test_allows_intentional_keep_when_within_budget(self) -> None:
        repo = self._mk_repo()
        module_path = repo / "lib/engine/lib/demo.sh"
        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.write_text("demo_func() { :; }\n", encoding="utf-8")
        self._write_main(repo, source_line='source "${LIB_DIR}/demo.sh"')
        self._write_manifest(repo, commands={"doctor": "python_complete"})
        self._write_ledger(
            repo,
            entries=[
                {
                    "shell_module": "lib/engine/lib/demo.sh",
                    "shell_function": "demo_func",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "status": "shell_intentional_keep",
                    "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"],
                    "delete_wave": "wave-a",
                    "notes": "fallback keep",
                    "commands": [],
                }
            ],
            command_mappings=[
                {
                    "command": "doctor",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"],
                }
            ],
        )

        result = evaluate_shell_prune_contract(
            repo,
            enforce_manifest_coverage=True,
            max_intentional_keep=1,
            phase="cutover",
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.intentional_keep_budget_actual, 1)

    def test_allows_empty_entries_when_no_shell_modules_are_sourced(self) -> None:
        repo = self._mk_repo()
        self._write_main(repo, source_line="# shell modules retired")
        self._write_manifest(repo, commands={"doctor": "python_complete"})
        self._write_ledger(
            repo,
            entries=[],
            command_mappings=[
                {
                    "command": "doctor",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"],
                }
            ],
        )

        result = evaluate_shell_prune_contract(repo, enforce_manifest_coverage=True)
        self.assertTrue(result.passed)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.status_counts.get("shell_intentional_keep", 0), 0)

    def test_fails_when_entries_empty_but_shell_modules_still_sourced(self) -> None:
        repo = self._mk_repo()
        self._write_main(repo, source_line='source "${LIB_DIR}/demo.sh"')
        self._write_manifest(repo, commands={"doctor": "python_complete"})
        self._write_ledger(
            repo,
            entries=[],
            command_mappings=[
                {
                    "command": "doctor",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"],
                }
            ],
        )

        result = evaluate_shell_prune_contract(repo, enforce_manifest_coverage=True)
        self.assertFalse(result.passed)
        self.assertTrue(any("non-empty entries list" in err for err in result.errors))


if __name__ == "__main__":
    unittest.main()
