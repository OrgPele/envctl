from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree, PlanAgentLaunchConfig, PlanAgentLaunchOutcome
from envctl_engine.planning.plan_agent.recovery import _print_launch_summary
from envctl_engine.planning.plan_agent.workflow import _tab_title_for_worktree


def verify_superset_desktop_workspace(runtime: Any, *, worktree: CreatedPlanWorktree, workspace_id: str) -> str | None:
    env = getattr(runtime, "env", {}) or {}
    if _superset_desktop_verify_disabled(env):
        return None
    home = str(env.get("HOME") or "").strip()
    if not home:
        return None
    db_path = Path(home) / ".superset" / "local.db"
    if not db_path.exists():
        return None

    deadline = time.monotonic() + _superset_desktop_verify_timeout_seconds(env)
    while True:
        state = _superset_desktop_workspace_state(db_path, workspace_id=workspace_id)
        if state == "present":
            runtime._emit(
                "planning.agent_launch.superset_desktop_workspace_ready",
                transport="superset",
                worktree=worktree.name,
                workspace_id=workspace_id,
            )
            return None
        if state not in {"missing", "locked"}:
            return None
        if time.monotonic() >= deadline:
            return (
                "Superset CLI returned workspace "
                f"{workspace_id}, but Superset desktop could not resolve it from {db_path}."
            )
        time.sleep(0.25)


def bridge_superset_desktop_workspace(
    runtime: Any,
    *,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
    workspace_id: str,
    payload: dict[str, Any] | list[Any],
) -> bool:
    env = getattr(runtime, "env", {}) or {}
    if _superset_desktop_bridge_disabled(env):
        return False
    home = str(env.get("HOME") or "").strip()
    if not home:
        return False
    home_path = Path(home)
    local_db = home_path / ".superset" / "local.db"
    tanstack_db = home_path / ".superset" / "tanstack-db.sqlite"
    if not local_db.exists() or not tanstack_db.exists():
        return False
    workspace_payload = workspace_payload_from_superset_payload(payload)
    if not workspace_payload:
        return False

    project_id = str(workspace_payload.get("projectId") or launch_config.superset_project or "").strip()
    if not project_id:
        return False
    host_id = str(workspace_payload.get("hostId") or "").strip()
    host_workspace = _superset_host_workspace(home_path, host_id=host_id, workspace_id=workspace_id)
    host_project = _superset_host_project(home_path, host_id=host_id, project_id=project_id)
    now_ms = _epoch_ms(workspace_payload.get("createdAt")) or int(time.time() * 1000)
    workspace_name = str(workspace_payload.get("name") or _superset_workspace_name(worktree)).strip() or worktree.name
    branch = str(workspace_payload.get("branch") or "").strip() or worktree.name
    worktree_path = str(host_workspace.get("worktree_path") or worktree.root).strip()
    project_root = str(host_project.get("repo_path") or worktree.root).strip()
    project_name = str(host_project.get("repo_name") or project_id).strip() or project_id
    github_owner = str(host_project.get("repo_owner") or "").strip() or None
    created_by = str(workspace_payload.get("createdByUserId") or "").strip() or None
    organization_id = str(workspace_payload.get("organizationId") or "").strip()
    tanstack_metadata = '{"relation":["public","v2_workspaces"],"operation":"insert"}'

    try:
        with sqlite3.connect(local_db, timeout=1.0) as connection:
            connection.execute("pragma busy_timeout=1000")
            connection.execute(
                """
                insert or ignore into projects
                (
                    id, main_repo_path, name, color, tab_order, last_opened_at, created_at,
                    default_branch, github_owner, default_app
                )
                values (?, ?, ?, 'default', 1, ?, ?, 'main', ?, 'finder')
                """,
                (project_id, project_root, project_name, now_ms, now_ms, github_owner),
            )
            connection.execute(
                """
                insert or replace into worktrees
                (id, project_id, path, branch, base_branch, created_at, created_by_superset)
                values (?, ?, ?, ?, 'main', ?, 1)
                """,
                (workspace_id, project_id, worktree_path, branch, now_ms),
            )
            connection.execute(
                """
                insert or replace into workspaces
                (
                    id, project_id, worktree_id, type, branch, name, tab_order, created_at,
                    updated_at, last_opened_at, is_unread, is_unnamed
                )
                values (?, ?, ?, 'worktree', ?, ?, 1, ?, ?, ?, 0, 0)
                """,
                (workspace_id, project_id, workspace_id, branch, workspace_name, now_ms, now_ms, now_ms),
            )
            connection.commit()
    except sqlite3.Error as exc:
        runtime._emit(
            "planning.agent_launch.superset_desktop_bridge_failed",
            reason="local_db_write_failed",
            transport="superset",
            worktree=worktree.name,
            workspace_id=workspace_id,
            error=str(exc),
        )
        return False

    try:
        with sqlite3.connect(tanstack_db, timeout=1.0) as connection:
            connection.execute("pragma busy_timeout=1000")
            workspace_table = _superset_tanstack_collection_table(
                connection,
                collection_id=f"v2_workspaces-{organization_id}",
            )
            if not workspace_table:
                runtime._emit(
                    "planning.agent_launch.superset_desktop_bridge_failed",
                    reason="tanstack_workspace_collection_missing",
                    transport="superset",
                    worktree=worktree.name,
                    workspace_id=workspace_id,
                    collection=f"v2_workspaces-{organization_id}",
                )
                return False
            connection.execute(
                f"""
                insert or replace into {workspace_table} (key, value, metadata, row_version)
                values (?, ?, ?, 2)
                """,
                (
                    f"s:{workspace_id}",
                    json.dumps(
                        {
                            "branch": branch,
                            "createdAt": _superset_timestamp(workspace_payload.get("createdAt"), now_ms),
                            "createdByUserId": created_by,
                            "hostId": host_id or None,
                            "id": workspace_id,
                            "name": workspace_name,
                            "organizationId": organization_id or None,
                            "projectId": project_id,
                            "taskId": workspace_payload.get("taskId"),
                            "type": "worktree",
                            "updatedAt": _superset_timestamp(workspace_payload.get("updatedAt"), now_ms),
                        },
                        separators=(",", ":"),
                    ),
                    tanstack_metadata,
                ),
            )
            connection.commit()
    except sqlite3.Error as exc:
        runtime._emit(
            "planning.agent_launch.superset_desktop_bridge_failed",
            reason="tanstack_db_write_failed",
            transport="superset",
            worktree=worktree.name,
            workspace_id=workspace_id,
            error=str(exc),
        )
        return False

    runtime._emit(
        "planning.agent_launch.superset_desktop_bridge",
        transport="superset",
        worktree=worktree.name,
        workspace_id=workspace_id,
        project=project_id,
    )
    return True


