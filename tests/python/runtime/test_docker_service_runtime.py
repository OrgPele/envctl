from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.runtime.docker_service_runtime import (
    DockerServiceLaunchCleanupError,
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
        self.launched_container: dict[str, str] | None = None
        self.local_images: set[str] = set()
        self.remote_exposed_ports: dict[str, dict[str, object]] = {}

    def run(self, command, **_kwargs):
        argv = [str(part) for part in command]
        self.calls.append(argv)
        if argv[:2] == ["docker", "build"]:
            self.build_env = dict(_kwargs.get("env", {}))
            self.local_images.add(argv[argv.index("--tag") + 1])
        if argv[:2] == ["docker", "run"]:
            env_file = Path(argv[argv.index("--env-file") + 1])
            self.env_file_payload = env_file.read_text(encoding="utf-8")
            labels = [argv[index + 1] for index, value in enumerate(argv) if value == "--label"]
            self.launched_container = {
                "id": "d" * 64,
                "name": argv[argv.index("--name") + 1],
                "scope": next(value.split("=", 1)[1] for value in labels if value.startswith("io.envctl.runtime-scope=")),
                "token": next(value.split("=", 1)[1] for value in labels if value.startswith("io.envctl.launch-token=")),
            }
            return SimpleNamespace(returncode=0, stdout=f"{'d' * 64}\n", stderr="")
        if argv[:3] == ["docker", "container", "inspect"]:
            reference = argv[-1]
            launched = self.launched_container
            if launched is not None and reference in {launched["id"], launched["name"]}:
                format_value = argv[argv.index("--format") + 1]
                if ".State.Running" in format_value:
                    return SimpleNamespace(
                        returncode=0,
                        stdout=f"{launched['id']}|true|{launched['scope']}\n",
                        stderr="",
                    )
                label_value = launched["token"] if "io.envctl.launch-token" in format_value else launched["scope"]
                return SimpleNamespace(
                    returncode=0,
                    stdout=f"{launched['id']}|{label_value}\n",
                    stderr="",
                )
            if self.existing_container is None:
                return SimpleNamespace(returncode=1, stdout="", stderr="No such container")
            running, owner = self.existing_container
            format_value = argv[argv.index("--format") + 1]
            if ".State.Running" not in format_value:
                return SimpleNamespace(returncode=0, stdout=f"{'c' * 64}|{owner}\n", stderr="")
            return SimpleNamespace(
                returncode=0,
                stdout=f"{'c' * 64}|{str(running).lower()}|{owner}\n",
                stderr="",
            )
        if argv[:3] == ["docker", "container", "ls"]:
            launched = self.launched_container
            token_filter = argv[argv.index("--filter") + 1]
            expected_token = token_filter.rpartition("=")[2]
            stdout = (
                f"{launched['id']}\n"
                if launched is not None and launched["token"] == expected_token
                else ""
            )
            return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        if argv[:3] == ["docker", "inspect", "--format"]:
            return SimpleNamespace(returncode=0 if self.running else 1, stdout="true\n" if self.running else "", stderr="")
        if argv[:3] == ["docker", "image", "inspect"]:
            image = argv[-1]
            if image not in self.local_images:
                return SimpleNamespace(returncode=1, stdout="", stderr="missing")
            if "--format" in argv:
                payload = self.remote_exposed_ports.get(image, {})
                return SimpleNamespace(returncode=0, stdout=json.dumps(payload) + "\n", stderr="")
            return SimpleNamespace(returncode=0, stdout="[]\n", stderr="")
        if argv[:2] == ["docker", "pull"]:
            self.local_images.add(argv[-1])
            return SimpleNamespace(returncode=0, stdout="pulled\n", stderr="")
        if argv[:3] == ["docker", "rm", "--force"]:
            if self.launched_container is not None and argv[-1] in {
                self.launched_container["id"],
                self.launched_container["name"],
            }:
                self.launched_container = None
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
    assert launch.container_id == "d" * 64
    assert any(event == "service.container.build" and payload["cache"] == "docker_layer_cache" for event, payload in events)


def test_docker_env_files_are_unique_private_and_independently_scoped(tmp_path: Path) -> None:
    runner = _Runner()
    runtime, _events = _runtime(tmp_path, runner)
    docker_runtime = DockerServiceRuntime(runtime, runner)

    first = docker_runtime._write_env_file(project_name="Main", service_name="backend", values={"SECRET": "one"})
    second = docker_runtime._write_env_file(project_name="Main", service_name="backend", values={"SECRET": "two"})
    try:
        assert first != second
        assert first.read_text(encoding="utf-8") == "SECRET=one\n"
        assert second.read_text(encoding="utf-8") == "SECRET=two\n"
        assert first.stat().st_mode & 0o777 == 0o600
        assert second.stat().st_mode & 0o777 == 0o600
    finally:
        assert docker_runtime._scrub_env_file(first) is None
        assert docker_runtime._scrub_env_file(second) is None


def test_stale_env_file_from_dead_process_is_scrubbed_before_new_write(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    runner = _Runner()
    runtime, _events = _runtime(tmp_path, runner)
    docker_runtime = DockerServiceRuntime(runtime, runner)
    run_dir = tmp_path / "runs" / "docker"
    run_dir.mkdir(parents=True)
    stale = run_dir / ".docker-env-aaaaaaaaaaaa-p99999999-stale123"
    stale.write_text("SECRET=stale\n", encoding="utf-8")
    monkeypatch.setattr(DockerServiceRuntime, "_pid_is_running", staticmethod(lambda _pid: False))

    current = docker_runtime._write_env_file(
        project_name="Main",
        service_name="backend",
        values={"SECRET": "current"},
    )
    try:
        assert not stale.exists()
        assert current.read_text(encoding="utf-8") == "SECRET=current\n"
    finally:
        assert docker_runtime._scrub_env_file(current) is None


def test_old_env_file_from_live_process_is_never_scrubbed(tmp_path: Path) -> None:
    runner = _Runner()
    runtime, _events = _runtime(tmp_path, runner, env={"ENVCTL_DOCKER_ENV_STALE_SECONDS": "0"})
    docker_runtime = DockerServiceRuntime(runtime, runner)
    run_dir = tmp_path / "runs" / "docker"
    run_dir.mkdir(parents=True)
    active = run_dir / f".docker-env-aaaaaaaaaaaa-p{os.getpid()}-active123"
    active.write_text("SECRET=active\n", encoding="utf-8")
    os.utime(active, (1, 1))

    current = docker_runtime._write_env_file(
        project_name="Main",
        service_name="backend",
        values={"SECRET": "current"},
    )
    try:
        assert active.read_text(encoding="utf-8") == "SECRET=active\n"
    finally:
        assert docker_runtime._scrub_env_file(active) is None
        assert docker_runtime._scrub_env_file(current) is None


def test_old_legacy_env_file_is_scrubbed_after_grace_period(tmp_path: Path) -> None:
    runner = _Runner()
    runtime, _events = _runtime(tmp_path, runner)
    docker_runtime = DockerServiceRuntime(runtime, runner)
    run_dir = tmp_path / "runs" / "docker"
    run_dir.mkdir(parents=True)
    stale = run_dir / ".docker-env-legacy"
    stale.write_text("SECRET=legacy\n", encoding="utf-8")
    os.utime(stale, (1, 1))

    current = docker_runtime._write_env_file(
        project_name="Main",
        service_name="backend",
        values={"SECRET": "current"},
    )
    try:
        assert not stale.exists()
    finally:
        assert docker_runtime._scrub_env_file(current) is None


def test_unscrubbable_stale_env_file_blocks_new_secret_write(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    runner = _Runner()
    runtime, _events = _runtime(tmp_path, runner)
    docker_runtime = DockerServiceRuntime(runtime, runner)
    run_dir = tmp_path / "runs" / "docker"
    run_dir.mkdir(parents=True)
    stale = run_dir / ".docker-env-aaaaaaaaaaaa-p99999999-stale123"
    stale.write_text("SECRET=stale\n", encoding="utf-8")
    original_unlink = Path.unlink
    original_open = os.open

    def fail_env_unlink(path: Path, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        if path == stale:
            raise OSError("unlink unavailable")
        return original_unlink(path, *args, **kwargs)

    def fail_env_truncate(path, flags, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        if Path(path) == stale and flags & os.O_TRUNC:
            raise OSError("truncate unavailable")
        return original_open(path, flags, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(DockerServiceRuntime, "_pid_is_running", staticmethod(lambda _pid: False))
        scoped.setattr(Path, "unlink", fail_env_unlink)
        scoped.setattr(os, "open", fail_env_truncate)
        try:
            docker_runtime._write_env_file(
                project_name="Main",
                service_name="backend",
                values={"SECRET": "current"},
            )
        except RuntimeError as exc:
            assert "stale docker env file cleanup failed" in str(exc).lower()
        else:
            raise AssertionError("an unscrubbable stale secret must block a new write")

    assert list(run_dir.glob(".docker-env-*")) == [stale]
    assert docker_runtime._scrub_env_file(stale) is None
    assert list(run_dir.glob(".docker-env-*")) == []


def test_partial_env_write_failure_cannot_mask_unscrubbable_secret_file(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    runner = _Runner()
    runtime, events = _runtime(tmp_path, runner)
    docker_runtime = DockerServiceRuntime(runtime, runner)
    original_unlink = Path.unlink
    original_open = os.open
    original_fdopen = os.fdopen

    class PartialWriteFailure:
        def __init__(self, handle) -> None:  # noqa: ANN001
            self.handle = handle

        def __enter__(self):  # noqa: ANN204
            return self

        def write(self, value: str) -> None:
            self.handle.write(value[:10])
            self.handle.flush()
            raise OSError("partial write failed")

        def __exit__(self, *_args) -> None:  # noqa: ANN002
            self.handle.close()

    def partial_fdopen(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        return PartialWriteFailure(original_fdopen(*args, **kwargs))

    def fail_env_unlink(path: Path, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        if path.name.startswith(".docker-env-"):
            raise OSError("unlink unavailable")
        return original_unlink(path, *args, **kwargs)

    def fail_env_truncate(path, flags, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        if Path(path).name.startswith(".docker-env-") and flags & os.O_TRUNC:
            raise OSError("truncate unavailable")
        return original_open(path, flags, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "fdopen", partial_fdopen)
        scoped.setattr(Path, "unlink", fail_env_unlink)
        scoped.setattr(os, "open", fail_env_truncate)
        try:
            docker_runtime._write_env_file(
                project_name="Main",
                service_name="backend",
                values={"SECRET": "do-not-leak"},
            )
        except RuntimeError as exc:
            detail = str(exc).lower()
            assert "partial write failed" in detail
            assert "secret scrub failed" in detail
        else:
            raise AssertionError("the partial write must report the secret cleanup failure")

    env_files = list((tmp_path / "runs" / "docker").glob(".docker-env-*"))
    assert len(env_files) == 1
    assert env_files[0].read_text(encoding="utf-8")
    assert any(event == "service.container.env_file_cleanup_warning" for event, _payload in events)
    assert docker_runtime._scrub_env_file(env_files[0]) is None
    assert list((tmp_path / "runs" / "docker").glob(".docker-env-*")) == []


def test_interrupt_during_env_write_scrubs_partial_secret_before_reraising(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    runner = _Runner()
    runtime, _events = _runtime(tmp_path, runner)
    docker_runtime = DockerServiceRuntime(runtime, runner)
    original_fdopen = os.fdopen

    class InterruptedWrite:
        def __init__(self, handle) -> None:  # noqa: ANN001
            self.handle = handle

        def __enter__(self):  # noqa: ANN204
            return self

        def write(self, value: str) -> None:
            self.handle.write(value)
            self.handle.flush()
            raise KeyboardInterrupt

        def __exit__(self, *_args) -> None:  # noqa: ANN002
            self.handle.close()

    monkeypatch.setattr(
        os,
        "fdopen",
        lambda *args, **kwargs: InterruptedWrite(original_fdopen(*args, **kwargs)),
    )

    try:
        docker_runtime._write_env_file(
            project_name="Main",
            service_name="backend",
            values={"SECRET": "must-not-remain"},
        )
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("the write interrupt must be restored after secret cleanup")

    assert list((tmp_path / "runs" / "docker").glob(".docker-env-*")) == []


def test_successful_docker_run_with_empty_stdout_uses_owned_container_name(tmp_path: Path) -> None:
    class EmptyOutputRunner(_Runner):
        def run(self, command, **kwargs):  # noqa: ANN001, ANN202
            result = super().run(command, **kwargs)
            if [str(part) for part in command][:2] == ["docker", "run"]:
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return result

    runner = EmptyOutputRunner()
    runtime, _events = _runtime(tmp_path, runner, env={"ENVCTL_BACKEND_DOCKER_IMAGE": "example/backend:dev"})

    launch = DockerServiceRuntime(runtime, runner).launch(
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

    assert launch.container_id == "d" * 64
    assert launch.launch_token
    assert not any(call[:3] == ["docker", "rm", "--force"] for call in runner.calls)


def test_successful_docker_run_with_malformed_stdout_resolves_owned_immutable_id(tmp_path: Path) -> None:
    class DiagnosticOutputRunner(_Runner):
        def run(self, command, **kwargs):  # noqa: ANN001, ANN202
            result = super().run(command, **kwargs)
            if [str(part) for part in command][:2] == ["docker", "run"]:
                return SimpleNamespace(returncode=0, stdout="unexpected diagnostic line\n", stderr="")
            return result

    runner = DiagnosticOutputRunner()
    runtime, _events = _runtime(tmp_path, runner, env={"ENVCTL_BACKEND_DOCKER_IMAGE": "example/backend:dev"})

    launch = DockerServiceRuntime(runtime, runner).launch(
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

    assert launch.container_id == "d" * 64
    assert launch.container_id != "unexpected diagnostic line"


def test_env_file_unlink_failure_scrubs_secrets_without_masking_success(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    runner = _Runner()
    runtime, events = _runtime(
        tmp_path,
        runner,
        env={"ENVCTL_BACKEND_DOCKER_IMAGE": "example/backend:dev"},
    )
    original_unlink = Path.unlink

    def fail_env_unlink(path: Path, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        if path.name.startswith(".docker-env-"):
            raise OSError("unlink unavailable")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_env_unlink)

    launch = DockerServiceRuntime(runtime, runner).launch(
        project_name="Main",
        project_root=tmp_path,
        service_name="backend",
        cwd=tmp_path,
        command=[],
        env={"SECRET": "do-not-leak"},
        host_port=8123,
        container_port=8123,
        listener_expected=True,
        log_path=str(tmp_path / "backend.log"),
    )

    env_files = list((tmp_path / "runs" / "docker").glob(".docker-env-*"))
    assert launch.container_id == "d" * 64
    assert len(env_files) == 1
    assert env_files[0].read_text(encoding="utf-8") == ""
    assert any(event == "service.container.env_file_cleanup_warning" for event, _payload in events)


def test_unscrubbable_env_file_fails_launch_and_removes_owned_container(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    runner = _Runner()
    runtime, events = _runtime(
        tmp_path,
        runner,
        env={"ENVCTL_BACKEND_DOCKER_IMAGE": "example/backend:dev"},
    )
    docker_runtime = DockerServiceRuntime(runtime, runner)
    original_unlink = Path.unlink
    original_open = os.open

    def fail_env_unlink(path: Path, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        if path.name.startswith(".docker-env-"):
            raise OSError("unlink unavailable")
        return original_unlink(path, *args, **kwargs)

    def fail_env_truncate(path, flags, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        if Path(path).name.startswith(".docker-env-") and flags & os.O_TRUNC:
            raise OSError("truncate unavailable")
        return original_open(path, flags, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "unlink", fail_env_unlink)
        scoped.setattr(os, "open", fail_env_truncate)
        try:
            docker_runtime.launch(
                project_name="Main",
                project_root=tmp_path,
                service_name="backend",
                cwd=tmp_path,
                command=[],
                env={"SECRET": "do-not-leak"},
                host_port=8123,
                container_port=8123,
                listener_expected=True,
                log_path=str(tmp_path / "backend.log"),
            )
        except RuntimeError as exc:
            assert "env file cleanup failed" in str(exc).lower()
        else:
            raise AssertionError("an unscrubbable secret file must fail the launch")

    env_files = list((tmp_path / "runs" / "docker").glob(".docker-env-*"))
    assert runner.launched_container is None
    assert ["docker", "rm", "--force", "d" * 64] in runner.calls
    assert any(event == "service.container.env_file_cleanup_warning" for event, _payload in events)
    assert len(env_files) == 1
    assert docker_runtime._scrub_env_file(env_files[0]) is None
    assert list((tmp_path / "runs" / "docker").glob(".docker-env-*")) == []


def test_pre_run_command_error_cannot_mask_unscrubbable_secret_file(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    runner = _Runner()
    runtime, events = _runtime(
        tmp_path,
        runner,
        env={
            "ENVCTL_BACKEND_DOCKER_IMAGE": "example/backend:dev",
            "ENVCTL_BACKEND_DOCKER_COMMAND_MODE": "invalid",
        },
    )
    docker_runtime = DockerServiceRuntime(runtime, runner)
    original_unlink = Path.unlink
    original_open = os.open

    def fail_env_unlink(path: Path, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        if path.name.startswith(".docker-env-"):
            raise OSError("unlink unavailable")
        return original_unlink(path, *args, **kwargs)

    def fail_env_truncate(path, flags, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        if Path(path).name.startswith(".docker-env-") and flags & os.O_TRUNC:
            raise OSError("truncate unavailable")
        return original_open(path, flags, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "unlink", fail_env_unlink)
        scoped.setattr(os, "open", fail_env_truncate)
        try:
            docker_runtime.launch(
                project_name="Main",
                project_root=tmp_path,
                service_name="backend",
                cwd=tmp_path,
                command=["python", "app.py"],
                env={"SECRET": "do-not-leak"},
                host_port=8123,
                container_port=8123,
                listener_expected=True,
                log_path=str(tmp_path / "backend.log"),
            )
        except RuntimeError as exc:
            detail = str(exc).lower()
            assert "invalid docker command mode" in detail
            assert "env file cleanup failed" in detail
            assert "secret scrub failed" in detail
        else:
            raise AssertionError("the pre-run error must report the secret cleanup failure")

    env_files = list((tmp_path / "runs" / "docker").glob(".docker-env-*"))
    assert not any(call[:2] == ["docker", "run"] for call in runner.calls)
    assert any(event == "service.container.env_file_cleanup_warning" for event, _payload in events)
    assert len(env_files) == 1
    assert docker_runtime._scrub_env_file(env_files[0]) is None
    assert list((tmp_path / "runs" / "docker").glob(".docker-env-*")) == []


def test_tokenized_stop_treats_already_absent_container_as_confirmed(tmp_path: Path) -> None:
    runner = _Runner()
    runtime, _events = _runtime(tmp_path, runner)

    stopped = DockerServiceRuntime(runtime, runner).stop(
        "envctl-app-main-backend",
        expected_launch_token="launch-token",
    )

    assert stopped
    assert not any(call[:3] == ["docker", "rm", "--force"] for call in runner.calls)


def test_tokenized_stop_removes_inspected_immutable_id_not_reused_name(tmp_path: Path) -> None:
    container_id = "a" * 64

    class NameReuseRunner(_Runner):
        def run(self, command, **kwargs):  # noqa: ANN001, ANN202
            argv = [str(part) for part in command]
            if argv[:3] == ["docker", "container", "inspect"]:
                self.calls.append(argv)
                return SimpleNamespace(
                    returncode=0,
                    stdout=f"{container_id}|launch-token\n",
                    stderr="",
                )
            return super().run(command, **kwargs)

    runner = NameReuseRunner()
    runtime, _events = _runtime(tmp_path, runner)

    stopped = DockerServiceRuntime(runtime, runner).stop(
        "envctl-app-main-backend",
        expected_launch_token="launch-token",
    )

    assert stopped
    remove = next(call for call in runner.calls if call[:3] == ["docker", "rm", "--force"])
    assert remove == ["docker", "rm", "--force", container_id]
    assert "envctl-app-main-backend" not in remove


def test_tokenized_stop_refuses_foreign_launch_token_without_deleting(tmp_path: Path) -> None:
    class ForeignTokenRunner(_Runner):
        def run(self, command, **kwargs):  # noqa: ANN001, ANN202
            argv = [str(part) for part in command]
            if argv[:3] == ["docker", "container", "inspect"]:
                self.calls.append(argv)
                return SimpleNamespace(
                    returncode=0,
                    stdout=f"{'b' * 64}|foreign-token\n",
                    stderr="",
                )
            return super().run(command, **kwargs)

    runner = ForeignTokenRunner()
    runtime, _events = _runtime(tmp_path, runner)

    stopped = DockerServiceRuntime(runtime, runner).stop(
        "envctl-app-main-backend",
        expected_launch_token="expected-token",
    )

    assert not stopped
    assert not any(call[:3] == ["docker", "rm", "--force"] for call in runner.calls)


def test_tokenized_stop_rejects_short_container_id_without_deleting(tmp_path: Path) -> None:
    class ShortIdentityRunner(_Runner):
        def run(self, command, **kwargs):  # noqa: ANN001, ANN202
            argv = [str(part) for part in command]
            if argv[:3] == ["docker", "container", "inspect"]:
                self.calls.append(argv)
                return SimpleNamespace(returncode=0, stdout="abcdef123456|launch-token\n", stderr="")
            return super().run(command, **kwargs)

    runner = ShortIdentityRunner()
    runtime, _events = _runtime(tmp_path, runner)

    stopped = DockerServiceRuntime(runtime, runner).stop(
        "envctl-app-main-backend",
        expected_launch_token="launch-token",
    )

    assert not stopped
    assert not any(call[:3] == ["docker", "rm", "--force"] for call in runner.calls)


def test_launch_transport_and_ownership_probe_failure_preserves_durable_identity(tmp_path: Path) -> None:
    class InspectFailureRunner(_Runner):
        def __init__(self) -> None:
            super().__init__()
            self.container_inspects = 0

        def run(self, command, **kwargs):  # noqa: ANN001, ANN202
            argv = [str(part) for part in command]
            if argv[:3] == ["docker", "container", "inspect"]:
                self.container_inspects += 1
                if self.container_inspects > 1:
                    raise OSError("inspect transport failed")
            if argv[:2] == ["docker", "run"]:
                env_file = Path(argv[argv.index("--env-file") + 1])
                self.env_file_payload = env_file.read_text(encoding="utf-8")
                raise OSError("docker run transport failed")
            return super().run(command, **kwargs)

    runner = InspectFailureRunner()
    runtime, _events = _runtime(tmp_path, runner, env={"ENVCTL_BACKEND_DOCKER_IMAGE": "example/backend:dev"})

    try:
        DockerServiceRuntime(runtime, runner).launch(
            project_name="Main",
            project_root=tmp_path,
            service_name="backend",
            cwd=tmp_path,
            command=[],
            env={"SECRET": "scrub-me"},
            host_port=8123,
            container_port=8123,
            listener_expected=True,
            log_path=str(tmp_path / "backend.log"),
        )
    except DockerServiceLaunchCleanupError as exc:
        assert "inspect transport failed" not in str(exc)
        assert "cleanup could not confirm" in str(exc).lower()
        assert exc.launch.container_id == exc.launch.container_name
        assert exc.launch.container_name.startswith("envctl-app-main-backend")
        assert exc.launch.launch_token
    else:
        raise AssertionError("unconfirmed launch cleanup must preserve durable identity")

    assert list((tmp_path / "runs" / "docker").glob(".docker-env-*")) == []


def test_timeout_accepted_container_is_found_by_token_after_delayed_visibility(tmp_path: Path) -> None:
    class DelayedVisibilityRunner(_Runner):
        def __init__(self) -> None:
            super().__init__()
            self.pending_container: dict[str, str] | None = None
            self.token_queries = 0

        def run(self, command, **kwargs):  # noqa: ANN001, ANN202
            argv = [str(part) for part in command]
            if argv[:2] == ["docker", "run"]:
                self.calls.append(argv)
                env_file = Path(argv[argv.index("--env-file") + 1])
                self.env_file_payload = env_file.read_text(encoding="utf-8")
                labels = [argv[index + 1] for index, value in enumerate(argv) if value == "--label"]
                self.pending_container = {
                    "id": "f" * 64,
                    "name": argv[argv.index("--name") + 1],
                    "scope": next(
                        value.split("=", 1)[1]
                        for value in labels
                        if value.startswith("io.envctl.runtime-scope=")
                    ),
                    "token": next(
                        value.split("=", 1)[1]
                        for value in labels
                        if value.startswith("io.envctl.launch-token=")
                    ),
                }
                return SimpleNamespace(returncode=124, stdout="", stderr="Command timed out")
            if argv[:3] == ["docker", "container", "ls"]:
                self.token_queries += 1
                if self.token_queries == 2:
                    self.launched_container = self.pending_container
                return super().run(command, **kwargs)
            return super().run(command, **kwargs)

    runner = DelayedVisibilityRunner()
    runtime, _events = _runtime(tmp_path, runner, env={"ENVCTL_BACKEND_DOCKER_IMAGE": "example/backend:dev"})

    try:
        DockerServiceRuntime(runtime, runner).launch(
            project_name="Main",
            project_root=tmp_path,
            service_name="backend",
            cwd=tmp_path,
            command=[],
            env={"SECRET": "scrub-me"},
            host_port=8123,
            container_port=8123,
            listener_expected=True,
            log_path=str(tmp_path / "backend.log"),
        )
    except RuntimeError as exc:
        assert "timed out" in str(exc).lower()
        assert not isinstance(exc, DockerServiceLaunchCleanupError)
    else:
        raise AssertionError("a timed-out Docker launch must fail after cleanup")

    assert runner.token_queries >= 2
    assert runner.launched_container is None
    assert ["docker", "rm", "--force", "f" * 64] in runner.calls
    assert list((tmp_path / "runs" / "docker").glob(".docker-env-*")) == []


def test_timeout_without_visible_container_preserves_pending_cleanup_authority(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    class TimeoutRunner(_Runner):
        def run(self, command, **kwargs):  # noqa: ANN001, ANN202
            argv = [str(part) for part in command]
            if argv[:2] == ["docker", "run"]:
                self.calls.append(argv)
                env_file = Path(argv[argv.index("--env-file") + 1])
                self.env_file_payload = env_file.read_text(encoding="utf-8")
                return SimpleNamespace(returncode=124, stdout="", stderr="Command timed out")
            return super().run(command, **kwargs)

    clock = [0.0]
    monkeypatch.setattr(
        "envctl_engine.runtime.docker_service_runtime.time.monotonic",
        lambda: clock[0],
    )
    monkeypatch.setattr(
        "envctl_engine.runtime.docker_service_runtime.time.sleep",
        lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    runner = TimeoutRunner()
    runtime, _events = _runtime(tmp_path, runner, env={"ENVCTL_BACKEND_DOCKER_IMAGE": "example/backend:dev"})
    docker_runtime = DockerServiceRuntime(runtime, runner)

    try:
        docker_runtime.launch(
            project_name="Main",
            project_root=tmp_path,
            service_name="backend",
            cwd=tmp_path,
            command=[],
            env={"SECRET": "scrub-me"},
            host_port=8123,
            container_port=8123,
            listener_expected=True,
            log_path=str(tmp_path / "backend.log"),
        )
    except DockerServiceLaunchCleanupError as exc:
        pending = exc.launch
    else:
        raise AssertionError("an uncertain timed-out launch must retain cleanup authority")

    assert pending.cleanup_pending_since is not None
    assert pending.container_id == pending.container_name
    assert not docker_runtime.stop(
        pending.container_id,
        expected_launch_token=pending.launch_token,
        pending_cleanup_since=pending.cleanup_pending_since,
    )
    assert list((tmp_path / "runs" / "docker").glob(".docker-env-*")) == []


def test_interrupt_after_daemon_accepts_run_removes_tokenized_container(tmp_path: Path) -> None:
    class InterruptAfterCreateRunner(_Runner):
        def run(self, command, **kwargs):  # noqa: ANN001, ANN202
            result = super().run(command, **kwargs)
            if [str(part) for part in command][:2] == ["docker", "run"]:
                raise KeyboardInterrupt
            return result

    runner = InterruptAfterCreateRunner()
    runtime, _events = _runtime(tmp_path, runner, env={"ENVCTL_BACKEND_DOCKER_IMAGE": "example/backend:dev"})

    try:
        DockerServiceRuntime(runtime, runner).launch(
            project_name="Main",
            project_root=tmp_path,
            service_name="backend",
            cwd=tmp_path,
            command=[],
            env={"SECRET": "scrub-me"},
            host_port=8123,
            container_port=8123,
            listener_expected=True,
            log_path=str(tmp_path / "backend.log"),
        )
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("the interrupt must be restored after confirmed cleanup")

    assert runner.launched_container is None
    assert ["docker", "rm", "--force", "d" * 64] in runner.calls
    assert any(call[:3] == ["docker", "container", "ls"] for call in runner.calls)
    assert list((tmp_path / "runs" / "docker").glob(".docker-env-*")) == []


def test_interrupt_during_cleanup_discovery_preserves_pending_authority(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    class TimeoutRunner(_Runner):
        def run(self, command, **kwargs):  # noqa: ANN001, ANN202
            argv = [str(part) for part in command]
            if argv[:2] == ["docker", "run"]:
                self.calls.append(argv)
                return SimpleNamespace(returncode=124, stdout="", stderr="Command timed out")
            return super().run(command, **kwargs)

    monkeypatch.setattr(
        "envctl_engine.runtime.docker_service_runtime.time.sleep",
        lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    runner = TimeoutRunner()
    runtime, _events = _runtime(tmp_path, runner, env={"ENVCTL_BACKEND_DOCKER_IMAGE": "example/backend:dev"})

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
    except DockerServiceLaunchCleanupError as exc:
        pending = exc.launch
    else:
        raise AssertionError("cleanup cancellation must surface durable launch authority")

    assert pending.cleanup_pending_since is not None
    assert pending.launch_token
    assert pending.container_id == pending.container_name


def test_interrupt_during_post_run_identity_probe_cannot_orphan_container(tmp_path: Path) -> None:
    class IdentityProbeInterruptRunner(_Runner):
        def __init__(self) -> None:
            super().__init__()
            self.interrupted = False

        def run(self, command, **kwargs):  # noqa: ANN001, ANN202
            argv = [str(part) for part in command]
            if (
                argv[:3] == ["docker", "container", "inspect"]
                and self.launched_container is not None
                and not self.interrupted
            ):
                self.calls.append(argv)
                self.interrupted = True
                raise KeyboardInterrupt
            return super().run(command, **kwargs)

    runner = IdentityProbeInterruptRunner()
    runtime, _events = _runtime(tmp_path, runner, env={"ENVCTL_BACKEND_DOCKER_IMAGE": "example/backend:dev"})

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
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("the identity-probe interrupt must be restored after cleanup")

    assert runner.launched_container is None
    assert ["docker", "rm", "--force", "d" * 64] in runner.calls


def test_interrupting_best_effort_start_event_cannot_preempt_authority_handoff(tmp_path: Path) -> None:
    runner = _Runner()
    runner.local_images.add("example/backend:dev")
    runtime, _events = _runtime(tmp_path, runner, env={"ENVCTL_BACKEND_DOCKER_IMAGE": "example/backend:dev"})

    def interrupt_start_event(event: str, **_payload: object) -> None:
        if event == "service.container.start":
            raise KeyboardInterrupt

    runtime._emit = interrupt_start_event
    confirmed: list[object] = []
    docker_runtime = DockerServiceRuntime(runtime, runner)

    launch = docker_runtime.launch(
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
        on_confirmed=confirmed.append,
    )

    assert confirmed == [launch]
    assert runner.launched_container is not None
    assert docker_runtime.stop(
        launch.container_id,
        expected_launch_token=launch.launch_token,
    )
    assert runner.launched_container is None


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


def test_stopped_container_preflight_rejects_invalid_running_state_and_missing_owner(tmp_path: Path) -> None:
    cases = (("not-a-bool", True, "invalid running state"), ("false", False, "another envctl runtime scope"))
    for running, include_owner, expected_error in cases:
        class InvalidPreflightRunner(_Runner):
            def run(self, command, **kwargs):  # noqa: ANN001, ANN202
                argv = [str(part) for part in command]
                if argv[:3] == ["docker", "container", "inspect"]:
                    self.calls.append(argv)
                    owner = DockerServiceRuntime(runtime, self)._runtime_scope_identity() if include_owner else ""
                    return SimpleNamespace(returncode=0, stdout=f"{'e' * 64}|{running}|{owner}\n", stderr="")
                return super().run(command, **kwargs)

        runner = InvalidPreflightRunner()
        runtime, _events = _runtime(
            tmp_path,
            runner,
            env={"ENVCTL_BACKEND_DOCKER_IMAGE": "example/backend:dev"},
        )

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
            assert expected_error in str(exc)
        else:
            raise AssertionError("invalid preflight identity must fail closed")

        assert not any(call[:3] == ["docker", "rm", "--force"] for call in runner.calls)
        assert not any(call[:2] == ["docker", "run"] for call in runner.calls)


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
    assert runner.calls[remove_index][-1] == "c" * 64


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


def test_container_env_preserves_browser_contract_urls_and_rewrites_internal_urls(tmp_path: Path) -> None:
    runner = _Runner()
    runtime, _events = _runtime(
        tmp_path,
        runner,
        env={"ENVCTL_BACKEND_CORS_ENV_KEY": "ALLOWED_BROWSER_ORIGINS"},
    )

    projected = DockerServiceRuntime(runtime, runner)._container_env(
        {
            "FRONTEND_BASE_URL": "http://localhost:5173",
            "ENVCTL_SOURCE_FRONTEND_URL": "http://127.0.0.1:5173",
            "CORS_ORIGINS_RAW": "http://localhost:5173,http://127.0.0.1:5173",
            "ALLOWED_BROWSER_ORIGINS": "http://localhost:5173",
            "DATABASE_URL": "postgres://user:pass@localhost:5432/app",
            "REDIS_URL": "redis://127.0.0.1:6379/0",
        }
    )

    assert projected["FRONTEND_BASE_URL"] == "http://localhost:5173"
    assert projected["ENVCTL_SOURCE_FRONTEND_URL"] == "http://127.0.0.1:5173"
    assert projected["CORS_ORIGINS_RAW"] == "http://localhost:5173,http://127.0.0.1:5173"
    assert projected["ALLOWED_BROWSER_ORIGINS"] == "http://localhost:5173"
    assert projected["DATABASE_URL"] == "postgres://user:pass@host.docker.internal:5432/app"
    assert projected["REDIS_URL"] == "redis://host.docker.internal:6379/0"


def test_remote_image_is_pulled_before_exposed_port_detection(tmp_path: Path) -> None:
    runner = _Runner()
    image = "example/frontend:remote"
    runner.remote_exposed_ports[image] = {"80/tcp": {}}
    runtime, _events = _runtime(tmp_path, runner, env={"ENVCTL_FRONTEND_DOCKER_IMAGE": image})

    DockerServiceRuntime(runtime, runner).launch(
        project_name="Main",
        project_root=tmp_path,
        service_name="frontend",
        cwd=tmp_path,
        command=[],
        env={},
        host_port=9100,
        container_port=9100,
        listener_expected=True,
        log_path=str(tmp_path / "frontend.log"),
    )

    pull_index = runner.calls.index(["docker", "pull", image])
    exposed_inspect_index = next(
        index
        for index, call in enumerate(runner.calls)
        if call[:3] == ["docker", "image", "inspect"] and "--format" in call
    )
    run_index = next(index for index, call in enumerate(runner.calls) if call[:2] == ["docker", "run"])
    assert pull_index < exposed_inspect_index < run_index
    assert "127.0.0.1:9100:80" in runner.calls[run_index]


def test_verified_stop_refuses_container_from_another_runtime_scope(tmp_path: Path) -> None:
    runner = _Runner()
    runner.existing_container = (True, "another-runtime")
    runtime, _events = _runtime(tmp_path, runner)

    stopped = terminate_service_record(
        runtime,
        ServiceRecord(
            name="Main Backend",
            type="backend",
            cwd=str(tmp_path),
            runtime_kind="docker",
            container_id="reused-container-id",
        ),
        aggressive=False,
        verify_ownership=True,
    )

    assert not stopped
    assert not any(call[:3] == ["docker", "rm", "--force"] for call in runner.calls)


def test_container_state_drives_health_and_stop(tmp_path: Path) -> None:
    runner = _Runner()
    runtime, events = _runtime(tmp_path, runner)
    runner.existing_container = (
        True,
        DockerServiceRuntime(runtime, runner)._runtime_scope_identity(),
    )
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
    assert ["docker", "rm", "--force", "c" * 64] in runner.calls
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
