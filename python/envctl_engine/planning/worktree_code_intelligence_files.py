from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path


def copy_worktree_code_intelligence_file(*, source: Path, target: Path) -> bool:
    if not source.is_file() or target.exists() or target.is_symlink():
        return False
    try:
        text = source.read_text(encoding="utf-8")
    except OSError:
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    except OSError:
        return False
    return True


def copy_worktree_serena_project_file(
    *,
    source: Path,
    target: Path,
    project_name: str,
    emit: Callable[..., object] | None,
) -> bool:
    if not source.is_file() or target.exists() or target.is_symlink():
        return False
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        if emit:
            emit(
                "setup.worktree.code_intelligence.serena_config",
                target=str(target),
                project_name=project_name,
                success=False,
                error=str(exc),
            )
        return False
    rewritten = rewrite_serena_project_name(text, project_name=project_name)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rewritten, encoding="utf-8")
    except OSError as exc:
        if emit:
            emit(
                "setup.worktree.code_intelligence.serena_config",
                target=str(target),
                project_name=project_name,
                success=False,
                error=str(exc),
            )
        return False
    if emit:
        emit(
            "setup.worktree.code_intelligence.serena_config",
            target=str(target),
            project_name=project_name,
            success=True,
        )
    return True


def rewrite_serena_project_name(text: str, *, project_name: str) -> str:
    pattern = re.compile(
        r"^(?P<prefix>project_name:\s*)(?P<quote>[\"']?)(?P<value>.*?)(?P=quote)(?P<suffix>\s*)$",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        return f"project_name: {project_name}\n{text}"
    quote = match.group("quote") or ""
    replacement = f"{match.group('prefix')}{quote}{project_name}{quote}{match.group('suffix')}"
    return text[: match.start()] + replacement + text[match.end() :]
