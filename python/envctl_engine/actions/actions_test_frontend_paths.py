from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from envctl_engine.actions.actions_test_models import SuggestionConfidence


def append_frontend_test_path(
    command: Sequence[str],
    frontend_test_path: str | None,
    *,
    project_root: Path | None = None,
    command_cwd: Path | None = None,
) -> list[str]:
    rendered = [str(part) for part in command]
    path_value = normalize_frontend_test_path(
        frontend_test_path,
        project_root=project_root,
        command_cwd=command_cwd,
    )
    if not path_value:
        return rendered
    if path_value in rendered:
        return rendered
    if "--" in rendered:
        return [*rendered, path_value]
    return [*rendered, "--", path_value]


def normalize_frontend_test_path(
    frontend_test_path: str | None,
    *,
    project_root: Path | None,
    command_cwd: Path | None,
) -> str | None:
    text = str(frontend_test_path or "").strip()
    if not text:
        return None
    normalized = text.replace("\\", "/").strip()
    if not normalized:
        return None
    normalized = normalized.rstrip("/")
    if not normalized:
        return None
    if command_cwd is None or project_root is None:
        return normalized
    if os.path.isabs(normalized):
        try:
            relative = os.path.relpath(normalized, command_cwd)
        except ValueError:
            return normalized
        return relative or "."
    try:
        relative_cwd = command_cwd.resolve().relative_to(project_root.resolve())
    except ValueError:
        return normalized
    prefix = relative_cwd.as_posix().rstrip("/")
    if not prefix or prefix == ".":
        return normalized
    if normalized == prefix:
        return "."
    prefixed = f"{prefix}/"
    if normalized.startswith(prefixed):
        trimmed = normalized[len(prefixed) :].strip("/")
        return trimmed or "."
    return normalized


def canonicalize_frontend_test_path(
    frontend_test_path: str | None,
    *,
    project_root: Path,
    frontend_dir_name: str | None = None,
) -> str | None:
    text = str(frontend_test_path or "").strip()
    if not text:
        return None
    normalized = text.replace("\\", "/").strip().rstrip("/")
    if not normalized:
        return None
    if os.path.isabs(normalized):
        return normalized
    package_root = _frontend_package_root_for_config(project_root, frontend_dir_name)
    if package_root is None:
        return normalized
    package_prefix = _frontend_dir_name_from_package_root(project_root, package_root)
    if not package_prefix:
        return normalized
    if normalized == package_prefix or normalized.startswith(f"{package_prefix}/"):
        return normalized
    package_candidate = package_root / normalized
    project_candidate = project_root / normalized
    if package_candidate.exists() or not project_candidate.exists():
        return f"{package_prefix}/{normalized}"
    return normalized


def _frontend_test_package_root(base_dir: Path) -> Path | None:
    package_root = base_dir / "frontend"
    package_json = package_root / "package.json"
    if not package_json.is_file():
        return None
    return package_root


def _frontend_package_root_for_config(project_root: Path, frontend_dir_name: str | None) -> Path | None:
    configured = str(frontend_dir_name or "").strip().strip("/")
    if configured and configured != ".":
        candidate = project_root / configured
        if candidate.exists() or candidate.parent.exists():
            return candidate
    return _frontend_test_package_root(project_root)


def _frontend_dir_name_from_package_root(project_root: Path, package_root: Path) -> str | None:
    try:
        package_prefix = package_root.resolve().relative_to(project_root.resolve()).as_posix().rstrip("/")
    except ValueError:
        return None
    return package_prefix or None


def _suggest_frontend_test_path_for_package_root(package_root: Path) -> str | None:
    for relative_name, _source, _label, confidence, _reason in _frontend_test_path_candidates(package_root):
        if confidence == "high":
            return relative_name
    return None


def _frontend_test_path_candidates(
    package_root: Path,
) -> list[tuple[str, str, str, SuggestionConfidence, str]]:
    preferred = ("tests", "test", "__tests__", "src", "app", "ui", "client")
    high_confidence: list[tuple[str, str, str, SuggestionConfidence, str]] = []
    low_confidence: list[tuple[str, str, str, SuggestionConfidence, str]] = []
    for relative_name in preferred:
        candidate = package_root / relative_name
        if not candidate.is_dir():
            continue
        if _directory_contains_test_files(candidate):
            high_confidence.append(
                (
                    relative_name,
                    "frontend_test_files",
                    f"{relative_name} test files",
                    "high",
                    f"Detected test/spec files under frontend/{relative_name}.",
                )
            )
        elif relative_name in {"tests", "test", "__tests__", "src"}:
            low_confidence.append(
                (
                    relative_name,
                    "frontend_common_test_root",
                    f"{relative_name} directory",
                    "low",
                    f"Detected common frontend test root frontend/{relative_name}, but no test/spec files.",
                )
            )
    return [*high_confidence, *low_confidence]


def _directory_contains_test_files(path: Path) -> bool:
    patterns = (
        "*.test.*",
        "*.spec.*",
    )
    for pattern in patterns:
        if next(path.rglob(pattern), None) is not None:
            return True
    return False
