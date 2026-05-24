from __future__ import annotations

from typing import Mapping

from envctl_engine.runtime.browser_diagnostics import launch_diagnostics_payload


def record_runtime_launch_diagnostics(
    *,
    route: object | None,
    runtime: object,
    project_name: str,
    frontend_port: int,
    backend_env: Mapping[str, str],
    prepared_launches: Mapping[str, object],
    backend_command_source: str | None,
    frontend_command_source: str | None,
) -> None:
    if route is None or not prepared_launches:
        return
    flags = getattr(route, "flags", None)
    if not isinstance(flags, dict):
        return
    project_diagnostics = flags.setdefault("_runtime_launch_diagnostics", {})
    if not isinstance(project_diagnostics, dict):
        return

    service_payloads: dict[str, object] = {}
    if "backend" in prepared_launches:
        cors_key = _backend_cors_key(runtime)
        origins = [token.strip() for token in str(backend_env.get(cors_key, "") or "").split(",") if token.strip()]
        backend_launch = prepared_launches["backend"]
        service_payloads["backend"] = launch_diagnostics_payload(
            project=project_name,
            service_name="backend",
            env=_launch_env(backend_launch),
            command_source=backend_command_source,
            argv=[],
            cors={
                "projected": bool(frontend_port > 0 and origins),
                "env_key": cors_key,
                "frontend_origin": backend_env.get("FRONTEND_BASE_URL"),
                "origins": origins,
                "effective_input": backend_env.get(cors_key),
            },
        )
    if "frontend" in prepared_launches:
        frontend_launch = prepared_launches["frontend"]
        service_payloads["frontend"] = launch_diagnostics_payload(
            project=project_name,
            service_name="frontend",
            env=_launch_env(frontend_launch),
            command_source=frontend_command_source,
            argv=[],
        )
    project_diagnostics[project_name] = service_payloads


def _backend_cors_key(runtime: object) -> str:
    env = getattr(runtime, "env", {})
    config_raw = getattr(getattr(runtime, "config", None), "raw", {})
    return str(
        env.get(
            "ENVCTL_BACKEND_CORS_ENV_KEY",
            config_raw.get("ENVCTL_BACKEND_CORS_ENV_KEY", "CORS_ORIGINS_RAW"),
        )
        or "CORS_ORIGINS_RAW"
    ).strip()


def _launch_env(launch: object) -> dict[str, str]:
    env = getattr(launch, "env", {})
    if isinstance(env, dict):
        return env
    if isinstance(env, Mapping):
        return dict(env)
    return {}