def restart_superset_desktop(runtime: Any, *, worktree: CreatedPlanWorktree, workspace_id: str) -> bool:
    env = getattr(runtime, "env", {}) or {}
    raw = str(env.get("ENVCTL_PLAN_AGENT_SUPERSET_DESKTOP_RESTART") or "true").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    for command in (
        ["osascript", "-e", 'quit app "Superset"'],
        ["open", "/Applications/Superset.app"],
    ):
        result = runtime.process_runner.run(command, cwd=Path(worktree.root), env=env, timeout=15.0)
        if getattr(result, "returncode", 1) != 0 and command[0] != "osascript":
            runtime._emit(
                "planning.agent_launch.superset_desktop_restart_failed",
                transport="superset",
                worktree=worktree.name,
                workspace_id=workspace_id,
                error=superset_completed_process_error_text(result),
            )
            return False
        time.sleep(2.0)
    runtime._emit(
        "planning.agent_launch.superset_desktop_restart",
        transport="superset",
        worktree=worktree.name,
        workspace_id=workspace_id,
    )
    return True


def print_superset_outcome_details(
    outcomes: list[PlanAgentLaunchOutcome],
    *,
    launch_config: PlanAgentLaunchConfig,
) -> None:
    for outcome in outcomes:
        if outcome.status == "failed":
            suffix = f": {outcome.reason}" if outcome.reason else ""
            _print_launch_summary(f"  - {outcome.worktree_name}: failed{suffix}")
            continue
        workspace_id = str(outcome.surface_id or "").strip()
        if workspace_id:
            _print_launch_summary(f"  - {outcome.worktree_name}: launched Superset workspace {workspace_id}")
            if not launch_config.superset_open:
                _print_launch_summary(f"    open: superset workspaces open {workspace_id}")
        else:
            _print_launch_summary(
                f"  - {outcome.worktree_name}: Superset command succeeded, but no workspace id was returned."
            )
        reason = str(outcome.reason or "").strip()
        if reason.startswith("open_failed:"):
            _print_launch_summary(f"    open failed: {reason.removeprefix('open_failed:').strip()}")
        elif reason.startswith("Superset CLI returned workspace"):
            _print_launch_summary(f"    desktop unavailable: {reason}")


def parse_superset_json_output(stdout: str) -> dict[str, Any] | list[Any] | None:
    text = str(stdout or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, (dict, list)):
        return parsed
    return None


def workspace_id_from_superset_payload(payload: dict[str, Any] | list[Any]) -> str | None:
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                found = workspace_id_from_superset_payload(item)
                if found:
                    return found
        return None
    workspace = payload.get("workspace")
    if isinstance(workspace, dict):
        workspace_id = str(workspace.get("id") or "").strip()
        if workspace_id:
            return workspace_id
    workspace_id = str(payload.get("workspace_id") or payload.get("id") or "").strip()
    if workspace_id:
        return workspace_id
    agents = payload.get("agents")
    if isinstance(agents, list):
        for item in agents:
            if isinstance(item, dict):
                workspace_id = str(item.get("workspace_id") or "").strip()
                if workspace_id:
                    return workspace_id
    return None


