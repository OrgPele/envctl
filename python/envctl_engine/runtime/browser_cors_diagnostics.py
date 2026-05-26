from __future__ import annotations

from typing import Any, Mapping, TypedDict
from urllib.parse import urlparse

from envctl_engine.startup.public_urls import resolve_public_host
from envctl_engine.state.models import ServiceRecord


class CorsProjectionPreview(TypedDict):
    env: dict[str, str]
    diagnostics: dict[str, object]


def cors_payload(
    *,
    backend_launch: object,
    backend_env: Mapping[str, str],
    frontend_url: object,
    config: Any | None,
    env: Mapping[str, str] | None,
) -> dict[str, object]:
    if isinstance(backend_launch, Mapping):
        raw_cors = backend_launch.get("cors")
    else:
        raw_cors = None
    if isinstance(raw_cors, Mapping):
        cors = {str(key): value for key, value in raw_cors.items()}
        origins = cors.get("origins")
        if not isinstance(origins, list):
            env_key = str(cors.get("env_key") or cors_env_key(config=config, env=env))
            origins = [token.strip() for token in str(backend_env.get(env_key, "")).split(",") if token.strip()]
            cors["origins"] = origins
        return cors
    env_key = cors_env_key(config=config, env=env)
    origins = [token.strip() for token in str(backend_env.get(env_key, "")).split(",") if token.strip()]
    return {
        "projected": bool(frontend_url and str(frontend_url) in origins),
        "env_key": env_key,
        "frontend_origin": frontend_url,
        "origins": origins,
        "effective_input": backend_env.get(env_key),
    }


def frontend_env_mismatch_warnings(
    *,
    project: str,
    frontend_env: Mapping[str, str],
    backend_service: ServiceRecord | None,
    supabase: object,
) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    backend_port = backend_service.actual_port if backend_service is not None else None
    if backend_port:
        api_port = url_port(str(frontend_env.get("VITE_API_URL") or frontend_env.get("VITE_BACKEND_URL") or ""))
        if api_port is not None and api_port != int(backend_port):
            warnings.append(
                {
                    "code": "frontend_env_backend_port_mismatch",
                    "project": project,
                    "env_key": "VITE_API_URL",
                    "expected_port": int(backend_port),
                    "actual_port": api_port,
                    "message": (
                        f"{project} frontend VITE_API_URL points at port {api_port}, "
                        f"but active backend is on port {backend_port}."
                    ),
                }
            )
    if isinstance(supabase, Mapping):
        expected = url_port(str(supabase.get("api_url") or ""))
        actual = url_port(str(frontend_env.get("VITE_SUPABASE_URL") or ""))
        if expected is not None and actual is not None and expected != actual:
            warnings.append(
                {
                    "code": "frontend_env_supabase_port_mismatch",
                    "project": project,
                    "env_key": "VITE_SUPABASE_URL",
                    "expected_port": expected,
                    "actual_port": actual,
                    "message": (
                        f"{project} frontend VITE_SUPABASE_URL points at port {actual}, "
                        f"but active Supabase API is on port {expected}."
                    ),
                }
            )
    return warnings


def cors_projection_preview(
    runtime: Any,
    *,
    frontend_port: int | None,
    backend_env: Mapping[str, str],
) -> CorsProjectionPreview:
    env_key = cors_env_key(config=getattr(runtime, "config", None), env=getattr(runtime, "env", None))
    if not frontend_port:
        return {"env": {}, "diagnostics": {"projected": False, "env_key": env_key, "origins": []}}
    host = resolve_public_host(env=getattr(runtime, "env", None), config=getattr(runtime, "config", None))
    origins = merge_cors_origins(str(backend_env.get(env_key, "") or ""), frontend_port=frontend_port, host=host)
    frontend_origin = f"http://{host}:{frontend_port}"
    return {
        "env": {
            "FRONTEND_BASE_URL": frontend_origin,
            "ENVCTL_SOURCE_FRONTEND_URL": frontend_origin,
            env_key: ",".join(origins),
        },
        "diagnostics": {
            "projected": True,
            "env_key": env_key,
            "frontend_origin": frontend_origin,
            "origins": origins,
            "effective_input": ",".join(origins),
        },
    }


def cors_env_key(*, config: Any | None, env: Mapping[str, str] | None) -> str:
    config_raw = getattr(config, "raw", {}) if config is not None else {}
    raw = ""
    if isinstance(env, Mapping):
        raw = str(env.get("ENVCTL_BACKEND_CORS_ENV_KEY") or "")
    if not raw and isinstance(config_raw, Mapping):
        raw = str(config_raw.get("ENVCTL_BACKEND_CORS_ENV_KEY") or "")
    return raw.strip() or "CORS_ORIGINS_RAW"


def url_port(value: str) -> int | None:
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    return parsed.port


def merge_cors_origins(existing: str, *, frontend_port: int, host: str) -> list[str]:
    origins: list[str] = []

    def add(value: str) -> None:
        normalized = value.strip()
        if normalized and normalized not in origins:
            origins.append(normalized)

    for token in existing.replace(";", ",").split(","):
        add(token)
    add(f"http://{host}:{frontend_port}")
    if host in {"localhost", "127.0.0.1"}:
        add(f"http://localhost:{frontend_port}")
        add(f"http://127.0.0.1:{frontend_port}")
    return origins


_cors_payload = cors_payload
_frontend_env_mismatch_warnings = frontend_env_mismatch_warnings
_cors_projection_preview = cors_projection_preview
_cors_env_key = cors_env_key
_url_port = url_port
_merge_cors_origins = merge_cors_origins
