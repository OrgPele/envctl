from __future__ import annotations

# ruff: noqa: F403,F405
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.constants import *
from envctl_engine.planning.plan_agent.models import *
from envctl_engine.planning.plan_agent.recovery import _persist_runtime_events_snapshot, _print_launch_summary
from envctl_engine.planning.plan_agent.workflow import (
    _codex_goal_text_for_worktree,
    _emit_codex_goal_event,
    _tab_title_for_worktree,
    _workflow_step_prompt_text,
)


def _launch_plan_agent_superset_workspaces(
    runtime: Any,
    *,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
    base_payload: dict[str, object],
) -> PlanAgentLaunchResult:
    if launch_config.cli != "codex":
        runtime._emit("planning.agent_launch.failed", reason="unsupported_superset_cli", **base_payload)
        return PlanAgentLaunchResult(status="failed", reason="unsupported_superset_cli")
    if not launch_config.superset_workspace and not launch_config.superset_project:
        runtime._emit("planning.agent_launch.skipped", reason="missing_superset_project", **base_payload)
        _print_launch_summary(
            "Plan agent launch skipped: Superset transport requires "
            "ENVCTL_PLAN_AGENT_SUPERSET_PROJECT or ENVCTL_PLAN_AGENT_SUPERSET_WORKSPACE."
        )
        return PlanAgentLaunchResult(status="skipped", reason="missing_superset_project")
    if launch_config.codex_cycles > 0:
        runtime._emit(
            "planning.agent_launch.superset_cycles_unsupported",
            reason="superset_public_cli_single_prompt",
            transport="superset",
            codex_cycles=launch_config.codex_cycles,
        )

    outcomes: list[PlanAgentLaunchOutcome] = []
    for worktree in created_worktrees:
        outcomes.append(
            _launch_single_superset_worktree(
                runtime,
                launch_config=launch_config,
                workflow=workflow,
                worktree=worktree,
                base_payload=base_payload,
            )
        )

    launched = [item for item in outcomes if item.status == "launched"]
    failed = [item for item in outcomes if item.status == "failed"]
    if failed and launched:
        _print_launch_summary(
            f"Superset plan agent launch finished with partial success: launched {len(launched)}, failed {len(failed)}."
        )
        _print_superset_outcome_details(outcomes, launch_config=launch_config)
        return PlanAgentLaunchResult(status="partial", reason="partial_failure", outcomes=tuple(outcomes))
    if failed:
        _print_launch_summary(f"Superset plan agent launch failed for {len(failed)} worktree(s).")
        _print_superset_outcome_details(outcomes, launch_config=launch_config)
        return PlanAgentLaunchResult(status="failed", reason="launch_failed", outcomes=tuple(outcomes))
    _print_launch_summary(f"Superset plan agent launch started {len(launched)} workspace/agent run(s).")
    _print_superset_outcome_details(outcomes, launch_config=launch_config)
    return PlanAgentLaunchResult(status="launched", reason="launched", outcomes=tuple(outcomes))


