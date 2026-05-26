from __future__ import annotations

import importlib.util
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Literal, cast

from envctl_engine.shared.python_project_metadata import pyproject_project_table_from_payload, read_pyproject

RUNTIME_DEPENDENCY_MODULES: tuple[str, ...] = (
    "prompt_toolkit",
    "psutil",
    "rich",
    "textual",
)

CANONICAL_CONTRIBUTOR_BOOTSTRAP_COMMANDS: tuple[str, ...] = (
    "uv sync --extra dev --python 3.12",
)

RuntimeDependencyContext = Literal["source_checkout", "installed_package", "contributor"]

_NAME_SEPARATOR_RE = re.compile(r"[-_.]+")
_REQUIREMENT_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]+\])?(.*)$")


@dataclass(frozen=True, slots=True)
class RuntimeDependencyManifestParity:
    requirements: tuple[str, ...]
    pyproject: tuple[str, ...]
    only_in_requirements: tuple[str, ...]
    only_in_pyproject: tuple[str, ...]

    @property
    def matches(self) -> bool:
        return not self.only_in_requirements and not self.only_in_pyproject


def python_dependency_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def missing_runtime_dependency_modules(
    *,
    import_available: Callable[[str], bool] = python_dependency_available,
) -> list[str]:
    return sorted(module for module in RUNTIME_DEPENDENCY_MODULES if not import_available(module))


def runtime_dependency_context(
    env: Mapping[str, str] | None = None,
    *,
    contributor: bool = False,
) -> RuntimeDependencyContext:
    if contributor:
        return "contributor"
    root = source_checkout_root(env)
    if root is not None and (root / "python" / "requirements.txt").is_file():
        return "source_checkout"
    return "installed_package"


def source_checkout_root(env: Mapping[str, str] | None = None) -> Path | None:
    if env is None:
        return None
    root = str(env.get("ENVCTL_ROOT_DIR", "")).strip()
    if not root:
        return None
    try:
        return Path(root).expanduser().resolve()
    except OSError:
        return None


def source_checkout_requirements_path(env: Mapping[str, str] | None = None) -> Path | None:
    root = source_checkout_root(env)
    if root is None:
        return None
    candidate = root / "python" / "requirements.txt"
    if candidate.is_file():
        return candidate
    return None


def runtime_dependency_failure_message(
    missing_modules: list[str] | tuple[str, ...],
    *,
    env: Mapping[str, str] | None = None,
    contributor: bool = False,
) -> str:
    normalized_missing = sorted({str(module).strip() for module in missing_modules if str(module).strip()})
    if not normalized_missing:
        normalized_missing = list(RUNTIME_DEPENDENCY_MODULES)
    lines = [f"Missing required envctl runtime Python packages: {', '.join(normalized_missing)}."]
    context = runtime_dependency_context(env, contributor=contributor)
    if context == "source_checkout":
        requirements_path = source_checkout_requirements_path(env)
        lines.append(
            " ".join(
                (
                    "This source-checkout invocation needs the envctl runtime dependencies installed",
                    "into the active interpreter.",
                )
            )
        )
        if requirements_path is None:
            lines.append("Install them with: python -m pip install -r python/requirements.txt")
        else:
            lines.append(f"Install them with: python -m pip install -r {requirements_path}")
        return "\n".join(lines)
    if context == "contributor":
        lines.append("Bootstrap the repo-local contributor environment with:")
        lines.extend(CANONICAL_CONTRIBUTOR_BOOTSTRAP_COMMANDS)
        return "\n".join(lines)
    lines.append("The installed envctl environment is incomplete and needs its packaged dependencies repaired.")
    lines.append("If you installed envctl with pipx, run: pipx reinstall envctl")
    lines.append(
        "Otherwise reinstall envctl in the same Python environment so its declared dependencies are installed."
    )
    return "\n".join(lines)


def runtime_dependency_manifest_parity(repo_root: Path) -> RuntimeDependencyManifestParity:
    requirements = tuple(sorted(_normalized_requirements_manifest(repo_root / "python" / "requirements.txt")))
    pyproject = tuple(sorted(_normalized_pyproject_dependencies(repo_root / "pyproject.toml")))
    requirements_set = set(requirements)
    pyproject_set = set(pyproject)
    return RuntimeDependencyManifestParity(
        requirements=requirements,
        pyproject=pyproject,
        only_in_requirements=tuple(sorted(requirements_set - pyproject_set)),
        only_in_pyproject=tuple(sorted(pyproject_set - requirements_set)),
    )


def _normalized_requirements_manifest(path: Path) -> list[str]:
    lines: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        candidate = raw_line.split("#", 1)[0].strip()
        if not candidate:
            continue
        lines.append(_normalize_requirement(candidate))
    return lines


def _normalized_pyproject_dependencies(path: Path) -> list[str]:
    payload = read_pyproject(path)
    project = pyproject_project_table_from_payload(payload)
    if project is None:
        raise ValueError(f"Missing [project] table in {path}")
    dependencies_raw = project.get("dependencies")
    if not isinstance(dependencies_raw, list):
        raise ValueError(f"Missing project.dependencies in {path}")
    dependencies = cast("list[object]", dependencies_raw)
    normalized: list[str] = []
    for item in dependencies:
        if not isinstance(item, str):
            raise ValueError(f"project.dependencies entries must be strings in {path}")
        normalized.append(_normalize_requirement(item))
    return normalized


def _normalize_requirement(raw_requirement: str) -> str:
    value = str(raw_requirement).strip()
    match = _REQUIREMENT_RE.match(value)
    if match is None:
        return re.sub(r"\s+", "", value)
    name, extras, remainder = match.groups()
    normalized_name = _NAME_SEPARATOR_RE.sub("-", name).lower()
    normalized_extras = ""
    if extras:
        items = sorted(part.strip().lower() for part in extras[1:-1].split(",") if part.strip())
        normalized_extras = f"[{','.join(items)}]"
    normalized_remainder = re.sub(r"\s+", "", remainder or "")
    return f"{normalized_name}{normalized_extras}{normalized_remainder}"
