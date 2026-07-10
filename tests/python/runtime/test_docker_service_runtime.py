from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from envctl_engine.runtime.docker_service_runtime import (
    DockerServiceRuntime,
    docker_service_container_name,
    refresh_container_log_snapshots,
    stop_container_log_followers,
)
from envctl_engine.runtime.lifecycle_service_termination import terminate_service_record
from envctl_engine.runtime.service_status_truth import service_truth_status
from envctl_engine.state.models import ServiceRecord


class _Runner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.env_file_payload = ""
        self.running = True
        self.port_ready = True
        self.terminated: list[int] = []
        self.build_env: dict[str, str] = {}
        self.existing_container: tuple[bool, str] | None = None

    def run(self, command, **_kwargs):
        argv = [str(part) for part in command]
        self.calls.append(argv)
        if argv[:2] == ["docker", "build"]:
            self.build_env = dict(_kwargs.get("env", {}))
        if argv[:2] == ["docker", "run"]:
            env_file = Path(argv[argv.index("--env-file") + 1])
            self.env_file_payload = env_file.read_text(encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="container-id\n", stderr="")
        if argv[:3] == ["docker", "container", "inspect"]:
            if self.existing_container is None:
                return SimpleNamespace(returncode=1, stdout="", stderr="No such container")
            running, owner = self.existing_container
            return SimpleNamespace(returncode=0, stdout=f"{str(running).lower()}|{owner}\n", stderr="")
        if argv[:3] == ["docker", "inspect", "--format"]:
            return SimpleNamespace(returncode=0 if self.running else 1, stdout="true\n" if self.running else "", stderr="")
        if argv[:3] == ["docker", "image", "inspect"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="missing")
        if argv[:3] == ["docker", "rm", "--force"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if argv[:2] == ["docker", "logs"]:
            return SimpleNamespace(returncode=0, stdout="container log\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    def start_background(self, command, **_kwargs):
        self.calls.append([str(part) for part in command])
        return SimpleNamespace(pid=4321)

    def wait_for_port(self, _port, **_kwargs):
        return self.port_ready

    def terminate_process_group(self, pid, **_kwargs):
        self.terminated.append(pid)
        return True


def _runtime(tmp_path: Path, runner: _Runner, *, env: dict[str, str] | None = None):
    events: list[tuple[str, dict[str, object]]] = []
    runtime = SimpleNamespace(
        env={"DOCKER_MODE": "true", **(env or {})},
        config=SimpleNamespace(raw={}, runtime_scope_dir=tmp_path / "runtime-scope"),
        process_runner=runner,
        _command_exists=lambda command: command == "docker",
        _run_dir_path=lambda run_id: tmp_path / "runs" / str(run_id),
        _emit=lambda event, **payload: events.append((event, payload)),
        _service_truth_timeout=lambda: 0.01,
    )
    return runtime, events


def test_container_names_preserve_root_identity_for_long_project_names(tmp_path: Path) -> None:
    first = docker_service_container_name(
        project_name="feature-" + ("very-long-name-" * 8),
        project_root=tmp_path / "one",
        service_name="backend",
    )
    second = docker_service_container_name(
        project_name="feature-" + ("very-long-name-" * 8),
        project_root=tmp_path / "two",
        service_name="backend",
    )

    assert len(first) <= 63
    assert len(second) <= 63
    assert first != second


def test_builds_with_docker_layer_cache_and_runs_managed_container(tmp_path: Path) -> None:
    runner = _Runner()
    runtime, events = _runtime(tmp_path, runner, env={"ENVCTL_BACKEND_DOCKER_COMMAND_MODE": "service"})
    service_root = tmp_path / "backend"
    service_root.mkdir()
    (service_root / "Dockerfile").write_text("FROM python:3.12-slim\nWORKDIR /app\n", encoding="utf-8")

    launch = DockerServiceRuntime(runtime, runner).launch(
        project_name="Feature One",
        project_root=tmp_path,
        service_name="backend",
        cwd=service_root,
        command=["python", "-m", "uvicorn", "app:api", "--host", "127.0.0.1", "--port", "8123"],
        env={
            "PATH": "/host/bin",
            "DATABASE_URL": "postgres://u:p@127.0.0.1:5432/db",
            "PORT": "8123",
            "VITE_API_URL": "http://localhost:8123/api/v1",
        },
        host_port=8123,
        container_port=8123,
        listener_expected=True,
        log_path=str(tmp_path / "backend.log"),
    )

    build_index = next(index for index, call in enumerate(runner.calls) if call[:2] == ["docker", "build"])
    run_index = next(index for index, call in enumerate(runner.calls) if call[:2] == ["docker", "run"])
    assert build_index < run_index
    docker_build = runner.calls[build_index]
    assert docker_build[docker_build.index("--build-arg") + 1] == "VITE_API_URL"
    assert "http://localhost:8123/api/v1" not in docker_build
    assert runner.build_env["VITE_API_URL"] == "http://localhost:8123/api/v1"
    docker_run = runner.calls[run_index]
    publish_index = docker_run.index("--publish")
    assert docker_run[publish_index : publish_index + 2] == ["--publish", "127.0.0.1:8123:8123"]
    assert "0.0.0.0" in docker_run
    runtime_label_index = docker_run.index("io.envctl.service=backend") + 2
    assert docker_run[runtime_label_index].startswith("io.envctl.runtime-scope=")
    assert "PATH=" not in runner.env_file_payload
    assert "DATABASE_URL=postgres://u:p@host.docker.internal:5432/db" in runner.env_file_payload
    assert launch.container_id == "container-id"
    assert any(event == "service.container.build" and payload["cache"] == "docker_layer_cache" for event, payload in events)


def test_running_untracked_container_is_not_replaced_or_removed(tmp_path: Path) -> None:
    runner = _Runner()
    runtime, _events = _runtime(tmp_path, runner, env={"ENVCTL_BACKEND_DOCKER_IMAGE": "example/backend:dev"})
    docker_runtime = DockerServiceRuntime(runtime, runner)
    runner.existing_container = (True, docker_runtime._runtime_scope_identity())

    try:
        docker_runtime.launch(
            project_name="Main",
            project_root=tmp_path,
            service_name="backend",
            cwd=tmp_path,
            command=[],
            env={},
            host_port=8123,
            container_port=8123,
            listener_expected=True,
            log_path=str(tmp_path / "backend.log"),
        )
    except RuntimeError as exc:
        assert "already running" in str(exc)
    else:
        raise AssertionError("expected the untracked running container to block startup")

    assert not any(call[:3] == ["docker", "rm", "--force"] for call in runner.calls)
    assert not any(call[:2] == ["docker", "run"] for call in runner.calls)


def test_container_owned_by_another_runtime_scope_is_not_replaced(tmp_path: Path) -> None:
    runner = _Runner()
    runtime, _events = _runtime(tmp_path, runner, env={"ENVCTL_BACKEND_DOCKER_IMAGE": "example/backend:dev"})
    runner.existing_container = (False, "another-runtime")

    try:
        DockerServiceRuntime(runtime, runner).launch(
            project_name="Main",
            project_root=tmp_path,
            service_name="backend",
            cwd=tmp_path,
            command=[],
            env={},
            host_port=8123,
            container_port=8123,
            listener_expected=True,
            log_path=str(tmp_path / "backend.log"),
        )
    except RuntimeError as exc:
        assert "another envctl runtime scope" in str(exc)
    else:
        raise AssertionError("expected the foreign runtime scope to block startup")

    assert not any(call[:3] == ["docker", "rm", "--force"] for call in runner.calls)


def test_stopped_container_from_same_runtime_scope_is_removed(tmp_path: Path) -> None:
    runner = _Runner()
    runtime, _events = _runtime(tmp_path, runner, env={"ENVCTL_BACKEND_DOCKER_IMAGE": "example/backend:dev"})
    docker_runtime = DockerServiceRuntime(runtime, runner)
    runner.existing_container = (False, docker_runtime._runtime_scope_identity())

    docker_runtime.launch(
        project_name="Main",
        project_root=tmp_path,
        service_name="backend",
        cwd=tmp_path,
        command=[],
        env={},
        host_port=8123,
        container_port=8123,
        listener_expected=True,
        log_path=str(tmp_path / "backend.log"),
    )

    inspect_index = next(index for index, call in enumerate(runner.calls) if call[:3] == ["docker", "container", "inspect"])
    remove_index = next(index for index, call in enumerate(runner.calls) if call[:3] == ["docker", "rm", "--force"])
    run_index = next(index for index, call in enumerate(runner.calls) if call[:2] == ["docker", "run"])
    assert inspect_index < remove_index < run_index


def test_configured_image_runs_without_build_and_preserves_browser_public_url(tmp_path: Path) -> None:
    runner = _Runner()
    runtime, _events = _runtime(
        tmp_path,
        runner,
        env={
            "ENVCTL_FRONTEND_DOCKER_IMAGE": "example/frontend:dev",
            "ENVCTL_FRONTEND_DOCKER_COMMAND": "npm run dev -- --host 0.0.0.0 --port 9000",
            "ENVCTL_FRONTEND_DOCKER_PORT": "9000",
        },
    )

    launch = DockerServiceRuntime(runtime, runner).launch(
        project_name="Main",
        project_root=tmp_path,
        service_name="frontend",
        cwd=tmp_path,
        command=["host-only-command"],
        env={
            "VITE_API_URL": "http://localhost:8000/api/v1",
            "REDIS_URL": "redis://localhost:6379",
            "PORT": "9100",
            "HOST": "127.0.0.1",
        },
        host_port=9100,
        container_port=9100,
        listener_expected=True,
        log_path=str(tmp_path / "frontend.log"),
    )

    assert not any(call[:2] == ["docker", "build"] for call in runner.calls)
    docker_run = next(call for call in runner.calls if call[:2] == ["docker", "run"])
    assert "example/frontend:dev" in docker_run
    assert "127.0.0.1:9100:9000" in docker_run
    assert docker_run[-8:] == ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "9000"]
    assert "VITE_API_URL=http://localhost:8000/api/v1" in runner.env_file_payload
    assert "REDIS_URL=redis://host.docker.internal:6379" in runner.env_file_payload
    assert "PORT=9000" in runner.env_file_payload
    assert "HOST=0.0.0.0" in runner.env_file_payload
    assert launch.image == "example/frontend:dev"


def test_container_state_drives_health_and_stop(tmp_path: Path) -> None:
    runner = _Runner()
    runtime, events = _runtime(tmp_path, runner)
    service = ServiceRecord(
        name="Main Backend",
        type="backend",
        cwd=str(tmp_path),
        pid=4321,
        requested_port=8123,
        actual_port=8123,
        status="running",
        runtime_kind="docker",
        container_id="container-id",
        container_name="envctl-app-main-backend",
        container_image="example/backend:dev",
    )

    assert service_truth_status(runtime, service) == "running"
    runner.port_ready = False
    assert service_truth_status(runtime, service) == "unreachable"
    assert terminate_service_record(runtime, service, aggressive=False, verify_ownership=True)
    assert ["docker", "rm", "--force", "container-id"] in runner.calls
    assert runner.terminated == [4321]
    assert any(event == "service.container.stop" for event, _payload in events)


def test_container_logs_are_snapshotted_and_followed_only_on_demand(tmp_path: Path) -> None:
    runner = _Runner()
    runtime, _events = _runtime(tmp_path, runner)
    log_path = tmp_path / "backend.log"
    service = ServiceRecord(
        name="Main Backend",
        type="backend",
        cwd=str(tmp_path),
        log_path=str(log_path),
        runtime_kind="docker",
        container_id="container-id",
    )
    state = SimpleNamespace(services={service.name: service})

    assert refresh_container_log_snapshots(runtime, state, tail=20, follow=False) == []
    assert log_path.read_text(encoding="utf-8") == "container log\n"
    assert not any(call[:3] == ["docker", "logs", "--follow"] for call in runner.calls)

    followers = refresh_container_log_snapshots(runtime, state, tail=20, follow=True)
    assert followers == [4321]
    assert any(call[:3] == ["docker", "logs", "--follow"] for call in runner.calls)
    stop_container_log_followers(runtime, followers)
    assert runner.terminated == [4321]