def _launch_single_superset_worktree(
    runtime: Any,
    *,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
    base_payload: dict[str, object],
) -> PlanAgentLaunchOutcome:
    prompt, prompt_error = _superset_initial_prompt(
        runtime,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
    )
    if prompt_error:
        runtime._emit(
            "planning.agent_launch.failed",
            reason="prompt_resolution_failed",
            transport="superset",
            worktree=worktree.name,
            error=prompt_error,
            **base_payload,
        )
        return PlanAgentLaunchOutcome(worktree.name, worktree.root, None, "failed", prompt_error)

    if launch_config.superset_workspace:
        command = [
            "superset",
            "agents",
            "run",
            "--workspace",
            launch_config.superset_workspace,
            "--agent",
            launch_config.cli,
            "--prompt",
            prompt,
            "--json",
        ]
        event_name = "planning.agent_launch.superset_agent_run"
        event_payload = {
            "workspace_id": launch_config.superset_workspace,
            "project": launch_config.superset_project or None,
        }
    else:
        branch, branch_warning = _git_branch_name(runtime, worktree.root)
        if branch_warning:
            runtime._emit(
                "planning.agent_launch.superset_branch_fallback",
                transport="superset",
                worktree=worktree.name,
                reason=branch_warning,
                fallback=worktree.name,
            )
        command = ["superset", "workspaces", "create"]
        if launch_config.superset_host:
            command.extend(["--host", launch_config.superset_host])
        elif launch_config.superset_local:
            command.append("--local")
        # Superset's public CLI accepts project and branch, but not an explicit worktree path.
        command.extend(
            [
                "--project",
                launch_config.superset_project,
                "--name",
                _superset_workspace_name(worktree),
                "--branch",
                branch or worktree.name,
                "--agent",
                launch_config.cli,
                "--prompt",
                prompt,
                "--json",
            ]
        )
        event_name = "planning.agent_launch.superset_workspace_create"
        event_payload = {
            "workspace_id": None,
            "project": launch_config.superset_project,
        }

    runtime._emit(
        event_name,
        transport="superset",
        worktree=worktree.name,
        command_kind=command[1] if len(command) > 1 else "superset",
        **event_payload,
    )
    result = runtime.process_runner.run(
        command,
        cwd=Path(worktree.root),
        env=getattr(runtime, "env", {}),
        timeout=60.0,
    )
    if getattr(result, "returncode", 1) != 0:
        error = _completed_process_error_text(result)
        runtime._emit(
            "planning.agent_launch.failed",
            reason="superset_command_failed",
            transport="superset",
            worktree=worktree.name,
            error=error,
            **base_payload,
        )
        return PlanAgentLaunchOutcome(worktree.name, worktree.root, None, "failed", error)

    parsed = _parse_superset_json_output(str(getattr(result, "stdout", "") or ""))
    if parsed is None:
        runtime._emit(
            "planning.agent_launch.superset_debug_output",
            transport="superset",
            worktree=worktree.name,
            stdout=str(getattr(result, "stdout", "") or "").strip(),
        )
        workspace_id = launch_config.superset_workspace or None
    else:
        workspace_id = _workspace_id_from_superset_payload(parsed) or launch_config.superset_workspace or None
        runtime._emit(
            "planning.agent_launch.superset_result",
            transport="superset",
            worktree=worktree.name,
            workspace_id=workspace_id,
            project=launch_config.superset_project or None,
        )

    bridge_applied = False
    if workspace_id and parsed is not None:
        bridge_applied = _bridge_superset_desktop_workspace(
            runtime,
            launch_config=launch_config,
            worktree=worktree,
            workspace_id=workspace_id,
            payload=parsed,
        )

    outcome_reason = None
    if launch_config.superset_open and workspace_id:
        open_error = _open_superset_workspace(
            runtime,
            launch_config=launch_config,
            worktree=worktree,
            workspace_id=workspace_id,
        )
        if open_error:
            outcome_reason = f"open_failed: {open_error}"
        else:
            desktop_error = _verify_superset_desktop_workspace(runtime, worktree=worktree, workspace_id=workspace_id)
            if desktop_error and bridge_applied and _restart_superset_desktop(
                runtime,
                worktree=worktree,
                workspace_id=workspace_id,
            ):
                _open_superset_workspace(
                    runtime,
                    launch_config=launch_config,
                    worktree=worktree,
                    workspace_id=workspace_id,
                )
                desktop_error = _verify_superset_desktop_workspace(
                    runtime,
                    worktree=worktree,
                    workspace_id=workspace_id,
                )
            if desktop_error:
                runtime._emit(
                    "planning.agent_launch.superset_desktop_workspace_unavailable",
                    reason="superset_desktop_workspace_unavailable",
                    transport="superset",
                    worktree=worktree.name,
                    project=launch_config.superset_project or None,
                    workspace_id=workspace_id,
                    error=desktop_error,
                )
                _persist_runtime_events_snapshot(runtime)
                return PlanAgentLaunchOutcome(worktree.name, worktree.root, workspace_id, "failed", desktop_error)
    elif not workspace_id:
        outcome_reason = "workspace_id_unavailable"
    _persist_runtime_events_snapshot(runtime)
    return PlanAgentLaunchOutcome(worktree.name, worktree.root, workspace_id, "launched", outcome_reason)


