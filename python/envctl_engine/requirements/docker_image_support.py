from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from envctl_engine.requirements.docker_runtime import (
    _env_value,
    _parse_env_bool,
    run_docker,
    run_result_error,
)
from envctl_engine.shared.protocols import ProcessRuntime


def docker_image_pull_policy(
    env: Mapping[str, str] | None,
    key: str,
    *,
    default: str = "missing",
    legacy_bool_key: str | None = None,
) -> str:
    raw = _env_value(env, key)
    if raw is not None:
        normalized = str(raw).strip().lower().replace("_", "-")
        if normalized in {"always", "missing", "if-missing", "never"}:
            return "missing" if normalized == "if-missing" else normalized
        if normalized in {"1", "true", "yes", "on", "enable", "enabled"}:
            return "always"
        if normalized in {"0", "false", "no", "off", "disable", "disabled"}:
            return "never"

    if legacy_bool_key is not None:
        legacy_raw = _env_value(env, legacy_bool_key)
        if legacy_raw is not None:
            return "always" if _parse_env_bool(legacy_raw, default=True) else "never"

    normalized_default = default.strip().lower().replace("_", "-")
    if normalized_default == "if-missing":
        return "missing"
    if normalized_default in {"always", "missing", "never"}:
        return normalized_default
    return "missing"


def docker_image_exists(
    process_runner: ProcessRuntime,
    *,
    image: str,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = 10.0,
) -> tuple[bool, str | None]:
    result, error = run_docker(
        process_runner,
        ["image", "inspect", image],
        cwd=cwd,
        env=env,
        timeout=timeout,
    )
    if result is None:
        return False, error
    return getattr(result, "returncode", 1) == 0, None


def ensure_docker_image_present(
    process_runner: ProcessRuntime,
    *,
    image: str,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    pull_policy_key: str,
    legacy_bool_key: str | None = None,
    inspect_timeout: float = 10.0,
    pull_timeout: float = 300.0,
) -> str | None:
    pull_policy = docker_image_pull_policy(env, pull_policy_key, legacy_bool_key=legacy_bool_key)
    if pull_policy == "never":
        return None
    if pull_policy == "missing":
        exists, exists_error = docker_image_exists(
            process_runner,
            image=image,
            cwd=cwd,
            env=env,
            timeout=inspect_timeout,
        )
        if exists_error is not None:
            return exists_error
        if exists:
            return None

    result, error = run_docker(
        process_runner,
        ["pull", image],
        cwd=cwd,
        env=env,
        timeout=pull_timeout,
    )
    if result is None:
        return error
    if getattr(result, "returncode", 1) != 0:
        return run_result_error(result, f"failed pulling image {image}")
    return None
