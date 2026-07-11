from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from envctl_engine.shared.parsing import parse_bool


_HOST_ENV_KEYS = {
    "HOME",
    "OLDPWD",
    "PATH",
    "PWD",
    "PYTHONHOME",
    "PYTHONPATH",
    "SHELL",
    "SHLVL",
    "TMPDIR",
    "VIRTUAL_ENV",
    "VIRTUAL_ENV_PROMPT",
    "ZDOTDIR",
    "_",
}
_PUBLIC_ENV_PREFIXES = ("VITE_", "NEXT_PUBLIC_", "PUBLIC_")
_PUBLIC_ENV_KEYS = {
    "BACKEND_CORS_ORIGINS",
    "CORS_ORIGINS",
    "FRONTEND_URL",
    "PUBLIC_URL",
}
_DOCKER_INFO_LOCK = threading.Lock()
_RUNTIME_SCOPE_LABEL = "io.envctl.runtime-scope"


def _docker_name(value: str, *, limit: int) -> str:
    normalized = re.sub(r"[^a-z0-9_.-]+", "-", value.strip().lower()).strip("-._")
    return (normalized or "service")[:limit]


def docker_service_container_name(*, project_name: str, project_root: Path, service_name: str) -> str:
    digest = hashlib.sha256(str(project_root.resolve()).encode()).hexdigest()[:10]
    prefix = _docker_name(f"envctl-app-{project_name}-{service_name}", limit=52)
    return f"{prefix}-{digest}"


@dataclass(frozen=True, slots=True)
class DockerServiceLaunch:
    container_id: str
    container_name: str
    image: str
    log_path: str


def docker_service_mode_enabled(runtime: Any) -> bool:
    env = getattr(runtime, "env", {})
    return parse_bool(str(env.get("DOCKER_MODE", "")), False)


def docker_service_uses_image_command(
    runtime: Any,
    service_name: str,
    *,
    docker_mode: bool | None = None,
) -> bool:
    if not (docker_service_mode_enabled(runtime) if docker_mode is None else docker_mode):
        return False
    env = getattr(runtime, "env", {})
    raw = getattr(getattr(runtime, "config", None), "raw", {})
    suffix = re.sub(r"[^A-Z0-9]+", "_", service_name.upper()).strip("_") or "SERVICE"

    def setting(name: str) -> str:
        for key in (f"ENVCTL_SERVICE_{suffix}_{name}", f"ENVCTL_{suffix}_{name}", f"ENVCTL_{name}"):
            value = str(env.get(key) or raw.get(key) or "").strip()
            if value:
                return value
        return ""

    if setting("DOCKER_COMMAND"):
        return False
    return (setting("DOCKER_COMMAND_MODE") or "image").lower() in {"image", "default"}


def state_uses_docker_services(state: object) -> bool:
    metadata = getattr(state, "metadata", {})
    if isinstance(metadata, dict) and str(metadata.get("application_runtime", "")).lower() == "docker":
        return True
    services = getattr(state, "services", {})
    return isinstance(services, dict) and any(
        str(getattr(service, "runtime_kind", "process") or "process").lower() == "docker"
        for service in services.values()
    )


