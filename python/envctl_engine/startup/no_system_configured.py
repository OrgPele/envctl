from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from envctl_engine.runtime.command_resolution import suggest_service_start_command

_DEFAULT_APP_SERVICES = frozenset({"backend", "frontend"})


def should_skip_unconfigured_default_app_services(
    *,
    config: Any,
    mode: str,
    selected_service_types: set[str],
    project_root: Path,
    env: Mapping[str, str] | None = None,
    command_exists: Callable[[str], bool] | None = None,
) -> bool:
    """Return true when service selection is only envctl's default app shell."""

    selected = {str(service).strip().lower() for service in selected_service_types if str(service).strip()}
    if not selected or not selected <= _DEFAULT_APP_SERVICES:
        return False
    if _has_explicit_local_app_signal(config, mode=mode, selected_service_types=selected, env=env):
        return False
    for service_name in selected:
        if suggest_service_start_command(
            service_name=service_name,
            project_root=project_root,
            command_exists=command_exists,
        ):
            return False
    return True


def skip_unconfigured_default_app_services(
    *,
    runtime: Any,
    context: Any,
    route: Any,
    mode: str,
    selected_service_types: set[str],
) -> bool:
    if str(getattr(route, "command", "") or "") != "plan":
        return False
    requested_scope = str(getattr(route, "flags", {}).get("runtime_scope", "") or "").strip().lower()
    if requested_scope != "entire-system":
        return False
    if not should_skip_unconfigured_default_app_services(
        config=runtime.config,
        mode=mode,
        selected_service_types=set(selected_service_types),
        project_root=context.root,
        env=getattr(runtime, "env", {}),
        command_exists=getattr(runtime, "_command_exists", None),
    ):
        return False

    warning = (
        f"No local app system is configured for {context.name}; envctl is continuing with the "
        "implementation session only. --entire-system was honored, but there was nothing configured "
        "to start."
    )
    record_warning = getattr(runtime, "_record_project_startup_warning", None)
    if callable(record_warning):
        record_warning(context.name, warning)
    runtime._emit(
        "service.attach.skipped",
        project=context.name,
        mode=mode,
        reason="no_system_configured",
        requested_scope=requested_scope,
        selected_services=sorted(selected_service_types),
    )
    return True


def _has_explicit_local_app_signal(
    config: Any,
    *,
    mode: str,
    selected_service_types: set[str],
    env: Mapping[str, str] | None,
) -> bool:
    explicit_keys = {str(key).strip().upper() for key in (getattr(config, "explicit_keys", ()) or ())}
    explicit_keys.update(str(key).strip().upper() for key in (env or {}) if str(key).strip())
    normalized_mode = str(mode).strip().lower() or "main"
    mode_prefix = normalized_mode.upper()
    for service_name in selected_service_types:
        service_prefix = service_name.upper()
        if {
            f"ENVCTL_{service_prefix}_START_CMD",
            f"{mode_prefix}_{service_prefix}_ENABLE",
            f"{mode_prefix}_STARTUP_ENABLE",
        } & explicit_keys:
            return True
    return False
