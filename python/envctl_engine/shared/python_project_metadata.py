from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import tomllib
from typing import cast


def read_pyproject(pyproject: Path) -> dict[str, object]:
    return cast("dict[str, object]", tomllib.loads(pyproject.read_text(encoding="utf-8")))


def load_pyproject(pyproject: Path) -> dict[str, object] | None:
    try:
        return read_pyproject(pyproject)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None


def pyproject_project_table_from_payload(payload: Mapping[str, object]) -> Mapping[str, object] | None:
    project = payload.get("project")
    if not isinstance(project, dict):
        return None
    return cast("Mapping[str, object]", project)


def pyproject_project_string_field_from_payload(payload: Mapping[str, object], field: str) -> str | None:
    field_name = field.strip()
    if not field_name:
        return None
    project = pyproject_project_table_from_payload(payload)
    if project is None:
        return None
    raw_value = project.get(field_name)
    if not isinstance(raw_value, str):
        return None
    value = raw_value.strip()
    return value or None


def pyproject_project_string_field(pyproject: Path, field: str) -> str | None:
    payload = load_pyproject(pyproject)
    if payload is None:
        return None
    return pyproject_project_string_field_from_payload(payload, field)


def pyproject_project_name(pyproject: Path) -> str | None:
    return pyproject_project_string_field(pyproject, "name")


def pyproject_project_version(pyproject: Path) -> str | None:
    return pyproject_project_string_field(pyproject, "version")


def pyproject_has_tool_table(pyproject: Path, table: str) -> bool:
    table_name = table.strip()
    if not table_name:
        return False
    payload = load_pyproject(pyproject)
    if payload is None:
        return False
    tool = payload.get("tool")
    if not isinstance(tool, dict):
        return False
    tool_table = cast("dict[str, object]", tool)
    return isinstance(tool_table.get(table_name), dict)


def pyproject_uses_poetry(pyproject: Path) -> bool:
    return pyproject_has_tool_table(pyproject, "poetry")