class DockerServiceRuntime:
    """Build and run application services as managed Docker containers."""

    def __init__(self, runtime: Any, process_runtime: Any, *, refresh_cache: bool = False) -> None:
        self.runtime = runtime
        self.process_runtime = process_runtime
        self.refresh_cache = refresh_cache

    def launch(
        self,
        *,
        project_name: str,
        project_root: Path,
        service_name: str,
        cwd: Path,
        command: Sequence[str],
        env: Mapping[str, str],
        host_port: int,
        container_port: int,
        listener_expected: bool,
        log_path: str,
    ) -> DockerServiceLaunch:
        self._require_docker()
        image = self._resolve_image(
            project_root=project_root,
            service_name=service_name,
            cwd=cwd,
            build_env=env,
        )
        container_name = self._container_name(
            project_name=project_name,
            project_root=project_root,
            service_name=service_name,
        )
        self._prepare_container_name(container_name)
        effective_container_port = self._container_port(service_name, container_port, image=image)
        container_env = self._container_env(env)
        if listener_expected and effective_container_port > 0:
            container_env["PORT"] = str(effective_container_port)
        env_file = self._write_env_file(
            project_name=project_name,
            service_name=service_name,
            values=container_env,
        )
        try:
            docker_command = [
                "docker",
                "run",
                "--detach",
                "--name",
                container_name,
                "--label",
                "io.envctl.managed=true",
                "--label",
                f"io.envctl.project={project_name}",
                "--label",
                f"io.envctl.service={service_name}",
                "--label",
                f"{_RUNTIME_SCOPE_LABEL}={self._runtime_scope_identity()}",
                "--add-host",
                "host.docker.internal:host-gateway",
                "--env-file",
                str(env_file),
            ]
            if listener_expected and host_port > 0:
                docker_command.extend(["--publish", f"127.0.0.1:{host_port}:{effective_container_port}"])
            workdir = self._setting(service_name, "DOCKER_WORKDIR")
            if workdir:
                docker_command.extend(["--workdir", workdir])
            docker_command.append(image)
            docker_command.extend(
                self._container_command(
                    service_name,
                    command,
                    project_root=project_root,
                    cwd=cwd,
                    host_port=host_port,
                    container_port=effective_container_port,
                )
            )
            result = self.process_runtime.run(
                docker_command,
                cwd=project_root,
                env={**os.environ, "DOCKER_BUILDKIT": "1"},
                timeout=self._timeout("ENVCTL_DOCKER_RUN_TIMEOUT_SECONDS", 120.0),
            )
        finally:
            env_file.unlink(missing_ok=True)
        if result.returncode != 0:
            detail = str(result.stderr or result.stdout or "docker run failed").strip()
            raise RuntimeError(detail)
        container_id = str(result.stdout or "").strip().splitlines()[-1]
        if not container_id:
            raise RuntimeError(f"docker run returned no container id for {project_name} {service_name}")
        launch = DockerServiceLaunch(
            container_id=container_id,
            container_name=container_name,
            image=image,
            log_path=log_path,
        )
        self.runtime._emit(
            "service.container.start",
            project=project_name,
            service=service_name,
            container_name=container_name,
            image=image,
            port=host_port if listener_expected else None,
        )
        return launch

    def wait_until_ready(self, launch: DockerServiceLaunch, *, port: int, listener_expected: bool) -> bool:
        if not self.container_running(launch.container_id):
            self.snapshot_logs(launch.container_id, launch.log_path, tail=200)
            return False
        if not listener_expected:
            return True
        ready = bool(
            self.process_runtime.wait_for_port(
                port,
                timeout=self._timeout("ENVCTL_SERVICE_LISTENER_TIMEOUT_SECONDS", 30.0),
            )
        )
        if not ready:
            self.snapshot_logs(launch.container_id, launch.log_path, tail=200)
        return ready

    def snapshot_logs(self, container: str, log_path: str, *, tail: int) -> bool:
        command = ["docker", "logs"]
        since_marker = Path(f"{log_path}.docker-since")
        if since_marker.is_file():
            try:
                command.extend(["--since", str(since_marker.stat().st_mtime)])
            except OSError:
                pass
        command.extend(["--tail", str(max(tail, 0)), container])
        result = self.process_runtime.run(
            command,
            timeout=30.0,
        )
        if result.returncode != 0:
            return False
        stdout = str(result.stdout or "")
        stderr = str(result.stderr or "")
        content = stdout + (("\n" if stdout and stderr and not stdout.endswith("\n") else "") + stderr)
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return True

    def follow_logs(self, container: str, log_path: str) -> int | None:
        process = self.process_runtime.start_background(
            ["docker", "logs", "--follow", "--since", "0s", container],
            stdout_path=log_path,
            stderr_path=log_path,
        )
        pid = getattr(process, "pid", None)
        return pid if isinstance(pid, int) and pid > 0 else None

    def stop(
        self,
        container: str,
        *,
        remove: bool = True,
        verify_ownership: bool = False,
    ) -> bool:
        if not container:
            return True
        if verify_ownership and not self._container_owned_by_runtime_scope(container):
            return False
        command = ["docker", "rm", "--force", container] if remove else ["docker", "stop", container]
        result = self.process_runtime.run(command, timeout=30.0)
        return result.returncode == 0 or "No such container" in str(result.stderr or "")

    def _container_owned_by_runtime_scope(self, container: str) -> bool:
        inspected = self.process_runtime.run(
            [
                "docker",
                "container",
                "inspect",
                "--format",
                f"{{{{index .Config.Labels {json.dumps(_RUNTIME_SCOPE_LABEL)}}}}}",
                container,
            ],
            timeout=10.0,
        )
        if inspected.returncode != 0:
            return "No such" in str(inspected.stderr or "")
        return str(inspected.stdout or "").strip() == self._runtime_scope_identity()

    def container_running(self, container: str) -> bool:
        if not container:
            return False
        result = self.process_runtime.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", container],
            timeout=10.0,
        )
        return result.returncode == 0 and str(result.stdout or "").strip().lower() == "true"

    def _resolve_image(
        self,
        *,
        project_root: Path,
        service_name: str,
        cwd: Path,
        build_env: Mapping[str, str],
    ) -> str:
        configured_image = self._setting(service_name, "DOCKER_IMAGE")
        dockerfile_setting = self._setting(service_name, "DOCKERFILE")
        dockerfile = self._resolve_path(dockerfile_setting, project_root) if dockerfile_setting else None
        if dockerfile is None and not configured_image:
            dockerfile = next(
                (path for path in (cwd / "Dockerfile", project_root / "Dockerfile") if path.is_file()),
                None,
            )
        if dockerfile is None:
            if configured_image:
                return configured_image
            raise RuntimeError(
                f"Docker mode needs ENVCTL_{self._service_key(service_name)}_DOCKER_IMAGE, "
                "ENVCTL_DOCKER_IMAGE, or a Dockerfile"
            )
        if not dockerfile.is_file():
            raise RuntimeError(f"Configured Dockerfile does not exist: {dockerfile}")
        context_setting = self._setting(service_name, "DOCKER_CONTEXT")
        context = self._resolve_path(context_setting, project_root) if context_setting else dockerfile.parent
        if context is None or not context.is_dir():
            raise RuntimeError(f"Configured Docker build context does not exist: {context}")
        image = configured_image or self._generated_image_name(project_root, service_name)
        self._build_image(
            image=image,
            dockerfile=dockerfile,
            context=context,
            service_name=service_name,
            build_env=build_env,
        )
        return image

    def _build_image(
        self,
        *,
        image: str,
        dockerfile: Path,
        context: Path,
        service_name: str,
        build_env: Mapping[str, str],
    ) -> None:
        policy = (self._setting(service_name, "DOCKER_BUILD_POLICY") or "cached").strip().lower()
        if policy in {"never", "image", "existing"}:
            if not self._image_exists(image):
                raise RuntimeError(f"Docker image {image!r} does not exist and build policy is {policy!r}")
            return
        if policy == "missing" and self._image_exists(image):
            self.runtime._emit("service.container.build", service=service_name, image=image, cache="image")
            return
        command = ["docker", "build", "--file", str(dockerfile), "--tag", image]
        if self.refresh_cache or parse_bool(
            str(getattr(self.runtime, "env", {}).get("RUN_SH_REFRESH_CACHE", "")),
            False,
        ):
            command.append("--pull")
        target = self._setting(service_name, "DOCKER_TARGET")
        if target:
            command.extend(["--target", target])
        build_arguments = self._docker_build_arguments(service_name, build_env)
        for key in sorted(build_arguments):
            command.extend(["--build-arg", key])
        command.append(str(context))
        self.runtime._emit(
            "service.container.build",
            service=service_name,
            image=image,
            dockerfile=str(dockerfile),
            context=str(context),
            cache="docker_layer_cache",
        )
        result = self.process_runtime.run(
            command,
            cwd=context,
            env={**os.environ, **build_arguments, "DOCKER_BUILDKIT": "1"},
            timeout=self._timeout("ENVCTL_DOCKER_BUILD_TIMEOUT_SECONDS", 900.0),
        )
        if result.returncode != 0:
            detail = str(result.stderr or result.stdout or "docker build failed").strip()
            raise RuntimeError(detail)

    def _image_exists(self, image: str) -> bool:
        return self.process_runtime.run(["docker", "image", "inspect", image], timeout=10.0).returncode == 0

    def _prepare_container_name(self, name: str) -> None:
        inspect = self.process_runtime.run(
            [
                "docker",
                "container",
                "inspect",
                "--format",
                f"{{{{.State.Running}}}}|{{{{index .Config.Labels {json.dumps(_RUNTIME_SCOPE_LABEL)}}}}}",
                name,
            ],
            timeout=10.0,
        )
        if inspect.returncode != 0:
            if "No such" in str(inspect.stderr or "") or "not found" in str(inspect.stderr or "").lower():
                return
            raise RuntimeError(str(inspect.stderr or inspect.stdout or f"failed to inspect {name}").strip())
        running_text, _separator, owner = str(inspect.stdout or "").strip().partition("|")
        expected_owner = self._runtime_scope_identity()
        if owner and owner != expected_owner:
            raise RuntimeError(
                f"Docker container {name!r} is managed by another envctl runtime scope; "
                "stop it from that runtime before starting this one"
            )
        if running_text.lower() == "true":
            raise RuntimeError(
                f"Docker container {name!r} is already running but was not resumed from current state; "
                "run envctl stop for this project before starting it again"
            )
        self._remove_container(name)

    def _remove_container(self, name: str) -> None:
        result = self.process_runtime.run(["docker", "rm", "--force", name], timeout=30.0)
        if result.returncode != 0 and "No such container" not in str(result.stderr or ""):
            raise RuntimeError(str(result.stderr or result.stdout or f"failed to remove {name}").strip())

    def _runtime_scope_identity(self) -> str:
        config = getattr(self.runtime, "config", None)
        scope = getattr(config, "runtime_scope_dir", None)
        if scope is None:
            scope = Path(self.runtime._run_dir_path("docker-scope")).parent
        return hashlib.sha256(str(Path(scope).resolve()).encode()).hexdigest()[:16]

    def _require_docker(self) -> None:
        command_exists = getattr(self.runtime, "_command_exists", None)
        if callable(command_exists) and not command_exists("docker"):
            raise RuntimeError("Docker mode requires the docker CLI")
        with _DOCKER_INFO_LOCK:
            if bool(getattr(self.runtime, "_docker_application_daemon_checked", False)):
                return
            result = self.process_runtime.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                timeout=15.0,
            )
            if result.returncode != 0:
                raise RuntimeError(str(result.stderr or "Docker daemon is unavailable").strip())
            setattr(self.runtime, "_docker_application_daemon_checked", True)

    def _container_command(
        self,
        service_name: str,
        command: Sequence[str],
        *,
        project_root: Path,
        cwd: Path,
        host_port: int,
        container_port: int,
    ) -> list[str]:
        override = self._setting(service_name, "DOCKER_COMMAND")
        command_mode = (self._setting(service_name, "DOCKER_COMMAND_MODE") or "image").lower()
        if override:
            resolved = shlex.split(override)
        elif command_mode in {"service", "envctl", "host"}:
            resolved = [str(part) for part in command]
        elif command_mode in {"image", "default"}:
            return []
        else:
            raise RuntimeError(
                f"Invalid Docker command mode for {service_name}: {command_mode!r}; expected image or service"
            )
        if not resolved:
            return []
        executable = Path(resolved[0])
        if executable.is_absolute():
            try:
                resolved[0] = str(executable.relative_to(cwd))
            except ValueError:
                try:
                    resolved[0] = str(executable.relative_to(project_root))
                except ValueError:
                    pass
        normalized: list[str] = []
        for part in resolved:
            if part in {"127.0.0.1", "localhost"}:
                normalized.append("0.0.0.0")
                continue
            if host_port > 0 and container_port > 0:
                if part == str(host_port):
                    normalized.append(str(container_port))
                    continue
                part = re.sub(
                    rf"^(--port=){re.escape(str(host_port))}$",
                    rf"\g<1>{container_port}",
                    part,
                )
            part = re.sub(r"^(--host=)(localhost|127\.0\.0\.1)$", r"\g<1>0.0.0.0", part)
            normalized.append(part)
        return normalized

    def _docker_build_arguments(
        self,
        service_name: str,
        build_env: Mapping[str, str],
    ) -> dict[str, str]:
        arguments = {
            str(key): str(value)
            for key, value in build_env.items()
            if str(key).startswith(_PUBLIC_ENV_PREFIXES)
        }
        configured = self._setting(service_name, "DOCKER_BUILD_ARGS")
        for token in configured.split(","):
            item = token.strip()
            if not item:
                continue
            key, separator, configured_value = item.partition("=")
            key = key.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise RuntimeError(f"Invalid Docker build argument name: {key!r}")
            if separator:
                arguments[key] = configured_value
            elif key in build_env:
                arguments[key] = str(build_env[key])
            else:
                raise RuntimeError(f"Docker build argument {key!r} is not present in the service environment")
        return arguments

    def _container_env(self, values: Mapping[str, str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for raw_key, raw_value in values.items():
            key = str(raw_key)
            if key in _HOST_ENV_KEYS or key.startswith("TERM_") or key.startswith("LC_"):
                continue
            value = str(raw_value)
            if key in {"HOST", "BIND_HOST", "LISTEN_HOST", "SERVER_HOST"} and value in {
                "localhost",
                "127.0.0.1",
            }:
                result[key] = "0.0.0.0"
                continue
            if key not in _PUBLIC_ENV_KEYS and not key.startswith(_PUBLIC_ENV_PREFIXES):
                value = re.sub(
                    r"(://(?:[^/@\s]+@)?)(localhost|127\.0\.0\.1)(?=[:/]|$)",
                    r"\1host.docker.internal",
                    value,
                )
                if key.endswith("_HOST") and value in {"localhost", "127.0.0.1"}:
                    value = "host.docker.internal"
            result[key] = value
        result["ENVCTL_CONTAINER_RUNTIME"] = "docker"
        result["ENVCTL_HOST_GATEWAY"] = "host.docker.internal"
        return result

    def _write_env_file(self, *, project_name: str, service_name: str, values: Mapping[str, str]) -> Path:
        run_dir = Path(self.runtime._run_dir_path(getattr(self.runtime, "_active_run_id", None) or "docker"))
        run_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(f"{project_name}\0{service_name}".encode()).hexdigest()[:12]
        path = run_dir / f".docker-env-{digest}"
        lines = [f"{key}={str(value).replace(chr(10), '')}" for key, value in sorted(values.items())]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        path.chmod(0o600)
        return path

    def _setting(self, service_name: str, suffix: str) -> str:
        env = getattr(self.runtime, "env", {})
        raw = getattr(getattr(self.runtime, "config", None), "raw", {})
        service_key = f"ENVCTL_{self._service_key(service_name)}_{suffix}"
        additional_service_key = f"ENVCTL_SERVICE_{self._service_key(service_name)}_{suffix}"
        global_key = f"ENVCTL_{suffix}"
        for key in (additional_service_key, service_key, global_key):
            value = str(env.get(key) or raw.get(key) or "").strip()
            if value:
                return value
        return ""

    def _container_port(self, service_name: str, host_port: int, *, image: str) -> int:
        value = self._setting(service_name, "DOCKER_PORT")
        if not value:
            self._ensure_image_available(image)
            exposed = self._single_exposed_port(image)
            return exposed if exposed is not None else host_port
        try:
            port = int(value)
        except ValueError as exc:
            raise RuntimeError(f"Invalid Docker container port for {service_name}: {value!r}") from exc
        if port <= 0 or port > 65535:
            raise RuntimeError(f"Invalid Docker container port for {service_name}: {value!r}")
        return port

    def _ensure_image_available(self, image: str) -> None:
        if self._image_exists(image):
            return
        self.runtime._emit("service.container.pull", image=image)
        pulled = self.process_runtime.run(
            ["docker", "pull", image],
            timeout=self._timeout("ENVCTL_DOCKER_PULL_TIMEOUT_SECONDS", 300.0),
        )
        if pulled.returncode != 0:
            detail = str(pulled.stderr or pulled.stdout or f"failed to pull Docker image {image}").strip()
            raise RuntimeError(detail)

    def _single_exposed_port(self, image: str) -> int | None:
        result = self.process_runtime.run(
            ["docker", "image", "inspect", "--format", "{{json .Config.ExposedPorts}}", image],
            timeout=10.0,
        )
        if result.returncode != 0:
            return None
        try:
            payload = json.loads(str(result.stdout or "null"))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict) or len(payload) != 1:
            return None
        raw_port = str(next(iter(payload))).partition("/")[0]
        try:
            port = int(raw_port)
        except ValueError:
            return None
        return port if 0 < port <= 65535 else None

    def _container_name(self, *, project_name: str, project_root: Path, service_name: str) -> str:
        return docker_service_container_name(
            project_name=project_name,
            project_root=project_root,
            service_name=service_name,
        )

    def _generated_image_name(self, project_root: Path, service_name: str) -> str:
        identity = self._repository_identity(project_root)
        digest = hashlib.sha256(str(project_root.resolve()).encode()).hexdigest()[:10]
        repo = _docker_name(identity.name, limit=32)
        service = _docker_name(service_name, limit=24)
        return f"envctl/{repo}-{service}:{digest}"

    @staticmethod
    def _repository_identity(project_root: Path) -> Path:
        dot_git = project_root / ".git"
        if dot_git.is_file():
            try:
                gitdir = dot_git.read_text(encoding="utf-8").strip().removeprefix("gitdir:").strip()
                resolved = (project_root / gitdir).resolve()
                if resolved.parent.name == "worktrees":
                    return resolved.parent.parent.parent
            except OSError:
                pass
        return project_root.resolve()

    @staticmethod
    def _service_key(service_name: str) -> str:
        return re.sub(r"[^A-Z0-9]+", "_", service_name.upper()).strip("_") or "SERVICE"

    @staticmethod
    def _resolve_path(value: str, project_root: Path) -> Path | None:
        if not value:
            return None
        path = Path(value).expanduser()
        return path.resolve() if path.is_absolute() else (project_root / path).resolve()

    def _timeout(self, key: str, default: float) -> float:
        value = str(getattr(self.runtime, "env", {}).get(key, "") or "").strip()
        try:
            return max(float(value), 1.0) if value else default
        except ValueError:
            return default


def refresh_container_log_snapshots(
    runtime: Any,
    state: object,
    *,
    tail: int,
    follow: bool,
) -> list[int]:
    docker_services = [
        service
        for service in getattr(state, "services", {}).values()
        if str(getattr(service, "runtime_kind", "process") or "process").lower() == "docker"
    ]
    if not docker_services:
        return []
    process_runner = getattr(runtime, "process_runner", None)
    if process_runner is None:
        return []
    docker_runtime = DockerServiceRuntime(runtime, process_runner)
    follower_pids: list[int] = []
    for service in docker_services:
        container = str(
            getattr(service, "container_id", "") or getattr(service, "container_name", "") or ""
        ).strip()
        log_path = str(getattr(service, "log_path", "") or "").strip()
        if not container or not log_path:
            continue
        docker_runtime.snapshot_logs(container, log_path, tail=tail)
        if follow:
            pid = docker_runtime.follow_logs(container, log_path)
            if pid is not None:
                follower_pids.append(pid)
    return follower_pids


def stop_container_log_followers(runtime: Any, pids: Sequence[int]) -> None:
    for pid in pids:
        try:
            runtime.process_runner.terminate_process_group(pid, term_timeout=1.0, kill_timeout=1.0)
        except Exception:  # noqa: BLE001
            continue
