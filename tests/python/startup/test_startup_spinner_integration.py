from __future__ import annotations

from contextlib import contextmanager
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.runtime.command_router import parse_route
from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord
from envctl_engine.runtime.engine_runtime import ProjectContext
from envctl_engine.state.models import PortPlan


class StartupSpinnerIntegrationTests(unittest.TestCase):
    def test_parallel_startup_uses_project_spinner_group_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-b" / "1").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                    "ENVCTL_REQUIREMENTS_STRICT": "false",
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_UI_SPINNER_MODE": "on",
                    "ENVCTL_BACKEND_MIGRATIONS_ON_STARTUP": "true",
                    "ENVCTL_BACKEND_START_CMD": "echo backend",
                    "ENVCTL_FRONTEND_START_CMD": "echo frontend",
                },
            )

            class _FakeProcess:
                def __init__(self, pid: int) -> None:
                    self.pid = pid

            class _FakeRunner:
                _pid = 9000

                def run(self, *_args, **_kwargs):  # noqa: ANN001
                    import subprocess

                    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

                def start(self, *_args, **_kwargs):  # noqa: ANN001
                    self._pid += 1
                    return _FakeProcess(self._pid)

                @staticmethod
                def wait_for_pid_port(*_args, **_kwargs):  # noqa: ANN001
                    return True

                @staticmethod
                def pid_owns_port(*_args, **_kwargs):  # noqa: ANN001
                    return True

                @staticmethod
                def find_pid_listener_port(*_args, **_kwargs):  # noqa: ANN001
                    return None

                @staticmethod
                def terminate(*_args, **_kwargs):  # noqa: ANN001
                    return True

                @staticmethod
                def is_pid_running(*_args, **_kwargs):  # noqa: ANN001
                    return True

            engine.process_runner = _FakeRunner()  # type: ignore[assignment]
            calls: list[tuple[str, str, str]] = []

            class _GroupStub:
                def __init__(self, projects, **_kwargs):  # noqa: ANN001
                    self._projects = list(projects)

                def __enter__(self):
                    calls.append(("enter", ",".join(self._projects), ""))
                    return self

                def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
                    _ = exc_type, exc, tb
                    calls.append(("exit", "", ""))
                    return False

                def update_project(self, project: str, message: str) -> None:
                    calls.append(("update", project, message))

                def mark_success(self, project: str, message: str) -> None:
                    calls.append(("success", project, message))

                def mark_failure(self, project: str, message: str) -> None:
                    calls.append(("failure", project, message))

                def print_detail(self, project: str, message: str) -> None:
                    calls.append(("detail", project, message))

            with (
                patch("envctl_engine.startup.startup_orchestrator._ProjectSpinnerGroup", _GroupStub),
                patch("envctl_engine.startup.startup_orchestrator.resolve_spinner_policy") as policy_mock,
                patch.object(engine, "_print_summary") as print_summary_mock,
            ):
                policy_mock.side_effect = lambda *_args, **_kwargs: type(
                    "_Policy",
                    (),
                    {
                        "mode": "on",
                        "enabled": True,
                        "reason": "",
                        "backend": "rich",
                        "min_ms": 120,
                        "verbose_events": False,
                        "style": "dots",
                    },
                )()
                code = engine.dispatch(parse_route(["--plan", "feature-a,feature-b", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertTrue(any(kind == "enter" for kind, _project, _msg in calls))
            updated_projects = {project for kind, project, _msg in calls if kind == "update"}
            self.assertIn("feature-a-1", updated_projects)
            self.assertIn("feature-b-1", updated_projects)
            succeeded_projects = {project for kind, project, _msg in calls if kind == "success"}
            self.assertIn("feature-a-1", succeeded_projects)
            self.assertIn("feature-b-1", succeeded_projects)
            success_messages = [msg for kind, _project, msg in calls if kind == "success"]
            self.assertTrue(success_messages)
            for message in success_messages:
                self.assertIn("backend=", message)
                self.assertIn("frontend=", message)
                self.assertIn("db=", message)
                self.assertIn("redis=", message)
                self.assertIn("n8n=", message)
            print_summary_mock.assert_not_called()

    def test_parallel_startup_renders_project_warning_under_matching_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            frontend_dir = repo / "trees" / "feature-a" / "1" / "frontend"
            other_backend_dir = repo / "trees" / "feature-b" / "1" / "backend"
            other_frontend_dir = repo / "trees" / "feature-b" / "1" / "frontend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            frontend_dir.mkdir(parents=True, exist_ok=True)
            other_backend_dir.mkdir(parents=True, exist_ok=True)
            other_frontend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            (backend_dir / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
            (other_backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                    "ENVCTL_REQUIREMENTS_STRICT": "false",
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_UI_SPINNER_MODE": "on",
                    "ENVCTL_BACKEND_MIGRATIONS_ON_STARTUP": "true",
                    "ENVCTL_BACKEND_START_CMD": "echo backend",
                    "ENVCTL_FRONTEND_START_CMD": "echo frontend",
                },
            )

            class _FakeProcess:
                def __init__(self, pid: int) -> None:
                    self.pid = pid

            class _FakeRunner:
                _pid = 9100

                def run(self, command, *_args, **_kwargs):  # noqa: ANN001
                    import subprocess

                    command_text = " ".join(str(token) for token in command)
                    if "alembic" in command_text and "upgrade" in command_text:
                        return subprocess.CompletedProcess(
                            args=command,
                            returncode=1,
                            stdout="",
                            stderr="ConnectionResetError: [Errno 54] Connection reset by peer",
                        )
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

                def start(self, *_args, **_kwargs):  # noqa: ANN001
                    self._pid += 1
                    return _FakeProcess(self._pid)

                @staticmethod
                def wait_for_pid_port(*_args, **_kwargs):  # noqa: ANN001
                    return True

                @staticmethod
                def pid_owns_port(*_args, **_kwargs):  # noqa: ANN001
                    return True

                @staticmethod
                def find_pid_listener_port(*_args, **_kwargs):  # noqa: ANN001
                    return None

                @staticmethod
                def terminate(*_args, **_kwargs):  # noqa: ANN001
                    return True

                @staticmethod
                def is_pid_running(*_args, **_kwargs):  # noqa: ANN001
                    return True

            engine.process_runner = _FakeRunner()  # type: ignore[assignment]
            calls: list[tuple[str, str, str]] = []

            class _GroupStub:
                def __init__(self, projects, **_kwargs):  # noqa: ANN001
                    self._projects = list(projects)

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
                    _ = exc_type, exc, tb
                    return False

                def update_project(self, project: str, message: str) -> None:
                    calls.append(("update", project, message))

                def mark_success(self, project: str, message: str) -> None:
                    calls.append(("success", project, message))

                def mark_failure(self, project: str, message: str) -> None:
                    calls.append(("failure", project, message))

                def print_detail(self, project: str, message: str) -> None:
                    calls.append(("detail", project, message))

            with (
                patch("envctl_engine.startup.startup_orchestrator._ProjectSpinnerGroup", _GroupStub),
                patch("envctl_engine.startup.startup_orchestrator.resolve_spinner_policy") as policy_mock,
            ):
                policy_mock.side_effect = lambda *_args, **_kwargs: type(
                    "_Policy",
                    (),
                    {
                        "mode": "on",
                        "enabled": True,
                        "reason": "",
                        "backend": "rich",
                        "min_ms": 120,
                        "verbose_events": False,
                        "style": "dots",
                    },
                )()
                code = engine.dispatch(parse_route(["--plan", "feature-a,feature-b", "--batch"], env={}))

            self.assertEqual(code, 0)
            success_messages = [msg for kind, project, msg in calls if kind == "success" and project == "feature-a-1"]
            self.assertEqual(len(success_messages), 1)
            self.assertIn("startup completed (backend=", success_messages[0])
            detail_messages = [msg for kind, project, msg in calls if kind == "detail" and project == "feature-a-1"]
            self.assertTrue(detail_messages)
            self.assertIn("Warning: backend migration step failed; continuing without migration", detail_messages[0])
            self.assertTrue(any("backend log:" in msg for msg in detail_messages))

    def test_startup_emits_spinner_policy_and_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "echo backend",
                    "ENVCTL_FRONTEND_START_CMD": "echo frontend",
                    "ENVCTL_UI_SPINNER_MODE": "on",
                },
            )

            class _FakeProcess:
                def __init__(self, pid: int) -> None:
                    self.pid = pid

            class _FakeRunner:
                _pid = 5000

                def run(self, *_args, **_kwargs):  # noqa: ANN001
                    import subprocess

                    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

                def start(self, *_args, **_kwargs):  # noqa: ANN001
                    self._pid += 1
                    return _FakeProcess(self._pid)

                @staticmethod
                def wait_for_pid_port(*_args, **_kwargs):  # noqa: ANN001
                    return True

                @staticmethod
                def pid_owns_port(*_args, **_kwargs):  # noqa: ANN001
                    return True

                @staticmethod
                def find_pid_listener_port(*_args, **_kwargs):  # noqa: ANN001
                    return None

                @staticmethod
                def terminate(*_args, **_kwargs):  # noqa: ANN001
                    return True

                @staticmethod
                def is_pid_running(*_args, **_kwargs):  # noqa: ANN001
                    return True

            engine.process_runner = _FakeRunner()  # type: ignore[assignment]

            spinner_calls: list[tuple[str, bool]] = []

            @contextmanager
            def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
                _ = start_immediately
                spinner_calls.append((message, enabled))

                class _SpinnerStub:
                    def update(self, _message: str) -> None:
                        return None

                    def succeed(self, _message: str) -> None:
                        return None

                    def fail(self, _message: str) -> None:
                        return None

                yield _SpinnerStub()

            with (
                patch("envctl_engine.startup.startup_orchestrator.spinner", side_effect=fake_spinner),
                patch("envctl_engine.startup.startup_orchestrator.resolve_spinner_policy") as policy_mock,
            ):
                policy_mock.side_effect = lambda *_args, **_kwargs: type(
                    "_Policy",
                    (),
                    {
                        "mode": "on",
                        "enabled": True,
                        "reason": "",
                        "backend": "rich",
                        "min_ms": 120,
                        "verbose_events": False,
                    },
                )()
                code = engine.dispatch(parse_route([], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            self.assertEqual(len(spinner_calls), 1)
            self.assertEqual(spinner_calls[0][1], True)
            self.assertTrue(any(event.get("event") == "ui.spinner.policy" for event in engine.events))
            self.assertTrue(any(event.get("event") == "ui.spinner.lifecycle" for event in engine.events))

    def test_restart_emits_spinner_for_prestop_and_startup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "echo backend",
                    "ENVCTL_FRONTEND_START_CMD": "echo frontend",
                    "ENVCTL_UI_SPINNER_MODE": "on",
                },
            )

            class _FakeProcess:
                def __init__(self, pid: int) -> None:
                    self.pid = pid

            class _FakeRunner:
                _pid = 6000

                def run(self, *_args, **_kwargs):  # noqa: ANN001
                    import subprocess

                    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

                def start(self, *_args, **_kwargs):  # noqa: ANN001
                    self._pid += 1
                    return _FakeProcess(self._pid)

                @staticmethod
                def wait_for_pid_port(*_args, **_kwargs):  # noqa: ANN001
                    return True

                @staticmethod
                def pid_owns_port(*_args, **_kwargs):  # noqa: ANN001
                    return True

                @staticmethod
                def find_pid_listener_port(*_args, **_kwargs):  # noqa: ANN001
                    return None

                @staticmethod
                def terminate(*_args, **_kwargs):  # noqa: ANN001
                    return True

                @staticmethod
                def is_pid_running(*_args, **_kwargs):  # noqa: ANN001
                    return True

            engine.process_runner = _FakeRunner()  # type: ignore[assignment]
            terminated: list[str] = []

            engine._try_load_existing_state = lambda mode=None, strict_mode_match=False: RunState(  # type: ignore[method-assign]
                run_id="run-old",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        requested_port=8000,
                        actual_port=8000,
                        pid=12345,
                        status="running",
                    )
                },
                requirements={
                    "Main": RequirementsResult(
                        project="Main",
                        db={"requested": 5432, "final": 5432, "retries": 0, "success": True},
                        redis={"requested": 6379, "final": 6379, "retries": 0, "success": True},
                        n8n={"requested": 5678, "final": 5678, "retries": 0, "success": True},
                        supabase={"requested": 5432, "final": 5432, "retries": 0, "success": True},
                    )
                },
            )
            engine._terminate_services_from_state = (  # type: ignore[method-assign]
                lambda state, selected_services, aggressive, verify_ownership: terminated.append(state.run_id)
            )

            spinner_calls: list[tuple[str, bool]] = []

            @contextmanager
            def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
                _ = start_immediately
                spinner_calls.append((message, enabled))

                class _SpinnerStub:
                    def update(self, _message: str) -> None:
                        return None

                    def succeed(self, _message: str) -> None:
                        return None

                    def fail(self, _message: str) -> None:
                        return None

                yield _SpinnerStub()

            with (
                patch("envctl_engine.startup.startup_orchestrator.spinner", side_effect=fake_spinner),
                patch("envctl_engine.startup.startup_orchestrator.resolve_spinner_policy") as policy_mock,
            ):
                policy_mock.side_effect = lambda *_args, **_kwargs: type(
                    "_Policy",
                    (),
                    {
                        "mode": "on",
                        "enabled": True,
                        "reason": "",
                        "backend": "rich",
                        "min_ms": 120,
                        "verbose_events": False,
                    },
                )()
                code = engine.dispatch(parse_route(["--restart"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            self.assertEqual(terminated, ["run-old"])
            self.assertEqual(len(spinner_calls), 2)
            messages = [message for message, _enabled in spinner_calls]
            self.assertIn("Restarting services...", messages)
            self.assertIn("Starting 1 project(s)...", messages)

    def test_restart_service_only_preserves_other_services_and_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "echo backend",
                    "ENVCTL_FRONTEND_START_CMD": "echo frontend",
                    "ENVCTL_UI_SPINNER_MODE": "off",
                },
            )
            previous_state = RunState(
                run_id="run-old",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        requested_port=8000,
                        actual_port=8000,
                        pid=11111,
                        status="running",
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo / "frontend"),
                        requested_port=9000,
                        actual_port=9000,
                        pid=22222,
                        status="running",
                    ),
                },
                requirements={
                    "Main": RequirementsResult(
                        project="Main",
                        db={"requested": 5432, "final": 5432, "retries": 0, "success": True, "enabled": True},
                        redis={"requested": 6379, "final": 6379, "retries": 0, "success": True, "enabled": False},
                        n8n={"requested": 5678, "final": 5678, "retries": 0, "success": True, "enabled": False},
                        supabase={"requested": 5432, "final": 5432, "retries": 0, "success": True, "enabled": False},
                        health="healthy",
                    )
                },
            )
            context = ProjectContext(
                name="Main",
                root=repo,
                ports={
                    "backend": PortPlan("Main", 8000, 8000, 8000, "requested"),
                    "frontend": PortPlan("Main", 9000, 9000, 9000, "requested"),
                    "db": PortPlan("Main", 5432, 5432, 5432, "requested"),
                    "redis": PortPlan("Main", 6379, 6379, 6379, "requested"),
                    "n8n": PortPlan("Main", 5678, 5678, 5678, "requested"),
                },
            )

            terminate_calls: list[set[str] | None] = []
            release_calls: list[str] = []
            captured_state: dict[str, RunState] = {}

            engine._try_load_existing_state = lambda mode=None, strict_mode_match=False: previous_state  # type: ignore[method-assign]
            engine._discover_projects = lambda mode: [context]  # type: ignore[method-assign]
            engine._reserve_project_ports = lambda _context: None  # type: ignore[method-assign]
            engine._terminate_services_from_state = (  # type: ignore[method-assign]
                lambda state, selected_services, aggressive, verify_ownership: terminate_calls.append(selected_services)
            )
            engine._release_requirement_ports = (  # type: ignore[method-assign]
                lambda _requirements: release_calls.append("released")
            )
            engine._start_project_context = (  # type: ignore[method-assign]
                lambda context, mode, route, run_id: (
                    previous_state.requirements["Main"],
                    {
                        "Main Backend": ServiceRecord(
                            name="Main Backend",
                            type="backend",
                            cwd=str(repo / "backend"),
                            requested_port=8000,
                            actual_port=8000,
                            pid=33333,
                            status="running",
                        )
                    },
                    [],
                )
            )
            engine._write_artifacts = (  # type: ignore[method-assign]
                lambda run_state, contexts, errors=None: captured_state.setdefault("state", run_state)
            )

            route = parse_route(["--restart", "Main", "--batch"], env={"ENVCTL_DEFAULT_MODE": "main"})
            route.flags.update(
                {
                    "services": ["Main Backend"],
                    "restart_service_types": ["backend"],
                    "restart_include_requirements": False,
                }
            )
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(terminate_calls, [{"Main Backend"}])
            self.assertEqual(release_calls, [])
            run_state = captured_state["state"]
            self.assertIn("Main Backend", run_state.services)
            self.assertIn("Main Frontend", run_state.services)
            self.assertEqual(run_state.services["Main Backend"].pid, 33333)
            self.assertEqual(run_state.services["Main Frontend"].pid, 22222)
            self.assertIn("Main", run_state.requirements)


if __name__ == "__main__":
    unittest.main()
