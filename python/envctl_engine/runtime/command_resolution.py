from __future__ import annotations

import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from envctl_engine.shared.node_tooling import detect_package_manager, detect_python_bin, load_package_json

CommandExists = Callable[[str], bool]


@dataclass(slots=True)
class CommandResolutionResult:
    command: list[str]
    source: str


class CommandResolutionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def resolve_requirement_start_command(
    *,
    service_name: str,
    project_root: Path,
    port: int,
    env: Mapping[str, str],
    config_raw: Mapping[str, str],
    command_exists: CommandExists | None = None,
) -> CommandResolutionResult:
    exists = command_exists or _default_command_exists
    env_key = f"ENVCTL_REQUIREMENT_{service_name.upper()}_CMD"
    raw = _override_value(env_key, env=env, config_raw=config_raw)
    if raw is not None:
        return CommandResolutionResult(
            command=_split_and_validate(raw, port=port, command_exists=exists),
            source="configured",
        )

    raise CommandResolutionError(
        "missing_requirement_start_command",
        (
            f"No real requirement command configured for '{service_name}'. "
            f"Set {env_key} or implement Python requirement adapters."
        ),
    )


def resolve_service_start_command(
    *,
    service_name: str,
    project_root: Path,
    port: int,
    env: Mapping[str, str],
    config_raw: Mapping[str, str],
    command_exists: CommandExists | None = None,
) -> CommandResolutionResult:
    exists = command_exists or _default_command_exists
    env_key = f"ENVCTL_{service_name.upper()}_START_CMD"
    raw = _override_value(env_key, env=env, config_raw=config_raw)
    if raw is not None:
        return CommandResolutionResult(
            command=_split_and_validate(raw, port=port, command_exists=exists),
            source="configured",
        )

    autodetected = _autodetect_service_command(
        service_name=service_name,
        project_root=project_root,
        port=port,
        command_exists=exists,
    )
    if autodetected is not None:
        return CommandResolutionResult(command=autodetected, source="autodetected")

    raise CommandResolutionError(
        "missing_service_start_command",
        (
            f"Unable to resolve real {service_name} start command "
            f"(autodetect_failed_{service_name}). Configure {env_key} or add a supported repo layout "
            "(for example FastAPI/Uvicorn backend or package.json dev script frontend)."
        ),
    )


def _autodetect_service_command(
    *,
    service_name: str,
    project_root: Path,
    port: int,
    command_exists: CommandExists,
) -> list[str] | None:
    if service_name == "backend":
        return _autodetect_backend(project_root=project_root, port=port, command_exists=command_exists)
    if service_name == "frontend":
        return _autodetect_frontend(project_root=project_root, port=port, command_exists=command_exists)
    return None


def _autodetect_backend(*, project_root: Path, port: int, command_exists: CommandExists) -> list[str] | None:
    backend_dir = project_root / "backend"
    search_roots = [backend_dir, project_root] if backend_dir.is_dir() else [project_root]

    for candidate_root in search_roots:
        pyproject = candidate_root / "pyproject.toml"
        if pyproject.is_file():
            python_bin = _detect_python_bin(
                project_root=project_root, service_root=candidate_root, command_exists=command_exists
            )
            app_ref = _detect_uvicorn_app_ref(candidate_root)
            if python_bin is not None and app_ref is not None:
                return [
                    python_bin,
                    "-m",
                    "uvicorn",
                    app_ref,
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ]

    for candidate_root in search_roots:
        package_json = candidate_root / "package.json"
        if package_json.is_file():
            command = _npm_like_dev_command(
                package_json=package_json,
                service_name="backend",
                port=port,
                command_exists=command_exists,
            )
            if command is not None:
                return command
    return None


def _autodetect_frontend(*, project_root: Path, port: int, command_exists: CommandExists) -> list[str] | None:
    frontend_dir = project_root / "frontend"
    search_roots = [frontend_dir, project_root] if frontend_dir.is_dir() else [project_root]

    for candidate_root in search_roots:
        package_json = candidate_root / "package.json"
        if not package_json.is_file():
            continue
        command = _npm_like_dev_command(
            package_json=package_json,
            service_name="frontend",
            port=port,
            command_exists=command_exists,
        )
        if command is not None:
            return command
    return None


def _npm_like_dev_command(
    *,
    package_json: Path,
    service_name: str,
    port: int,
    command_exists: CommandExists,
) -> list[str] | None:
    payload = load_package_json(package_json)
    if payload is None:
        return None
    scripts = payload.get("scripts")
    if not isinstance(scripts, dict):
        return None
    dev_script = scripts.get("dev")
    if not isinstance(dev_script, str) or not dev_script.strip():
        return None

    manager = detect_package_manager(package_json.parent, command_exists=command_exists)
    if manager is None:
        return None

    lowered_dev = dev_script.lower()
    if manager == "bun":
        command = ["bun", "run", "dev"]
        if "vite" in lowered_dev and service_name == "frontend":
            command.extend(["--", "--port", str(port), "--host"])
        return command
    if manager in {"npm", "pnpm", "yarn"}:
        command = [manager, "run", "dev"]
        if "vite" in lowered_dev and service_name == "frontend":
            command.extend(["--", "--port", str(port), "--host"])
        return command
    return None


def _detect_python_bin(*, project_root: Path, service_root: Path, command_exists: CommandExists) -> str | None:
    return detect_python_bin(service_root, project_root, command_exists=command_exists)


def _detect_uvicorn_app_ref(service_root: Path) -> str | None:
    candidates = [
        (service_root / "app" / "main.py", "app.main:app"),
        (service_root / "main.py", "main:app"),
        (service_root / "src" / "main.py", "main:app"),
    ]
    for path, ref in candidates:
        if path.is_file():
            return ref
    return None


def _override_value(key: str, *, env: Mapping[str, str], config_raw: Mapping[str, str]) -> str | None:
    if key in env:
        value = env.get(key)
        return value if value else None
    value = config_raw.get(key)
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _split_and_validate(raw: str, *, port: int, command_exists: CommandExists) -> list[str]:
    parsed = shlex.split(raw.replace("{port}", str(port)))
    if not parsed:
        raise CommandResolutionError("invalid_command", "Resolved command is empty")
    executable = parsed[0]
    if not command_exists(executable):
        raise CommandResolutionError(
            "missing_command_executable",
            f"Resolved command executable not found: {executable}",
        )
    return parsed


def _default_command_exists(executable: str) -> bool:
    if "/" in executable:
        return Path(executable).expanduser().exists()
    return shutil.which(executable) is not None
