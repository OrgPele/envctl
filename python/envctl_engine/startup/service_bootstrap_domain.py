from __future__ import annotations

# pyright: reportUnusedFunction=false

import time
from pathlib import Path
from typing import Any, Mapping

from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.protocols import ProjectContextLike
from envctl_engine.startup.service_backend_migration_support import (
    _backend_async_driver_mismatch_error as _backend_async_driver_mismatch_error,
    _backend_bootstrap_strict as _backend_bootstrap_strict,
    _backend_env_warning_line as _backend_env_warning_line,
    _backend_has_migrations as _backend_has_migrations,
    _backend_migration_retry_env_for_async_driver_mismatch as _backend_migration_retry_env_for_async_driver_mismatch,
    _backend_migrations_enabled as _backend_migrations_enabled,
    _backend_missing_revision_id as _backend_missing_revision_id,
    _bootstrap_failure_suggestion as _bootstrap_failure_suggestion,
    _emit_bootstrap_phase as _emit_bootstrap_phase,
    _pyproject_uses_poetry as _pyproject_uses_poetry,
    _rewrite_database_url_to_asyncpg as _rewrite_database_url_to_asyncpg,
    _run_backend_bootstrap_command as _run_backend_bootstrap_command,
    _run_backend_migration_step as _run_backend_migration_step,
)
from envctl_engine.startup.service_frontend_bootstrap_support import (
    _frontend_dependency_install_required as _frontend_dependency_install_required,
    _frontend_dependency_installed as _frontend_dependency_installed,
    _frontend_install_commands as _frontend_install_commands,
    _frontend_missing_direct_dependency as _frontend_missing_direct_dependency,
    _prepare_frontend_runtime as _prepare_frontend_runtime,
    _run_frontend_bootstrap_command as _run_frontend_bootstrap_command,
)
from envctl_engine.startup.service_env_support import (
    _BACKEND_SENSITIVE_ENV_KEYS as _BACKEND_SENSITIVE_ENV_KEYS,
    _BackendEnvContract as _BackendEnvContract,
    _emit_backend_env_resolved as _emit_backend_env_resolved,
    _env_assignment_key as _env_assignment_key,
    _EnvFileResolution as _EnvFileResolution,
    _normalize_projected_backend_env as _normalize_projected_backend_env,
    _override_env_path as _override_env_path,
    _read_env_file_safe as _read_env_file_safe,
    _resolve_backend_env_contract as _resolve_backend_env_contract,
    _resolve_backend_env_file as _resolve_backend_env_file,
    _resolve_backend_env_file_resolution as _resolve_backend_env_file_resolution,
    _resolve_env_file_resolution as _resolve_env_file_resolution,
    _resolve_frontend_env_file as _resolve_frontend_env_file,
    _resolve_frontend_env_file_resolution as _resolve_frontend_env_file_resolution,
    _resolve_override_env_path_details as _resolve_override_env_path_details,
    _scrub_backend_sensitive_env as _scrub_backend_sensitive_env,
    _service_env_from_file as _service_env_from_file,
    _skip_local_db_env as _skip_local_db_env,
    _sync_backend_env_file as _sync_backend_env_file,
    _sync_frontend_local_env_file as _sync_frontend_local_env_file,
)
from envctl_engine.startup.service_runtime_state_support import (
    _backend_dependency_file_mentions as _backend_dependency_file_mentions,
    _backend_dependency_fingerprint as _backend_dependency_fingerprint,
    _backend_dependency_install_required as _backend_dependency_install_required,
    _backend_runtime_fingerprint as _backend_runtime_fingerprint,
    _backend_runtime_prep_required as _backend_runtime_prep_required,
    _backend_runtime_prep_state_path as _backend_runtime_prep_state_path,
    _backend_runtime_probe_modules as _backend_runtime_probe_modules,
    _backend_bootstrap_state_path as _backend_bootstrap_state_path,
    _frontend_runtime_prep_required as _frontend_runtime_prep_required,
    _frontend_runtime_prep_state_path as _frontend_runtime_prep_state_path,
    _poetry_backend_environment_ready as _poetry_backend_environment_ready,
    _read_backend_bootstrap_state as _read_backend_bootstrap_state,
    _read_backend_runtime_prep_state as _read_backend_runtime_prep_state,
    _read_frontend_runtime_prep_state as _read_frontend_runtime_prep_state,
    _write_backend_bootstrap_state as _write_backend_bootstrap_state,
    _write_backend_runtime_prep_state as _write_backend_runtime_prep_state,
    _write_frontend_runtime_prep_state as _write_frontend_runtime_prep_state,
)

_STATE_DIRNAME = ".envctl-state"


