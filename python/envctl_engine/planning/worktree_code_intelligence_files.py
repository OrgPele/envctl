from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path


def ensure_worktree_git_excludes(*, root: Path, patterns: tuple[str, ...]) -> bool:
    exclude_path = worktree_git_exclude_path(root)
    if exclude_path is None:
        return False
    try:
        existing = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
    except OSError:
        return False
    existing_lines = {line.strip() for line in existing.splitlines()}
    missing = [pattern for pattern in patterns if pattern and pattern not in existing_lines]
    if not missing:
        return True
    try:
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        with exclude_path.open("a", encoding="utf-8") as handle:
            handle.write(prefix)
            handle.write("# envctl local generated artifacts\n")
            handle.write("\n".join(missing))
            handle.write("\n")
    except OSError:
        return False
    return True


def worktree_git_exclude_path(root: Path) -> Path | None:
    dot_git = root / ".git"
    if dot_git.is_dir():
        return dot_git / "info" / "exclude"
    if not dot_git.is_file():
        return None
    try:
        text = dot_git.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    raw = text.split(":", 1)[1].strip()
    if not raw:
        return None
    git_dir = Path(raw)
    if not git_dir.is_absolute():
        git_dir = (dot_git.parent / git_dir).resolve()
    if not git_dir.exists():
        return None
    common_dir = _git_common_dir(git_dir)
    return common_dir / "info" / "exclude"


def _git_common_dir(git_dir: Path) -> Path:
    commondir = git_dir / "commondir"
    try:
        raw = commondir.read_text(encoding="utf-8").strip()
    except OSError:
        return git_dir
    if not raw:
        return git_dir
    common_dir = Path(raw)
    if not common_dir.is_absolute():
        common_dir = git_dir / common_dir
    return common_dir.resolve()


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


def write_worktree_serena_project_local_file(
    *,
    target: Path,
    project_name: str,
    emit: Callable[..., object] | None,
) -> bool:
    text = f'project_name: "{project_name}"\n'
    try:
        if target.is_file() and target.read_text(encoding="utf-8") == text:
            return True
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    except OSError as exc:
        if emit:
            emit(
                "setup.worktree.code_intelligence.serena_local_config",
                target=str(target),
                project_name=project_name,
                success=False,
                error=str(exc),
            )
        return False
    if emit:
        emit(
            "setup.worktree.code_intelligence.serena_local_config",
            target=str(target),
            project_name=project_name,
            success=True,
        )
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