def workspace_payload_from_superset_payload(payload: dict[str, Any] | list[Any]) -> dict[str, Any]:
    if isinstance(payload, dict):
        workspace = payload.get("workspace")
        if isinstance(workspace, dict):
            return workspace
        return payload
    for item in payload:
        if isinstance(item, dict):
            found = workspace_payload_from_superset_payload(item)
            if found:
                return found
    return {}


def superset_completed_process_error_text(result: object) -> str:
    stderr = str(getattr(result, "stderr", "") or "").strip()
    stdout = str(getattr(result, "stdout", "") or "").strip()
    if stderr and stdout:
        return f"{stderr}\n{stdout}"
    if stderr:
        return stderr
    if stdout:
        return stdout
    return f"exit:{getattr(result, 'returncode', 1)}"


def _superset_desktop_verify_disabled(env: dict[str, str]) -> bool:
    raw = str(env.get("ENVCTL_PLAN_AGENT_SUPERSET_DESKTOP_VERIFY") or "").strip().lower()
    return raw in {"0", "false", "no", "off"}


def _superset_desktop_verify_timeout_seconds(env: dict[str, str]) -> float:
    raw = str(env.get("ENVCTL_PLAN_AGENT_SUPERSET_DESKTOP_VERIFY_TIMEOUT") or "").strip()
    if not raw:
        return 5.0
    try:
        value = float(raw)
    except ValueError:
        return 5.0
    return max(0.0, min(value, 30.0))


def _superset_desktop_workspace_state(db_path: Path, *, workspace_id: str) -> str:
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=0.2) as connection:
            row = connection.execute("select 1 from workspaces where id = ? limit 1", (workspace_id,)).fetchone()
    except sqlite3.OperationalError as exc:
        message = str(exc).lower()
        if "locked" in message or "busy" in message:
            return "locked"
        return "unavailable"
    except sqlite3.Error:
        return "unavailable"
    return "present" if row else "missing"


def _superset_desktop_bridge_disabled(env: dict[str, str]) -> bool:
    raw = str(env.get("ENVCTL_PLAN_AGENT_SUPERSET_DESKTOP_BRIDGE") or "").strip().lower()
    return raw in {"0", "false", "no", "off"}


def _superset_tanstack_collection_table(connection: sqlite3.Connection, *, collection_id: str) -> str:
    if not collection_id or collection_id.endswith("-"):
        return ""
    try:
        row = connection.execute(
            "select table_name from collection_registry where collection_id = ? limit 1",
            (collection_id,),
        ).fetchone()
    except sqlite3.Error:
        return ""
    if not row:
        return ""
    table_name = str(row[0] or "").strip()
    if not table_name.replace("_", "").isalnum() or not table_name.startswith("c_"):
        return ""
    try:
        exists = connection.execute(
            "select 1 from sqlite_master where type = 'table' and name = ? limit 1",
            (table_name,),
        ).fetchone()
    except sqlite3.Error:
        return ""
    return table_name if exists else ""


def _superset_host_workspace(home: Path, *, host_id: str, workspace_id: str) -> dict[str, object]:
    host_db = home / ".superset" / "host" / host_id / "host.db"
    if not host_id or not host_db.exists():
        return {}
    try:
        with sqlite3.connect(f"file:{host_db}?mode=ro", uri=True, timeout=0.2) as connection:
            row = connection.execute(
                "select worktree_path, branch, created_at from workspaces where id = ? limit 1",
                (workspace_id,),
            ).fetchone()
    except sqlite3.Error:
        return {}
    if not row:
        return {}
    return {"worktree_path": row[0], "branch": row[1], "created_at": row[2]}


def _superset_host_project(home: Path, *, host_id: str, project_id: str) -> dict[str, object]:
    host_db = home / ".superset" / "host" / host_id / "host.db"
    if not host_id or not host_db.exists():
        return {}
    try:
        with sqlite3.connect(f"file:{host_db}?mode=ro", uri=True, timeout=0.2) as connection:
            row = connection.execute(
                "select repo_path, repo_owner, repo_name, created_at from projects where id = ? limit 1",
                (project_id,),
            ).fetchone()
    except sqlite3.Error:
        return {}
    if not row:
        return {}
    return {"repo_path": row[0], "repo_owner": row[1], "repo_name": row[2], "created_at": row[3]}


def _epoch_ms(value: object) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def _superset_timestamp(value: object, fallback_ms: int) -> str:
    text = str(value or "").strip()
    if text:
        return text.replace("T", " ").replace("Z", "+00")
    return datetime.fromtimestamp(fallback_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f+00")


def _superset_workspace_name(worktree: CreatedPlanWorktree) -> str:
    return _tab_title_for_worktree(worktree.name)


__all__ = tuple(name for name in globals() if not name.startswith("_"))
