from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from ..common import container_exists, run_docker, run_result_error
from .formatting import _sanitize_service_state_text


def _inspect_auth_gateway_services(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    service_names: list[str],
) -> list[dict[str, object]]:
    return [
        _inspect_auth_gateway_service(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            compose_path=compose_path,
            env=env,
            service_name=service_name,
        )
        for service_name in service_names
    ]


def _inspect_auth_gateway_service(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    service_name: str,
) -> dict[str, object]:
    direct_summary = _inspect_compose_service_from_container_name(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        env=env,
        service_name=service_name,
    )
    if direct_summary is not None:
        return direct_summary

    json_summary = _inspect_compose_service_from_ps_json(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        service_name=service_name,
    )
    if json_summary is not None:
        return json_summary

    result, run_error = run_docker(
        process_runner,
        ["compose", "-p", compose_project_name, "-f", str(compose_path), "ps", "-q", service_name],
        cwd=compose_root,
        env=env,
        timeout=10.0,
    )
    summary: dict[str, object] = {"service": service_name}
    if result is None:
        summary["inspect_error"] = _sanitize_service_state_text(run_error or "docker compose ps failed")
        return summary
    if getattr(result, "returncode", 1) != 0:
        summary["inspect_error"] = _sanitize_service_state_text(run_result_error(result, "docker compose ps failed"))
        return summary
    container_id = str(getattr(result, "stdout", "") or "").strip().splitlines()[0:1]
    if not container_id:
        summary["status"] = "missing"
        return summary
    summary["container"] = container_id[0]
    state_result, state_error = run_docker(
        process_runner,
        ["inspect", "-f", "{{json .State}}", container_id[0]],
        cwd=compose_root,
        env=env,
        timeout=10.0,
    )
    if state_result is None:
        summary["inspect_error"] = _sanitize_service_state_text(state_error or "docker inspect failed")
        return summary
    if getattr(state_result, "returncode", 1) != 0:
        summary["inspect_error"] = _sanitize_service_state_text(run_result_error(state_result, "docker inspect failed"))
        return summary
    state_text = str(getattr(state_result, "stdout", "") or "").strip()
    _populate_service_summary_from_state(summary, state_text)
    if len(summary) == 2 and "container" in summary:
        summary["status"] = "unknown"
    return summary


def _inspect_compose_service_from_container_name(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    env: Mapping[str, str] | None,
    service_name: str,
) -> dict[str, object] | None:
    container_name = _compose_container_name(compose_project_name=compose_project_name, service_name=service_name)
    exists, exists_error = container_exists(
        process_runner,
        container_name=container_name,
        cwd=compose_root,
        env=env,
    )
    if exists_error is not None or not exists:
        return None
    summary: dict[str, object] = {"service": service_name, "container": container_name}
    state_result, state_error = run_docker(
        process_runner,
        ["inspect", "-f", "{{json .State}}", container_name],
        cwd=compose_root,
        env=env,
        timeout=10.0,
    )
    if state_result is None:
        summary["inspect_error"] = _sanitize_service_state_text(state_error or "docker inspect failed")
        return summary
    if getattr(state_result, "returncode", 1) != 0:
        return None
    _populate_service_summary_from_state(summary, str(getattr(state_result, "stdout", "") or ""))
    if len(summary) == 2 and "container" in summary:
        summary["status"] = "unknown"
    return summary


def _compose_container_name(*, compose_project_name: str, service_name: str) -> str:
    return f"{compose_project_name}-{service_name}-1"


def _populate_service_summary_from_state(summary: dict[str, object], state_text: str) -> None:
    state_text = str(state_text or "").strip()
    try:
        state = json.loads(state_text) if state_text else {}
    except json.JSONDecodeError:
        state = {"Status": state_text}
    if isinstance(state, dict):
        status = state.get("Status")
        if status:
            summary["status"] = str(status)
        health = state.get("Health")
        if isinstance(health, dict) and health.get("Status"):
            summary["health"] = str(health.get("Status"))
        exit_code = state.get("ExitCode")
        if isinstance(exit_code, int) or (isinstance(exit_code, str) and exit_code.strip()):
            summary["exit_code"] = str(exit_code)
        state_error_value = state.get("Error")
        if state_error_value:
            summary["state_error"] = _sanitize_service_state_text(str(state_error_value))


def _inspect_compose_service_from_ps_json(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    service_name: str,
) -> dict[str, object] | None:
    result, run_error = run_docker(
        process_runner,
        ["compose", "-p", compose_project_name, "-f", str(compose_path), "ps", "--format", "json", service_name],
        cwd=compose_root,
        env=env,
        timeout=10.0,
    )
    if result is None or run_error is not None or getattr(result, "returncode", 1) != 0:
        return None
    raw = str(getattr(result, "stdout", "") or "").strip()
    if not raw:
        return None
    rows: list[object] = []
    try:
        decoded = json.loads(raw)
        if isinstance(decoded, list):
            rows = decoded
        elif isinstance(decoded, dict):
            rows = [decoded]
    except json.JSONDecodeError:
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                return None
    summary: dict[str, object] = {"service": service_name}
    if not rows:
        summary["status"] = "missing"
        return summary
    row = next((item for item in rows if isinstance(item, dict)), None)
    if not isinstance(row, dict):
        return None
    container = row.get("ID") or row.get("Name") or row.get("ContainerID")
    if container:
        summary["container"] = str(container)
    state = row.get("State") or row.get("Status")
    status, health = _parse_compose_ps_status(state)
    if status:
        summary["status"] = status
    row_health = row.get("Health") or row.get("HealthStatus")
    if row_health:
        health = str(row_health).strip().lower()
    if health:
        summary["health"] = health
    publishers = row.get("Publishers") or row.get("Ports")
    if publishers:
        summary["ports"] = _sanitize_service_state_text(str(publishers))
    if len(summary) == 1:
        summary["status"] = "unknown"
    return summary


def _parse_compose_ps_status(value: object) -> tuple[str | None, str | None]:
    text = str(value or "").strip()
    if not text:
        return None, None
    lowered = text.lower()
    status: str | None = None
    for candidate in ("running", "created", "exited", "dead", "paused", "restarting", "removing"):
        if candidate in lowered:
            status = candidate
            break
    health: str | None = None
    if "healthy" in lowered:
        health = "healthy"
    if "unhealthy" in lowered:
        health = "unhealthy"
    if "starting" in lowered:
        health = "starting"
    return status or lowered.split()[0], health