def _superset_initial_prompt(
    runtime: Any,
    *,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
) -> tuple[str, str | None]:
    if not workflow.steps:
        return "", "prompt_resolution_failed: empty_workflow"
    step = workflow.steps[0]
    prompt, prompt_error = _workflow_step_prompt_text(
        runtime,
        launch_config=launch_config,
        cli=launch_config.cli,
        step=step,
        worktree=worktree,
    )
    if prompt_error is not None:
        return prompt, prompt_error
    if launch_config.cli != "codex" or not launch_config.codex_goal_enable:
        return prompt, None
    goal_text = _codex_goal_text_for_worktree(
        worktree=worktree,
        preset=launch_config.preset,
        workflow_mode=workflow.mode,
        omx_workflow=launch_config.omx_workflow,
    )
    _emit_codex_goal_event(
        runtime,
        "planning.agent_launch.codex_goal_embedded",
        cli=launch_config.cli,
        workflow=workflow,
        transport="superset",
        worktree=worktree,
    )
    return f"/goal {goal_text}\n\n{prompt}", None


def _git_branch_name(runtime: Any, cwd: Path) -> tuple[str, str | None]:
    result = runtime.process_runner.run(
        ["git", "-C", str(cwd), "branch", "--show-current"],
        cwd=cwd,
        env=getattr(runtime, "env", {}),
        timeout=10.0,
    )
    if getattr(result, "returncode", 1) != 0:
        return "", "git_branch_unavailable"
    branch = str(getattr(result, "stdout", "") or "").strip()
    if not branch:
        return "", "git_branch_unavailable"
    return branch, None


def _superset_workspace_name(worktree: CreatedPlanWorktree) -> str:
    return _tab_title_for_worktree(worktree.name)


def _open_superset_workspace(
    runtime: Any,
    *,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
    workspace_id: str,
) -> str | None:
    command = ["superset", "workspaces", "open", workspace_id]
    runtime._emit(
        "planning.agent_launch.superset_open",
        transport="superset",
        worktree=worktree.name,
        project=launch_config.superset_project or None,
        workspace_id=workspace_id,
        command_kind="open",
    )
    result = runtime.process_runner.run(
        command,
        cwd=Path(worktree.root),
        env=getattr(runtime, "env", {}),
        timeout=30.0,
    )
    if getattr(result, "returncode", 1) == 0:
        return None
    error = _completed_process_error_text(result)
    runtime._emit(
        "planning.agent_launch.superset_open_failed",
        reason="superset_open_failed",
        transport="superset",
        worktree=worktree.name,
        project=launch_config.superset_project or None,
        workspace_id=workspace_id,
        error=error,
    )
    return error


def _verify_superset_desktop_workspace(runtime: Any, *, worktree: CreatedPlanWorktree, workspace_id: str) -> str | None:
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


def _bridge_superset_desktop_workspace(
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
    workspace_payload = _workspace_payload_from_superset_payload(payload)
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


def _superset_desktop_bridge_disabled(env: dict[str, str]) -> bool:
    raw = str(env.get("ENVCTL_PLAN_AGENT_SUPERSET_DESKTOP_BRIDGE") or "").strip().lower()
    return raw in {"0", "false", "no", "off"}


def _workspace_payload_from_superset_payload(payload: dict[str, Any] | list[Any]) -> dict[str, Any]:
    if isinstance(payload, dict):
        workspace = payload.get("workspace")
        if isinstance(workspace, dict):
            return workspace
        return payload
    for item in payload:
        if isinstance(item, dict):
            found = _workspace_payload_from_superset_payload(item)
            if found:
                return found
    return {}


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


def _restart_superset_desktop(runtime: Any, *, worktree: CreatedPlanWorktree, workspace_id: str) -> bool:
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
                error=_completed_process_error_text(result),
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


def _print_superset_outcome_details(
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


def _parse_superset_json_output(stdout: str) -> dict[str, Any] | list[Any] | None:
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


def _workspace_id_from_superset_payload(payload: dict[str, Any] | list[Any]) -> str | None:
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                found = _workspace_id_from_superset_payload(item)
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


def _completed_process_error_text(result: object) -> str:
    stderr = str(getattr(result, "stderr", "") or "").strip()
    stdout = str(getattr(result, "stdout", "") or "").strip()
    if stderr and stdout:
        return f"{stderr}\n{stdout}"
    if stderr:
        return stderr
    if stdout:
        return stdout
    return f"exit:{getattr(result, 'returncode', 1)}"


__all__ = tuple(name for name in globals() if not name.startswith("__"))
