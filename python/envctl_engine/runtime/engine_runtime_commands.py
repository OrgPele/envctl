from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
from typing import Any, Mapping

from envctl_engine.runtime.command_resolution import resolve_requirement_start_command, resolve_service_start_command


def requirement_command(
    runtime: Any,
    *,
    service_name: str,
    port: int,
    project_root: Path | None = None,
) -> list[str]:
    return requirement_command_resolved(
        runtime,
        service_name=service_name,
        port=port,
        project_root=project_root,
    )[0]


def requirement_command_source(
    runtime: Any,
    *,
    service_name: str,
    port: int,
    project_root: Path | None = None,
) -> str:
    return requirement_command_resolved(
        runtime,
        service_name=service_name,
        port=port,
        project_root=project_root,
    )[1]


def requirement_command_resolved(
    runtime: Any,
    *,
    service_name: str,
    port: int,
    project_root: Path | None = None,
) -> tuple[list[str], str]:
    result = resolve_requirement_start_command(
        service_name=service_name,
        project_root=(project_root or runtime.config.base_dir),
        port=port,
        env=runtime.env,
        config_raw=runtime.config.raw,
        command_exists=runtime._command_exists,
    )
    return result.command, result.source


def service_start_command(
    runtime: Any,
    *,
    service_name: str,
    project_root: Path | None = None,
    port: int = 0,
) -> list[str]:
    return service_start_command_resolved(
        runtime,
        service_name=service_name,
        project_root=project_root,
        port=port,
    )[0]


def service_command_source(
    runtime: Any,
    *,
    service_name: str,
    project_root: Path | None = None,
    port: int = 0,
) -> str:
    return service_start_command_resolved(
        runtime,
        service_name=service_name,
        project_root=project_root,
        port=port,
    )[1]


def service_start_command_resolved(
    runtime: Any,
    *,
    service_name: str,
    project_root: Path | None = None,
    port: int = 0,
) -> tuple[list[str], str]:
    result = resolve_service_start_command(
        service_name=service_name,
        project_root=(project_root or runtime.config.base_dir),
        port=port,
        env=runtime.env,
        config_raw=runtime.config.raw,
        command_exists=runtime._command_exists,
    )
    return result.command, result.source


def command_override_value(runtime: Any, key: str) -> str | None:
    if key in runtime.env:
        raw = runtime.env.get(key)
        return raw if raw else None
    raw_cfg = runtime.config.raw.get(key)
    if raw_cfg is None:
        return None
    return raw_cfg if raw_cfg else None


def split_command(
    runtime: Any,
    raw: str,
    *,
    port: int | None = None,
    replacements: Mapping[str, str] | None = None,
) -> list[str]:
    value = raw
    if replacements:
        for key, replacement in replacements.items():
            value = value.replace(f"{{{key}}}", replacement)
    if port is not None:
        value = value.replace("{port}", str(port))
    parsed = shlex.split(value)
    if not parsed:
        raise RuntimeError("Resolved command is empty")
    executable = parsed[0]
    if not runtime._command_exists(executable):
        raise RuntimeError(f"Resolved command executable not found: {executable}")
    return parsed


def command_env(runtime: Any, *, port: int, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env.update(runtime.env)
    env["PORT"] = str(port)
    if extra:
        env.update(extra)
    return env


def default_python_executable(runtime: Any) -> str:
    candidates = [
        runtime.env.get("PYTHON_BIN"),
        runtime.env.get("PYTHON_CMD"),
        os.environ.get("PYTHON_BIN"),
        os.environ.get("PYTHON_CMD"),
        shutil.which("python3.12"),
        shutil.which("python3"),
        shutil.which("python"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if runtime._command_exists(candidate):
            return candidate
    return "python3"


def command_exists(executable: str) -> bool:
    if "/" in executable:
        return Path(executable).expanduser().exists()
    return shutil.which(executable) is not None
