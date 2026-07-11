from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from envctl_engine.planning import discover_tree_projects
from envctl_engine.runtime.launcher_support import main_repo_root_for_linked_worktree
from envctl_engine.runtime.runtime_context import resolve_process_runtime


@dataclass(frozen=True, slots=True)
class CurrentWorktreeTargetResolver:
    runtime: Any
    require_configured_main_root: bool
    require_configured_root_match: bool
    current_cwd: Callable[[], Path]
    discover_tree_projects: Callable[[Path, str], list[tuple[str, Path]]]
    main_repo_root_for_linked_worktree: Callable[[Path], Path | None]
    git_main_repo_root_for_worktree: Callable[..., Path | None] | None

    def resolve(self) -> object | None:
        cwd = self._current_working_directory()
        raw_runtime = getattr(self.runtime, "raw_runtime", self.runtime)
        configured_root_path = self._configured_root(raw_runtime)
        if self.require_configured_main_root and configured_root_path == cwd:
            return None

        trees_dir_name = str(getattr(getattr(raw_runtime, "config", None), "trees_dir_name", "trees"))
        repo_root = self._repo_root(cwd, configured_root_path=configured_root_path, trees_dir_name=trees_dir_name)
        if repo_root is None:
            return None

        matches = self._matching_candidates(cwd, repo_root=repo_root, trees_dir_name=trees_dir_name)
        if len(matches) == 1:
            return matches[0]
        if matches:
            return None
        return self._linked_worktree_candidate(
            cwd,
            repo_root=repo_root,
            configured_root_path=configured_root_path,
            raw_runtime=raw_runtime,
        )

    def _current_working_directory(self) -> Path:
        invocation_cwd = str(getattr(self.runtime, "env", {}).get("ENVCTL_INVOCATION_CWD") or "").strip()
        if invocation_cwd:
            return Path(invocation_cwd).expanduser().resolve()
        return self.current_cwd().resolve()

    @staticmethod
    def _configured_root(raw_runtime: Any) -> Path | None:
        configured_root = getattr(getattr(raw_runtime, "config", None), "base_dir", None)
        if configured_root is None:
            return None
        return Path(str(configured_root)).expanduser().resolve()

    def _repo_root(self, cwd: Path, *, configured_root_path: Path | None, trees_dir_name: str) -> Path | None:
        if self.require_configured_main_root:
            if configured_root_path is None:
                return None
            repo_root = repo_root_from_worktree_layout(cwd, trees_dir_name)
            if repo_root is None:
                repo_root = self.main_repo_root_for_linked_worktree(cwd)
            if repo_root is None:
                resolver = self.git_main_repo_root_for_worktree or main_repo_root_for_worktree
                repo_root = resolver(worktree_root=cwd, runtime=self.runtime, trees_dir_name=trees_dir_name)
            if repo_root is None or repo_root.resolve() != configured_root_path:
                return None
            return repo_root

        resolver = self.git_main_repo_root_for_worktree or main_repo_root_for_worktree
        repo_root = resolver(worktree_root=cwd, runtime=self.runtime, trees_dir_name=trees_dir_name)
        if repo_root is None:
            return None
        if (
            self.require_configured_root_match
            and configured_root_path is not None
            and repo_root.resolve() != configured_root_path
        ):
            return None
        return repo_root

    def _matching_candidates(self, cwd: Path, *, repo_root: Path, trees_dir_name: str) -> list[object]:
        candidates = [
            SimpleNamespace(name=name, root=root)
            for name, root in self.discover_tree_projects(repo_root, trees_dir_name)
        ]
        return [
            candidate
            for candidate in candidates
            if _path_is_at_or_under(cwd, Path(str(getattr(candidate, "root"))).resolve())
        ]

    @staticmethod
    def _linked_worktree_candidate(
        cwd: Path,
        *,
        repo_root: Path,
        configured_root_path: Path | None,
        raw_runtime: Any,
    ) -> object | None:
        """Resolve a Git-linked checkout that lives outside the configured trees directory."""

        top_level_raw = _git_output(raw_runtime, cwd, ["rev-parse", "--show-toplevel"])
        if not top_level_raw:
            return None
        try:
            top_level = Path(top_level_raw).expanduser().resolve()
        except OSError:
            return None
        if not _path_is_at_or_under(cwd, top_level):
            return None

        normalized_repo_root = repo_root.resolve()
        if top_level == normalized_repo_root:
            return None
        if configured_root_path is not None and top_level == configured_root_path:
            return None

        branch = _git_output(raw_runtime, top_level, ["branch", "--show-current"])
        return SimpleNamespace(name=branch or top_level.name, root=top_level)


