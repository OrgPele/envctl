from __future__ import annotations

from collections.abc import Callable, Iterable
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from typing import cast
import unittest
from unittest.mock import patch

from envctl_engine.runtime.docker_service_runtime import DockerServiceLaunch
from envctl_engine.runtime.service_manager import ServiceCleanupError, ServiceManager, ServiceStartDescriptor
from envctl_engine.shared.ports import PortPlanner
from envctl_engine.startup.service_attach_execution import ServiceAttachRunner
from envctl_engine.startup.service_execution_records import PreparedServiceLaunch
from envctl_engine.state.models import PortPlan, ServiceRecord


def port_plan(port: int) -> PortPlan:
    return PortPlan(project="Main", requested=port, assigned=port, final=port, source="test")


class ServiceAttachExecutionTests(unittest.TestCase):
    def test_later_layer_failure_rolls_back_and_tracks_prior_layer_records(self) -> None:
        project_root = Path("/tmp/envctl-project")
        voice = SimpleNamespace(
            name="voice-runtime",
            start_cmd="python voice.py",
            depends_on=("backend",),
            start_order=25,
            expect_listener=True,
            critical=True,
            env_suffix="VOICE_RUNTIME",
        )
        worker = SimpleNamespace(
            name="worker",
            start_cmd="python worker.py",
            depends_on=("voice-runtime",),
            start_order=50,
            expect_listener=False,
            critical=True,
            env_suffix="WORKER",
        )
        attach_layers: list[tuple[str, ...]] = []
        backend_record = ServiceRecord(
            name="Main Backend",
            type="backend",
            cwd=str(project_root / "backend"),
            pid=61001,
            actual_port=8000,
        )

        def generic_attach(**kwargs: object) -> dict[str, ServiceRecord]:
            descriptors = tuple(cast(Iterable[ServiceStartDescriptor], kwargs["descriptors"]))
            layer = tuple(descriptor.service_type for descriptor in descriptors)
            attach_layers.append(layer)
            if "worker" not in layer:
                return {backend_record.name: backend_record}
            raise RuntimeError("worker startup failed")

        runtime = SimpleNamespace(
            services=SimpleNamespace(start_services_with_attach=generic_attach),
            _terminate_started_services=lambda _services: (_ for _ in ()).throw(OSError("layer terminator crashed")),
            config=SimpleNamespace(
                app_service_by_name=lambda name: {"voice-runtime": voice, "worker": worker}.get(name)
            ),
            _conflict_remaining={},
            _emit=lambda *_args, **_kwargs: None,
        )
        runner = ServiceAttachRunner(
            runtime=runtime,
            process_runtime=SimpleNamespace(),
            port_allocator=SimpleNamespace(
                reserve_next=lambda port, owner: port,
                session_id="attach-session",
            ),
            project_name="Main",
            project_root=project_root,
            backend_plan=port_plan(8000),
            frontend_plan=port_plan(5173),
            backend_cwd=project_root / "backend",
            frontend_cwd=project_root / "frontend",
            backend_log_path="/logs/backend.txt",
            frontend_log_path="/logs/frontend.txt",
            backend_env_extra={},
            frontend_env_extra={},
            command_env_builder=lambda port, extra: dict(extra),
            prepared_launches={
                "backend": PreparedServiceLaunch(
                    service_name="backend",
                    cwd=project_root / "backend",
                    log_path="/logs/backend.txt",
                    requested_port=8000,
                    env={},
                    command_source="configured",
                ),
                "worker": PreparedServiceLaunch(
                    service_name="worker",
                    cwd=project_root / "worker",
                    log_path="/logs/worker.txt",
                    requested_port=0,
                    env={},
                    command_source="configured",
                    listener_expected=False,
                ),
                "voice-runtime": PreparedServiceLaunch(
                    service_name="voice-runtime",
                    cwd=project_root / "voice-runtime",
                    log_path="/logs/voice.txt",
                    requested_port=8010,
                    env={},
                    command_source="configured",
                ),
            },
            selected_service_types={"backend", "voice-runtime", "worker"},
            additional_services=(voice, worker),
            backend_listener_expected=True,
            rebound_delta=0,
        )

        with self.assertRaises(ServiceCleanupError) as raised:
            runner.start(attach_parallel=False, on_service_retry=lambda *_args: None)

        self.assertEqual(attach_layers, [("backend", "voice-runtime"), ("worker",)])
        self.assertIs(raised.exception.unterminated_services["Main Backend"], backend_record)
        self.assertEqual(backend_record.port_lock_session, "attach-session")
        self.assertIn("cleanup error: layer terminator crashed", str(raised.exception))

    def test_process_launch_without_pid_never_invents_envctl_or_adjacent_pid(self) -> None:
        project_root = Path("/tmp/envctl-project")
        runtime = SimpleNamespace(
            _conflict_remaining={},
            _emit=lambda *_args, **_kwargs: None,
            _service_start_command_resolved=lambda **_kwargs: (["backend"], "configured"),
        )
        runner = ServiceAttachRunner(
            runtime=runtime,
            process_runtime=SimpleNamespace(start_background=lambda *_args, **_kwargs: object()),
            port_allocator=SimpleNamespace(reserve_next=lambda port, owner: port),
            project_name="Main",
            project_root=project_root,
            backend_plan=port_plan(8000),
            frontend_plan=port_plan(5173),
            backend_cwd=project_root / "backend",
            frontend_cwd=project_root / "frontend",
            backend_log_path="/logs/backend.txt",
            frontend_log_path="/logs/frontend.txt",
            backend_env_extra={},
            frontend_env_extra={},
            command_env_builder=lambda port, extra: dict(extra),
            prepared_launches={
                "backend": PreparedServiceLaunch(
                    service_name="backend",
                    cwd=project_root / "backend",
                    log_path="/logs/backend.txt",
                    requested_port=8000,
                    env={},
                    command_source="configured",
                )
            },
            selected_service_types={"backend"},
            additional_services=(),
            backend_listener_expected=True,
            rebound_delta=0,
        )

        success, error, pid = runner.start_backend(8000)

        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertIsNone(pid)

    def test_post_spawn_telemetry_failure_still_returns_real_pid_to_manager(self) -> None:
        project_root = Path("/tmp/envctl-project")

        def emit(event: str, **payload: object) -> None:
            if event == "service.start" or payload.get("phase") == "process_launch":
                raise OSError("event sink failed")

        runtime = SimpleNamespace(
            _conflict_remaining={},
            _emit=emit,
            _service_start_command_resolved=lambda **_kwargs: (["backend"], "configured"),
        )
        runner = ServiceAttachRunner(
            runtime=runtime,
            process_runtime=SimpleNamespace(start_background=lambda *_args, **_kwargs: SimpleNamespace(pid=62001)),
            port_allocator=SimpleNamespace(reserve_next=lambda port, owner: port),
            project_name="Main",
            project_root=project_root,
            backend_plan=port_plan(8000),
            frontend_plan=port_plan(5173),
            backend_cwd=project_root / "backend",
            frontend_cwd=project_root / "frontend",
            backend_log_path="/logs/backend.txt",
            frontend_log_path="/logs/frontend.txt",
            backend_env_extra={},
            frontend_env_extra={},
            command_env_builder=lambda port, extra: dict(extra),
            prepared_launches={
                "backend": PreparedServiceLaunch(
                    service_name="backend",
                    cwd=project_root / "backend",
                    log_path="/logs/backend.txt",
                    requested_port=8000,
                    env={},
                    command_source="configured",
                )
            },
            selected_service_types={"backend"},
            additional_services=(),
            backend_listener_expected=True,
            rebound_delta=0,
        )

        success, error, pid = runner.start_backend(8000)

        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertEqual(pid, 62001)

    def test_process_spawn_error_is_structured_without_listener_wait(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(
            _conflict_remaining={},
            _emit=lambda event, **payload: events.append((event, payload)),
            _service_start_command_resolved=lambda **_kwargs: (["missing-backend"], "configured"),
        )
        runner = ServiceAttachRunner(
            runtime=runtime,
            process_runtime=SimpleNamespace(
                start_background=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    FileNotFoundError("missing interpreter")
                )
            ),
            port_allocator=SimpleNamespace(reserve_next=lambda port, owner: port),
            project_name="Main",
            project_root=Path("/repo"),
            backend_plan=port_plan(8000),
            frontend_plan=port_plan(5173),
            backend_cwd=Path("/repo/backend"),
            frontend_cwd=Path("/repo/frontend"),
            backend_log_path="/logs/backend.txt",
            frontend_log_path="/logs/frontend.txt",
            backend_env_extra={},
            frontend_env_extra={},
            command_env_builder=lambda port, extra: dict(extra),
            prepared_launches={
                "backend": PreparedServiceLaunch(
                    service_name="backend",
                    cwd=Path("/repo/backend"),
                    log_path="/logs/backend.txt",
                    requested_port=8000,
                    env={},
                    command_source="configured",
                )
            },
            selected_service_types={"backend"},
            additional_services=(),
            backend_listener_expected=True,
            rebound_delta=0,
        )

        success, error, pid = runner.start_backend(8000)

        self.assertFalse(success)
        self.assertIn("process spawn failed for missing-backend", error)
        self.assertIsNone(pid)
        failure_events = [payload for event, payload in events if event == "service.failure"]
        self.assertEqual(failure_events[0]["failure_class"], "process_spawn_failed")

    def test_explicit_docker_mode_launches_and_annotates_container_service(self) -> None:
        project_root = Path("/tmp/envctl-project")
        runtime = SimpleNamespace(
            env={},
            config=SimpleNamespace(raw={}),
            services=ServiceManager(),
            _conflict_remaining={},
            _emit=lambda _event, **_payload: None,
            _service_start_command_resolved=lambda **kwargs: self.fail(
                f"host command resolution must be skipped: {kwargs}"
            ),
        )
        runner = ServiceAttachRunner(
            runtime=runtime,
            process_runtime=SimpleNamespace(),
            port_allocator=SimpleNamespace(reserve_next=lambda port, owner: port),
            project_name="Main",
            project_root=project_root,
            backend_plan=port_plan(8000),
            frontend_plan=port_plan(5173),
            backend_cwd=project_root / "backend",
            frontend_cwd=project_root / "frontend",
            backend_log_path="/logs/backend.txt",
            frontend_log_path="/logs/frontend.txt",
            backend_env_extra={"PORT": "8000"},
            frontend_env_extra={},
            command_env_builder=lambda port, extra: {**extra, "PORT": str(port)},
            prepared_launches={
                "backend": PreparedServiceLaunch(
                    service_name="backend",
                    cwd=project_root / "backend",
                    log_path="/logs/backend.txt",
                    requested_port=8000,
                    env={"PORT": "8000"},
                    command_source="configured",
                )
            },
            selected_service_types={"backend"},
            additional_services=(),
            backend_listener_expected=True,
            rebound_delta=0,
            docker_mode=True,
        )
        launch = DockerServiceLaunch(
            container_id="container-id",
            container_name="envctl-app-main-backend",
            image="example/backend:dev",
            log_path="/logs/backend.txt",
        )

        with (
            patch(
                "envctl_engine.startup.service_attach_execution.DockerServiceRuntime.launch",
                return_value=launch,
            ) as docker_launch,
            patch(
                "envctl_engine.startup.service_attach_execution.DockerServiceRuntime.wait_until_ready",
                return_value=True,
            ),
        ):
            records = runner.start(attach_parallel=False, on_service_retry=lambda *_args: None)

        record = records["Main Backend"]
        self.assertEqual(record.runtime_kind, "docker")
        self.assertEqual(record.container_id, "container-id")
        self.assertEqual(record.container_name, "envctl-app-main-backend")
        self.assertEqual(record.container_image, "example/backend:dev")
        docker_launch.assert_called_once()
        self.assertEqual(docker_launch.call_args.kwargs["command"], [])

        runtime.config.raw["ENVCTL_BACKEND_DOCKER_COMMAND"] = "uvicorn app:api --port 8000"
        self.assertEqual(runner._core_service_command("backend", 8001), [])

        runtime.config.raw.pop("ENVCTL_BACKEND_DOCKER_COMMAND")
        runtime.config.raw["ENVCTL_BACKEND_DOCKER_COMMAND_MODE"] = "service"
        resolved_calls: list[dict[str, object]] = []
        runtime._service_start_command_resolved = lambda **kwargs: (
            resolved_calls.append(kwargs) or ["container-service", "--port", str(kwargs["port"])],
            "configured",
        )
        self.assertEqual(
            runner._core_service_command("backend", 8001),
            ["container-service", "--port", "8001"],
        )
        self.assertEqual(resolved_calls, [{"service_name": "backend", "project_root": project_root, "port": 8001}])

    def test_failed_optional_docker_readiness_removes_container_before_degrading(self) -> None:
        project_root = Path("/tmp/envctl-project")
        optional_service = SimpleNamespace(
            name="voice-runtime",
            start_cmd="python voice.py --port {port}",
            depends_on=(),
            start_order=25,
            expect_listener=True,
            critical=False,
            env_suffix="VOICE_RUNTIME",
        )
        runtime = SimpleNamespace(
            env={"ENVCTL_VOICE_RUNTIME_DOCKER_IMAGE": "example/voice:dev"},
            config=SimpleNamespace(
                raw={},
                app_service_by_name=lambda name: optional_service if name == "voice-runtime" else None,
            ),
            services=ServiceManager(),
            _conflict_remaining={},
            _emit=lambda event, **payload: None,
            _split_command=lambda *args, **kwargs: self.fail("host command resolution must be skipped"),
        )
        runner = ServiceAttachRunner(
            runtime=runtime,
            process_runtime=SimpleNamespace(),
            port_allocator=SimpleNamespace(reserve_next=lambda port, owner: port),
            project_name="Main",
            project_root=project_root,
            backend_plan=port_plan(8000),
            frontend_plan=port_plan(5173),
            backend_cwd=project_root / "backend",
            frontend_cwd=project_root / "frontend",
            backend_log_path="/logs/backend.txt",
            frontend_log_path="/logs/frontend.txt",
            backend_env_extra={},
            frontend_env_extra={},
            command_env_builder=lambda port, extra: {**extra, "PORT": str(port)},
            prepared_launches={
                "voice-runtime": PreparedServiceLaunch(
                    service_name="voice-runtime",
                    cwd=project_root / "voice-runtime",
                    log_path="/logs/voice.txt",
                    requested_port=8010,
                    env={"PORT": "8010"},
                    command_source="configured",
                )
            },
            selected_service_types={"voice-runtime"},
            additional_services=(optional_service,),
            backend_listener_expected=True,
            rebound_delta=0,
            docker_mode=True,
        )
        launch = DockerServiceLaunch(
            container_id="failed-container-id",
            container_name="envctl-app-main-voice-runtime",
            image="example/voice:dev",
            log_path="/logs/voice.txt",
        )

        with (
            patch(
                "envctl_engine.startup.service_attach_execution.DockerServiceRuntime.launch",
                return_value=launch,
            ),
            patch(
                "envctl_engine.startup.service_attach_execution.DockerServiceRuntime.wait_until_ready",
                return_value=False,
            ),
            patch(
                "envctl_engine.startup.service_attach_execution.DockerServiceRuntime.stop",
                return_value=True,
            ) as stop_container,
        ):
            records = runner.start(attach_parallel=False, on_service_retry=lambda *args: None)

        record = records["Main Voice Runtime"]
        self.assertEqual(record.status, "degraded")
        self.assertTrue(record.degraded)
        self.assertIsNone(record.container_id)
        self.assertEqual(runner._container_launches, {})
        stop_container.assert_called_once_with("failed-container-id")

        runner._container_launches["voice-runtime"] = launch
        with patch(
            "envctl_engine.startup.service_attach_execution.DockerServiceRuntime.stop",
            return_value=False,
        ):
            self.assertEqual(
                runner._remove_failed_container_launch("voice-runtime", launch),
                "failed to remove container",
            )
        self.assertEqual(runner._container_launches, {"voice-runtime": launch})

    def test_runner_builds_layered_descriptors_and_preserves_additional_urls(self) -> None:
        project_root = Path("/tmp/envctl-project")
        events: list[tuple[str, dict[str, object]]] = []
        layers: list[tuple[str, ...]] = []
        process_commands: list[tuple[list[str], str, int]] = []

        voice = SimpleNamespace(
            name="voice-runtime",
            start_cmd="python voice.py --port {port}",
            depends_on=("backend",),
            start_order=25,
            expect_listener=True,
            critical=True,
            env_suffix="VOICE_RUNTIME",
        )
        worker = SimpleNamespace(
            name="worker",
            start_cmd="python worker.py",
            depends_on=("voice-runtime",),
            start_order=50,
            expect_listener=False,
            critical=False,
            env_suffix="WORKER",
        )

        def start_services_with_attach(**kwargs: object) -> dict[str, ServiceRecord]:
            descriptor_items = cast(Iterable[ServiceStartDescriptor], kwargs["descriptors"])
            descriptors = tuple(descriptor_items)
            layers.append(tuple(descriptor.service_type for descriptor in descriptors))
            records: dict[str, ServiceRecord] = {}
            for descriptor in descriptors:
                ok, error, pid = descriptor.start(descriptor.requested_port)
                self.assertTrue(ok, error)
                detect_actual = descriptor.detect_actual
                self.assertIsNotNone(detect_actual)
                assert detect_actual is not None
                actual = detect_actual(pid, descriptor.requested_port)
                records[f"Main {descriptor.service_type.title().replace('-', ' ')}"] = ServiceRecord(
                    name=f"Main {descriptor.service_type.title().replace('-', ' ')}",
                    type=descriptor.service_type,
                    cwd=descriptor.cwd,
                    requested_port=descriptor.requested_port or None,
                    actual_port=actual,
                    status="running",
                    listener_expected=descriptor.listener_expected,
                    public_url=descriptor.public_url,
                    health_url=descriptor.health_url,
                )
            return records

        runtime = SimpleNamespace(
            config=SimpleNamespace(
                app_service_by_name=lambda name: {"voice-runtime": voice, "worker": worker}.get(name),
            ),
            services=SimpleNamespace(start_services_with_attach=start_services_with_attach),
            _conflict_remaining={},
            _emit=lambda event, **payload: events.append((event, payload)),
            _service_start_command_resolved=lambda service_name, project_root, port: (
                [service_name, str(port)],
                "configured",
            ),
            _split_command=lambda command, port, replacements, cwd: [
                command.split()[1],
                str(port),
                replacements["service_name"],
                str(cwd),
            ],
            _detect_service_actual_port=lambda service_name, requested_port, **kwargs: (
                8101 if service_name == "backend" else 8022 if service_name == "voice-runtime" else requested_port
            ),
            _listener_truth_enforced=lambda: True,
            _service_listener_failure_detail=lambda **kwargs: "",
        )
        process_runtime = SimpleNamespace(
            start_background=lambda command, cwd, env, stdout_path, stderr_path: (
                process_commands.append((list(command), str(cwd), int(env["PORT"]))) or SimpleNamespace(pid=4321)
            )
        )
        runner = ServiceAttachRunner(
            runtime=runtime,
            process_runtime=process_runtime,
            port_allocator=SimpleNamespace(
                reserve_next=lambda port, owner: port,
                session_id="layered-session",
            ),
            project_name="Main",
            project_root=project_root,
            backend_plan=port_plan(8000),
            frontend_plan=port_plan(5173),
            backend_cwd=project_root / "backend",
            frontend_cwd=project_root / "frontend",
            backend_log_path="/logs/backend.txt",
            frontend_log_path="/logs/frontend.txt",
            backend_env_extra={"PORT": "8000"},
            frontend_env_extra={"PORT": "5173"},
            command_env_builder=lambda port, extra: {**extra, "PORT": str(port)},
            prepared_launches={
                "backend": PreparedServiceLaunch(
                    service_name="backend",
                    cwd=project_root / "backend",
                    log_path="/logs/backend.txt",
                    requested_port=8000,
                    env={"PORT": "8000"},
                    command_source="configured",
                ),
                "voice-runtime": PreparedServiceLaunch(
                    service_name="voice-runtime",
                    cwd=project_root / "voice-runtime",
                    log_path="/logs/voice.txt",
                    requested_port=8010,
                    env={
                        "PORT": "8010",
                        "ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PUBLIC_URL": "http://localhost:8010",
                        "ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_HEALTH_URL": "http://localhost:8010/readyz",
                    },
                    command_source="configured",
                ),
                "worker": PreparedServiceLaunch(
                    service_name="worker",
                    cwd=project_root / "worker",
                    log_path="/logs/worker.txt",
                    requested_port=0,
                    env={"PORT": "0"},
                    command_source="configured",
                    listener_expected=False,
                ),
            },
            selected_service_types={"backend", "voice-runtime", "worker"},
            additional_services=(voice, worker),
            backend_listener_expected=True,
            rebound_delta=0,
        )

        records = runner.start(attach_parallel=True, on_service_retry=lambda *args: None)

        self.assertEqual(layers, [("backend", "voice-runtime"), ("worker",)])
        self.assertEqual(records["Main Backend"].actual_port, 8101)
        self.assertEqual(
            {record.port_lock_session for record in records.values()},
            {"layered-session"},
        )
        self.assertEqual(records["Main Voice Runtime"].actual_port, 8022)
        self.assertIsNone(records["Main Worker"].actual_port)
        self.assertEqual(records["Main Voice Runtime"].public_url, "http://localhost:8010")
        self.assertIn((["backend", "8000"], str(project_root / "backend"), 8000), process_commands)
        self.assertIn(
            (
                ["voice.py", "8010", "voice-runtime", str(project_root / "voice-runtime")],
                str(project_root / "voice-runtime"),
                8010,
            ),
            process_commands,
        )
        self.assertIn(
            ("service.bind.skipped", {"project": "Main", "service": "worker", "reason": "listener_not_expected"}),
            events,
        )
        self.assertTrue(
            any(
                event == "service.attach.phase"
                and payload["service"] == "voice-runtime"
                and payload["phase"] == "actual_port_detection"
                for event, payload in events
            )
        )
        self.assertTrue(
            any(
                event == "service.attach.phase"
                and payload["service"] == "voice-runtime"
                and payload["phase"] == "process_launch"
                for event, payload in events
            )
        )

    def test_additional_listener_truth_failure_emits_failure_event(self) -> None:
        project_root = Path("/tmp/envctl-project")
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(
            services=SimpleNamespace(),
            _conflict_remaining={},
            _emit=lambda event, **payload: events.append((event, payload)),
            _service_start_command_resolved=lambda service_name, project_root, port: (
                [service_name, str(port)],
                "configured",
            ),
            _detect_service_actual_port=lambda **kwargs: None,
            _listener_truth_enforced=lambda: True,
            _service_listener_failure_detail=lambda **kwargs: "process exited",
        )
        runner = ServiceAttachRunner(
            runtime=runtime,
            process_runtime=SimpleNamespace(),
            port_allocator=SimpleNamespace(reserve_next=lambda port, owner: port),
            project_name="Main",
            project_root=project_root,
            backend_plan=port_plan(8000),
            frontend_plan=port_plan(5173),
            backend_cwd=project_root / "backend",
            frontend_cwd=project_root / "frontend",
            backend_log_path="/logs/backend.txt",
            frontend_log_path="/logs/frontend.txt",
            backend_env_extra={},
            frontend_env_extra={},
            command_env_builder=lambda port, extra: dict(extra),
            prepared_launches={
                "voice-runtime": PreparedServiceLaunch(
                    service_name="voice-runtime",
                    cwd=project_root / "voice-runtime",
                    log_path="/logs/voice.txt",
                    requested_port=8010,
                    env={"PORT": "8010"},
                    command_source="configured",
                )
            },
            selected_service_types={"voice-runtime"},
            additional_services=(),
            backend_listener_expected=True,
            rebound_delta=0,
        )

        with self.assertRaisesRegex(
            RuntimeError,
            r"voice-runtime process exited before opening its listener for Main on port 8010 \(process exited\)",
        ):
            runner.detect_additional_actual("voice-runtime", pid=4321, requested=8010)

        self.assertIn(
            (
                "service.failure",
                {
                    "project": "Main",
                    "service": "voice-runtime",
                    "failure_class": "process_exited",
                    "requested_port": 8010,
                    "detail": "process exited",
                },
            ),
            events,
        )

    def test_missing_nested_executable_is_reported_as_dependency_failure(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        detail = (
            "process 2304354 exited; log_path: /tmp/voice-runtime.txt; "
            "log: scripts/envctl/start-voice-runtime.sh: line 20: exec: python: not found"
        )
        runtime = SimpleNamespace(
            services=SimpleNamespace(),
            _conflict_remaining={},
            _emit=lambda event, **payload: events.append((event, payload)),
            _detect_service_actual_port=lambda **_kwargs: None,
            _listener_truth_enforced=lambda: True,
            _service_listener_failure_detail=lambda **_kwargs: detail,
        )
        runner = ServiceAttachRunner(
            runtime=runtime,
            process_runtime=SimpleNamespace(),
            port_allocator=SimpleNamespace(reserve_next=lambda port, owner: port),
            project_name="refactoring-elevenlabs-agent-runtime-automation-and-pipecat-strangler-3",
            project_root=Path("/repo"),
            backend_plan=port_plan(8000),
            frontend_plan=port_plan(5173),
            backend_cwd=Path("/repo/backend"),
            frontend_cwd=Path("/repo/frontend"),
            backend_log_path="/logs/backend.txt",
            frontend_log_path="/logs/frontend.txt",
            backend_env_extra={},
            frontend_env_extra={},
            command_env_builder=lambda port, extra: dict(extra),
            prepared_launches={
                "voice-runtime": PreparedServiceLaunch(
                    service_name="voice-runtime",
                    cwd=Path("/repo/voice-runtime"),
                    log_path="/tmp/voice-runtime.txt",
                    requested_port=8251,
                    env={"PORT": "8251"},
                    command_source="configured",
                )
            },
            selected_service_types={"voice-runtime"},
            additional_services=(),
            backend_listener_expected=True,
            rebound_delta=0,
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "voice-runtime is missing a required executable or module",
        ):
            runner.detect_additional_actual("voice-runtime", pid=2304354, requested=8251)

        failure_events = [payload for event, payload in events if event == "service.failure"]
        self.assertEqual(failure_events[0]["failure_class"], "dependency_missing")
        self.assertEqual(failure_events[0]["detail"], detail)

    def test_core_only_runner_uses_legacy_service_manager_when_generic_attach_is_missing(self) -> None:
        attach_kwargs: dict[str, object] = {}
        runtime = SimpleNamespace(
            services=SimpleNamespace(
                start_project_with_attach=lambda **kwargs: (
                    attach_kwargs.update(kwargs)
                    or {"Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd="/repo")}
                )
            ),
            _conflict_remaining={},
            _emit=lambda event, **payload: None,
            _service_start_command_resolved=lambda service_name, project_root, port: (
                [service_name, str(port)],
                "configured",
            ),
            _detect_service_actual_port=lambda **kwargs: kwargs["requested_port"],
            _listener_truth_enforced=lambda: True,
            _service_listener_failure_detail=lambda **kwargs: "",
        )
        runner = ServiceAttachRunner(
            runtime=runtime,
            process_runtime=SimpleNamespace(start=lambda *args, **kwargs: SimpleNamespace(pid=123)),
            port_allocator=SimpleNamespace(
                reserve_next=lambda port, owner: port,
                session_id="legacy-attach-session",
            ),
            project_name="Main",
            project_root=Path("/repo"),
            backend_plan=port_plan(8000),
            frontend_plan=port_plan(5173),
            backend_cwd=Path("/repo/backend"),
            frontend_cwd=Path("/repo/frontend"),
            backend_log_path="/logs/backend.txt",
            frontend_log_path="/logs/frontend.txt",
            backend_env_extra={},
            frontend_env_extra={},
            command_env_builder=lambda port, extra: dict(extra),
            prepared_launches={
                "backend": PreparedServiceLaunch(
                    service_name="backend",
                    cwd=Path("/repo/backend"),
                    log_path="/logs/backend.txt",
                    requested_port=8000,
                    env={},
                    command_source="configured",
                )
            },
            selected_service_types={"backend"},
            additional_services=(),
            backend_listener_expected=True,
            rebound_delta=0,
        )

        records = runner.start(attach_parallel=False, on_service_retry=lambda *args: None)

        self.assertIn("Main Backend", records)
        self.assertEqual(
            records["Main Backend"].port_lock_session,
            "legacy-attach-session",
        )
        self.assertTrue(callable(attach_kwargs["start_backend"]))
        self.assertFalse(attach_kwargs["parallel_start"])

    def test_multiple_service_retries_release_every_failed_port_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            planner = PortPlanner(
                lock_dir=tmpdir,
                session_id="startup-session",
                availability_checker=lambda _port: True,
            )
            planner.reserve_next(8000, owner="Main:backend")

            def generic_attach(**kwargs: object) -> dict[str, ServiceRecord]:
                reserve_next = cast(Callable[[int], int], kwargs["reserve_next"])
                on_retry = cast(Callable[[str, int, int, int, str | None], None], kwargs["on_retry"])
                retry_one = reserve_next(8001)
                on_retry("backend", 8000, retry_one, 1, "address already in use")
                retry_two = reserve_next(retry_one + 1)
                on_retry("backend", retry_one, retry_two, 2, "address already in use")
                return {}

            runtime = SimpleNamespace(
                services=SimpleNamespace(start_services_with_attach=generic_attach),
                _conflict_remaining={},
                _emit=lambda *_args, **_kwargs: None,
            )
            runner = ServiceAttachRunner(
                runtime=runtime,
                process_runtime=SimpleNamespace(),
                port_allocator=planner,
                project_name="Main",
                project_root=Path("/repo"),
                backend_plan=port_plan(8000),
                frontend_plan=port_plan(5173),
                backend_cwd=Path("/repo/backend"),
                frontend_cwd=Path("/repo/frontend"),
                backend_log_path="/logs/backend.txt",
                frontend_log_path="/logs/frontend.txt",
                backend_env_extra={},
                frontend_env_extra={},
                command_env_builder=lambda port, extra: dict(extra),
                prepared_launches={
                    "backend": PreparedServiceLaunch(
                        service_name="backend",
                        cwd=Path("/repo/backend"),
                        log_path="/logs/backend.txt",
                        requested_port=8000,
                        env={},
                        command_source="configured",
                    )
                },
                selected_service_types={"backend"},
                additional_services=(),
                backend_listener_expected=True,
                rebound_delta=0,
            )

            runner.start(attach_parallel=False, on_service_retry=lambda *_args: None)

            locks = list(Path(tmpdir).glob("*.lock"))
            self.assertEqual([path.name for path in locks], ["8002.lock"])
            payload = json.loads(locks[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["owner"], "Main:services")

    def test_failed_rebound_frontend_releases_attempt_locks_without_bulk_session_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            planner = PortPlanner(
                lock_dir=tmpdir,
                session_id="startup-session",
                availability_checker=lambda _port: True,
            )
            planner.reserve_next(5173, owner="Main:frontend")
            live_pids = {123}
            process_runtime = SimpleNamespace(
                start_background=lambda *_args, **_kwargs: SimpleNamespace(pid=123),
                is_pid_running=lambda pid: pid in live_pids,
                terminate_process_group=lambda pid, **_kwargs: live_pids.discard(pid) or True,
            )
            runtime = SimpleNamespace(
                services=ServiceManager(),
                _conflict_remaining={},
                _emit=lambda *_args, **_kwargs: None,
                _service_start_command_resolved=lambda **_kwargs: (["frontend"], "configured"),
                _detect_service_actual_port=lambda **_kwargs: None,
                _listener_truth_enforced=lambda: True,
                _service_listener_failure_detail=lambda **_kwargs: "listener missing",
            )
            runner = ServiceAttachRunner(
                runtime=runtime,
                process_runtime=process_runtime,
                port_allocator=planner,
                project_name="Main",
                project_root=Path("/repo"),
                backend_plan=port_plan(8000),
                frontend_plan=port_plan(5173),
                backend_cwd=Path("/repo/backend"),
                frontend_cwd=Path("/repo/frontend"),
                backend_log_path="/logs/backend.txt",
                frontend_log_path="/logs/frontend.txt",
                backend_env_extra={},
                frontend_env_extra={},
                command_env_builder=lambda port, extra: dict(extra),
                prepared_launches={
                    "frontend": PreparedServiceLaunch(
                        service_name="frontend",
                        cwd=Path("/repo/frontend"),
                        log_path="/logs/frontend.txt",
                        requested_port=5173,
                        env={},
                        command_source="configured",
                    )
                },
                selected_service_types={"frontend"},
                additional_services=(),
                backend_listener_expected=True,
                rebound_delta=2,
            )

            with self.assertRaisesRegex(RuntimeError, "listener not detected"):
                runner.start(attach_parallel=False, on_service_retry=lambda *_args: None)

            # Failure finalization keeps the whole session when managed
            # requirements remain, so per-attempt cleanup must be sufficient.
            self.assertEqual(list(Path(tmpdir).glob("*.lock")), [])


if __name__ == "__main__":
    unittest.main()
