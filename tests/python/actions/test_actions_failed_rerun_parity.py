from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.python.actions.actions_parity_test_support import (
    PythonEngineRuntime,
    RunState,
    ServiceRecord,
    _ActionsParityTestCase,
    default_git_state_components,
    engine_runtime_module,
    parse_route,
)


class ActionsFailedRerunParityTests(_ActionsParityTestCase):
    def test_failed_only_backend_rerun_uses_saved_exact_test_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_python = repo / "backend" / ".venv" / "bin" / "python"
            backend_python.parent.mkdir(parents=True, exist_ok=True)
            backend_python.write_text("", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-failed-rerun",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )
            head, status_hash, status_lines = default_git_state_components(repo)
            manifest_dir = engine.runtime_root / "runs" / state.run_id / "test-results" / "run_20260312_100000" / "Main"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / "failed_tests_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-12T10:00:00+00:00",
                        "project_name": "Main",
                        "project_root": str(repo),
                        "git_state": {
                            "head": head,
                            "status_hash": status_hash,
                            "status_lines": status_lines,
                        },
                        "entries": [
                            {
                                "suite": "Backend (pytest)",
                                "source": "backend_pytest",
                                "failed_tests": [
                                    "backend/tests/test_auth.py::test_signup_regression",
                                    "backend/tests/test_users.py::test_profile",
                                ],
                                "failed_files": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state.metadata["project_test_summaries"] = {
                "Main": {
                    "manifest_path": str(manifest_path),
                    "failed_tests": 2,
                    "status": "failed",
                }
            }
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            captured_commands: list[list[str]] = []

            class _PassingRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = None

                def run_tests(self, command, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
                    from envctl_engine.test_output.parser_base import TestResult

                    captured_commands.append(list(command))
                    self.last_result = TestResult(passed=2, failed=0, skipped=0, total=2)
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _PassingRunner):
                code = engine.dispatch(parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            self.assertTrue(captured_commands[0][0].endswith("/backend/.venv/bin/python"))
            self.assertEqual(
                captured_commands[0][1:],
                [
                    "-m",
                    "pytest",
                    "backend/tests/test_auth.py::test_signup_regression",
                    "backend/tests/test_users.py::test_profile",
                ],
            )

