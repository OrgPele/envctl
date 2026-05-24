# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.startup.startup_spinner_integration_test_support import *


class StartupSpinnerDisplayTests(StartupSpinnerIntegrationTestCase):
    def test_project_spinner_detail_hyperlinks_local_paths_without_touching_lifecycle_payload(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        group = ProjectSpinnerGroup(
            projects=["feature-a-1"],
            enabled=True,
            policy=type(
                "_Policy",
                (),
                {
                    "enabled": True,
                    "backend": "rich",
                    "style": "dots",
                },
            )(),
            emit=lambda event, **payload: events.append((event, payload)),
            component="startup_orchestrator",
            op_id="startup.execute",
            env={"ENVCTL_UI_HYPERLINK_MODE": "on"},
        )
        buffer = _TtyStringIO()
        group._stream = buffer  # type: ignore[attr-defined]
        group.print_detail("feature-a-1", "backend log: /tmp/runtime/feature-a-1_backend.txt")

        rendered = buffer.getvalue()
        self.assertIn("\x1b]8;;file://", rendered)
        self.assertIn("backend log: /tmp/runtime/feature-a-1_backend.txt", strip_ansi(rendered))
        lifecycle_messages = [payload.get("message", "") for event, payload in events if event == "ui.spinner.lifecycle"]
        self.assertEqual(lifecycle_messages, ["backend log: /tmp/runtime/feature-a-1_backend.txt"])

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
                self.assertIn("startup completed", message)
                self.assertIn("backend=", message)
                self.assertIn("frontend=", message)
                self.assertNotIn("db=", message)
                self.assertNotIn("redis=", message)
                self.assertNotIn("n8n=", message)
            print_summary_mock.assert_not_called()

    def test_startup_emits_spinner_policy_and_lifecycle(self) -> None:
        tmpdir = tempfile.mkdtemp()
        try:
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
                patch("envctl_engine.startup.lifecycle.spinner", side_effect=fake_spinner),
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
                    },
                )()
                code = engine.dispatch(parse_route([], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            self.assertEqual(len(spinner_calls), 1)
            self.assertEqual(spinner_calls[0][1], True)
            self.assertTrue(any(event.get("event") == "ui.spinner.policy" for event in engine.events))
            self.assertTrue(any(event.get("event") == "ui.spinner.lifecycle" for event in engine.events))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
