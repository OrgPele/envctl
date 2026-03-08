from __future__ import annotations

import importlib
import json
import subprocess
import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

_shell_prune = importlib.import_module("envctl_engine.shell.shell_prune")
evaluate_shell_prune_contract = _shell_prune.evaluate_shell_prune_contract
load_shell_ownership_ledger = _shell_prune.load_shell_ownership_ledger


class ShellOwnershipLedgerTests(unittest.TestCase):
    def test_repository_ledger_exists_and_passes_contract_checks(self) -> None:
        result = evaluate_shell_prune_contract(REPO_ROOT, enforce_manifest_coverage=True)
        self.assertTrue(result.ledger_exists)
        self.assertEqual(result.errors, [])

    def test_ledger_has_required_schema_fields(self) -> None:
        payload = load_shell_ownership_ledger(REPO_ROOT)
        self.assertIsInstance(payload, dict)
        self.assertIn("entries", payload)
        self.assertIn("command_mappings", payload)
        self.assertIsInstance(payload["entries"], list)
        self.assertIsInstance(payload["command_mappings"], list)

    def test_python_complete_commands_are_mapped(self) -> None:
        result = evaluate_shell_prune_contract(REPO_ROOT, enforce_manifest_coverage=True)
        self.assertEqual(result.missing_python_complete_commands, [])

    def test_repository_ledger_matches_generator_for_command_mappings(self) -> None:
        ledger_path = REPO_ROOT / "docs" / "planning" / "refactoring" / "envctl-shell-ownership-ledger.json"
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
        completed = subprocess.run(
            [
                "python3",
                str(REPO_ROOT / "scripts" / "generate_shell_ownership_ledger.py"),
                "--repo",
                str(REPO_ROOT),
                "--stdout",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        generated = json.loads(completed.stdout)
        def _by_command(items: object) -> dict[str, dict[str, object]]:
            mapping: dict[str, dict[str, object]] = {}
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict):
                    continue
                command = str(item.get("command", "")).strip()
                if command:
                    mapping[command] = item
            return mapping

        self.assertEqual(
            _by_command(generated.get("command_mappings")),
            _by_command(payload.get("command_mappings")),
        )

    def test_wave_entries_have_evidence_tests(self) -> None:
        payload = load_shell_ownership_ledger(REPO_ROOT)
        entries = payload.get("entries", [])
        source_modules = payload.get("source_modules", [])
        if isinstance(source_modules, list) and not source_modules:
            self.assertEqual(entries, [])
            return
        modules_requiring_evidence = {
            "lib/engine/lib/actions.sh",
            "lib/engine/lib/analysis.sh",
            "lib/engine/lib/cli.sh",
            "lib/engine/lib/config.sh",
            "lib/engine/lib/config_loader.sh",
            "lib/engine/lib/core.sh",
            "lib/engine/lib/create_pr_helpers.sh",
            "lib/engine/lib/debug.sh",
            "lib/engine/lib/deploy_production_helpers.sh",
            "lib/engine/lib/docker.sh",
            "lib/engine/lib/env.sh",
            "lib/engine/lib/fs.sh",
            "lib/engine/lib/git.sh",
            "lib/engine/lib/loader.sh",
            "lib/engine/lib/planning.sh",
            "lib/engine/lib/ports.sh",
            "lib/engine/lib/pr.sh",
            "lib/engine/lib/python.sh",
            "lib/engine/lib/requirements_core.sh",
            "lib/engine/lib/requirements_seed.sh",
            "lib/engine/lib/requirements_supabase.sh",
            "lib/engine/lib/run_all_trees_cli.sh",
            "lib/engine/lib/run_all_trees_helpers.sh",
            "lib/engine/lib/run_cache.sh",
            "lib/engine/lib/runtime_map.sh",
            "lib/engine/lib/services_lifecycle.sh",
            "lib/engine/lib/services_logs.sh",
            "lib/engine/lib/services_registry.sh",
            "lib/engine/lib/services_worktrees.sh",
            "lib/engine/lib/setup_worktrees.sh",
            "lib/engine/lib/state.sh",
            "lib/engine/lib/summary.sh",
            "lib/engine/lib/test_runner.sh",
            "lib/engine/lib/tests.sh",
            "lib/engine/lib/ui.sh",
            "lib/engine/lib/worktrees.sh",
        }
        wave_entries = [entry for entry in entries if entry.get("shell_module") in modules_requiring_evidence]
        self.assertTrue(wave_entries, "expected wave modules in shell ownership ledger")
        for entry in wave_entries:
            evidence_tests = entry.get("evidence_tests")
            self.assertIsInstance(evidence_tests, list)
            self.assertTrue(
                evidence_tests,
                f"missing evidence_tests for {entry.get('shell_module')}::{entry.get('shell_function')}",
            )
            missing = [
                str(path)
                for path in evidence_tests
                if not (REPO_ROOT / str(path)).is_file()
            ]
            self.assertEqual(
                missing,
                [],
                f"missing evidence test paths for {entry.get('shell_module')}::{entry.get('shell_function')}",
            )

    def test_repository_ledger_passes_strict_cutover_budgets_when_shell_modules_are_retired(self) -> None:
        result = evaluate_shell_prune_contract(
            REPO_ROOT,
            enforce_manifest_coverage=True,
            max_unmigrated=0,
            max_partial_keep=0,
            max_intentional_keep=0,
            phase="cutover",
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.status_counts.get("unmigrated", 0), 0)

    def test_unmigrated_entries_use_granular_owner_symbols(self) -> None:
        payload = load_shell_ownership_ledger(REPO_ROOT)
        entries = payload.get("entries", [])
        self.assertIsInstance(entries, list)
        coarse_entries = [
            entry
            for entry in entries
            if isinstance(entry, dict)
            and str(entry.get("status", "")) == "unmigrated"
            and str(entry.get("python_owner_symbol", "")) == "PythonEngineRuntime.dispatch"
        ]
        self.assertEqual(coarse_entries, [])


if __name__ == "__main__":
    unittest.main()
