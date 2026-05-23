# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.startup.startup_spinner_integration_test_support import *


class StartupSpinnerParallelProgressTests(StartupSpinnerIntegrationTestCase):
    def test_shared_tree_requirements_progress_uses_tree_project_not_main(self) -> None:
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
                    "REDIS_ENABLE": "true",
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
                    "ENVCTL_BACKEND_START_CMD": "echo backend",
                    "ENVCTL_FRONTEND_START_CMD": "echo frontend",
                },
            )

            class _FakeProcess:
                def __init__(self, pid: int) -> None:
                    self.pid = pid

            class _FakeRunner:
                _pid = 9200

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

            def fake_start_requirement_component(context, component, plan, reserve_next, **_kwargs):  # noqa: ANN001
                final_port = reserve_next(plan.final)
                return RequirementOutcome(
                    service_name=component,
                    success=True,
                    requested_port=plan.requested,
                    final_port=final_port,
                    retries=0,
                )

            engine._start_requirement_component = fake_start_requirement_component  # type: ignore[method-assign]
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
                patch("envctl_engine.startup.lifecycle.resolve_spinner_policy") as policy_mock,
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
            requirement_updates = [
                (project, message)
                for kind, project, message in calls
                if kind == "update" and "requirements" in message.lower()
            ]
            self.assertTrue(requirement_updates)
            self.assertNotIn("Main", {project for project, _message in requirement_updates})
            self.assertTrue(
                {project for project, _message in requirement_updates}.issubset({"feature-a-1", "feature-b-1"})
            )
            shared_ready_updates = [
                message for _project, message in requirement_updates if message.startswith("Shared requirements ready")
            ]
            self.assertTrue(shared_ready_updates)
            self.assertLessEqual(sum("redis=" in message for _project, message in requirement_updates), 1)
            self.assertFalse(
                any(
                    message.startswith(f"Requirements ready for {project}: redis=")
                    for project, message in requirement_updates
                    if project in {"feature-a-1", "feature-b-1"}
                )
            )

            isolated_updates: list[tuple[str, str]] = []
            isolated_route = parse_route(["--tree", "--isolated-deps"], env={})
            isolated_route.flags["_spinner_update_project"] = lambda project, message: isolated_updates.append(
                (project, message)
            )
            isolated_context = ProjectContext(
                name="feature-a-1",
                root=repo / "trees" / "feature-a" / "1",
                ports=engine.port_planner.plan_project_stack("feature-a-1", index=0),
            )
            engine.startup_orchestrator.start_requirements_for_project(
                cast(Any, isolated_context),
                mode="trees",
                route=isolated_route,
            )
            self.assertTrue(isolated_updates)
            self.assertNotIn("None", {project for project, _message in isolated_updates})
            self.assertEqual({project for project, _message in isolated_updates}, {"feature-a-1"})
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
                patch("envctl_engine.startup.lifecycle.resolve_spinner_policy") as policy_mock,
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
            self.assertTrue(all("\x1b]8;;file://" not in msg for msg in detail_messages))
            self.assertTrue(any("backend log:" in msg for msg in detail_messages))
