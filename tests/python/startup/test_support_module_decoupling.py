from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.startup.resume_restore_support import restore_missing  # noqa: E402
from envctl_engine.startup.requirements_execution import start_requirements_for_project as requirements_start_impl  # noqa: E402
from envctl_engine.startup.service_execution import start_project_services as service_start_impl  # noqa: E402
from envctl_engine.startup.startup_execution_support import (  # noqa: E402
    _maybe_prewarm_docker,
    _requirements_failure_message,
    start_requirements_for_project,
    start_project_services,
)
from envctl_engine.startup.startup_selection_support import _tree_preselected_projects_from_state  # noqa: E402
from envctl_engine.config import AppServiceConfig  # noqa: E402
from envctl_engine.runtime.command_router import parse_route  # noqa: E402
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord  # noqa: E402


class _SpinnerStub:
    def __enter__(self) -> "_SpinnerStub":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def update(self, message: str) -> None:
        _ = message

    def fail(self, message: str) -> None:
        _ = message

    def succeed(self, message: str) -> None:
        _ = message


class _PortAllocatorStub:
    def reserve_next(self, preferred: int, *, owner: str) -> int:
        _ = owner
        return preferred

    def update_final_port(self, plan: object, final_port: int, *, source: str) -> None:
        _ = (plan, final_port, source)

    def release(self, port: int) -> None:
        _ = port


