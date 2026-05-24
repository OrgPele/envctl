from __future__ import annotations

from pathlib import Path


def is_repo_root(path: Path) -> bool:
    return (path / ".git").is_dir() or (path / ".git").is_file()


def find_repo_root(candidate: Path) -> Path | None:
    current = Path(candidate).expanduser()
    if current.is_file():
        current = current.parent
    current = current.resolve()
    while True:
        if is_repo_root(current):
            return current
        if current.parent == current:
            return None
        current = current.parent


def main_repo_root_for_linked_worktree(worktree_root: Path) -> Path | None:
    git_file = worktree_root.resolve() / ".git"
    if not git_file.is_file():
        return None
    try:
        first_line = git_file.read_text(encoding="utf-8").splitlines()[0].strip()
    except (IndexError, OSError, UnicodeDecodeError):
        return None
    if not first_line.lower().startswith("gitdir:"):
        return None
    raw_git_dir = first_line.split(":", 1)[1].strip()
    if not raw_git_dir:
        return None
    git_dir = Path(raw_git_dir).expanduser()
    if not git_dir.is_absolute():
        git_dir = git_file.parent / git_dir
    git_dir = git_dir.resolve()
    if git_dir.parent.name == "worktrees" and git_dir.parent.parent.name == ".git":
        return git_dir.parent.parent.parent.resolve()
    common_dir_file = git_dir / "commondir"
    if not common_dir_file.is_file():
        return None
    try:
        common_dir_raw = common_dir_file.read_text(encoding="utf-8").splitlines()[0].strip()
    except (IndexError, OSError, UnicodeDecodeError):
        return None
    if not common_dir_raw:
        return None
    common_dir = Path(common_dir_raw).expanduser()
    if not common_dir.is_absolute():
        common_dir = git_dir / common_dir
    common_dir = common_dir.resolve()
    if common_dir.name == ".git":
        return common_dir.parent.resolve()
    return None


def repo_root_with_readable_main_config_from_worktree(worktree_root: Path) -> Path | None:
    main_repo_root = main_repo_root_for_linked_worktree(worktree_root)
    if main_repo_root is None:
        return None
    config_file = main_repo_root / ".envctl"
    if not config_file.is_file():
        return None
    try:
        with config_file.open("r", encoding="utf-8"):
            pass
    except OSError:
        return None
    return main_repo_root


def is_envctl_managed_worktree_root(worktree_root: Path, main_repo_root: Path) -> bool:
    worktree_root = worktree_root.resolve()
    main_repo_root = main_repo_root.resolve()
    try:
        relative = worktree_root.relative_to(main_repo_root)
    except ValueError:
        return False
    if len(relative.parts) != 3 or relative.parts[0] != "trees":
        return False
    return (worktree_root / ".envctl-state" / "worktree-provenance.json").is_file()


def canonical_envctl_project_root(candidate: Path) -> Path:
    """Resolve the envctl control-plane root for a path inside a Git checkout.

    Linked worktrees of a managed envctl project share the owning main repo's
    .envctl, runtime scope, state, port locks, and latest-run artifacts. This
    helper intentionally resolves only that metadata root; callers that need the
    user's current source checkout should continue using ENVCTL_INVOCATION_CWD.
    """

    repo_root = find_repo_root(candidate)
    if repo_root is None:
        return Path(candidate).expanduser().resolve()
    readable_main_root = repo_root_with_readable_main_config_from_worktree(repo_root)
    if readable_main_root is not None:
        return readable_main_root
    main_repo_root = main_repo_root_for_linked_worktree(repo_root)
    if main_repo_root is not None and is_envctl_managed_worktree_root(repo_root, main_repo_root):
        return main_repo_root
    return repo_root
