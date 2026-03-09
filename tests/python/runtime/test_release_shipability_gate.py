from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.shell.release_gate import ShipabilityResult, evaluate_shipability


class ReleaseShipabilityGateTests(unittest.TestCase):
    _PARITY_MANIFEST_PATH = "contracts/python_engine_parity_manifest.json"
    _SHELL_LEDGER_PATH = "contracts/envctl-shell-ownership-ledger.json"
    _REQUIRED_ENGINE_INIT = "python/envctl_engine/__init__.py"
    _DEMO_MAIN_PATH = "lib/engine/main.sh"
    _DEMO_MODULE_PATH = "lib/engine/lib/demo.sh"
    _COMMAND_PARITY_TEST = "tests/python/test_engine_runtime_command_parity.py"
    _COMPAT_SHIM_ALLOWLIST = ["lib/envctl.sh", "lib/engine/main.sh", "scripts/install.sh"]
    _BASE_REQUIRED_PATHS = [
        "python/envctl_engine",
        _PARITY_MANIFEST_PATH,
        _SHELL_LEDGER_PATH,
    ]
    _BASE_REQUIRED_SCOPES = ["python/envctl_engine", "contracts"]

    def _init_repo(self, root: Path) -> None:
        subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True, capture_output=True, text=True)

    def _commit_paths(self, repo: Path, *paths: str, message: str = "init") -> None:
        subprocess.run(
            ["git", "-C", str(repo), "add", *paths],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", message],
            check=True,
            capture_output=True,
            text=True,
        )

    def _write_required_engine_init(self, repo: Path) -> None:
        required_dir = repo / "python" / "envctl_engine"
        required_dir.mkdir(parents=True, exist_ok=True)
        (required_dir / "__init__.py").write_text('"""ok"""\n', encoding="utf-8")

    def _write_parity_manifest(self, repo: Path) -> None:
        parity_manifest = repo / self._PARITY_MANIFEST_PATH
        parity_manifest.parent.mkdir(parents=True, exist_ok=True)
        parity_manifest.write_text(
            json.dumps(
                {
                    "generated_at": "2026-02-25",
                    "commands": {"doctor": "python_complete"},
                    "modes": {},
                }
            ),
            encoding="utf-8",
        )

    def _write_shell_ownership_ledger(
        self,
        repo: Path,
        *,
        status: str,
        evidence_tests: list[str],
        include_command_mapping: bool = True,
        command_mapping_evidence_tests: list[str] | None = None,
    ) -> None:
        ledger_path = repo / self._SHELL_LEDGER_PATH
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        command_mappings: list[dict[str, object]] = []
        if include_command_mapping:
            command_mappings.append(
                {
                    "command": "doctor",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "evidence_tests": list(
                        command_mapping_evidence_tests
                        or [self._COMMAND_PARITY_TEST]
                    ),
                }
            )
        ledger_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "generated_at": "2026-02-25T00:00:00Z",
                    "entries": [
                        {
                            "shell_module": self._DEMO_MODULE_PATH,
                            "shell_function": "demo_func",
                            "python_owner_module": "python/envctl_engine/engine_runtime.py",
                            "python_owner_symbol": "PythonEngineRuntime._doctor",
                            "status": status,
                            "evidence_tests": list(evidence_tests),
                            "delete_wave": "wave-a",
                            "notes": "test",
                            "commands": [],
                        }
                    ],
                    "command_mappings": command_mappings,
                    "compat_shim_allowlist": list(self._COMPAT_SHIM_ALLOWLIST),
                }
            ),
            encoding="utf-8",
        )

    def _write_demo_shell_files(self, repo: Path) -> None:
        main_path = repo / self._DEMO_MAIN_PATH
        main_path.parent.mkdir(parents=True, exist_ok=True)
        main_path.write_text('source "${LIB_DIR}/demo.sh"\n', encoding="utf-8")
        demo_module = repo / self._DEMO_MODULE_PATH
        demo_module.parent.mkdir(parents=True, exist_ok=True)
        demo_module.write_text("demo_func() { :; }\n", encoding="utf-8")

    def _prepare_shell_contract_repo(
        self,
        repo: Path,
        *,
        status: str,
        evidence_tests: list[str],
        include_command_mapping: bool = True,
        command_mapping_evidence_tests: list[str] | None = None,
        extra_tracked_paths: list[str] | None = None,
    ) -> None:
        self._write_required_engine_init(repo)
        self._write_parity_manifest(repo)
        self._write_shell_ownership_ledger(
            repo,
            status=status,
            evidence_tests=evidence_tests,
            include_command_mapping=include_command_mapping,
            command_mapping_evidence_tests=command_mapping_evidence_tests,
        )
        self._write_demo_shell_files(repo)
        tracked_paths = [
            self._REQUIRED_ENGINE_INIT,
            self._PARITY_MANIFEST_PATH,
            self._SHELL_LEDGER_PATH,
            self._DEMO_MAIN_PATH,
            self._DEMO_MODULE_PATH,
        ]
        tracked_paths.extend(extra_tracked_paths or [])
        self._commit_paths(repo, *tracked_paths)

    def test_release_shipability_script_leaves_shell_budgets_undefined_when_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            if str(REPO_ROOT) not in sys.path:
                sys.path.insert(0, str(REPO_ROOT))
            from scripts import release_shipability_gate

            captured: dict[str, object] = {}

            def _capture(**kwargs: object) -> ShipabilityResult:
                captured.update(kwargs)
                return ShipabilityResult(passed=True, errors=[], warnings=[])

            with patch("envctl_engine.shell.release_gate.evaluate_shipability", side_effect=_capture):
                code = release_shipability_gate.main([
                    "--repo",
                    str(repo),
                    "--skip-shell-prune-contract",
                    "--skip-parity-sync",
                ])

            self.assertEqual(code, 0)
            self.assertIsNone(captured.get("shell_prune_max_unmigrated"))
            self.assertIsNone(captured.get("shell_prune_max_partial_keep"))
            self.assertIsNone(captured.get("shell_prune_max_intentional_keep"))
            self.assertEqual(captured.get("require_shell_budget_complete"), False)

    def test_gate_passes_when_required_paths_are_tracked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)

            required_dir = repo / "python" / "envctl_engine"
            required_dir.mkdir(parents=True, exist_ok=True)
            (required_dir / "__init__.py").write_text('"""ok"""\n', encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(repo), "add", "python/envctl_engine/__init__.py"],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True, capture_output=True, text=True)

            result = evaluate_shipability(
                repo_root=repo,
                required_paths=["python/envctl_engine"],
                required_scopes=["python/envctl_engine"],
                check_tests=False,
                enforce_parity_sync=False,
                enforce_shell_prune_contract=False,
            )
            self.assertTrue(result.passed)
            self.assertEqual(result.errors, [])

    def test_gate_fails_when_required_scope_has_untracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)

            required_dir = repo / "tests" / "python"
            required_dir.mkdir(parents=True, exist_ok=True)
            (required_dir / "tracked.py").write_text("x = 1\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(repo), "add", "tests/python/tracked.py"],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "tracked"], check=True, capture_output=True, text=True)

            (required_dir / "untracked.py").write_text("x = 2\n", encoding="utf-8")

            result = evaluate_shipability(
                repo_root=repo,
                required_paths=["tests/python"],
                required_scopes=["tests/python"],
                check_tests=False,
                enforce_parity_sync=False,
                enforce_shell_prune_contract=False,
            )
            self.assertFalse(result.passed)
            self.assertTrue(any("untracked" in err for err in result.errors))

    def test_gate_fails_when_shell_prune_contract_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)

            self._prepare_shell_contract_repo(
                repo,
                status="python_partial_keep_temporarily",
                evidence_tests=[self._COMMAND_PARITY_TEST],
                include_command_mapping=False,
            )

            result = evaluate_shipability(
                repo_root=repo,
                required_paths=self._BASE_REQUIRED_PATHS,
                required_scopes=self._BASE_REQUIRED_SCOPES,
                check_tests=False,
                enforce_parity_sync=False,
                enforce_shell_prune_contract=True,
            )
            self.assertFalse(result.passed)
            self.assertTrue(any("python_complete command mapping missing" in err for err in result.errors))

    def test_gate_fails_when_unmigrated_entries_exceed_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)

            self._prepare_shell_contract_repo(
                repo,
                status="unmigrated",
                evidence_tests=[],
            )

            result = evaluate_shipability(
                repo_root=repo,
                required_paths=self._BASE_REQUIRED_PATHS,
                required_scopes=self._BASE_REQUIRED_SCOPES,
                check_tests=False,
                enforce_parity_sync=False,
                enforce_shell_prune_contract=True,
                shell_prune_max_unmigrated=0,
                shell_prune_phase="cutover",
            )
            self.assertFalse(result.passed)
            self.assertTrue(any("unmigrated entries exceed budget" in err for err in result.errors))

    def test_gate_enforces_shell_prune_budget_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)

            self._prepare_shell_contract_repo(
                repo,
                status="unmigrated",
                evidence_tests=[],
            )

            result = evaluate_shipability(
                repo_root=repo,
                required_paths=self._BASE_REQUIRED_PATHS,
                required_scopes=self._BASE_REQUIRED_SCOPES,
                check_tests=False,
                enforce_parity_sync=False,
                enforce_shell_prune_contract=True,
            )
            self.assertFalse(result.passed)
            self.assertTrue(any("unmigrated entries exceed budget" in err for err in result.errors))

    def test_gate_fails_when_partial_keep_entries_exceed_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)

            self._prepare_shell_contract_repo(
                repo,
                status="python_partial_keep_temporarily",
                evidence_tests=["tests/python/test_missing_evidence.py"],
            )

            result = evaluate_shipability(
                repo_root=repo,
                required_paths=self._BASE_REQUIRED_PATHS,
                required_scopes=self._BASE_REQUIRED_SCOPES,
                check_tests=False,
                enforce_parity_sync=False,
                enforce_shell_prune_contract=True,
                shell_prune_max_unmigrated=0,
                shell_prune_max_partial_keep=0,
                shell_prune_phase="cutover",
            )
            self.assertFalse(result.passed)
            self.assertTrue(any("partial_keep entries exceed budget" in err for err in result.errors))

    def test_gate_allows_covered_partial_keep_entries_with_zero_budget_pre_cutover(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)

            tests_dir = repo / "tests" / "python"
            tests_dir.mkdir(parents=True, exist_ok=True)
            (tests_dir / "test_engine_runtime_command_parity.py").write_text("x = 1\n", encoding="utf-8")

            self._prepare_shell_contract_repo(
                repo,
                status="python_partial_keep_temporarily",
                evidence_tests=[self._COMMAND_PARITY_TEST],
                extra_tracked_paths=[self._COMMAND_PARITY_TEST],
            )

            result = evaluate_shipability(
                repo_root=repo,
                required_paths=self._BASE_REQUIRED_PATHS,
                required_scopes=self._BASE_REQUIRED_SCOPES,
                check_tests=False,
                enforce_parity_sync=False,
                enforce_shell_prune_contract=True,
                shell_prune_max_unmigrated=0,
                shell_prune_max_partial_keep=0,
                shell_prune_phase="wave-1",
            )
            self.assertTrue(result.passed)
            self.assertEqual(result.errors, [])

    def test_gate_fails_when_cutover_has_covered_partial_keep_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)

            tests_dir = repo / "tests" / "python"
            tests_dir.mkdir(parents=True, exist_ok=True)
            (tests_dir / "test_engine_runtime_command_parity.py").write_text("x = 1\n", encoding="utf-8")

            self._prepare_shell_contract_repo(
                repo,
                status="python_partial_keep_temporarily",
                evidence_tests=[self._COMMAND_PARITY_TEST],
                extra_tracked_paths=[self._COMMAND_PARITY_TEST],
            )

            result = evaluate_shipability(
                repo_root=repo,
                required_paths=self._BASE_REQUIRED_PATHS,
                required_scopes=self._BASE_REQUIRED_SCOPES,
                check_tests=False,
                enforce_parity_sync=False,
                enforce_shell_prune_contract=True,
                shell_prune_max_unmigrated=0,
                shell_prune_max_partial_keep=0,
                shell_prune_phase="cutover",
            )
            self.assertFalse(result.passed)
            self.assertTrue(any("partial_keep entries exceed budget" in err for err in result.errors))

    def test_gate_enforces_partial_keep_budget_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)

            self._prepare_shell_contract_repo(
                repo,
                status="python_partial_keep_temporarily",
                evidence_tests=[self._COMMAND_PARITY_TEST],
            )

            result = evaluate_shipability(
                repo_root=repo,
                required_paths=self._BASE_REQUIRED_PATHS,
                required_scopes=self._BASE_REQUIRED_SCOPES,
                check_tests=False,
                enforce_parity_sync=False,
                enforce_shell_prune_contract=True,
            )
            self.assertFalse(result.passed)
            self.assertTrue(any("partial_keep entries exceed budget" in err for err in result.errors))

    def test_gate_enforces_intentional_keep_budget_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)

            self._prepare_shell_contract_repo(
                repo,
                status="shell_intentional_keep",
                evidence_tests=[self._COMMAND_PARITY_TEST],
            )

            result = evaluate_shipability(
                repo_root=repo,
                required_paths=self._BASE_REQUIRED_PATHS,
                required_scopes=self._BASE_REQUIRED_SCOPES,
                check_tests=False,
                enforce_parity_sync=False,
                enforce_shell_prune_contract=True,
            )
            self.assertFalse(result.passed)
            self.assertTrue(any("intentional_keep entries exceed budget" in err for err in result.errors))

    def test_gate_fails_when_intentional_keep_entries_exceed_configured_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)

            self._prepare_shell_contract_repo(
                repo,
                status="shell_intentional_keep",
                evidence_tests=[self._COMMAND_PARITY_TEST],
            )

            result = evaluate_shipability(
                repo_root=repo,
                required_paths=self._BASE_REQUIRED_PATHS,
                required_scopes=self._BASE_REQUIRED_SCOPES,
                check_tests=False,
                enforce_parity_sync=False,
                enforce_shell_prune_contract=True,
                shell_prune_max_unmigrated=0,
                shell_prune_max_partial_keep=0,
                shell_prune_max_intentional_keep=0,
                shell_prune_phase="cutover",
            )
            self.assertFalse(result.passed)
            self.assertTrue(any("intentional_keep entries exceed budget" in err for err in result.errors))

    def test_gate_requires_complete_shell_budget_for_cutover_with_explicit_unmigrated_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)

            self._prepare_shell_contract_repo(
                repo,
                status="shell_intentional_keep",
                evidence_tests=[self._COMMAND_PARITY_TEST],
            )

            result = evaluate_shipability(
                repo_root=repo,
                required_paths=self._BASE_REQUIRED_PATHS,
                required_scopes=self._BASE_REQUIRED_SCOPES,
                check_tests=False,
                enforce_parity_sync=False,
                enforce_shell_prune_contract=True,
                shell_prune_max_unmigrated=0,
                shell_prune_phase="cutover",
                require_shell_budget_complete=True,
            )
            self.assertFalse(result.passed)
            self.assertTrue(any("shell_partial_keep_budget_undefined" in err for err in result.errors))
            self.assertTrue(any("shell_intentional_keep_budget_undefined" in err for err in result.errors))

    def test_gate_fails_when_strict_shell_budget_profile_missing_intentional_keep_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)

            self._prepare_shell_contract_repo(
                repo,
                status="shell_intentional_keep",
                evidence_tests=[self._COMMAND_PARITY_TEST],
            )

            result = evaluate_shipability(
                repo_root=repo,
                required_paths=self._BASE_REQUIRED_PATHS,
                required_scopes=self._BASE_REQUIRED_SCOPES,
                check_tests=False,
                enforce_parity_sync=False,
                enforce_shell_prune_contract=True,
                shell_prune_max_unmigrated=0,
                shell_prune_max_partial_keep=0,
                shell_prune_phase="cutover",
                require_shell_budget_complete=True,
            )
            self.assertFalse(result.passed)
            self.assertTrue(any("shell_intentional_keep_budget_undefined" in err for err in result.errors))

    def test_gate_requires_complete_budget_profile_when_cutover_unmigrated_budget_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)

            self._prepare_shell_contract_repo(
                repo,
                status="shell_intentional_keep",
                evidence_tests=[self._COMMAND_PARITY_TEST],
            )

            result = evaluate_shipability(
                repo_root=repo,
                required_paths=self._BASE_REQUIRED_PATHS,
                required_scopes=self._BASE_REQUIRED_SCOPES,
                check_tests=False,
                enforce_parity_sync=False,
                enforce_shell_prune_contract=True,
                shell_prune_max_unmigrated=0,
                shell_prune_phase="cutover",
                require_shell_budget_complete=False,
            )
            self.assertFalse(result.passed)
            self.assertTrue(any("shell_partial_keep_budget_undefined" in err for err in result.errors))
            self.assertTrue(any("shell_intentional_keep_budget_undefined" in err for err in result.errors))

    def test_gate_fails_when_docs_flags_are_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)

            docs = repo / "docs" / "important-flags.md"
            docs.parent.mkdir(parents=True, exist_ok=True)
            docs.write_text(
                "# Important Flags\n\n| Flag | Purpose |\n| --- | --- |\n| `--definitely-not-supported` | test |\n",
                encoding="utf-8",
            )

            result = evaluate_shipability(
                repo_root=repo,
                required_paths=[],
                required_scopes=[],
                check_tests=False,
                enforce_parity_sync=False,
                enforce_shell_prune_contract=False,
                enforce_documented_flag_parity=True,
            )
            self.assertFalse(result.passed)
            self.assertTrue(any("unsupported by parser" in err for err in result.errors))

    def test_gate_fails_when_shell_flags_are_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)

            shell_cli = repo / "lib" / "engine" / "lib" / "run_all_trees_cli.sh"
            shell_cli.parent.mkdir(parents=True, exist_ok=True)
            shell_cli.write_text(
                "#!/usr/bin/env bash\n"
                "case \"$1\" in\n"
                "  --definitely-unsupported-shell-flag) ;;\n"
                "esac\n",
                encoding="utf-8",
            )

            result = evaluate_shipability(
                repo_root=repo,
                required_paths=[],
                required_scopes=[],
                check_tests=False,
                enforce_parity_sync=False,
                enforce_shell_prune_contract=False,
                enforce_documented_flag_parity=False,
                enforce_shell_flag_parity=True,
            )
            self.assertFalse(result.passed)
            self.assertTrue(any("shell flags unsupported by parser" in err for err in result.errors))

    def test_gate_fails_when_manifest_and_runtime_parity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)

            self._write_required_engine_init(repo)
            self._write_parity_manifest(repo)
            self._commit_paths(repo, self._REQUIRED_ENGINE_INIT, self._PARITY_MANIFEST_PATH)

            with patch("envctl_engine.runtime.engine_runtime.PythonEngineRuntime.PARTIAL_COMMANDS", ("start",)):
                result = evaluate_shipability(
                    repo_root=repo,
                    required_paths=["python/envctl_engine", self._PARITY_MANIFEST_PATH],
                    required_scopes=["python/envctl_engine", "docs/planning"],
                    check_tests=False,
                    enforce_parity_sync=True,
                    enforce_shell_prune_contract=False,
                    enforce_documented_flag_parity=False,
                    enforce_shell_flag_parity=False,
                )
            self.assertFalse(result.passed)
            self.assertTrue(any("parity manifest/runtime mismatch" in err for err in result.errors))

    def test_gate_check_tests_runs_python_and_python_bats_lanes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            bats_dir = repo / "tests" / "bats"
            bats_dir.mkdir(parents=True, exist_ok=True)
            (bats_dir / "python_sample.bats").write_text("#!/usr/bin/env bats\n", encoding="utf-8")
            (bats_dir / "parallel_trees_python_e2e.bats").write_text("#!/usr/bin/env bats\n", encoding="utf-8")
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "add",
                    "tests/bats/python_sample.bats",
                    "tests/bats/parallel_trees_python_e2e.bats",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "tests"], check=True, capture_output=True, text=True)

            with patch("envctl_engine.shell.release_gate._run_cmd", return_value=0) as run_cmd:
                result = evaluate_shipability(
                    repo_root=repo,
                    required_paths=[],
                    required_scopes=[],
                    check_tests=True,
                    enforce_parity_sync=False,
                    enforce_shell_prune_contract=False,
                    enforce_documented_flag_parity=False,
                    enforce_shell_flag_parity=False,
                )

            self.assertTrue(result.passed)
            self.assertEqual(run_cmd.call_count, 2)
            python_call = run_cmd.call_args_list[0]
            bats_call = run_cmd.call_args_list[1]

            self.assertEqual(
                list(python_call.args[1]),
                [
                    ".venv/bin/python",
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "tests/python",
                    "-p",
                    "test_*.py",
                ],
            )
            self.assertEqual(
                list(bats_call.args[1]),
                [
                    "bats",
                    "tests/bats/python_sample.bats",
                    "tests/bats/parallel_trees_python_e2e.bats",
                ],
            )
            self.assertFalse(bool(bats_call.kwargs.get("shell", False)))


if __name__ == "__main__":
    unittest.main()
