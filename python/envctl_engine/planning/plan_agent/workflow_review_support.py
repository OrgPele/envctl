from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

from envctl_engine.planning import planning_feature_name
from envctl_engine.planning.plan_agent.constants import (
    _DONE_PLANNING_ROOT,
    _PLANNING_ROOT,
    _WORKTREE_PROVENANCE_PATH,
)


def _review_prompt_arguments(
    *,
    project_name: str,
    project_root: Path,
    review_bundle_path: Path | None,
    original_plan_path: Path | None,
) -> str:
    parts = [f'Project: {project_name}']
    if review_bundle_path is not None:
        parts.append(f'Review bundle: "{review_bundle_path}"')
    parts.append(f'Worktree directory: "{project_root}"')
    if original_plan_path is not None:
        parts.append(f'Original plan file: "{original_plan_path}"')
    return "\n".join(str(part).strip() for part in parts if str(part).strip())


def _review_original_plan_path(project_name: str, project_root: Path, *, repo_root: Path) -> Path | None:
    recorded_plan = _recorded_plan_file_from_worktree(project_root)
    resolved = _resolve_recorded_plan_file(Path(repo_root), recorded_plan)
    if resolved is not None:
        return resolved
    if recorded_plan:
        return None
    return _infer_plan_file_from_feature(Path(repo_root), feature_name=_feature_name_from_project_name(project_name))


def _recorded_plan_file_from_worktree(project_root: Path) -> str:
    provenance_path = Path(project_root) / _WORKTREE_PROVENANCE_PATH
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(provenance, dict):
        return ""
    return str(provenance.get("plan_file", "")).strip()


def _resolve_recorded_plan_file(repo_root: Path, recorded_plan: str) -> Path | None:
    normalized_plan = str(recorded_plan or "").strip()
    if not normalized_plan:
        return None
    normalized = Path(normalized_plan.replace("\\", "/").lstrip("./"))
    for root in (_PLANNING_ROOT, _DONE_PLANNING_ROOT):
        candidate = repo_root / root / normalized
        if candidate.is_file():
            return candidate.resolve()
    return None


def _feature_name_from_project_name(project_name: str) -> str:
    normalized = str(project_name).strip()
    return re.sub(r"-\d+$", "", normalized)


def _infer_plan_file_from_feature(repo_root: Path, *, feature_name: str) -> Path | None:
    normalized_feature = str(feature_name).strip()
    if not normalized_feature:
        return None
    active_matches = _plan_matches_for_feature(repo_root / _PLANNING_ROOT, feature_name=normalized_feature)
    if len(active_matches) == 1:
        return active_matches[0]
    if active_matches:
        return None
    archived_matches = _plan_matches_for_feature(repo_root / _DONE_PLANNING_ROOT, feature_name=normalized_feature)
    if len(archived_matches) == 1:
        return archived_matches[0]
    return None


def _plan_matches_for_feature(planning_root: Path, *, feature_name: str) -> list[Path]:
    if not planning_root.is_dir():
        return []
    matches: list[Path] = []
    for candidate in sorted(planning_root.glob("*/*.md")):
        if candidate.name == "README.md":
            continue
        relative = candidate.relative_to(planning_root)
        if planning_feature_name(str(relative).replace("\\", "/")) != feature_name:
            continue
        matches.append(candidate.resolve())
    return matches


def _active_plan_selector_for_path(*, repo_root: Path, plan_path: Path) -> str | None:
    planning_root = repo_root / _PLANNING_ROOT
    try:
        selector = str(plan_path.relative_to(planning_root)).replace("\\", "/")
    except ValueError:
        return None
    selector = selector.strip()
    if not selector:
        return None
    return selector


def resolve_plan_agent_launch_command(
    *,
    project_name: str,
    project_root: Path,
    repo_root: Path,
    envctl_executable: str = "envctl",
) -> str | None:
    plan_path = _review_original_plan_path(project_name, project_root, repo_root=repo_root)
    selector = (
        _active_plan_selector_for_path(repo_root=repo_root, plan_path=plan_path)
        if plan_path is not None
        else None
    )
    if not selector and _recorded_plan_file_from_worktree(project_root):
        return None
    if not selector:
        selector = f"{_feature_name_from_project_name(project_name)}.md"
    return " ".join(
        (
            shlex.quote(envctl_executable),
            "--repo",
            shlex.quote(_cli_display_path(repo_root)),
            "--plan",
            shlex.quote(selector),
            "--tmux",
            "--opencode",
            "--headless",
            "--new-session",
        )
    )


def _cli_display_path(path: Path) -> str:
    raw = str(path)
    if raw.startswith("/private/var/"):
        return raw.removeprefix("/private")
    return raw


__all__ = tuple(name for name in globals() if not name.startswith("__"))
