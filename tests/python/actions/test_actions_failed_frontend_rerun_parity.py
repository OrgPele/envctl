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


class ActionsFailedFrontendRerunParityTests(_ActionsParityTestCase):
    def test_failed_only_frontend_rerun_uses_saved_failed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            frontend_dir = repo / "frontend"
            frontend_dir.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-failed-frontend",
                mode="main",
                services={
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo),
                        pid=2222,
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    )
                },
            )
            head, status_hash, status_lines = default_git_state_components(repo)
            manifest_dir = engine.runtime_root / "runs" / state.run_id / "test-results" / "run_20260312_101000" / "Main"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / "failed_tests_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-12T10:10:00+00:00",
                        "project_name": "Main",
                        "project_root": str(repo),
                        "git_state": {
                            "head": head,
                            "status_hash": status_hash,
                            "status_lines": status_lines,
                        },
                        "entries": [
                            {
                                "suite": "Frontend (package test)",
                                "source": "frontend_package_test",
                                "failed_tests": [
                                    "src/components/a.test.ts::renders",
                                    "src/components/b.test.ts::fails",
                                    "src/components/a.test.ts",
                                ],
                                "failed_files": [
                                    "src/components/a.test.ts",
                                    "src/components/b.test.ts",
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state.metadata["project_test_summaries"] = {
                "Main": {
                    "manifest_path": str(manifest_path),
                    "failed_tests": 3,
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

            with (
                patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _PassingRunner),
                patch("envctl_engine.actions.action_test_support.detect_package_manager", return_value="bun"),
            ):
                code = engine.dispatch(parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            self.assertEqual(
                captured_commands[0],
                [
                    "bun",
                    "run",
                    "test",
                    "--",
                    "src/components/a.test.ts",
                    "src/components/b.test.ts",
                ],
            )

    def test_failed_only_frontend_rerun_derives_failed_files_from_legacy_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            frontend_dir = repo / "frontend"
            frontend_dir.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-failed-frontend-legacy",
                mode="main",
                services={
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo),
                        pid=2222,
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    )
                },
            )
            head, status_hash, status_lines = default_git_state_components(repo)
            manifest_dir = engine.runtime_root / "runs" / state.run_id / "test-results" / "run_20260312_101500" / "Main"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / "failed_tests_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-12T10:15:00+00:00",
                        "project_name": "Main",
                        "project_root": str(repo),
                        "git_state": {
                            "head": head,
                            "status_hash": status_hash,
                            "status_lines": status_lines,
                        },
                        "entries": [
                            {
                                "suite": "Frontend (package test)",
                                "source": "frontend_package_test",
                                "failed_tests": [
                                    "src/components/a.test.ts::renders",
                                    "src/components/b.test.ts::fails",
                                    "src/components/a.test.ts",
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state.metadata["project_test_summaries"] = {
                "Main": {
                    "manifest_path": str(manifest_path),
                    "failed_tests": 3,
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

            with (
                patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _PassingRunner),
                patch("envctl_engine.actions.action_test_support.detect_package_manager", return_value="bun"),
            ):
                code = engine.dispatch(parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            self.assertEqual(
                captured_commands[0],
                [
                    "bun",
                    "run",
                    "test",
                    "--",
                    "src/components/a.test.ts",
                    "src/components/b.test.ts",
                ],
            )

    def test_failed_only_frontend_rerun_normalizes_repo_relative_failed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "src" / "components").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-failed-frontend-repo-relative",
                mode="main",
                services={
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo),
                        pid=2222,
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    )
                },
            )
            head, status_hash, status_lines = default_git_state_components(repo)
            manifest_dir = engine.runtime_root / "runs" / state.run_id / "test-results" / "run_20260313_031100" / "Main"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / "failed_tests_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-13T03:11:00+00:00",
                        "project_name": "Main",
                        "project_root": str(repo),
                        "git_state": {
                            "head": head,
                            "status_hash": status_hash,
                            "status_lines": status_lines,
                        },
                        "entries": [
                            {
                                "suite": "Frontend (package test)",
                                "source": "frontend_package_test",
                                "failed_tests": [
                                    "frontend/src/components/a.test.ts::renders",
                                    "frontend/src/components/b.test.ts::fails",
                                ],
                                "failed_files": [
                                    "frontend/src/components/a.test.ts",
                                    "frontend/src/components/b.test.ts",
                                ],
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

            with (
                patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _PassingRunner),
                patch("envctl_engine.actions.action_test_support.detect_package_manager", return_value="bun"),
            ):
                code = engine.dispatch(parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            self.assertEqual(
                captured_commands[0],
                [
                    "bun",
                    "run",
                    "test",
                    "--",
                    "src/components/a.test.ts",
                    "src/components/b.test.ts",
                ],
            )

