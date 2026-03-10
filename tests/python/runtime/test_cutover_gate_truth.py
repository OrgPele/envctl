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

    def _write_required_files(self, repo: Path, *, blocking_gaps: int = 0) -> None:
        (repo / "python" / "envctl_engine").mkdir(parents=True, exist_ok=True)
        (repo / "python" / "envctl_engine" / "__init__.py").write_text('"""ok"""\n', encoding="utf-8")
        (repo / "tests" / "python").mkdir(parents=True, exist_ok=True)
        (repo / "tests" / "python" / "test_stub.py").write_text("x = 1\n", encoding="utf-8")

        manifest = repo / "contracts" / "python_engine_parity_manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            '{"generated_at":"2026-03-09T00:00:00","commands":{"doctor":"python_complete"},"modes":{}}',
            encoding="utf-8",
        )
        gap_report = repo / "contracts" / "python_runtime_gap_report.json"
        gap_report.write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-09T00:00:00Z",
                    "summary": {
                        "gap_count": blocking_gaps,
                        "high_or_medium_gap_count": blocking_gaps,
                        "by_severity": {"high": blocking_gaps, "medium": 0, "low": 0},
                    },
                    "gaps": [],
                }
            ),
            encoding="utf-8",
        )

        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "add",
                "python/envctl_engine/__init__.py",
                "tests/python/test_stub.py",
                "contracts/python_engine_parity_manifest.json",
                "contracts/python_runtime_gap_report.json",
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

            engine = self._runtime(repo, runtime_root, {"ENVCTL_RUNTIME_TRUTH_MODE": "strict"})
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

    def test_doctor_reports_runtime_gap_contract_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._write_required_files(repo, blocking_gaps=1)

            engine = self._runtime(repo, runtime_root, {"ENVCTL_RUNTIME_TRUTH_MODE": "strict"})
            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--doctor"], env={}))

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("runtime_readiness_status: fail", rendered)
            self.assertIn("runtime_gap_blocking_count: 1", rendered)

    def test_strict_start_blocks_when_runtime_readiness_has_blocking_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._write_required_files(repo, blocking_gaps=1)

            engine = self._runtime(repo, runtime_root, {"ENVCTL_RUNTIME_TRUTH_MODE": "strict"})
            buffer = StringIO()
            with redirect_stdout(buffer):
                code = engine.dispatch(parse_route(["start", "--batch"], env={}))

            self.assertEqual(code, 1)
            self.assertIn("strict runtime readiness gate is incomplete", buffer.getvalue())
            reasons = [
                str(event.get("reason", ""))
                for event in engine.events
                if event.get("event") == "cutover.gate.fail_reason" and event.get("gate") == "shipability"
            ]
            self.assertIn("runtime_readiness_contract_failed", reasons)

    def test_strict_start_does_not_enforce_runtime_readiness_when_contract_files_are_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)

            engine = self._runtime(repo, runtime_root, {"ENVCTL_RUNTIME_TRUTH_MODE": "strict"})
            engine._discover_projects = lambda mode=None: []  # type: ignore[assignment]
            out = StringIO()
            with redirect_stdout(out):
                engine.dispatch(parse_route(["start", "--batch"], env={}))

            self.assertNotIn("strict runtime readiness gate is incomplete", out.getvalue())
            fail_reasons = [
                str(event.get("reason", ""))
                for event in engine.events
                if event.get("event") == "cutover.gate.fail_reason" and event.get("gate") == "shipability"
            ]
            self.assertNotIn("runtime_readiness_contract_failed", fail_reasons)

    def test_strict_resume_blocks_when_runtime_readiness_has_blocking_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._write_required_files(repo, blocking_gaps=1)

            engine = self._runtime(repo, runtime_root, {"ENVCTL_RUNTIME_TRUTH_MODE": "strict"})
            engine._try_load_existing_state = lambda mode=None, strict_mode_match=True: RunState(run_id="run-1", mode="main")  # type: ignore[assignment]
            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["resume", "--batch"], env={}))

            self.assertEqual(code, 1)
            self.assertIn("strict runtime readiness gate is incomplete", out.getvalue())

    def test_cutover_gate_evaluation_event_reports_runtime_readiness_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            self._init_repo(repo)
            self._write_required_files(repo)

            engine = self._runtime(repo, runtime_root, {"ENVCTL_RUNTIME_TRUTH_MODE": "strict"})
            readiness = engine._doctor_readiness_gates()

            self.assertTrue(readiness["shipability"])
            evaluate_events = [event for event in engine.events if event.get("event") == "cutover.gate.evaluate"]
            self.assertEqual(len(evaluate_events), 1)
            self.assertEqual(evaluate_events[0].get("runtime_readiness_contract_passed"), True)
            self.assertEqual(evaluate_events[0].get("runtime_readiness_blocking_gap_count"), 0)


if __name__ == "__main__":
    unittest.main()