def configured_service_types_for_mode(config: Any, runtime_mode: str) -> list[str]:
    if hasattr(config, "profile_for_mode"):
        profile = config.profile_for_mode(runtime_mode)
        configured: list[str] = []
        if bool(getattr(profile, "backend_enable", False)):
            configured.append("backend")
        if bool(getattr(profile, "frontend_enable", False)):
            configured.append("frontend")
        return configured
    return [
        service_name
        for service_name, enabled in (
            ("backend", config.service_enabled_for_mode(runtime_mode, "backend")),
            ("frontend", config.service_enabled_for_mode(runtime_mode, "frontend")),
        )
        if enabled
    ]


def _prepare_backend_runtime(
    self: Any,
    *,
    context: ProjectContextLike,
    backend_cwd: Path,
    backend_log_path: str,
    project_env_base: Mapping[str, str],
    route: Route | None,
    backend_env_file: Path | None,
    backend_env_is_default: bool,
) -> None:
    prepare_started = time.monotonic()
    requirements_file = backend_cwd / "requirements.txt"
    pyproject_file = backend_cwd / "pyproject.toml"
    manager = "poetry" if pyproject_file.is_file() and self._command_exists("poetry") else "pip"
    env_contract = _resolve_backend_env_contract(
        self,
        context=context,
        backend_cwd=backend_cwd,
        base_env=self._command_env(port=0),
        projected_env=project_env_base,
    )
    env = env_contract.env
    env_merge_started = time.monotonic()
    if (
        env_contract.env_file_path is not None
        and env_contract.env_file_path.is_file()
        and env_contract.env_file_is_default
        and not env_contract.skip_local_db_env
    ):
        self._sync_backend_env_file(env_contract.env_file_path, env=env)
    _emit_bootstrap_phase(
        self,
        project=context.name,
        service="backend",
        phase="env_merge",
        started=env_merge_started,
    )

    uses_poetry = pyproject_file.is_file() and _pyproject_uses_poetry(pyproject_file) and self._command_exists("poetry")
    probe_modules = _backend_runtime_probe_modules(backend_cwd) if uses_poetry else ()

    def _poetry_environment_ready() -> bool:
        return _poetry_backend_environment_ready(
            self,
            backend_cwd=backend_cwd,
            env=env,
            modules=probe_modules,
        )

    poetry_install_decision: tuple[bool, str, dict[str, object]] | None = None
    poetry_install_check_emitted = False
    migrations_enabled = _backend_migrations_enabled(self, route)
    runtime_required, runtime_reason, runtime_state = _backend_runtime_prep_required(
        backend_cwd=backend_cwd,
        manager=manager,
        env=env,
        backend_env_file=env_contract.env_file_path,
        backend_env_is_default=env_contract.env_file_is_default,
        skip_local_db_env=env_contract.skip_local_db_env,
        migrations_enabled=migrations_enabled,
    )
    if not runtime_required:
        if uses_poetry:
            install_check_started = time.monotonic()
            poetry_install_decision = _backend_dependency_install_required(
                backend_cwd=backend_cwd,
                manager="poetry",
                environment_ready=_poetry_environment_ready if probe_modules else None,
            )
            install_required, install_reason, _install_state = poetry_install_decision
            _emit_bootstrap_phase(
                self,
                project=context.name,
                service="backend",
                phase="dependency_install_check",
                started=install_check_started,
                reason=install_reason,
            )
            poetry_install_check_emitted = True
            if not install_required:
                self._emit(
                    "service.bootstrap.skip",
                    project=context.name,
                    service="backend",
                    manager=manager,
                    step="install",
                    reason=install_reason,
                )
                _emit_bootstrap_phase(
                    self,
                    project=context.name,
                    service="backend",
                    phase="dependency_install",
                    started=time.monotonic(),
                    status="reused",
                    reason=install_reason,
                )
            else:
                runtime_required = True

        if not runtime_required:
            self._emit(
                "service.bootstrap.skip",
                project=context.name,
                service="backend",
                manager=manager,
                step="prepare",
                reason=runtime_reason,
            )
            _emit_bootstrap_phase(
                self,
                project=context.name,
                service="backend",
                phase="prepare",
                started=prepare_started,
                status="reused",
                reason=runtime_reason,
            )
            return

    if uses_poetry:
        install_check_started = time.monotonic()
        if poetry_install_decision is None:
            poetry_install_decision = _backend_dependency_install_required(
                backend_cwd=backend_cwd,
                manager="poetry",
                environment_ready=_poetry_environment_ready if probe_modules else None,
            )
        install_required, install_reason, install_state = poetry_install_decision
        if not poetry_install_check_emitted:
            _emit_bootstrap_phase(
                self,
                project=context.name,
                service="backend",
                phase="dependency_install_check",
                started=install_check_started,
                reason=install_reason,
            )
        if install_required:
            install_started = time.monotonic()
            self._emit(
                "service.bootstrap",
                project=context.name,
                service="backend",
                manager="poetry",
                step="install",
                reason=install_reason,
            )
            self._run_backend_bootstrap_command(
                context=context,
                command=["poetry", "install"],
                cwd=backend_cwd,
                backend_log_path=backend_log_path,
                env=env,
                step="poetry install",
            )
            _write_backend_bootstrap_state(backend_cwd=backend_cwd, state=install_state)
            _emit_bootstrap_phase(
                self,
                project=context.name,
                service="backend",
                phase="dependency_install",
                started=install_started,
                reason=install_reason,
            )
        else:
            self._emit(
                "service.bootstrap.skip",
                project=context.name,
                service="backend",
                manager="poetry",
                step="install",
                reason=install_reason,
            )
            _emit_bootstrap_phase(
                self,
                project=context.name,
                service="backend",
                phase="dependency_install",
                started=time.monotonic(),
                status="reused",
                reason=install_reason,
            )
        if migrations_enabled and self._backend_has_migrations(backend_cwd):
            migration_started = time.monotonic()
            self._emit("service.bootstrap", project=context.name, service="backend", manager="poetry", step="migrate")
            self._run_backend_migration_step(
                context=context,
                command=["poetry", "run", "alembic", "upgrade", "head"],
                cwd=backend_cwd,
                backend_log_path=backend_log_path,
                env=env,
                env_contract=env_contract,
                step="poetry alembic upgrade head",
            )
            _emit_bootstrap_phase(
                self,
                project=context.name,
                service="backend",
                phase="migration",
                started=migration_started,
            )
        else:
            _emit_bootstrap_phase(
                self,
                project=context.name,
                service="backend",
                phase="migration",
                started=time.monotonic(),
                status="skipped",
                reason="disabled_or_not_present",
            )
        _write_backend_runtime_prep_state(backend_cwd=backend_cwd, state=runtime_state)
        _emit_bootstrap_phase(
            self,
            project=context.name,
            service="backend",
            phase="prepare",
            started=prepare_started,
        )
        return

    if not requirements_file.is_file():
        return

    venv_dir = backend_cwd / "venv"
    venv_python = venv_dir / "bin" / "python"
    if not venv_python.exists():
        python_bin = self._default_python_executable()
        venv_started = time.monotonic()
        self._emit("service.bootstrap", project=context.name, service="backend", manager="venv", step="create")
        self._run_backend_bootstrap_command(
            context=context,
            command=[python_bin, "-m", "venv", str(venv_dir)],
            cwd=backend_cwd,
            backend_log_path=backend_log_path,
            env=env,
            step="python -m venv",
        )
        _emit_bootstrap_phase(
            self,
            project=context.name,
            service="backend",
            phase="venv_create",
            started=venv_started,
        )

    install_check_started = time.monotonic()
    install_required, install_reason, install_state = _backend_dependency_install_required(
        backend_cwd=backend_cwd,
        manager="pip",
    )
    _emit_bootstrap_phase(
        self,
        project=context.name,
        service="backend",
        phase="dependency_install_check",
        started=install_check_started,
        reason=install_reason,
    )
    if install_required:
        install_started = time.monotonic()
        self._emit(
            "service.bootstrap",
            project=context.name,
            service="backend",
            manager="pip",
            step="install",
            reason=install_reason,
        )
        self._run_backend_bootstrap_command(
            context=context,
            command=[str(venv_python), "-m", "pip", "install", "-r", "requirements.txt"],
            cwd=backend_cwd,
            backend_log_path=backend_log_path,
            env=env,
            step="pip install -r requirements.txt",
        )
        _write_backend_bootstrap_state(backend_cwd=backend_cwd, state=install_state)
        _emit_bootstrap_phase(
            self,
            project=context.name,
            service="backend",
            phase="dependency_install",
            started=install_started,
            reason=install_reason,
        )
    else:
        self._emit(
            "service.bootstrap.skip",
            project=context.name,
            service="backend",
            manager="pip",
            step="install",
            reason=install_reason,
        )
        _emit_bootstrap_phase(
            self,
            project=context.name,
            service="backend",
            phase="dependency_install",
            started=time.monotonic(),
            status="reused",
            reason=install_reason,
        )
    if migrations_enabled and self._backend_has_migrations(backend_cwd):
        migration_started = time.monotonic()
        self._emit("service.bootstrap", project=context.name, service="backend", manager="alembic", step="migrate")
        self._run_backend_migration_step(
            context=context,
            command=[str(venv_python), "-m", "alembic", "upgrade", "head"],
            cwd=backend_cwd,
            backend_log_path=backend_log_path,
            env=env,
            env_contract=env_contract,
            step="alembic upgrade head",
        )
        _emit_bootstrap_phase(
            self,
            project=context.name,
            service="backend",
            phase="migration",
            started=migration_started,
        )
    else:
        _emit_bootstrap_phase(
            self,
            project=context.name,
            service="backend",
            phase="migration",
            started=time.monotonic(),
            status="skipped",
            reason="disabled_or_not_present",
        )
    _write_backend_runtime_prep_state(backend_cwd=backend_cwd, state=runtime_state)
    _emit_bootstrap_phase(
        self,
        project=context.name,
        service="backend",
        phase="prepare",
        started=prepare_started,
    )
