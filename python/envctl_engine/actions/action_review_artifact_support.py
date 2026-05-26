from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from envctl_engine.actions.action_review_context import ReviewActionContext
from envctl_engine.shared.artifact_names import safe_artifact_stem


def file_has_text(path: Path) -> bool:
    try:
        return bool(path.read_text(encoding="utf-8").strip())
    except OSError:
        return False


def tree_changelog_path(context: ReviewActionContext) -> Path | None:
    tree_name = "main" if context.project_name.strip().lower() == "main" else context.project_name.strip()
    changelog_name = f"{safe_artifact_stem(tree_name, fallback='project')}_changelog.md"
    candidate = context.project_root / "docs" / "changelog" / changelog_name
    if candidate.is_file() and file_has_text(candidate):
        return candidate
    return None


def summary_output_path(
    repo_root: Path,
    directory: str,
    prefix: str,
    label: str | None = None,
) -> Path:
    return timestamped_markdown_path(repo_root / directory, prefix, label)


def timestamped_markdown_path(output_dir: Path, prefix: str, label: str | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    safe_prefix = safe_artifact_stem(prefix, fallback="artifact")
    if label:
        safe_label = safe_artifact_stem(label, fallback="artifact")
        return output_dir / f"{safe_prefix}_{safe_label}_{timestamp}.md"
    return output_dir / f"{safe_prefix}_{timestamp}.md"


def write_markdown_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
