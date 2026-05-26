from __future__ import annotations

from collections.abc import Callable, Mapping
import shutil
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from envctl_engine.runtime import service_command_autodetect
from envctl_engine.shared.python_project_metadata import pyproject_uses_poetry as _shared_pyproject_uses_poetry

CommandExists = Callable[[str], bool]


@dataclass(slots=True)
class CommandResolutionResult:
    command: list[str]
    source: str


class CommandResolutionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code: str = code
        super().__init__(f"{code}: {message}")


def suggest_service_start_command(
    *,
    service_name: str,
    project_root: Path,
    command_exists: CommandExists | None = None,
) -> str | None:
    return service_command_autodetect.suggest_service_start_command(
        service_name=service_name,
        project_root=project_root,
        command_exists=command_exists or _default_command_exists,
    )


def suggest_service_directory(*, service_name: str, project_root: Path) -> str | None:
    return service_command_autodetect.suggest_service_directory(service_name=service_name, project_root=project_root)


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
            command=_split_and_validate(
                raw,
                port=port,
                command_exists=exists,
                search_roots=[project_root],
            ),
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
        _validate_configured_service_layout(
            service_name=service_name,
            project_root=project_root,
            config_raw=config_raw,
            raw_command=raw,
        )
        service_root = _configured_service_root(
            service_name=service_name,
            project_root=project_root,
            config_raw=config_raw,
        )
        python_runner_prefix = (
            _prepared_backend_python_runner_prefix(
                service_root=service_root,
                project_root=project_root,
                command_exists=exists,
            )
            if service_name == "backend"
            else ()
        )
        return CommandResolutionResult(
            command=_split_and_validate(
                raw,
                port=port,
                command_exists=exists,
                search_roots=[service_root, project_root],
                python_runner_prefix=python_runner_prefix,
            ),
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
    return service_command_autodetect.autodetect_service_command(
        service_name=service_name,
        project_root=project_root,
        port=port,
        command_exists=command_exists,
    )


def _override_value(key: str, *, env: Mapping[str, str], config_raw: Mapping[str, str]) -> str | None:
    if key in env:
        value = env.get(key)
        return value if value else None
    value = config_raw.get(key)
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _configured_service_root(*, service_name: str, project_root: Path, config_raw: Mapping[str, str]) -> Path:
    dir_key = "BACKEND_DIR" if service_name == "backend" else "FRONTEND_DIR"
    raw_dir = str(config_raw.get(dir_key, "") or "").strip()
    if raw_dir:
        candidate = (project_root / raw_dir).resolve()
        if candidate.is_dir():
            return candidate
    autodetected = suggest_service_directory(service_name=service_name, project_root=project_root)
    if autodetected:
        candidate = (project_root / autodetected).resolve()
        if candidate.is_dir():
            return candidate
    return project_root


def _validate_configured_service_layout(
    *,
    service_name: str,
    project_root: Path,
    config_raw: Mapping[str, str],
    raw_command: str,
) -> None:
    if service_name != "backend":
        return
    if not _configured_command_requires_python_backend_layout(raw_command):
        return
    raw_dir = str(config_raw.get("BACKEND_DIR", "backend") or "backend").strip() or "backend"
    candidate = (project_root / raw_dir).resolve()
    if candidate.is_dir():
        return
    raise CommandResolutionError(
        "missing_service_directory",
        f"Configured backend directory not found: {candidate}",
    )


def _configured_command_requires_python_backend_layout(raw_command: str) -> bool:
    try:
        parts = shlex.split(raw_command.replace("{port}", "0"))
    except ValueError:
        return False
    if len(parts) < 4:
        return False
    executable = parts[0]
    if executable not in {"python", "python3", "python3.12"}:
        return False
    return parts[1:4] == ["-m", "uvicorn", "app.main:app"]


def _split_and_validate(
    raw: str,
    *,
    port: int,
    command_exists: CommandExists,
    search_roots: list[Path] | None = None,
    python_runner_prefix: tuple[str, ...] = (),
) -> list[str]:
    parsed = shlex.split(raw.replace("{port}", str(port)))
    if not parsed:
        raise CommandResolutionError("invalid_command", "Resolved command is empty")
    if _looks_like_env_assignment(parsed[0]):
        raise CommandResolutionError(
            "unsupported_command_env_prefix",
            (
                "Use service env overlays instead of shell-prefix env assignments, "
                "or wrap explicitly in `sh -c`."
            ),
        )
    parsed = _normalize_configured_python_command(parsed, runner_prefix=python_runner_prefix)
    executable = parsed[0]
    if not _command_exists_for_roots(executable, command_exists=command_exists, search_roots=search_roots or []):
        raise CommandResolutionError(
            "missing_command_executable",
            f"Resolved command executable not found: {executable}",
        )
    return parsed


def _looks_like_env_assignment(token: str) -> bool:
    if "=" not in token or token.startswith("="):
        return False
    name, _value = token.split("=", 1)
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name))


def _default_command_exists(executable: str) -> bool:
    if "/" in executable:
        return Path(executable).expanduser().exists()
    return shutil.which(executable) is not None


def _command_exists_for_roots(
    executable: str,
    *,
    command_exists: CommandExists,
    search_roots: list[Path],
) -> bool:
    if "/" not in executable:
        return command_exists(executable)
    candidate = Path(executable).expanduser()
    if candidate.is_absolute():
        return candidate.exists()
    if candidate.exists():
        return True
    for root in search_roots:
        resolved = (root / candidate).expanduser()
        if resolved.exists():
            return True
    return False


def _normalize_configured_python_command(command: list[str], *, runner_prefix: tuple[str, ...]) -> list[str]:
    if not command or not runner_prefix:
        return command
    executable = command[0]
    if executable not in {"python", "python3", "python3.12"}:
        return command
    return [*runner_prefix, *command[1:]]


def _prepared_backend_python_runner_prefix(
    *,
    service_root: Path,
    project_root: Path,
    command_exists: CommandExists,
) -> tuple[str, ...]:
    pyproject = service_root / "pyproject.toml"
    if _pyproject_uses_poetry(pyproject) and command_exists("poetry"):
        return ("poetry", "run", "python")
    python_bin = service_command_autodetect.detect_python_bin_for_service(
        project_root=project_root,
        service_root=service_root,
        command_exists=command_exists,
    )
    if python_bin is None or "/" not in python_bin:
        return ()
    return (python_bin,)


def _pyproject_uses_poetry(pyproject_file: Path) -> bool:
    return pyproject_file.is_file() and _shared_pyproject_uses_poetry(pyproject_file)
