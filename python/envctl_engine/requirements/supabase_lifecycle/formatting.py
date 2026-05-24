from __future__ import annotations

from collections.abc import Mapping
import re

from .types import _SupabaseStartupBudget, SupabaseAuthHealthProbeResult


def _format_auth_service_state(service_state: Mapping[str, object]) -> str:
    service = str(service_state.get("service") or "unknown")
    parts = [service]
    container = str(service_state.get("container") or "").strip()
    if container:
        parts.append(f"container={container[:12]}")
    for key in ("status", "health", "exit_code", "state_error", "inspect_error"):
        value = str(service_state.get(key) or "").strip()
        if value:
            parts.append(f"{key}={_sanitize_service_state_text(value)}")
    return ":".join(parts[:1]) + (":" + " ".join(parts[1:]) if len(parts) > 1 else "")


def _format_auth_service_states(service_states: list[dict[str, object]]) -> str:
    return "|".join(_format_auth_service_state(service_state) for service_state in service_states)


def _sanitize_service_state_text(value: str) -> str:
    lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
    lines = [line for line in lines if not _is_python_traceback_noise(line)]
    text = " ".join(lines).strip()
    text = re.sub(
        r"\b[A-Z0-9_]*(?:KEY|SECRET|PASSWORD|TOKEN|AUTHORIZATION|APIKEY)[A-Z0-9_]*=[^\s;]+",
        "[redacted]",
        text,
        flags=re.IGNORECASE,
    )
    return (text or "unavailable")[:240]


def _supabase_auth_health_url(env: Mapping[str, str] | None, public_port: int) -> str:
    public_url = str((env or {}).get("SUPABASE_PUBLIC_URL") or f"http://localhost:{public_port}").rstrip("/")
    return f"{public_url}/auth/v1/health"


def _supabase_local_auth_health_url(public_port: int) -> str:
    return f"http://127.0.0.1:{public_port}/auth/v1/health"


def _is_python_traceback_noise(line: str) -> bool:
    text = str(line).strip()
    return bool(
        text == "Traceback (most recent call last):"
        or text.startswith("During handling of the above exception")
        or re.match(r'^File ".+", line \d+, in .+$', text)
    )


def _supabase_auth_failure_detail(
    *,
    probe: SupabaseAuthHealthProbeResult,
    actions: list[str],
    service_names: list[str],
    public_port: int,
    public_health_url: str,
    service_states: list[dict[str, object]] | None = None,
    startup_budget: _SupabaseStartupBudget | None = None,
    auth_probe_timeout_seconds: float | None = None,
    probe_attempt_count: int | None = None,
) -> str:
    parts = [
        "phase=auth_health",
        f"probe_phase={probe.phase}",
        f"services={','.join(service_names) if service_names else 'none'}",
        f"public_port={public_port}",
        f"probe_url={probe.health_url}",
        f"actions={','.join(actions)}",
        f"auth_probe_timeout_s={auth_probe_timeout_seconds:g}" if auth_probe_timeout_seconds is not None else "",
        f"attempts={probe_attempt_count}" if probe_attempt_count is not None else "",
        f"last_error={probe.last_error or 'unknown'}",
    ]
    parts = [part for part in parts if part]
    if startup_budget is not None:
        parts.append(f"startup_budget_s={startup_budget.timeout_seconds:g}")
        parts.append(f"elapsed_ms={startup_budget.elapsed_ms():g}")
    if service_states:
        parts.append(f"service_state={_format_auth_service_states(service_states)}")
    if public_health_url != probe.health_url:
        parts.append(f"public_url={public_health_url}")
    return " ".join(parts)


def _supabase_compose_failure_detail(
    *,
    phase: str,
    error: str | None,
    services: list[str],
    service_states: list[dict[str, object]],
    compose_timeout_seconds: float,
    public_port: int | None,
    health_url: str | None,
    startup_budget: _SupabaseStartupBudget | None = None,
) -> str:
    parts = [
        f"phase={phase}",
        f"services={','.join(services) if services else 'none'}",
        f"compose_timeout_s={compose_timeout_seconds:g}",
    ]
    if startup_budget is not None:
        parts.append(f"startup_budget_s={startup_budget.timeout_seconds:g}")
        parts.append(f"elapsed_ms={startup_budget.elapsed_ms():g}")
    if public_port is not None:
        parts.append(f"public_port={public_port}")
    if health_url:
        parts.append(f"probe_url={health_url}")
    if service_states:
        parts.append(f"service_state={_format_auth_service_states(service_states)}")
    if error:
        parts.append(f"last_error={_sanitize_service_state_text(error)}")
    return " ".join(parts)


def _supabase_db_failure_detail(
    *,
    db_port: int,
    timeout_seconds: float,
    attempts: int,
    startup_budget: _SupabaseStartupBudget,
    service_states: list[dict[str, object]],
    last_error: str,
) -> str:
    parts = [
        "phase=db_probe",
        f"db_port={db_port}",
        f"db_probe_timeout_s={timeout_seconds:g}",
        f"attempts={max(1, attempts)}",
        f"startup_budget_s={startup_budget.timeout_seconds:g}",
        f"elapsed_ms={startup_budget.elapsed_ms():g}",
        f"last_error={_sanitize_service_state_text(last_error)}",
    ]
    if service_states:
        parts.append(f"service_state={_format_auth_service_states(service_states)}")
    return " ".join(parts)

