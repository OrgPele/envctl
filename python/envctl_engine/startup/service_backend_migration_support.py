from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Mapping

from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.parsing import parse_bool
from envctl_engine.shared.python_project_metadata import pyproject_uses_poetry as _shared_pyproject_uses_poetry
from envctl_engine.startup.service_env_support import _BackendEnvContract
from envctl_engine.ui.path_links import render_path_for_terminal


def _backend_migrations_enabled(self: Any, route: Route | None) -> bool:
    if route is None:
        raw = self.env.get("ENVCTL_BACKEND_MIGRATIONS_ON_STARTUP") or self.config.raw.get(
            "ENVCTL_BACKEND_MIGRATIONS_ON_STARTUP"
        )
        return parse_bool(raw, True)
    if bool(route.flags.get("_dependency_bootstrap_no_migrations")):
        return False
    if bool(route.flags.get("_resume_restore")):
        return False
    raw = self.env.get("ENVCTL_BACKEND_MIGRATIONS_ON_STARTUP") or self.config.raw.get(
        "ENVCTL_BACKEND_MIGRATIONS_ON_STARTUP"
    )
    return parse_bool(raw, True)


def _pyproject_uses_poetry(pyproject_file: Path) -> bool:
    return pyproject_file.is_file() and _shared_pyproject_uses_poetry(pyproject_file)


def _bootstrap_failure_suggestion(step: str, error: str, cwd: Path) -> str:
    lower_error = error.lower()
    if "poetry install" in step.lower() or "poetry" in lower_error:
        if "set `packages`" in error or "no packages found" in lower_error:
            return (
                f"\nTip: this project has pyproject.toml but does not use Poetry.\n"
                f"Fix: create a venv manually in {cwd}:\n"
                f"  python -m venv venv && source venv/bin/activate && pip install -e .\n"
                f"Or add TREES_BACKEND_ENABLE=false to your .envctl to skip backend bootstrap."
            )
        if "lock file" in lower_error or "poetry.lock" in lower_error:
            return (
                f"\nTip: Poetry lock file is missing. Run `poetry lock` in {cwd},\n"
                f"or set TREES_BACKEND_ENABLE=false in .envctl to skip bootstrap."
            )
        return (
            "\nTip: Poetry install failed. Check that the project is configured for Poetry.\n"
            "If this project uses pip/setuptools instead, add TREES_BACKEND_ENABLE=false to .envctl."
        )
    if "pip install" in lower_error or "pip" in lower_error:
        return f"\nTip: pip install failed. Check that requirements.txt or pyproject.toml is valid in {cwd}."
    return ""


def _run_backend_bootstrap_command(
    self: Any,
    *,
    context: object,
    command: list[str],
    cwd: Path,
    backend_log_path: str,
    env: Mapping[str, str],
    step: str,
) -> None:
    result = self.process_runner.run(
        command,
        cwd=cwd,
        env=env,
        timeout=300.0,
    )
    if result.returncode == 0:
        return
    error = self._command_result_error_text(result=result)
    if backend_log_path:
        try:
            Path(backend_log_path).parent.mkdir(parents=True, exist_ok=True)
            with Path(backend_log_path).open("a", encoding="utf-8") as handle:
                handle.write(f"[envctl] backend bootstrap step failed ({step}): {error}\n")
        except OSError:
            pass
    suggestion = _bootstrap_failure_suggestion(step, error, cwd)
    log_hint = f"\nLog: {backend_log_path}" if backend_log_path else ""
    project = str(getattr(context, "name", "") or "project")
    raise RuntimeError(f"backend bootstrap failed for {project} during {step}: {error}{log_hint}\n{suggestion}")


