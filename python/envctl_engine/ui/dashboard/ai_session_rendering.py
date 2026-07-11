from __future__ import annotations

import json
from pathlib import Path
import re
import shlex
from typing import Any, Callable

from envctl_engine.state.models import RunState


def print_dashboard_ai_session_row(
    self: Any,
    *,
    state: RunState,
    project: str,
    gray: str,
    dim: str,
    reset: str,
    render_launch_fallback: bool,
    project_root_fn: Callable[..., Path | None],
    current_tmux_target_fn: Callable[..., tuple[str, str]],
) -> None:
    import subprocess  # noqa: PLC0415
    from envctl_engine.planning.plan_agent.workflow_review_support import (  # noqa: PLC0415
        resolve_plan_agent_launch_command,
    )
    from envctl_engine.runtime.session_management import list_tmux_sessions  # noqa: PLC0415

    project_root = project_root_fn(self, state=state, project=project)
    repo_root = dashboard_repo_root_for_project(project_root=project_root)
    envctl_executable = "envctl"
    launch_command = None
    if project_root is not None and repo_root is not None:
        launch_command = resolve_plan_agent_launch_command(
            project_name=project,
            project_root=project_root,
            repo_root=repo_root,
            envctl_executable=envctl_executable,
        )
    if launch_command is None and project_root is not None:
        launch_command = _dashboard_worktree_ai_launch_command(
            project_root=project_root,
            envctl_executable=envctl_executable,
        )
    sessions = list_tmux_sessions()
    matching = [
        session
        for session in sessions
        if _dashboard_session_matches_project(project_root=project_root, project=project, session=session)
    ]
    current_session, current_path = current_tmux_target_fn(subprocess_module=subprocess)
    if matching:
        for session in matching:
            if _dashboard_session_is_attached(
                project_root=project_root,
                session=session,
                current_session=current_session,
                current_path=current_path,
            ):
                session_message = "attached"
            else:
                session_message = "detached"
            print(f"    {gray}AI session:{reset} {dim}{session['attach']} ({session_message}){reset}")
        return
    if not render_launch_fallback or not launch_command:
        return
    print(f"    {dim}○{reset} {gray}Run AI:{reset} {dim}{launch_command}{reset}")


def _dashboard_session_matches_project(*, project_root: Path | None, project: str, session: dict[str, str]) -> bool:
    if project_root is not None and _dashboard_session_matches_project_root(project_root=project_root, session=session):
        return True
    if project_root is not None and _dashboard_session_name_matches_envctl_plan_agent(
        project_root=project_root,
        project=project,
        session_name=str(session.get("name", "") or ""),
    ):
        return True
    if _dashboard_session_name_matches_project(project=project, session_name=str(session.get("name", "") or "")):
        return True
    return _dashboard_window_matches_project(project=project, window_name=str(session.get("windows", "") or ""))


def _dashboard_session_is_attached(
    *,
    project_root: Path | None,
    session: dict[str, str],
    current_session: str,
    current_path: str,
) -> bool:
    if str(session.get("name", "") or "").strip() != current_session:
        return False
    if project_root is None:
        return False
    return _dashboard_path_matches_project_root(project_root=project_root, candidate_path=current_path)


def _dashboard_window_matches_project(*, project: str, window_name: str) -> bool:
    from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree  # noqa: PLC0415
    from envctl_engine.planning.plan_agent.tmux_transport import _tmux_window_name_for_worktree  # noqa: PLC0415

    expected_window = _tmux_window_name_for_worktree(CreatedPlanWorktree(name=project, root=Path("."), plan_file=""))
    normalized_expected = str(expected_window).strip().lower()
    normalized_windows = {part.strip().lower() for part in str(window_name).split(",") if part.strip()}
    return normalized_expected in normalized_windows


def _dashboard_session_name_matches_envctl_plan_agent(*, project_root: Path, project: str, session_name: str) -> bool:
    from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree  # noqa: PLC0415
    from envctl_engine.planning.plan_agent.tmux_transport import _tmux_session_name_for_worktree  # noqa: PLC0415

    normalized_session = str(session_name or "").strip().lower()
    if not normalized_session:
        return False
    repo_root = dashboard_repo_root_for_project(project_root=project_root)
    if repo_root is None:
        return False
    try:
        worktree = CreatedPlanWorktree(name=project, root=project_root.resolve(strict=False), plan_file="")
        expected_names = {
            _tmux_session_name_for_worktree(repo_root, worktree, cli=cli).lower()
            for cli in ("codex", "opencode")
        }
    except (OSError, ValueError):
        return False
    return any(
        normalized_session == expected or normalized_session.startswith(f"{expected}-") for expected in expected_names
    )


def _dashboard_session_name_matches_project(*, project: str, session_name: str) -> bool:
    project_feature = _dashboard_project_feature_slug(project)
    session_feature = _dashboard_omx_session_feature_slug(session_name)
    return bool(project_feature and session_feature and project_feature == session_feature)


