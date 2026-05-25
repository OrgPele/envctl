from __future__ import annotations

from collections.abc import Mapping
import json
import time
from pathlib import Path

from ..adapter_base import env_float, port_mismatch_policy, timeout_error
from ..common import (
    ContainerStartResult,
    container_exists,
    container_host_port,
    container_status,
    ensure_docker_image_present,
    is_bind_conflict,
    run_docker,
    run_result_error,
)
from .config import _db_probe_timeout_seconds
from envctl_engine.shared.dependency_compose_assets import (
    DEFAULT_SUPABASE_JWT_SECRET,
    default_supabase_anon_key,
    default_supabase_service_role_key,
)


class NativeSupabaseDatabaseStarter:
    def __init__(
        self,
        *,
        process_runner,
        compose_root: Path,
        compose_project_name: str,
        project_root: Path,
        db_port: int,
        env: Mapping[str, str] | None,
    ) -> None:
        self.process_runner = process_runner
        self.compose_root = compose_root
        self.compose_project_name = compose_project_name
        self.project_root = project_root
        self.db_port = db_port
        self.env = env
        self.container_name = f"{compose_project_name}-supabase-db-1"
        self.create_timeout_seconds = env_float(
            env,
            "ENVCTL_SUPABASE_DB_CREATE_TIMEOUT_SECONDS",
            25.0,
            minimum=5.0,
        )
        self.start_timeout_seconds = _native_db_start_timeout_seconds(env)
        self.listener_wait_timeout = _db_probe_timeout_seconds(env)
        self.volume_name = f"{compose_project_name}_supabase_db_data"
        self.image = (env or {}).get("SUPABASE_DB_IMAGE") or "supabase/postgres:15.1.0.147"

    def start(self) -> ContainerStartResult:
        existing, existing_error = self._container_exists()
        if existing_error:
            return self._failure(existing_error)
        if existing:
            existing_result = self._handle_existing_container()
            if existing_result is not None:
                return existing_result
        image_error = self._ensure_image()
        if image_error is not None:
            return self._failure(image_error)
        create_error = self._create_container()
        if create_error is not None:
            return self._failure(create_error)
        return self._start_and_probe(port=self.db_port, container_reused=False, port_adopted=False)

    def _handle_existing_container(self) -> ContainerStartResult | None:
        mapped_port, port_error = container_host_port(
            self.process_runner,
            container_name=self.container_name,
            container_port=5432,
            cwd=self.project_root,
            env=self.env,
        )
        if port_error:
            return self._failure(port_error)
        status, status_error = container_status(
            self.process_runner,
            container_name=self.container_name,
            cwd=self.project_root,
            env=self.env,
        )
        if status_error:
            return self._failure(status_error)
        if mapped_port is None:
            remove_error = self._remove_existing()
            return self._failure(remove_error) if remove_error is not None else None
        if mapped_port != self.db_port:
            return self._handle_port_mismatch(mapped_port=mapped_port, status=status)
        reused = self._start_and_probe(port=self.db_port, status=status, container_reused=True, port_adopted=False)
        if reused.success:
            return reused
        if reused.error is not None and not reused.error.startswith("probe timeout waiting for readiness"):
            return reused
        remove_error = self._remove_existing()
        if remove_error is not None:
            return self._failure(f"{reused.error}; {remove_error}")
        return None

    def _handle_port_mismatch(self, *, mapped_port: int, status: str) -> ContainerStartResult | None:
        if port_mismatch_policy(self.env) == "adopt_existing":
            adopted = self._start_and_probe(
                port=mapped_port,
                status=status,
                container_reused=True,
                port_adopted=True,
            )
            if adopted.success:
                return adopted
            if adopted.error is not None and not adopted.error.startswith("probe timeout waiting for readiness"):
                return adopted
            remove_error = self._remove_existing()
            return self._failure(f"{adopted.error}; {remove_error}") if remove_error is not None else None
        remove_error = self._remove_existing()
        return self._failure(remove_error) if remove_error is not None else None

    def _start_and_probe(
        self,
        *,
        port: int,
        container_reused: bool,
        port_adopted: bool,
        status: str | None = None,
    ) -> ContainerStartResult:
        if status != "running":
            start_error = self._start_container(port)
            if start_error is not None:
                return self._failure(start_error)
        if bool(self.process_runner.wait_for_port(port, timeout=self.listener_wait_timeout)):
            return ContainerStartResult(
                success=True,
                container_name=self.container_name,
                effective_port=port,
                port_adopted=port_adopted,
                container_reused=container_reused,
            )
        return self._failure(f"probe timeout waiting for readiness on port {port}")

    def _start_container(self, port: int) -> str | None:
        start_result, start_error = run_docker(
            self.process_runner,
            ["start", self.container_name],
            cwd=self.project_root,
            env=self.env,
            timeout=self.start_timeout_seconds,
        )
        recovered = False
        recovery_error = None
        start_timed_out = (start_result is None and timeout_error(start_error)) or (
            start_result is not None and getattr(start_result, "returncode", 1) == 124
        )
        if start_timed_out:
            recovered, recovery_error = _recover_native_db_start_timeout(
                process_runner=self.process_runner,
                container_name=self.container_name,
                port=port,
                cwd=self.project_root,
                env=self.env,
                listener_wait_timeout=self.listener_wait_timeout,
            )
        if (start_result is None or start_timed_out) and not recovered:
            return _native_db_timeout_error_for_retry(
                port=port,
                start_error=start_error
                or (
                    run_result_error(start_result, "failed starting supabase db container")
                    if start_result is not None
                    else None
                ),
                recovery_error=recovery_error,
            )
        if start_result is not None and getattr(start_result, "returncode", 1) != 0:
            return run_result_error(start_result, "failed starting supabase db container")
        return None

    def _ensure_image(self) -> str | None:
        return ensure_docker_image_present(
            self.process_runner,
            image=self.image,
            cwd=self.project_root,
            env=self.env,
            pull_policy_key="ENVCTL_SUPABASE_DB_PULL_POLICY",
            legacy_bool_key="ENVCTL_SUPABASE_DB_PULL_IMAGE",
            inspect_timeout=env_float(self.env, "ENVCTL_SUPABASE_DB_IMAGE_INSPECT_TIMEOUT_SECONDS", 10.0, minimum=1.0),
            pull_timeout=env_float(self.env, "ENVCTL_SUPABASE_DB_PULL_TIMEOUT_SECONDS", 300.0, minimum=30.0),
        )

    def _create_container(self) -> str | None:
        create_result, create_error = run_docker(
            self.process_runner,
            self._create_command(),
            cwd=self.project_root,
            env=self.env,
            timeout=self.create_timeout_seconds,
        )
        if create_result is None:
            recovered = timeout_error(create_error) and _recover_native_db_create_timeout(
                process_runner=self.process_runner,
                container_name=self.container_name,
                cwd=self.project_root,
                env=self.env,
            )
            return None if recovered else create_error
        if getattr(create_result, "returncode", 1) != 0:
            return run_result_error(create_result, "failed creating supabase db container")
        return None

    def _create_command(self) -> list[str]:
        env_values = self.env or {}
        jwt_secret = env_values.get("SUPABASE_JWT_SECRET") or DEFAULT_SUPABASE_JWT_SECRET
        anon_key = env_values.get("SUPABASE_ANON_KEY") or default_supabase_anon_key(secret=jwt_secret)
        service_role_key = env_values.get("SUPABASE_SERVICE_ROLE_KEY") or default_supabase_service_role_key(
            secret=jwt_secret
        )
        return [
            "create",
            "--name",
            self.container_name,
            "-e",
            f"POSTGRES_PASSWORD={env_values.get('SUPABASE_DB_PASSWORD', 'supabase-db-password')}",
            "-e",
            "POSTGRES_DB=postgres",
            "-e",
            "POSTGRES_USER=postgres",
            "-e",
            f"JWT_SECRET={jwt_secret}",
            "-e",
            f"ANON_KEY={anon_key}",
            "-e",
            f"SERVICE_ROLE_KEY={service_role_key}",
            "-p",
            f"{self.db_port}:5432",
            "-v",
            f"{self.volume_name}:/var/lib/postgresql/data",
            "-v",
            (
                f"{self.compose_root / 'init' / '01-create-n8n-db.sql'}:"
                "/docker-entrypoint-initdb.d/01-create-n8n-db.sql:ro"
            ),
            "-v",
            (
                f"{self.compose_root / 'init' / '02-bootstrap-gotrue-auth.sql'}:"
                "/docker-entrypoint-initdb.d/02-bootstrap-gotrue-auth.sql:ro"
            ),
            self.image,
        ]

    def _container_exists(self) -> tuple[bool, str | None]:
        return container_exists(
            self.process_runner,
            container_name=self.container_name,
            cwd=self.project_root,
            env=self.env,
        )

    def _remove_existing(self) -> str | None:
        return _force_remove_native_db_container(
            process_runner=self.process_runner,
            container_name=self.container_name,
            cwd=self.project_root,
            env=self.env,
        )

    def _failure(self, error: str | None) -> ContainerStartResult:
        return ContainerStartResult(success=False, container_name=self.container_name, error=error)


