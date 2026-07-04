from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from envctl_engine.planning.worktree_code_intelligence_files import ensure_worktree_git_excludes
from envctl_engine.runtime.codex_tmux_support import _tmux_session_exists
from envctl_engine.runtime.runtime_context import resolve_process_runtime
from envctl_engine.shared.parsing import parse_bool


WORKTREE_PROVENANCE_SCHEMA_VERSION = 1
WORKTREE_PROVENANCE_PATH = Path(".envctl-state") / "worktree-provenance.json"
FRESH_AI_LAUNCH_IN_PROGRESS_TTL_SECONDS = 24 * 60 * 60


def write_worktree_provenance(
    self: Any,
    *,
    target: Path,
    plan_file: str | None = None,
    created_for_fresh_ai_launch: bool = False,
    launch_transport: str = "",
) -> None:
    provenance = build_worktree_provenance(
        self,
        plan_file=plan_file,
        created_for_fresh_ai_launch=created_for_fresh_ai_launch,
        launch_transport=launch_transport,
    )
    if provenance is None or not target.is_dir():
        return
    ensure_worktree_git_excludes(root=target, patterns=(".envctl-state/",))
    path = target / WORKTREE_PROVENANCE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return


def build_worktree_provenance(
    self: Any,
    *,
    plan_file: str | None = None,
    created_for_fresh_ai_launch: bool = False,
    launch_transport: str = "",
) -> dict[str, object] | None:
    invocation_branch = _invocation_worktree_branch(self)
    if invocation_branch:
        return _worktree_provenance_payload(
            self,
            source_branch=invocation_branch,
            resolution_reason="invocation_worktree_branch",
            plan_file=plan_file,
            created_for_fresh_ai_launch=created_for_fresh_ai_launch,
            launch_transport=launch_transport,
        )

    source_branch = git_command_output(self, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if source_branch and source_branch != "HEAD":
        return _worktree_provenance_payload(
            self,
            source_branch=source_branch,
            resolution_reason="attached_branch",
            plan_file=plan_file,
            created_for_fresh_ai_launch=created_for_fresh_ai_launch,
            launch_transport=launch_transport,
        )

    default_branch = detect_default_branch(self)
    if not default_branch:
        return None
    return _worktree_provenance_payload(
        self,
        source_branch=default_branch,
        resolution_reason="default_branch_detached_head",
        plan_file=plan_file,
        created_for_fresh_ai_launch=created_for_fresh_ai_launch,
        launch_transport=launch_transport,
    )


def _invocation_worktree_branch(self: Any) -> str:
    raw_cwd = str(getattr(self, "env", {}).get("ENVCTL_INVOCATION_CWD") or "").strip()
    if not raw_cwd:
        return ""
    try:
        invocation_cwd = Path(raw_cwd).resolve()
        repo_root = Path(self.config.base_dir).resolve()
    except OSError:
        return ""
    root_text = git_command_output_at(self, invocation_cwd, ["rev-parse", "--show-toplevel"]).strip()
    if not root_text:
        return ""
    try:
        invocation_root = Path(root_text).resolve()
    except OSError:
        return ""
    if invocation_root == repo_root:
        return ""
    branch = git_command_output_at(self, invocation_root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    return branch if branch and branch != "HEAD" else ""


def _worktree_provenance_payload(
    self: Any,
    *,
    source_branch: str,
    resolution_reason: str,
    plan_file: str | None = None,
    created_for_fresh_ai_launch: bool = False,
    launch_transport: str = "",
) -> dict[str, object]:
    source_ref = resolve_branch_ref(self, source_branch=source_branch)
    payload: dict[str, object] = {
        "schema_version": WORKTREE_PROVENANCE_SCHEMA_VERSION,
        "source_branch": source_branch,
        "source_ref": source_ref or source_branch,
        "resolution_reason": resolution_reason,
        "created_from_repo": str(self.config.base_dir.resolve()),
        "recorded_at": datetime.now(tz=UTC).isoformat(),
    }
    normalized_plan_file = str(plan_file or "").strip()
    if normalized_plan_file:
        payload["plan_file"] = normalized_plan_file
    if created_for_fresh_ai_launch:
        payload["created_for_fresh_ai_launch"] = True
        payload["fresh_ai_launch_status"] = "launching"
    normalized_transport = str(launch_transport or "").strip().lower()
    if normalized_transport:
        payload["launch_transport"] = normalized_transport
    return payload


def resolve_branch_ref(self: Any, *, source_branch: str) -> str:
    normalized = source_branch.strip()
    if not normalized:
        return ""
    for candidate in (f"origin/{normalized}", normalized):
        if git_command_output(self, ["rev-parse", "--verify", candidate]).strip():
            return candidate
    return normalized


def detect_default_branch(self: Any) -> str:
    ref = git_command_output(self, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"]).strip()
    if ref.startswith("origin/"):
        return ref.split("origin/", 1)[1]
    for candidate in ("main", "master"):
        if git_command_output(self, ["rev-parse", "--verify", candidate]).strip():
            return candidate
    return "main"


def git_command_output(self: Any, args: list[str]) -> str:
    return git_command_output_at(self, Path(self.config.base_dir), args)


def git_command_output_at(self: Any, cwd: Path, args: list[str]) -> str:
    result = resolve_process_runtime(self).run(
        ["git", "-C", str(cwd), *args],
        cwd=cwd,
        env=self._command_env(port=0),
        timeout=30.0,
    )
    if getattr(result, "returncode", 1) != 0:
        return ""
    return str(getattr(result, "stdout", ""))


def active_fresh_ai_worktree_protection_reason(
    self: Any,
    *,
    name: str,
    root: Path,
    tmux_session_exists: Callable[[Any, str], bool] = _tmux_session_exists,
) -> str:
    provenance = read_worktree_provenance(root)
    if not parse_bool(provenance.get("created_for_fresh_ai_launch"), False):
        return ""
    status = str(provenance.get("fresh_ai_launch_status") or "").strip().lower()
    if status in {"launching", "queued", "starting"}:
        recorded_at = str(provenance.get("recorded_at") or "").strip()
        if fresh_ai_launch_marker_is_fresh(recorded_at):
            return "fresh_ai_launch_in_progress"
    session_name = str(provenance.get("session_name") or provenance.get("native_session_id") or "").strip()
    if session_name and tmux_session_exists(self, session_name):
        return "active_ai_session"
    return ""


def fresh_ai_launch_marker_is_fresh(recorded_at: str) -> bool:
    if not recorded_at:
        return True
    try:
        parsed = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    age = datetime.now(tz=UTC) - parsed.astimezone(UTC)
    return age.total_seconds() <= FRESH_AI_LAUNCH_IN_PROGRESS_TTL_SECONDS


def read_worktree_provenance(root: Path) -> dict[str, object]:
    path = Path(root) / WORKTREE_PROVENANCE_PATH
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