def _run_backend_migration_step(
    self: Any,
    *,
    context: object,
    command: list[str],
    cwd: Path,
    backend_log_path: str,
    env: Mapping[str, str],
    env_contract: _BackendEnvContract | None = None,
    step: str,
) -> None:
    project = str(getattr(context, "name", "") or "project")
    try:
        self._run_backend_bootstrap_command(
            context=context,
            command=command,
            cwd=cwd,
            backend_log_path=backend_log_path,
            env=env,
            step=step,
        )
        return
    except RuntimeError as exc:
        retry_env = self._backend_migration_retry_env_for_async_driver_mismatch(
            env=env,
            error_message=str(exc),
        )
        if retry_env is not None:
            self._emit(
                "service.bootstrap.retry",
                project=project,
                service="backend",
                step=step,
                reason="async_driver_mismatch",
            )
            self._run_backend_bootstrap_command(
                context=context,
                command=command,
                cwd=cwd,
                backend_log_path=backend_log_path,
                env=retry_env,
                step=f"{step} (async driver fallback)",
            )
            return
        if self._backend_bootstrap_strict():
            raise
        message = str(exc)
        record_warning = getattr(self, "_record_project_startup_warning", None)
        if callable(record_warning):
            record_warning(
                project,
                f"Warning: backend migration step failed; continuing without migration ({message})",
            )
            if backend_log_path:
                record_warning(project, f"backend log: {backend_log_path}")
            detail = _backend_env_warning_line(env_contract)
            if detail is not None:
                record_warning(project, detail)
        else:
            print(f"Warning: backend migration step failed for {project}; continuing without migration ({message})")
            if backend_log_path:
                print("  backend log:")
                rendered_path = render_path_for_terminal(backend_log_path, env=getattr(self, "env", {}))
                print(f"  {rendered_path}")
            detail = _backend_env_warning_line(env_contract)
            if detail is not None:
                print(detail)
        missing_revision = _backend_missing_revision_id(message)
        if missing_revision:
            hint_text = (
                "hint: alembic revision "
                f"{missing_revision} is missing in this worktree history. "
                f"Inspect migration chain in {cwd} "
                "(`alembic heads`, `alembic history`), then align DB revision "
                "(for local dev only, `alembic stamp head` can unblock)."
            )
            if callable(record_warning):
                record_warning(project, hint_text)
            else:
                print(f"  {hint_text}")
        self._emit(
            "service.bootstrap.warning",
            project=project,
            service="backend",
            step=step,
            error=message,
            backend_log_path=backend_log_path,
            missing_revision=missing_revision,
            env_file_path=str(env_contract.env_file_path) if env_contract and env_contract.env_file_path else None,
            env_file_source=env_contract.env_file_source if env_contract else None,
            override_resolution=env_contract.override_resolution if env_contract else None,
        )


def _backend_env_warning_line(env_contract: _BackendEnvContract | None) -> str | None:
    if env_contract is None:
        return None
    parts = [f"backend env source: {env_contract.env_file_source}"]
    if env_contract.env_file_path is not None:
        parts.append(str(env_contract.env_file_path))
    if env_contract.override_requested:
        parts.append(f"override_resolution={env_contract.override_resolution}")
    return " | ".join(parts)


def _backend_migration_retry_env_for_async_driver_mismatch(
    self: Any,
    *,
    env: Mapping[str, str],
    error_message: str,
) -> dict[str, str] | None:
    if not self._backend_async_driver_mismatch_error(error_message):
        return None
    current_url = str(env.get("DATABASE_URL", "")).strip()
    rewritten_url = self._rewrite_database_url_to_asyncpg(current_url)
    if rewritten_url is None or rewritten_url == current_url:
        return None
    retry_env = dict(env)
    for key in ("DATABASE_URL", "SQLALCHEMY_DATABASE_URL", "ASYNC_DATABASE_URL"):
        retry_env[key] = rewritten_url
    return retry_env


def _backend_async_driver_mismatch_error(message: str) -> bool:
    normalized = (message or "").lower()
    mismatch_tokens = (
        "requires an async driver",
        "is not async",
        "loaded 'psycopg2'",
        'loaded "psycopg2"',
    )
    return any(token in normalized for token in mismatch_tokens)


def _backend_missing_revision_id(message: str) -> str | None:
    if not message:
        return None
    match = re.search(
        r"can't locate revision identified by ['\"]([^'\"]+)['\"]",
        str(message),
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    revision = str(match.group(1)).strip()
    return revision or None


def _rewrite_database_url_to_asyncpg(database_url: str) -> str | None:
    value = (database_url or "").strip()
    if not value:
        return None
    if value.startswith("postgresql+asyncpg://"):
        return value
    replacements = (
        ("postgresql+psycopg2://", "postgresql+asyncpg://"),
        ("postgresql+psycopg://", "postgresql+asyncpg://"),
        ("postgresql://", "postgresql+asyncpg://"),
        ("postgres://", "postgresql+asyncpg://"),
    )
    for source, target in replacements:
        if value.startswith(source):
            return target + value[len(source) :]
    return None


def _emit_bootstrap_phase(
    self: Any,
    *,
    project: str,
    service: str,
    phase: str,
    started: float,
    status: str = "ok",
    reason: str | None = None,
) -> None:
    emit = getattr(self, "_emit", None)
    if not callable(emit):
        return
    emit(
        "service.bootstrap.phase",
        project=project,
        service=service,
        phase=phase,
        status=status,
        reason=reason,
        duration_ms=round((time.monotonic() - started) * 1000.0, 2),
    )


def _backend_bootstrap_strict(self: Any) -> bool:
    raw = self.env.get("ENVCTL_BACKEND_BOOTSTRAP_STRICT") or self.config.raw.get("ENVCTL_BACKEND_BOOTSTRAP_STRICT")
    return parse_bool(raw, False)


def _backend_has_migrations(backend_cwd: Path) -> bool:
    migration_markers = (
        backend_cwd / "alembic.ini",
        backend_cwd / "alembic" / "versions",
        backend_cwd / "migrations" / "versions",
    )
    return any(marker.exists() for marker in migration_markers)