def _start_supabase_db_native(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    project_root: Path,
    db_port: int,
    env: Mapping[str, str] | None,
) -> ContainerStartResult:
    return NativeSupabaseDatabaseStarter(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        project_root=project_root,
        db_port=db_port,
        env=env,
    ).start()


def _recover_native_db_start_timeout(
    *,
    process_runner,
    container_name: str,
    port: int,
    cwd: Path,
    env: Mapping[str, str] | None,
    listener_wait_timeout: float,
) -> tuple[bool, str | None]:
    recovery_deadline = time.monotonic() + _native_db_start_recovery_timeout_seconds(env)
    published_port: int | None = None
    while time.monotonic() < recovery_deadline:
        status, status_error = container_status(
            process_runner,
            container_name=container_name,
            cwd=cwd,
            env=env,
        )
        if status_error is None and status == "running":
            published_port = _native_db_published_port(
                process_runner,
                container_name=container_name,
                cwd=cwd,
                env=env,
            )
            if published_port is not None and bool(
                process_runner.wait_for_port(published_port, timeout=min(listener_wait_timeout, 1.0))
            ):
                return True, None
        state_error = _native_db_state_error(
            process_runner,
            container_name=container_name,
            cwd=cwd,
            env=env,
        )
        if is_bind_conflict(state_error):
            return False, state_error
        sleeper = getattr(process_runner, "sleep", None)
        if callable(sleeper):
            sleeper(1.0)
        else:
            time.sleep(1.0)
    status, status_error = container_status(
        process_runner,
        container_name=container_name,
        cwd=cwd,
        env=env,
    )
    if status_error is None and status == "running":
        published_port = _native_db_published_port(
            process_runner,
            container_name=container_name,
            cwd=cwd,
            env=env,
        )
        if published_port is None:
            return False, f"published host port missing for port {port}"
        if bool(process_runner.wait_for_port(published_port, timeout=min(listener_wait_timeout, 1.0))):
            return True, None
        return False, f"probe timeout waiting for readiness on port {published_port}"
    state_error = _native_db_state_error(
        process_runner,
        container_name=container_name,
        cwd=cwd,
        env=env,
    )
    if is_bind_conflict(state_error):
        return False, state_error
    return False, None


