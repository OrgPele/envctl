from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.runtime.command_router import parse_route
from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime, run_state_to_json
from envctl_engine.state.models import RunState, ServiceRecord


class CutoverGateTruthTests(unittest.TestCase):
    def _init_repo(self, root: Path) -> None:
        subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True, capture_output=True, text=True)

    def _write_required_files(self, repo: Path) -> None:
        (repo / "python" / "envctl_engine").mkdir(parents=True, exist_ok=True)
        (repo / "python" / "envctl_engine" / "__init__.py").write_text('"""ok"""\n', encoding="utf-8")
        (repo / "tests" / "python").mkdir(parents=True, exist_ok=True)
        (repo / "tests" / "python" / "test_stub.py").write_text("x = 1\n", encoding="utf-8")
        (repo / "tests" / "bats").mkdir(parents=True, exist_ok=True)
        (repo / "tests" / "bats" / "parallel_trees_python_e2e.bats").write_text(
            "#!/usr/bin/env bats\n", encoding="utf-8"
        )
        (repo / "tests" / "bats" / "python_engine_parity.bats").write_text(
            "#!/usr/bin/env bats\n", encoding="utf-8"
        )

        manifest = repo / "contracts" / "python_engine_parity_manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            '{"generated_at":"2026-02-25","commands":{"doctor":"python_complete"},"modes":{}}',
            encoding="utf-8",
        )

        ledger = repo / "contracts" / "envctl-shell-ownership-ledger.json"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger_payload = {
            "version": 1,
            "generated_at": "2026-02-25T00:00:00Z",
            "entries": [
                {
                    "shell_module": "lib/engine/lib/demo.sh",
                    "shell_function": "demo_func",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "status": "python_partial_keep_temporarily",
                    "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"],
                    "delete_wave": "wave-1",
                    "notes": "test",
                    "commands": ["doctor"],
                }
            ],
            "command_mappings": [
                {
                    "command": "doctor",
                    "python_owner_module": "python/envctl_engine/engine_runtime.py",
                    "python_owner_symbol": "PythonEngineRuntime._doctor",
                    "evidence_tests": ["tests/python/test_engine_runtime_command_parity.py"],
                }
            ],
            "compat_shim_allowlist": ["lib/envctl.sh", "lib/engine/main.sh", "scripts/install.sh"],
        }
        ledger.write_text(json.dumps(ledger_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        main_path = repo / "lib" / "engine" / "main.sh"
        main_path.parent.mkdir(parents=True, exist_ok=True)
        main_path.write_text('source "${LIB_DIR}/demo.sh"\n', encoding="utf-8")
        demo_module = repo / "lib" / "engine" / "lib" / "demo.sh"
        demo_module.parent.mkdir(parents=True, exist_ok=True)
        demo_module.write_text("demo_func() { :; }\n", encoding="utf-8")

        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "add",
                "python/envctl_engine/__init__.py",
                "tests/python/test_stub.py",
                "tests/bats/parallel_trees_python_e2e.bats",
                "tests/bats/python_engine_parity.bats",
                "contracts/python_engine_parity_manifest.json",
                "contracts/envctl-shell-ownership-ledger.json",
                "lib/engine/main.sh",
                "lib/engine/lib/demo.sh",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True, capture_output=True, text=True)

    def _runtime(self, repo: Path, runtime_root: Path, env: dict[str, str]) -> PythonEngineRuntime:
        config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime_root), **env})
        return PythonEngineRuntime(config, env=env)

    def test_strict_cutover_fails_when_synthetic_state_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._write_required_files(repo)

            engine = self._runtime(
                repo,
                runtime_root,
                {
                    "ENVCTL_RUNTIME_TRUTH_MODE": "strict",
                },
            )
            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        requested_port=8000,
                        actual_port=8001,
                        status="simulated",
                    )
                },
            )
            state_path = engine._run_state_path()
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(run_state_to_json(state), encoding="utf-8")

            readiness = engine._doctor_readiness_gates()
            self.assertFalse(readiness["command_parity"])
            self.assertFalse(all(readiness.values()))

    def test_strict_cutover_fails_when_shell_budget_is_undefined(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._write_required_files(repo)

            engine = self._runtime(
                repo,
                runtime_root,
                {
                    "ENVCTL_RUNTIME_TRUTH_MODE": "strict",
                    "ENVCTL_SHELL_PRUNE_MAX_UNMIGRATED": "",
                },
            )
            readiness = engine._doctor_readiness_gates()
            self.assertFalse(readiness["shipability"])

    def test_strict_cutover_fails_when_intentional_keep_budget_is_undefined(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._write_required_files(repo)

            engine = self._runtime(
                repo,
                runtime_root,
                {
                    "ENVCTL_RUNTIME_TRUTH_MODE": "strict",
                    "ENVCTL_SHELL_PRUNE_MAX_UNMIGRATED": "0",
                    "ENVCTL_SHELL_PRUNE_MAX_PARTIAL_KEEP": "0",
                    "ENVCTL_SHELL_PRUNE_MAX_INTENTIONAL_KEEP": "",
                },
            )
            readiness = engine._doctor_readiness_gates()
            self.assertFalse(readiness["shipability"])
            reasons = [
                str(event.get("reason", ""))
                for event in engine.events
                if event.get("event") == "cutover.gate.fail_reason" and event.get("gate") == "shipability"
            ]
            self.assertIn("shell_intentional_keep_budget_undefined", reasons)

    def test_strict_start_blocks_when_shell_budget_profile_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._write_required_files(repo)

            engine = self._runtime(
                repo,
                runtime_root,
                {
                    "ENVCTL_RUNTIME_TRUTH_MODE": "strict",
                    "ENVCTL_SHELL_PRUNE_MAX_UNMIGRATED": "0",
                    "ENVCTL_SHELL_PRUNE_MAX_PARTIAL_KEEP": "0",
                    "ENVCTL_SHELL_PRUNE_MAX_INTENTIONAL_KEEP": "",
                },
            )
            buffer = StringIO()
            with redirect_stdout(buffer):
                code = engine.dispatch(parse_route(["start", "--batch"], env={}))

            self.assertEqual(code, 1)
            self.assertIn("Startup blocked: strict cutover shell budget profile is incomplete.", buffer.getvalue())
            reasons = [
                str(event.get("reason", ""))
                for event in engine.events
                if event.get("event") == "cutover.gate.fail_reason"
                and event.get("gate") == "shipability"
                and event.get("scope") == "start"
            ]
            self.assertIn("shell_intentional_keep_budget_undefined", reasons)
            evaluate_events = [
                event
                for event in engine.events
                if event.get("event") == "cutover.gate.evaluate" and event.get("scope") == "start"
            ]
            self.assertEqual(len(evaluate_events), 1)
            self.assertEqual(evaluate_events[0].get("shipability"), False)
            self.assertEqual(evaluate_events[0].get("shell_budget_profile_required"), True)
            self.assertEqual(evaluate_events[0].get("shell_budget_profile_complete"), False)

    def test_strict_resume_blocks_when_shell_budget_profile_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._write_required_files(repo)

            engine = self._runtime(
                repo,
                runtime_root,
                {
                    "ENVCTL_RUNTIME_TRUTH_MODE": "strict",
                    "ENVCTL_SHELL_PRUNE_MAX_UNMIGRATED": "0",
                    "ENVCTL_SHELL_PRUNE_MAX_PARTIAL_KEEP": "0",
                    "ENVCTL_SHELL_PRUNE_MAX_INTENTIONAL_KEEP": "",
                },
            )
            state = RunState(run_id="run-1", mode="main", services={})
            state_path = engine._run_state_path()
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(run_state_to_json(state), encoding="utf-8")

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = engine.dispatch(parse_route(["--resume"], env={}))

            self.assertEqual(code, 1)
            self.assertIn("Resume blocked: strict cutover shell budget profile is incomplete.", buffer.getvalue())
            reasons = [
                str(event.get("reason", ""))
                for event in engine.events
                if event.get("event") == "cutover.gate.fail_reason"
                and event.get("gate") == "shipability"
                and event.get("scope") == "resume"
            ]
            self.assertIn("shell_intentional_keep_budget_undefined", reasons)
            evaluate_events = [
                event
                for event in engine.events
                if event.get("event") == "cutover.gate.evaluate" and event.get("scope") == "resume"
            ]
            self.assertEqual(len(evaluate_events), 1)
            self.assertEqual(evaluate_events[0].get("shipability"), False)
            self.assertEqual(evaluate_events[0].get("shell_budget_profile_required"), True)
            self.assertEqual(evaluate_events[0].get("shell_budget_profile_complete"), False)


if __name__ == "__main__":
    unittest.main()
