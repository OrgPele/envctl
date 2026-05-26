from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from ..common_contracts import build_container_name
from ...shared.dependency_compose_assets import materialize_dependency_compose, supabase_managed_env

def _normalize_compose_error(error: str, *, compose_project_name: str) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for raw in str(error).splitlines():
        line = raw.strip()
        if not line:
            continue
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
    normalized = "\n".join(lines).strip()
    if not normalized:
        return normalized
    if _is_container_name_conflict(normalized):
        container_name = _extract_conflicting_container_name(normalized)
        detail = f"conflicting container={container_name}" if container_name else "conflicting container already exists"
        return (
            f"supabase compose namespace conflict for project {compose_project_name}: {detail}. "
            "This usually means the stack is not using a project-scoped compose namespace "
            "or a stale conflicting container still exists."
        )
    return normalized


def _is_container_name_conflict(error: str) -> bool:
    lowered = error.lower()
    return "container name" in lowered and "already in use" in lowered and "conflict" in lowered


def _extract_conflicting_container_name(error: str) -> str | None:
    match = re.search(r'container name\s+"?/?([^"\s]+)"?', error, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip() or None


def _resolve_supabase_compose_workspace(
    *,
    project_root: Path,
    project_name: str,
    db_port: int,
    public_port: int | None = None,
    runtime_root: Path | None,
    env: Mapping[str, str] | None,
) -> tuple[Path, Path]:
    if runtime_root is None:
        compose_root = project_root / "supabase"
        return compose_root, compose_root / "docker-compose.yml"

    materialized = materialize_dependency_compose(
        runtime_root=runtime_root,
        dependency_name="supabase",
        project_name=project_name,
        compose_project_name=build_supabase_project_name(
            project_root=project_root,
            project_name=project_name,
        ),
        env_values=supabase_managed_env(db_port=db_port, public_port=public_port, env=env),
    )
    return materialized.stack_root, materialized.compose_file



def build_supabase_project_name(*, project_root: Path, project_name: str) -> str:
    return build_container_name(
        prefix="envctl-supabase",
        project_root=project_root,
        project_name=project_name,
    )
