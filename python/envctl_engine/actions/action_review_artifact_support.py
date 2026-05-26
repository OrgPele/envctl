from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from envctl_engine.actions.action_review_context import ReviewActionContext


def file_has_text(path: Path) -> bool:
    try:
        return bool(path.read_text(encoding="utf-8").strip())
    except OSError:
        return False


def tree_changelog_path(context: ReviewActionContext, *, sanitize_label_fn: Callable[[str], str]) -> Path | None:
    tree_name = "main" if context.project_name.strip().lower() == "main" else context.project_name.strip()
    candidate = context.project_root / "docs" / "changelog" / f"{sanitize_label_fn(tree_name)}_changelog.md"
    if candidate.is_file() and file_has_text(candidate):
        return candidate
    return None


def summary_output_path(
    repo_root: Path,
    directory: str,
    prefix: str,
    label: str | None = None,
    *,
    sanitize_label_fn: Callable[[str], str],
) -> Path:
    output_dir = repo_root / directory
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    if label:
        return output_dir / f"{prefix}_{sanitize_label_fn(label)}_{timestamp}.md"
    return output_dir / f"{prefix}_{timestamp}.md"


def write_markdown_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
