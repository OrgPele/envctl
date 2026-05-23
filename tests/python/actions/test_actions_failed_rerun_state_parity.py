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
    action_test_support_module,
    default_git_state_components,
    engine_runtime_module,
    parse_route,
)


class ActionsFailedRerunStateParityTests(_ActionsParityTestCase):
    def test_failed_only_rerun_allows_saved_manifest_from_different_git_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={"NO_COLOR": "1"})
            state = RunState(
                run_id="run-stale-failed",
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
                metadata={},
            )
            manifest_dir = engine.runtime_root / "runs" / state.run_id / "test-results" / "run_20260312_103000" / "Main"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / "failed_tests_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-12T10:30:00+00:00",
                        "project_name": "Main",
                        "project_root": str(repo),
                        "git_state": {
                            "head": "stale-head",
                            "status_hash": "stale-hash",
                            "status_lines": 99,
                        },
                        "entries": [
                            {
                                "suite": "Backend (pytest)",
                                "source": "backend_pytest",
                                "failed_tests": ["backend/tests/test_auth.py::test_signup_regression"],
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
                    "failed_tests": 1,
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
                def __init__(self, *args: object, **kwargs: object) -> None:
                    self.last_result = None

                def run_tests(self, command, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
                    captured_commands.append(list(command))
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _PassingRunner),
            ):
                code = engine.dispatch(parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            self.assertEqual(
                captured_commands[0][1:], ["-m", "pytest", "backend/tests/test_auth.py::test_signup_regression"]
            )

    def test_failed_only_backend_pytest_rerun_uses_poetry_project_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            backend = repo / "backend"
            backend.mkdir(parents=True, exist_ok=True)
            (backend / "pyproject.toml").write_text("[tool.poetry]\nname = 'backend'\n", encoding="utf-8")
            entry = action_test_support_module.FailedTestManifestEntry(
                source="backend_pytest",
                suite="Backend (pytest)",
                failed_tests=("backend/tests/test_auth.py::test_signup_regression",),
                failed_files=(),
            )

            with patch("envctl_engine.actions.action_test_support.shutil.which", side_effect=lambda name: f"/usr/bin/{name}"):
                spec = action_test_support_module._failed_rerun_spec_for_entry(
                    entry,
                    project_name="Main",
                    project_root=repo,
                    repo_root=repo,
                    target_obj=None,
                )

            self.assertFalse(isinstance(spec, str))
            self.assertIsNotNone(spec)
            self.assertEqual(
                spec.spec.command,
                [
                    "poetry",
                    "--project",
                    str(backend),
                    "run",
                    "python",
                    "-m",
                    "pytest",
                    "backend/tests/test_auth.py::test_signup_regression",
                ],
            )

    def test_failed_only_interrupt_preserves_previous_summary_metadata_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_python = repo / "backend" / ".venv" / "bin" / "python"
            backend_python.parent.mkdir(parents=True, exist_ok=True)
            backend_python.write_text("", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={"NO_COLOR": "1"})
            state = RunState(
                run_id="run-failed-only-interrupt",
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
            previous_dir = engine.runtime_root / "runs" / state.run_id / "test-results" / "run_20260319_120000" / "Main"
            previous_dir.mkdir(parents=True, exist_ok=True)
            previous_manifest_path = previous_dir / "failed_tests_manifest.json"
            previous_manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-19T12:00:00+00:00",
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
                                "failed_tests": ["backend/tests/test_auth.py::test_signup_regression"],
                                "failed_files": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            previous_summary_path = previous_dir / "failed_tests_summary.txt"
            previous_summary_path.write_text("previous summary", encoding="utf-8")
            previous_short_summary_path = engine.runtime_root / "runs" / state.run_id / "ft_interrupt_preserved.txt"
            previous_short_summary_path.write_text("previous summary", encoding="utf-8")
            original_metadata = {
                "Main": {
                    "summary_path": str(previous_summary_path),
                    "short_summary_path": str(previous_short_summary_path),
                    "manifest_path": str(previous_manifest_path),
                    "failed_tests": 1,
                    "failed_manifest_entries": 1,
                    "status": "failed",
                }
            }
            state.metadata["project_test_summaries"] = dict(original_metadata)
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )
            terminated_pids: list[int] = []
            engine.process_runner = SimpleNamespace(  # type: ignore[assignment]
                terminate_process_group=lambda pid, **_kwargs: terminated_pids.append(pid) or True,
            )

            class _InterruptingRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = None

                def run_tests(
                    self,
                    command,
                    *,
                    cwd=None,
                    env=None,
                    timeout=None,
                    process_started_callback=None,
                ):  # noqa: ANN001
                    _ = command, cwd, env, timeout
                    if callable(process_started_callback):
                        process_started_callback(7331)
                    raise KeyboardInterrupt

            with patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _InterruptingRunner):
                with self.assertRaises(KeyboardInterrupt):
                    engine.dispatch(parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            refreshed = engine._try_load_existing_state(mode="main", strict_mode_match=True)
            self.assertIsNotNone(refreshed)
            assert refreshed is not None
            self.assertEqual(refreshed.metadata.get("project_test_summaries"), original_metadata)
            self.assertEqual(terminated_pids, [7331])
            self.assertFalse(any(event.get("event") == "test.summary.persisted" for event in engine.events))