def _recover_native_db_create_timeout(
    *,
    process_runner,
    container_name: str,
    cwd: Path,
    env: Mapping[str, str] | None,
) -> bool:
    for _ in range(5):
        exists, exists_error = container_exists(
            process_runner,
            container_name=container_name,
            cwd=cwd,
            env=env,
        )
        if exists_error is None and exists:
            return True
        sleeper = getattr(process_runner, "sleep", None)
        if callable(sleeper):
            sleeper(1.0)
        else:
            time.sleep(1.0)
    return False


def _native_db_start_timeout_seconds(env: Mapping[str, str] | None) -> float:
    parsed = env_float(env, "ENVCTL_SUPABASE_DB_START_TIMEOUT_SECONDS", 8.0, minimum=1.0)
    if parsed <= 0:
        return 8.0
    return parsed


def _native_db_start_recovery_timeout_seconds(env: Mapping[str, str] | None) -> float:
    parsed = env_float(env, "ENVCTL_SUPABASE_DB_START_RECOVERY_TIMEOUT_SECONDS", 18.0, minimum=1.0)
    if parsed <= 0:
        return 18.0
    return parsed


def _native_db_state_error(
    process_runner,
    *,
    container_name: str,
    cwd: Path,
    env: Mapping[str, str] | None,
) -> str | None:
    result, error = run_docker(
        process_runner,
        ["inspect", "-f", "{{.State.Error}}", container_name],
        cwd=cwd,
        env=env,
        timeout=10.0,
    )
    if result is None or getattr(result, "returncode", 1) != 0:
        return error
    value = str(getattr(result, "stdout", "") or "").strip()
    return value or None


def _native_db_published_port(
    process_runner,
    *,
    container_name: str,
    cwd: Path,
    env: Mapping[str, str] | None,
) -> int | None:
    result, error = run_docker(
        process_runner,
        ["inspect", "-f", "{{json .NetworkSettings.Ports}}", container_name],
        cwd=cwd,
        env=env,
        timeout=10.0,
    )
    if result is None or getattr(result, "returncode", 1) != 0:
        return None
    payload = str(getattr(result, "stdout", "") or "").strip()
    if not payload:
        return None
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    binding = decoded.get("5432/tcp")
    if not isinstance(binding, list) or not binding:
        return None
    first = binding[0]
    if not isinstance(first, dict):
        return None
    raw_port = str(first.get("HostPort", "")).strip()
    if not raw_port:
        return None
    try:
        return int(raw_port)
    except ValueError:
        return None


def _native_db_timeout_error_for_retry(
    *,
    port: int,
    start_error: str | None,
    recovery_error: str | None,
) -> str:
    if recovery_error:
        return recovery_error
    if timeout_error(start_error):
        return f"host port binding incomplete for port {port} after docker start timeout"
    return start_error or "failed starting supabase db container"


def _force_remove_native_db_container(
    *,
    process_runner,
    container_name: str,
    cwd: Path,
    env: Mapping[str, str] | None,
) -> str | None:
    rm_result, rm_error = run_docker(
        process_runner,
        ["rm", "-f", container_name],
        cwd=cwd,
        env=env,
        timeout=10.0,
    )
    if rm_result is None:
        return rm_error
    if getattr(rm_result, "returncode", 1) != 0:
        return run_result_error(rm_result, "failed removing supabase db container")
    return None
