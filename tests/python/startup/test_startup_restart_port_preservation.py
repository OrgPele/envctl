# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.startup.startup_spinner_integration_test_support import *


class StartupRestartPortPreservationTests(StartupSpinnerIntegrationTestCase):
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
                code = engine.dispatch(parse_route(["--restart"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            self.assertEqual(terminated, ["run-old"])
            self.assertEqual(len(spinner_calls), 2)
            messages = [message for message, _enabled in spinner_calls]
            self.assertIn("Restarting services...", messages)
            self.assertIn("Starting 1 project(s)...", messages)

    def test_interactive_main_restart_reuses_previous_backend_and_frontend_ports_after_cleanup(self) -> None:
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
                    "ENVCTL_PORT_AVAILABILITY_MODE": "lock_only",
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
            engine.port_planner.availability_checker = lambda _port: True
            self.assertEqual(engine.port_planner.reserve_next(8000, owner="Main:backend"), 8000)
            self.assertEqual(engine.port_planner.reserve_next(9000, owner="Main:frontend"), 9000)

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
                        listener_pids=[22223],
                    ),
                },
                requirements={
                    "Main": RequirementsResult(
                        project="Main",
                        db={"requested": 5432, "final": 5432, "retries": 0, "success": True, "enabled": False},
                        redis={"requested": 6379, "final": 6379, "retries": 0, "success": True, "enabled": False},
                        n8n={"requested": 5678, "final": 5678, "retries": 0, "success": True, "enabled": False},
                        supabase={"requested": 5432, "final": 5432, "retries": 0, "success": True, "enabled": False},
                        health="healthy",
                    )
                },
            )
            captured_state: dict[str, RunState] = {}
            captured_env: dict[str, str] = {}

            engine._try_load_existing_state = lambda mode=None, strict_mode_match=False: previous_state  # type: ignore[method-assign]
            engine._terminate_services_from_state = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            engine._listener_pids_for_port = lambda _port: []  # type: ignore[method-assign]
            engine._start_project_context = (  # type: ignore[method-assign]
                lambda context, mode, route, run_id: (
                    engine._reserve_project_ports(context, route=route)
                    or
                    captured_env.update(
                        engine._project_service_env(
                            context,
                            requirements=previous_state.requirements["Main"],
                            route=route,
                            service_name="frontend",
                        )
                    )
                    or ProjectStartupResult(
                        requirements=previous_state.requirements["Main"],
                        services={
                            "Main Backend": ServiceRecord(
                                name="Main Backend",
                                type="backend",
                                cwd=str(repo / "backend"),
                                requested_port=context.ports["backend"].requested,
                                actual_port=context.ports["backend"].final,
                                pid=33333,
                                status="running",
                            ),
                            "Main Frontend": ServiceRecord(
                                name="Main Frontend",
                                type="frontend",
                                cwd=str(repo / "frontend"),
                                requested_port=context.ports["frontend"].requested,
                                actual_port=context.ports["frontend"].final,
                                pid=44444,
                                status="running",
                            ),
                        },
                        warnings=[],
                    )
                )
            )
            engine._write_artifacts = (  # type: ignore[method-assign]
                lambda run_state, contexts, errors=None: captured_state.setdefault("state", run_state)
            )

            route = parse_route(["--restart", "--batch"], env={"ENVCTL_DEFAULT_MODE": "main"})
            route.flags.update(
                {
                    "services": ["Main Backend", "Main Frontend"],
                    "restart_service_types": ["backend", "frontend"],
                    "restart_include_requirements": False,
                    "interactive_command": True,
                }
            )
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            run_state = captured_state["state"]
            self.assertEqual(run_state.services["Main Backend"].actual_port, 8000)
            self.assertEqual(run_state.services["Main Frontend"].actual_port, 9000)
            self.assertEqual(captured_env.get("BACKEND_URL"), "http://localhost:8000")
            runtime_map = build_runtime_map(run_state)
            self.assertEqual(runtime_map["projection"]["Main"]["backend_url"], "http://localhost:8000")
            self.assertEqual(runtime_map["projection"]["Main"]["frontend_url"], "http://localhost:9000")
            rebounds = [
                event
                for event in engine.events
                if event.get("event") == "port.rebound" and event.get("service") in {"backend", "frontend"}
            ]
            self.assertEqual(rebounds, [])

    def test_interactive_main_restart_rebounds_only_when_previous_port_still_unavailable(self) -> None:
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
            engine.port_planner.availability_checker = lambda _port: True
            self.assertEqual(engine.port_planner.reserve_next(8000, owner="Main:backend"), 8000)
            self.assertEqual(engine.port_planner.reserve_next(9000, owner="Main:frontend"), 9000)
            engine.port_planner.availability_checker = lambda port: port != 8000

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
                        db={"requested": 5432, "final": 5432, "retries": 0, "success": True, "enabled": False},
                        redis={"requested": 6379, "final": 6379, "retries": 0, "success": True, "enabled": False},
                        n8n={"requested": 5678, "final": 5678, "retries": 0, "success": True, "enabled": False},
                        supabase={"requested": 5432, "final": 5432, "retries": 0, "success": True, "enabled": False},
                        health="healthy",
                    )
                },
            )
            captured_state: dict[str, RunState] = {}
            captured_env: dict[str, str] = {}

            engine._try_load_existing_state = lambda mode=None, strict_mode_match=False: previous_state  # type: ignore[method-assign]
            engine._terminate_services_from_state = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            engine._listener_pids_for_port = lambda _port: []  # type: ignore[method-assign]
            engine._start_project_context = (  # type: ignore[method-assign]
                lambda context, mode, route, run_id: (
                    engine._reserve_project_ports(context, route=route)
                    or
                    captured_env.update(
                        engine._project_service_env(
                            context,
                            requirements=previous_state.requirements["Main"],
                            route=route,
                            service_name="frontend",
                        )
                    )
                    or ProjectStartupResult(
                        requirements=previous_state.requirements["Main"],
                        services={
                            "Main Backend": ServiceRecord(
                                name="Main Backend",
                                type="backend",
                                cwd=str(repo / "backend"),
                                requested_port=context.ports["backend"].requested,
                                actual_port=context.ports["backend"].final,
                                pid=33333,
                                status="running",
                            ),
                            "Main Frontend": ServiceRecord(
                                name="Main Frontend",
                                type="frontend",
                                cwd=str(repo / "frontend"),
                                requested_port=context.ports["frontend"].requested,
                                actual_port=context.ports["frontend"].final,
                                pid=44444,
                                status="running",
                            ),
                        },
                        warnings=[],
                    )
                )
            )
            engine._write_artifacts = (  # type: ignore[method-assign]
                lambda run_state, contexts, errors=None: captured_state.setdefault("state", run_state)
            )

            route = parse_route(["--restart", "--batch"], env={"ENVCTL_DEFAULT_MODE": "main"})
            route.flags.update(
                {
                    "services": ["Main Backend", "Main Frontend"],
                    "restart_service_types": ["backend", "frontend"],
                    "restart_include_requirements": False,
                    "interactive_command": True,
                }
            )
            with patch("sys.stdout", new_callable=StringIO) as stdout:
                code = engine.dispatch(route)

            self.assertEqual(code, 0, [event for event in engine.events if event.get("event") == "startup.failed"])
            run_state = captured_state["state"]
            self.assertEqual(run_state.services["Main Backend"].actual_port, 8001)
            self.assertEqual(run_state.services["Main Frontend"].actual_port, 9000)
            self.assertEqual(captured_env.get("BACKEND_URL"), "http://localhost:8001")
            runtime_map = build_runtime_map(run_state)
            self.assertEqual(runtime_map["projection"]["Main"]["backend_url"], "http://localhost:8001")
            self.assertEqual(runtime_map["projection"]["Main"]["frontend_url"], "http://localhost:9000")
            backend_rebounds = [
                event
                for event in engine.events
                if event.get("event") == "port.rebound" and event.get("service") == "backend"
            ]
            self.assertEqual(len(backend_rebounds), 1)
            self.assertEqual(backend_rebounds[0].get("project"), "Main")
            self.assertEqual(backend_rebounds[0].get("restart_preferred_port"), 8000)
            self.assertEqual(backend_rebounds[0].get("port"), 8001)
            self.assertEqual(backend_rebounds[0].get("rebound_reason"), "restart_preferred_port_unavailable")
            self.assertTrue(backend_rebounds[0].get("interactive_command"))
            frontend_rebounds = [
                event
                for event in engine.events
                if event.get("event") == "port.rebound" and event.get("service") == "frontend"
            ]
            self.assertEqual(frontend_rebounds, [])
            self.assertIn(
                "Port changed: Main Backend 8000 -> 8001 (previous port still in use)",
                strip_ansi(stdout.getvalue()),
            )

    def test_interactive_main_restart_reuses_selected_additional_service_port_after_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "voice-runtime").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                    "ENVCTL_ADDITIONAL_SERVICES": "voice-runtime",
                    "ENVCTL_SERVICE_VOICE_RUNTIME_ENABLE_MAIN": "true",
                    "ENVCTL_SERVICE_VOICE_RUNTIME_DIR": "voice-runtime",
                    "ENVCTL_SERVICE_VOICE_RUNTIME_START_CMD": "python -m voice --port {port}",
                    "ENVCTL_SERVICE_VOICE_RUNTIME_PORT_BASE": "8010",
                }
            )
            engine = PythonEngineRuntime(config, env={"ENVCTL_UI_SPINNER_MODE": "off"})
            engine.port_planner.availability_checker = lambda _port: True
            self.assertEqual(engine.port_planner.reserve_next(8010, owner="Main:voice-runtime"), 8010)

            previous_state = RunState(
                run_id="run-old",
                mode="main",
                services={
                    "Main Voice Runtime": ServiceRecord(
                        name="Main Voice Runtime",
                        type="voice-runtime",
                        cwd=str(repo / "voice-runtime"),
                        requested_port=8010,
                        actual_port=8010,
                        pid=22222,
                        status="running",
                        project="Main",
                        service_slug="voice-runtime",
                    ),
                },
                requirements={"Main": RequirementsResult(project="Main", health="healthy")},
            )
            captured_state: dict[str, RunState] = {}

            engine._try_load_existing_state = lambda mode=None, strict_mode_match=False: previous_state  # type: ignore[method-assign]
            engine._terminate_services_from_state = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            engine._listener_pids_for_port = lambda _port: []  # type: ignore[method-assign]
            engine._start_project_context = (  # type: ignore[method-assign]
                lambda context, mode, route, run_id: (
                    engine._reserve_project_ports(context, route=route)
                    or ProjectStartupResult(
                        requirements=previous_state.requirements["Main"],
                        services={
                            "Main Voice Runtime": ServiceRecord(
                                name="Main Voice Runtime",
                                type="voice-runtime",
                                cwd=str(repo / "voice-runtime"),
                                requested_port=context.ports["voice-runtime"].requested,
                                actual_port=context.ports["voice-runtime"].final,
                                pid=33333,
                                status="running",
                                project="Main",
                                service_slug="voice-runtime",
                            )
                        },
                        warnings=[],
                    )
                )
            )
            engine._write_artifacts = (  # type: ignore[method-assign]
                lambda run_state, contexts, errors=None: captured_state.setdefault("state", run_state)
            )

            route = parse_route(["--restart", "--batch"], env={"ENVCTL_DEFAULT_MODE": "main"})
            route.flags.update(
                {
                    "services": ["Main Voice Runtime"],
                    "restart_service_types": ["voice-runtime"],
                    "restart_include_requirements": False,
                    "interactive_command": True,
                }
            )
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            run_state = captured_state["state"]
            self.assertEqual(run_state.services["Main Voice Runtime"].actual_port, 8010)
            self.assertEqual(run_state.services["Main Voice Runtime"].requested_port, 8010)
            self.assertEqual(run_state.services["Main Voice Runtime"].service_slug, "voice-runtime")
            self.assertEqual(
                [event for event in engine.events if event.get("event") == "port.rebound"],
                [],
            )

    def test_interactive_main_restart_rebounds_selected_additional_service_when_prior_port_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "voice-runtime").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                    "ENVCTL_ADDITIONAL_SERVICES": "voice-runtime",
                    "ENVCTL_SERVICE_VOICE_RUNTIME_ENABLE_MAIN": "true",
                    "ENVCTL_SERVICE_VOICE_RUNTIME_DIR": "voice-runtime",
                    "ENVCTL_SERVICE_VOICE_RUNTIME_START_CMD": "python -m voice --port {port}",
                    "ENVCTL_SERVICE_VOICE_RUNTIME_PORT_BASE": "8010",
                }
            )
            engine = PythonEngineRuntime(config, env={"ENVCTL_UI_SPINNER_MODE": "off"})
            engine.port_planner.availability_checker = lambda _port: True
            self.assertEqual(engine.port_planner.reserve_next(8010, owner="Main:voice-runtime"), 8010)
            engine.port_planner.availability_checker = lambda port: port != 8010

            previous_state = RunState(
                run_id="run-old",
                mode="main",
                services={
                    "Main Voice Runtime": ServiceRecord(
                        name="Main Voice Runtime",
                        type="voice-runtime",
                        cwd=str(repo / "voice-runtime"),
                        requested_port=8010,
                        actual_port=8010,
                        pid=22222,
                        status="running",
                        project="Main",
                        service_slug="voice-runtime",
                    ),
                },
                requirements={"Main": RequirementsResult(project="Main", health="healthy")},
            )
            captured_state: dict[str, RunState] = {}

            engine._try_load_existing_state = lambda mode=None, strict_mode_match=False: previous_state  # type: ignore[method-assign]
            engine._terminate_services_from_state = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            engine._listener_pids_for_port = lambda _port: []  # type: ignore[method-assign]
            engine._start_project_context = (  # type: ignore[method-assign]
                lambda context, mode, route, run_id: (
                    engine._reserve_project_ports(context, route=route)
                    or ProjectStartupResult(
                        requirements=previous_state.requirements["Main"],
                        services={
                            "Main Voice Runtime": ServiceRecord(
                                name="Main Voice Runtime",
                                type="voice-runtime",
                                cwd=str(repo / "voice-runtime"),
                                requested_port=context.ports["voice-runtime"].requested,
                                actual_port=context.ports["voice-runtime"].final,
                                pid=33333,
                                status="running",
                                project="Main",
                                service_slug="voice-runtime",
                            )
                        },
                        warnings=[],
                    )
                )
            )
            engine._write_artifacts = (  # type: ignore[method-assign]
                lambda run_state, contexts, errors=None: captured_state.setdefault("state", run_state)
            )

            route = parse_route(["--restart", "--batch"], env={"ENVCTL_DEFAULT_MODE": "main"})
            route.flags.update(
                {
                    "services": ["Main Voice Runtime"],
                    "restart_service_types": ["voice-runtime"],
                    "restart_include_requirements": False,
                    "interactive_command": True,
                }
            )
            with patch("sys.stdout", new_callable=StringIO) as stdout:
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            run_state = captured_state["state"]
            self.assertEqual(run_state.services["Main Voice Runtime"].actual_port, 8011)
            rebound_events = [event for event in engine.events if event.get("event") == "port.rebound"]
            self.assertEqual(len(rebound_events), 1)
            self.assertEqual(rebound_events[0].get("service"), "voice-runtime")
            self.assertEqual(rebound_events[0].get("restart_preferred_port"), 8010)
            self.assertEqual(rebound_events[0].get("restart_conflict_detail"), "listener")
            self.assertIn(
                "Port changed: Main Voice Runtime 8010 -> 8011 (previous port still in use)",
                strip_ansi(stdout.getvalue()),
            )