def _dashboard_project_feature_slug(project: str) -> str:
    normalized = str(project or "").strip()
    normalized = re.sub(r"-\d+$", "", normalized)
    return _dashboard_normalized_feature_slug(normalized)


def _dashboard_omx_session_feature_slug(session_name: str) -> str:
    normalized = str(session_name or "").strip().lower()
    match = re.fullmatch(r"omx-\d+-(?P<feature>.+)-\d+-[a-z0-9]+", normalized)
    if match is None:
        return ""
    feature = re.sub(r"-\d+$", "", match.group("feature"))
    return _dashboard_normalized_feature_slug(feature)


def _dashboard_normalized_feature_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")


def _dashboard_project_root_from_state(*, state: RunState, project: str) -> Path | None:
    metadata_roots = state.metadata.get("project_roots")
    if not isinstance(metadata_roots, dict):
        return None
    root_raw = str(metadata_roots.get(project, "") or "").strip()
    if not root_raw:
        return None
    return Path(root_raw).expanduser().resolve(strict=False)


def dashboard_repo_root_for_project(*, project_root: Path | None) -> Path | None:
    if project_root is None:
        return None
    provenance_repo_root = _dashboard_repo_root_from_provenance(project_root=project_root)
    if provenance_repo_root is not None:
        return provenance_repo_root
    tree_layout_repo_root = _dashboard_repo_root_from_tree_layout(project_root=project_root)
    if tree_layout_repo_root is not None:
        return tree_layout_repo_root
    current = project_root.resolve(strict=False)
    for candidate in (current, *current.parents):
        if (candidate / "todo" / "plans").is_dir() or (candidate / "todo" / "done").is_dir():
            return candidate
    for candidate in (current, *current.parents):
        if (candidate / "todo").is_dir():
            return candidate
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _dashboard_repo_root_from_provenance(*, project_root: Path) -> Path | None:
    provenance_path = project_root / ".envctl-state" / "worktree-provenance.json"
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(provenance, dict):
        return None
    repo_root_raw = str(provenance.get("created_from_repo", "") or "").strip()
    if not repo_root_raw:
        return None
    repo_root = Path(repo_root_raw).expanduser().resolve(strict=False)
    if (repo_root / ".git").exists() or (repo_root / "todo").is_dir():
        return repo_root
    return None


def _dashboard_repo_root_from_tree_layout(*, project_root: Path) -> Path | None:
    current = project_root.resolve(strict=False)
    for trees_dir in current.parents:
        if trees_dir.name != "trees":
            continue
        repo_root = trees_dir.parent
        if repo_root == current:
            continue
        try:
            current.relative_to(trees_dir)
        except ValueError:
            continue
        if (repo_root / "todo" / "plans").is_dir() or (repo_root / "todo" / "done").is_dir():
            return repo_root
        if (repo_root / ".git").exists() and (repo_root / "todo").is_dir():
            return repo_root
    return None


def _dashboard_worktree_ai_launch_command(*, project_root: Path, envctl_executable: str) -> str | None:
    root = project_root.expanduser().resolve(strict=False)
    if not (root / "MAIN_TASK.md").is_file():
        return None
    return " ".join(
        (
            shlex.quote(envctl_executable),
            "--repo",
            shlex.quote(_dashboard_cli_display_path(root)),
            "codex-tmux",
        )
    )


def _dashboard_cli_display_path(path: Path) -> str:
    raw = str(path)
    if raw.startswith("/private/var/"):
        return raw.removeprefix("/private")
    return raw


def _dashboard_session_matches_project_root(*, project_root: Path, session: dict[str, str]) -> bool:
    paths_raw = str(session.get("paths", "") or "")
    if not paths_raw:
        return False
    for raw_path in paths_raw.splitlines():
        candidate = str(raw_path).strip()
        if not candidate:
            continue
        if _dashboard_path_matches_project_root(project_root=project_root, candidate_path=candidate):
            return True
    return False


def _dashboard_path_matches_project_root(*, project_root: Path, candidate_path: str) -> bool:
    normalized_project_root = str(project_root.resolve(strict=False))
    normalized_candidate = str(candidate_path).replace(" (deleted)", "").strip()
    if not normalized_candidate:
        return False
    try:
        resolved_candidate = str(Path(normalized_candidate).expanduser().resolve(strict=False))
    except Exception:
        resolved_candidate = normalized_candidate
    if resolved_candidate == normalized_project_root:
        return True
    return resolved_candidate.startswith(f"{normalized_project_root}/")


def dashboard_current_tmux_target(*, subprocess_module: Any) -> tuple[str, str]:
    try:
        result = subprocess_module.run(
            ["tmux", "display-message", "-p", "#{session_name}\n#{pane_current_path}"],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except Exception:
        return "", ""
    if result.returncode != 0:
        return "", ""
    lines = [line.strip() for line in str(result.stdout or "").splitlines() if line.strip()]
    if len(lines) < 2:
        return "", ""
    return lines[0], lines[1]

_dashboard_repo_root_for_project = dashboard_repo_root_for_project
_dashboard_current_tmux_target = dashboard_current_tmux_target
