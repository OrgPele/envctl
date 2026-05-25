from __future__ import annotations

from typing import Mapping


SAFE_BACKEND_ENV_KEYS = {
    "FRONTEND_BASE_URL",
    "ENVCTL_SOURCE_FRONTEND_URL",
    "CORS_ORIGINS_RAW",
}


def safe_env_preview(env: Mapping[str, object], *, service_name: str) -> dict[str, str]:
    preview: dict[str, str] = {}
    normalized_service = str(service_name).strip().lower()
    for key, value in sorted(env.items(), key=lambda item: str(item[0])):
        name = str(key).strip()
        if not name:
            continue
        if normalized_service == "frontend":
            allowed = name.startswith("VITE_") or name.startswith("ENVCTL_SOURCE_")
        else:
            allowed = name in SAFE_BACKEND_ENV_KEYS or name.startswith("ENVCTL_SOURCE_")
        if not allowed:
            continue
        if is_secret_key(name) and not name.startswith("VITE_"):
            continue
        preview[name] = redacted_env_value(name, value)
    return preview


def redacted_env_value(key: str, value: object) -> str:
    if is_secret_key(key):
        return "<redacted>"
    return str(value)


def is_secret_key(key: str) -> bool:
    upper = key.upper()
    if upper.startswith("ENVCTL_SOURCE_"):
        upper = upper[len("ENVCTL_SOURCE_") :]
    return any(token in upper for token in ("PASSWORD", "SECRET", "SERVICE_ROLE", "JWT", "TOKEN", "KEY"))


def source_alias_env(env: Mapping[str, object]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for key, value in env.items():
        name = str(key).strip()
        if not name or name.startswith("ENVCTL_SOURCE_"):
            continue
        if not name.replace("_", "").isalnum() or name[0].isdigit():
            continue
        text = str(value)
        if text:
            aliases[f"ENVCTL_SOURCE_{name}"] = text
    return aliases


_SAFE_BACKEND_ENV_KEYS = SAFE_BACKEND_ENV_KEYS
_redacted_env_value = redacted_env_value
_is_secret_key = is_secret_key
_source_alias_env = source_alias_env