def resolve_current_worktree_target(
    *,
    runtime: Any,
    require_configured_main_root: bool = False,
    require_configured_root_match: bool = False,
    current_cwd: Callable[[], Path] = Path.cwd,
    discover_tree_projects_fn: Callable[[Path, str], list[tuple[str, Path]]] = discover_tree_projects,
    main_repo_root_for_linked_worktree_fn: Callable[[Path], Path | None] = main_repo_root_for_linked_worktree,
    git_main_repo_root_for_worktree_fn: Callable[..., Path | None] | None = None,
) -> object | None:
    return CurrentWorktreeTargetResolver(
        runtime=runtime,
        require_configured_main_root=require_configured_main_root,
        require_configured_root_match=require_configured_root_match,
        current_cwd=current_cwd,
        discover_tree_projects=discover_tree_projects_fn,
        main_repo_root_for_linked_worktree=main_repo_root_for_linked_worktree_fn,
        git_main_repo_root_for_worktree=git_main_repo_root_for_worktree_fn,
    ).resolve()


def main_repo_root_for_worktree(*, worktree_root: Path, runtime: Any, trees_dir_name: str | None = None) -> Path | None:
    raw_runtime = getattr(runtime, "raw_runtime", runtime)
    configured_trees_dir = trees_dir_name or getattr(getattr(raw_runtime, "config", None), "trees_dir_name", "trees")
    normalized_trees_dir = str(configured_trees_dir).strip().rstrip("/")
    repo_root_from_layout = repo_root_from_worktree_layout(worktree_root, normalized_trees_dir)
    if repo_root_from_layout is not None:
        return repo_root_from_layout

    process_runtime = resolve_process_runtime(raw_runtime)
    run = getattr(process_runtime, "run", None)
    if not callable(run):
        return None

    completed = run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=worktree_root,
        timeout=10.0,
    )
    if getattr(completed, "returncode", 1) != 0:
        return None
    top_level = Path(str(getattr(completed, "stdout", "") or "").strip()).resolve()

    common = run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=worktree_root,
        timeout=10.0,
    )
    if getattr(common, "returncode", 1) != 0:
        return top_level
    common_dir_raw = str(getattr(common, "stdout", "") or "").strip()
    if not common_dir_raw:
        return top_level
    common_dir_path = Path(common_dir_raw)
    common_dir = (
        (worktree_root / common_dir_path).resolve()
        if not common_dir_path.is_absolute()
        else common_dir_path.resolve()
    )
    if common_dir.name == ".git":
        return common_dir.parent
    if common_dir.name == "worktrees" and common_dir.parent.name == ".git":
        return common_dir.parent.parent
    return top_level


def repo_root_from_worktree_layout(worktree_root: Path, trees_dir_name: str) -> Path | None:
    normalized = str(trees_dir_name).strip().rstrip("/")
    if not normalized:
        return None

    resolved_target = worktree_root.resolve()
    nested_suffix = Path(normalized)
    flat_prefix = f"{nested_suffix.name}-"

    ancestors = [resolved_target, *resolved_target.parents]
    for candidate_repo_root in ancestors:
        nested_root = candidate_repo_root / nested_suffix
        if nested_root == resolved_target or nested_root in resolved_target.parents:
            return candidate_repo_root

        flat_parent = nested_root.parent
        if flat_parent == resolved_target or flat_parent not in ancestors:
            continue
        current = resolved_target
        while current != flat_parent and flat_parent in current.parents:
            if current.parent == flat_parent and current.name.startswith(flat_prefix):
                return candidate_repo_root
            current = current.parent
    return None


def _path_is_at_or_under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _git_output(runtime: object, cwd: Path, args: list[str]) -> str:
    try:
        process_runtime = resolve_process_runtime(runtime)
        completed = process_runtime.run(
            ["git", *args],
            cwd=cwd,
            timeout=10.0,
        )
    except Exception:  # noqa: BLE001 - target inference must fail closed
        return ""
    if getattr(completed, "returncode", 1) != 0:
        return ""
    return str(getattr(completed, "stdout", "") or "").strip()