class StartupSupportModuleDecouplingTests(unittest.TestCase):
    def test_startup_execution_support_reexports_new_owner_modules(self) -> None:
        self.assertIs(start_requirements_for_project, requirements_start_impl)
        self.assertIs(start_project_services, service_start_impl)

    def test_tree_preselected_projects_uses_local_state_helpers(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="trees",
            services={
                "Feature Backend": ServiceRecord(name="Feature Backend", type="backend", cwd="."),
            },
            requirements={
                "Main": RequirementsResult(project="Main", components={}, health="healthy", failures=[]),
            },
        )
        runtime = SimpleNamespace(
            _try_load_existing_state=lambda **kwargs: state,
            _project_name_from_service=lambda name: name.split()[0],
        )
        project_contexts = [
            SimpleNamespace(name="Main"),
            SimpleNamespace(name="Feature"),
            SimpleNamespace(name="Missing"),
        ]

        result = _tree_preselected_projects_from_state(
            SimpleNamespace(runtime=runtime),
            runtime=runtime,
            project_contexts=project_contexts,
        )

        self.assertEqual(result, ["Feature", "Main"])

    def test_maybe_prewarm_docker_does_not_require_orchestrator_wrapper_methods(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(
            env={},
            config=SimpleNamespace(raw={}),
            _requirement_enabled=lambda requirement_id, mode, route: requirement_id == "postgres",
            _command_exists=lambda command: command == "docker",
            process_runner=SimpleNamespace(
                run=lambda command, timeout: SimpleNamespace(returncode=0, stderr="", stdout="")
            ),
            _emit=lambda event, **payload: events.append((event, payload)),
        )

        _maybe_prewarm_docker(SimpleNamespace(runtime=runtime), route=None, mode="main")

        self.assertEqual(events[-1][0], "requirements.docker_prewarm")
        self.assertEqual(events[-1][1]["used"], True)
        self.assertEqual(events[-1][1]["success"], True)
        self.assertEqual(events[-1][1]["command"], ["docker", "ps"])

    def test_restore_missing_uses_runtime_port_allocator_without_resume_wrappers(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(
            port_planner=_PortAllocatorStub(),
            env={},
            config=SimpleNamespace(raw={}, base_dir=Path("/tmp")),
            _project_name_from_service=lambda name: "Main",
            _requirements_ready=lambda requirements: True,
            _emit=lambda event, **payload: events.append((event, payload)),
            _tree_parallel_startup_config=lambda **kwargs: (False, 1),
            _resume_context_for_project=lambda state, project: None,
        )
        state = RunState(run_id="run-1", mode="main", services={}, requirements={})

        errors = restore_missing(
            SimpleNamespace(runtime=runtime),
            state,
            ["Main Backend"],
            spinner_factory=lambda *args, **kwargs: _SpinnerStub(),
            spinner_enabled_fn=lambda env: False,
            use_spinner_policy_fn=lambda policy: nullcontext(),
            emit_spinner_policy_fn=lambda emit, policy, context: None,
            resolve_spinner_policy_fn=lambda env: SimpleNamespace(enabled=False, backend="rich", style="dots"),
        )

        self.assertEqual(errors, ["Main: project root not found"])
        self.assertEqual(events[0][0], "resume.restore.execution")
        self.assertEqual(events[-1][0], "resume.restore.timing")

    def test_requirements_failure_message_summarizes_docker_daemon_outage(self) -> None:
        requirements = RequirementsResult(
            project="Main",
            components={
                "redis": {
                    "enabled": True,
                    "success": False,
                    "error": (
                        "failed to connect to the docker API at "
                        "unix:///Users/kfiramar/.docker/run/docker.sock; "
                        "check if the path is correct and if the daemon is running"
                    ),
                },
                "n8n": {
                    "enabled": True,
                    "success": False,
                    "error": (
                        "failed to connect to the docker API at "
                        "unix:///Users/kfiramar/.docker/run/docker.sock; "
                        "check if the path is correct and if the daemon is running"
                    ),
                },
                "supabase": {
                    "enabled": True,
                    "success": False,
                    "error": (
                        "failed to connect to the docker API at "
                        "unix:///Users/kfiramar/.docker/run/docker.sock; "
                        "check if the path is correct and if the daemon is running"
                    ),
                },
            },
            health="degraded",
            failures=[
                "redis:FailureClass.HARD_START_FAILURE:failed to connect to the docker API",
                "n8n:FailureClass.HARD_START_FAILURE:failed to connect to the docker API",
                "supabase:FailureClass.HARD_START_FAILURE:failed to connect to the docker API",
            ],
        )

        message = _requirements_failure_message("Main", requirements)

        self.assertIn("Docker is not running.", message)
        self.assertIn("Docker is required for Main dependencies:", message)
        self.assertIn("redis", message)
        self.assertIn("supabase", message)
        self.assertIn("n8n", message)
        self.assertNotIn("FailureClass.HARD_START_FAILURE", message)

    def test_requirements_failure_message_falls_back_for_non_docker_errors(self) -> None:
        requirements = RequirementsResult(
            project="Main",
            components={
                "postgres": {
                    "enabled": True,
                    "success": False,
                    "error": "bind: address already in use",
                }
            },
            health="degraded",
            failures=["postgres:FailureClass.BIND_CONFLICT_RETRYABLE:bind: address already in use"],
        )

        message = _requirements_failure_message("Main", requirements)

        self.assertEqual(
            message,
            "Requirements unavailable for Main: "
            "postgres:FailureClass.BIND_CONFLICT_RETRYABLE:bind: address already in use",
        )

    def test_start_project_services_allows_parallel_prep_with_sequential_attach_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            project_root = root / "repo"
            project_root.mkdir(parents=True, exist_ok=True)
            run_dir = root / "runtime" / "run-1"
            prep_started = {
                "backend": threading.Event(),
                "frontend": threading.Event(),
            }
            overlap_hits: list[str] = []
            attach_modes: list[bool] = []

            def prepare_backend_runtime(**kwargs: object) -> None:
                _ = kwargs
                prep_started["backend"].set()
                if prep_started["frontend"].wait(0.2):
                    overlap_hits.append("backend")

            def prepare_frontend_runtime(**kwargs: object) -> None:
                _ = kwargs
                prep_started["frontend"].set()
                if prep_started["backend"].wait(0.2):
                    overlap_hits.append("frontend")

            def start_project_with_attach(**kwargs: object) -> dict[str, ServiceRecord]:
                attach_modes.append(bool(kwargs["parallel_start"]))
                return {
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(project_root),
                        status="running",
                        requested_port=8000,
                        actual_port=8000,
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(project_root),
                        status="running",
                        requested_port=3000,
                        actual_port=3000,
                    ),
                }

            runtime = SimpleNamespace(
                port_planner=_PortAllocatorStub(),
                env={},
                config=SimpleNamespace(raw={}, backend_dir_name="backend", frontend_dir_name="frontend"),
                services=SimpleNamespace(start_project_with_attach=start_project_with_attach),
                _invoke_envctl_hook=lambda **kwargs: SimpleNamespace(found=False, success=False, payload=None),
                _run_dir_path=lambda run_id: run_dir,
                _project_service_env=lambda context, requirements, route=None: {},
                _resolve_backend_env_file=lambda context, backend_cwd: (None, False),
                _resolve_frontend_env_file=lambda context, frontend_cwd: None,
                _service_env_from_file=lambda base_env, env_file, include_app_env_file: dict(base_env),
                _service_enabled_for_mode=lambda mode, service: True,
                _prepare_backend_runtime=prepare_backend_runtime,
                _prepare_frontend_runtime=prepare_frontend_runtime,
                _service_command_source=lambda **kwargs: "configured",
                _emit=lambda event, **payload: None,
            )
            orchestrator = SimpleNamespace(
                runtime=runtime,
                _process_runtime=lambda rt: SimpleNamespace(start_background=lambda *args, **kwargs: None),
                _restart_service_types_for_project=lambda **kwargs: {"backend", "frontend"},
                _suppress_timing_output=lambda route: True,
            )
            context = SimpleNamespace(
                name="Main",
                root=project_root,
                ports={
                    "backend": SimpleNamespace(final=8000),
                    "frontend": SimpleNamespace(final=3000),
                },
            )
            requirements = RequirementsResult(project="Main", components={}, health="healthy", failures=[])
            route = parse_route(
                ["start", "--service-sequential", "--service-prep-parallel"],
                env={"ENVCTL_DEFAULT_MODE": "main"},
            )

            records = start_project_services(
                orchestrator,
                context,
                requirements=requirements,
                run_id="run-1",
                route=route,
            )

            self.assertIn("Main Backend", records)
            self.assertIn("Main Frontend", records)
            self.assertEqual(attach_modes, [False])
            self.assertEqual(sorted(overlap_hits), ["backend", "frontend"])

    def test_start_project_services_integrates_additional_listener_and_worker_by_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            project_root = root / "repo"
            for dirname in ("backend", "frontend", "voice-runtime", "worker"):
                (project_root / dirname).mkdir(parents=True, exist_ok=True)
            run_dir = root / "runtime" / "run-integration"
            voice = AppServiceConfig(
                name="voice-runtime",
                env_suffix="VOICE_RUNTIME",
                enabled_main=True,
                enabled_trees=False,
                dir_name="voice-runtime",
                start_cmd="python -m voice --port {port}",
                port_base=8010,
                public_url_template="http://${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_HOST}:${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PORT}",
                health_url_template="http://${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_HOST}:${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PORT}/readyz",
                depends_on=("backend",),
            )
            worker = AppServiceConfig(
                name="worker",
                env_suffix="WORKER",
                enabled_main=False,
                enabled_trees=True,
                dir_name="worker",
                start_cmd="python worker.py",
                expect_listener=False,
                depends_on=("frontend",),
            )
            started_layers: list[tuple[str, ...]] = []

            def service_enabled_for_mode(mode: str, service_name: str) -> bool:
                if service_name in {"backend", "frontend"}:
                    return True
                if service_name == "voice-runtime":
                    return mode == "main"
                if service_name == "worker":
                    return mode == "trees"
                return False

            def project_service_env(context, requirements, route=None, service_name=None):  # noqa: ANN001
                _ = requirements, route
                env = {"ENVCTL_PROJECT_NAME": context.name}
                if service_name == "voice-runtime":
                    port = context.ports["voice-runtime"].final
                    env.update(
                        {
                            "ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_HOST": "localhost",
                            "ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PORT": str(port),
                            "ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PUBLIC_URL": f"http://localhost:{port}",
                            "ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_HEALTH_URL": f"http://localhost:{port}/readyz",
                        }
                    )
                return env

            def start_services_with_attach(**kwargs: object) -> dict[str, ServiceRecord]:
                descriptors = tuple(kwargs["descriptors"])
                started_layers.append(tuple(descriptor.service_type for descriptor in descriptors))
                records: dict[str, ServiceRecord] = {}
                for descriptor in descriptors:
                    descriptor.start(descriptor.requested_port)
                    actual = descriptor.detect_actual(1234, descriptor.requested_port)
                    service_type = descriptor.service_type
                    name = {
                        "backend": "Main Backend",
                        "frontend": "Main Frontend",
                        "voice-runtime": "Main Voice Runtime",
                        "worker": "Main Worker",
                    }[service_type]
                    records[name] = ServiceRecord(
                        name=name,
                        type=service_type,
                        cwd=descriptor.cwd,
                        requested_port=descriptor.requested_port or None,
                        actual_port=actual or None,
                        status="running",
                        listener_expected=descriptor.listener_expected,
                        public_url=descriptor.public_url,
                        health_url=descriptor.health_url,
                        project="Main",
                        service_slug=service_type,
                    )
                return records

            runtime = SimpleNamespace(
                port_planner=_PortAllocatorStub(),
                env={
                    "ENVCTL_BACKEND_START_CMD": "python backend.py --port {port}",
                    "ENVCTL_FRONTEND_START_CMD": "npm run dev -- --port {port}",
                },
                config=SimpleNamespace(
                    raw={},
                    backend_dir_name="backend",
                    frontend_dir_name="frontend",
                    additional_services=(voice, worker),
                    all_app_service_names_for_mode=lambda mode: (
                        "backend",
                        "frontend",
                        *(service.name for service in (voice, worker) if service.enabled_for_mode(mode)),
                    ),
                    app_service_by_name=lambda name: {"voice-runtime": voice, "worker": worker}.get(name),
                ),
                services=SimpleNamespace(start_services_with_attach=start_services_with_attach),
                _invoke_envctl_hook=lambda **kwargs: SimpleNamespace(found=False, success=False, payload=None),
                _run_dir_path=lambda run_id: run_dir,
                _project_service_env=project_service_env,
                _resolve_backend_env_file=lambda context, backend_cwd: (None, False),
                _resolve_frontend_env_file=lambda context, frontend_cwd: None,
                _prepare_backend_runtime=lambda **kwargs: None,
                _prepare_frontend_runtime=lambda **kwargs: None,
                _service_env_from_file=lambda base_env, env_file, include_app_env_file: dict(base_env),
                _service_enabled_for_mode=service_enabled_for_mode,
                _service_command_source=lambda **kwargs: "configured",
                _service_start_command_resolved=lambda service_name, **kwargs: ("python -c pass", "configured"),
                _split_command=lambda command, **kwargs: ["python", "-c", "pass"],
                _detect_service_actual_port=lambda service_name, pid, requested_port, **kwargs: 8022
                if service_name == "voice-runtime"
                else requested_port,
                _listener_truth_enforced=lambda: True,
                _service_listener_failure_detail=lambda **kwargs: "",
                _conflict_remaining={},
                _emit=lambda event, **payload: None,
            )
            orchestrator = SimpleNamespace(
                runtime=runtime,
                _process_runtime=lambda rt: SimpleNamespace(
                    start_background=lambda *args, **kwargs: SimpleNamespace(pid=1234)
                ),
                _restart_service_types_for_project=lambda route, project_name, default_service_types: set(default_service_types),
                _suppress_timing_output=lambda route: True,
            )
            context = SimpleNamespace(
                name="Main",
                root=project_root,
                ports={
                    "backend": SimpleNamespace(final=8000),
                    "frontend": SimpleNamespace(final=9000),
                    "voice-runtime": SimpleNamespace(final=8010),
                },
            )

            main_records = start_project_services(
                orchestrator,
                context,
                requirements=RequirementsResult(project="Main"),
                run_id="run-main",
                route=parse_route(["start", "--main", "--entire-system"], env={"ENVCTL_DEFAULT_MODE": "main"}),
            )
            trees_records = start_project_services(
                orchestrator,
                context,
                requirements=RequirementsResult(project="Main"),
                run_id="run-trees",
                route=parse_route(["start", "--trees", "--entire-system"], env={"ENVCTL_DEFAULT_MODE": "trees"}),
            )

        self.assertIn("Main Voice Runtime", main_records)
        self.assertNotIn("Main Worker", main_records)
        voice_record = main_records["Main Voice Runtime"]
        self.assertEqual(voice_record.actual_port, 8022)
        self.assertEqual(voice_record.public_url, "http://localhost:8022")
        self.assertEqual(voice_record.health_url, "http://localhost:8022/readyz")
        self.assertIn("Main Worker", trees_records)
        self.assertNotIn("Main Voice Runtime", trees_records)
        self.assertFalse(trees_records["Main Worker"].listener_expected)
        self.assertIsNone(trees_records["Main Worker"].actual_port)
        self.assertIn(("backend", "frontend"), started_layers)
        self.assertIn(("voice-runtime",), started_layers)
        self.assertIn(("worker",), started_layers)

    def test_start_project_services_resolves_additional_relative_command_from_service_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            project_root = root / "repo"
            service_root = project_root / "voice-runtime"
            service_root.mkdir(parents=True, exist_ok=True)
            run_dir = root / "runtime" / "run-relative-command"
            service = AppServiceConfig(
                name="voice-runtime",
                env_suffix="VOICE_RUNTIME",
                enabled_main=True,
                enabled_trees=True,
                dir_name="voice-runtime",
                start_cmd="scripts/envctl/start-voice-runtime.sh {port}",
                port_base=8010,
            )
            split_calls: list[dict[str, object]] = []

            def start_services_with_attach(**kwargs: object) -> dict[str, ServiceRecord]:
                records: dict[str, ServiceRecord] = {}
                for descriptor in kwargs["descriptors"]:
                    ok, detail, pid = descriptor.start(descriptor.requested_port)
                    self.assertTrue(ok, detail)
                    records["Main Voice Runtime"] = ServiceRecord(
                        name="Main Voice Runtime",
                        type="voice-runtime",
                        cwd=str(service_root),
                        requested_port=descriptor.requested_port,
                        actual_port=descriptor.requested_port,
                        status="running",
                        pid=pid,
                        project="Main",
                        service_slug="voice-runtime",
                    )
                return records

            runtime = SimpleNamespace(
                port_planner=_PortAllocatorStub(),
                env={},
                config=SimpleNamespace(
                    raw={},
                    backend_dir_name="backend",
                    frontend_dir_name="frontend",
                    additional_services=(service,),
                    all_app_service_names_for_mode=lambda mode: ("voice-runtime",),
                    app_service_by_name=lambda name: service if name == "voice-runtime" else None,
                ),
                services=SimpleNamespace(start_services_with_attach=start_services_with_attach),
                _invoke_envctl_hook=lambda **kwargs: SimpleNamespace(found=False, success=False, payload=None),
                _run_dir_path=lambda run_id: run_dir,
                _project_service_env=lambda context, requirements, route=None, service_name=None: {},
                _resolve_backend_env_file=lambda context, backend_cwd: (None, False),
                _resolve_frontend_env_file=lambda context, frontend_cwd: None,
                _prepare_backend_runtime=lambda **kwargs: None,
                _prepare_frontend_runtime=lambda **kwargs: None,
                _service_env_from_file=lambda base_env, env_file, include_app_env_file: dict(base_env),
                _service_enabled_for_mode=lambda mode, service_name: service_name == "voice-runtime",
                _service_command_source=lambda **kwargs: "configured",
                _split_command=lambda command, **kwargs: split_calls.append({"command": command, **kwargs}) or [
                    "scripts/envctl/start-voice-runtime.sh",
                    str(kwargs["port"]),
                ],
                _detect_service_actual_port=lambda **kwargs: 8010,
                _listener_truth_enforced=lambda: True,
                _service_listener_failure_detail=lambda **kwargs: "",
                _conflict_remaining={},
                _emit=lambda event, **payload: None,
            )
            orchestrator = SimpleNamespace(
                runtime=runtime,
                _process_runtime=lambda rt: SimpleNamespace(
                    start_background=lambda *args, **kwargs: SimpleNamespace(pid=1234)
                ),
                _restart_service_types_for_project=lambda **kwargs: {"voice-runtime"},
                _suppress_timing_output=lambda route: True,
            )
            context = SimpleNamespace(
                name="Main",
                root=project_root,
                ports={
                    "backend": SimpleNamespace(final=8000),
                    "frontend": SimpleNamespace(final=9000),
                    "voice-runtime": SimpleNamespace(final=8010),
                },
            )

            records = start_project_services(
                orchestrator,
                context,
                requirements=RequirementsResult(project="Main"),
                run_id="run-relative-command",
                route=parse_route(["start", "--main", "--service", "voice-runtime"], env={}),
            )

        self.assertIn("Main Voice Runtime", records)
        self.assertEqual(split_calls[0]["cwd"], service_root)

    def test_start_project_services_reprojects_additional_service_urls_after_rebound(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            project_root = root / "repo"
            (project_root / "voice-runtime").mkdir(parents=True, exist_ok=True)
            run_dir = root / "runtime" / "run-urls"
            service = AppServiceConfig(
                name="voice-runtime",
                env_suffix="VOICE_RUNTIME",
                enabled_main=True,
                enabled_trees=True,
                dir_name="voice-runtime",
                start_cmd="python -m voice --port {port}",
                port_base=8010,
                public_url_template="http://${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_HOST}:${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PORT}",
                health_url_template="http://${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_HOST}:${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PORT}/readyz",
            )

            def project_service_env(context, requirements, route=None, service_name=None):  # noqa: ANN001
                _ = requirements, route
                env = {"ENVCTL_PROJECT_NAME": context.name}
                if service_name == "voice-runtime":
                    port = context.ports["voice-runtime"].final
                    env.update(
                        {
                            "ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_HOST": "localhost",
                            "ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PORT": str(port),
                            "ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_URL": f"http://localhost:{port}",
                            "ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PUBLIC_URL": f"http://localhost:{port}",
                            "ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_HEALTH_URL": f"http://localhost:{port}/readyz",
                        }
                    )
                return env

            def start_services_with_attach(**kwargs: object) -> dict[str, ServiceRecord]:
                records: dict[str, ServiceRecord] = {}
                for descriptor in kwargs["descriptors"]:
                    descriptor.start(descriptor.requested_port)
                    actual = descriptor.detect_actual(1234, descriptor.requested_port)
                    records["Main Voice Runtime"] = ServiceRecord(
                        name="Main Voice Runtime",
                        type="voice-runtime",
                        cwd=str(project_root / "voice-runtime"),
                        requested_port=descriptor.requested_port,
                        actual_port=actual,
                        status="running",
                        public_url=descriptor.public_url,
                        health_url=descriptor.health_url,
                        project="Main",
                        service_slug="voice-runtime",
                    )
                return records

            runtime = SimpleNamespace(
                port_planner=_PortAllocatorStub(),
                env={},
                config=SimpleNamespace(
                    raw={},
                    backend_dir_name="backend",
                    frontend_dir_name="frontend",
                    additional_services=(service,),
                    all_app_service_names_for_mode=lambda mode: ("voice-runtime",),
                    app_service_by_name=lambda name: service if name == "voice-runtime" else None,
                ),
                services=SimpleNamespace(start_services_with_attach=start_services_with_attach),
                _invoke_envctl_hook=lambda **kwargs: SimpleNamespace(found=False, success=False, payload=None),
                _run_dir_path=lambda run_id: run_dir,
                _project_service_env=project_service_env,
                _resolve_backend_env_file=lambda context, backend_cwd: (None, False),
                _resolve_frontend_env_file=lambda context, frontend_cwd: None,
                _prepare_backend_runtime=lambda **kwargs: None,
                _prepare_frontend_runtime=lambda **kwargs: None,
                _service_env_from_file=lambda base_env, env_file, include_app_env_file: dict(base_env),
                _service_enabled_for_mode=lambda mode, service_name: service_name == "voice-runtime",
                _service_command_source=lambda **kwargs: "configured",
                _split_command=lambda command, **kwargs: ["python", "-c", "pass"],
                _detect_service_actual_port=lambda **kwargs: 8019,
                _listener_truth_enforced=lambda: True,
                _service_listener_failure_detail=lambda **kwargs: "",
                _conflict_remaining={},
                _emit=lambda event, **payload: None,
            )
            orchestrator = SimpleNamespace(
                runtime=runtime,
                _process_runtime=lambda rt: SimpleNamespace(start_background=lambda *args, **kwargs: SimpleNamespace(pid=1234)),
                _restart_service_types_for_project=lambda **kwargs: {"voice-runtime"},
                _suppress_timing_output=lambda route: True,
            )
            context = SimpleNamespace(
                name="Main",
                root=project_root,
                ports={
                    "backend": SimpleNamespace(final=8000),
                    "frontend": SimpleNamespace(final=3000),
                    "voice-runtime": SimpleNamespace(final=8010),
                },
            )

            records = start_project_services(
                orchestrator,
                context,
                requirements=RequirementsResult(project="Main"),
                run_id="run-urls",
                route=parse_route(["start", "--main"], env={"ENVCTL_DEFAULT_MODE": "main"}),
            )

        record = records["Main Voice Runtime"]
        self.assertEqual(context.ports["voice-runtime"].final, 8019)
        self.assertEqual(record.public_url, "http://localhost:8019")
        self.assertEqual(record.health_url, "http://localhost:8019/readyz")


if __name__ == "__main__":
    unittest.main()
