from __future__ import annotations

# ruff: noqa: F403,F405
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.constants import *
from envctl_engine.planning.plan_agent.models import *
from envctl_engine.planning.plan_agent.recovery import _persist_runtime_events_snapshot, _print_launch_summary
from envctl_engine.planning.plan_agent.superset_desktop_support import (
    bridge_superset_desktop_workspace,
    parse_superset_json_output,
    print_superset_outcome_details,
    restart_superset_desktop,
    superset_completed_process_error_text,
    verify_superset_desktop_workspace,
    workspace_id_from_superset_payload,
)
from envctl_engine.planning.plan_agent.workflow import (
    _codex_goal_text_for_worktree,
    _emit_codex_goal_event,
    _tab_title_for_worktree,
    _workflow_step_prompt_text,
)


_SUPERSET_CODEX_GOAL_AGENT_ID = "0e19b1f7-51b4-45a1-84c1-0d9c5d6dbb5f"
_SUPERSET_CODEX_GOAL_LAUNCHER = r'''#!/usr/bin/env python3
from __future__ import annotations

import json
import fcntl
import os
import pty
import select
import signal
import struct
import sys
import termios
import time
import tty


def _load_payload() -> tuple[str, str]:
    raw = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return "", raw
    if not isinstance(payload, dict):
        return "", raw
    return str(payload.get("goal") or ""), str(payload.get("prompt") or "")


def _paste(fd: int, text: str) -> None:
    os.write(fd, b"\x1b[200~")
    os.write(fd, text.encode("utf-8", "replace"))
    os.write(fd, b"\x1b[201~")


def _resize_child(master_fd: int, source_fd: int) -> None:
    try:
        packed = fcntl.ioctl(source_fd, termios.TIOCGWINSZ, b"\0" * 8)
        rows, cols, xpix, ypix = struct.unpack("HHHH", packed)
    except OSError:
        rows, cols, xpix, ypix = 24, 120, 0, 0
    if rows <= 0:
        rows = 24
    if cols <= 0:
        cols = 120
    try:
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, xpix, ypix))
    except OSError:
        pass


def main() -> int:
    goal, prompt = _load_payload()
    pid, master_fd = pty.fork()
    if pid == 0:
        os.execvp("codex", ["codex", "--dangerously-bypass-approvals-and-sandbox"])

    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    resize_requested = True

    def _request_resize(_signum: int, _frame: object) -> None:
        nonlocal resize_requested
        resize_requested = True

    signal.signal(signal.SIGWINCH, _request_resize)
    old_attrs = None
    if os.isatty(stdin_fd):
        old_attrs = termios.tcgetattr(stdin_fd)
        tty.setraw(stdin_fd)

    buffer = b""
    goal_typed = not goal
    goal_submit_attempts = 0
    goal_next_submit_at = 0.0
    prompt_pasted = not prompt
    prompt_submit_attempts = 0
    prompt_next_submit_at = 0.0
    start = time.monotonic()
    try:
        while True:
            if resize_requested:
                resize_requested = False
                _resize_child(master_fd, stdout_fd if os.isatty(stdout_fd) else stdin_fd)
            readable, _, _ = select.select([master_fd, stdin_fd], [], [], 0.05)
            if master_fd in readable:
                try:
                    data = os.read(master_fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                os.write(stdout_fd, data)
                buffer = (buffer + data)[-20000:]

            if stdin_fd in readable:
                try:
                    data = os.read(stdin_fd, 65536)
                except OSError:
                    data = b""
                if data:
                    os.write(master_fd, data)

            now = time.monotonic()
            if not goal_typed and (b"OpenAI Codex" in buffer or b"Tip:" in buffer or now - start > 8.0):
                os.write(master_fd, f"/goal {goal}".encode("utf-8", "replace"))
                goal_typed = True
                goal_next_submit_at = now + 0.25

            if goal_typed and not prompt_pasted and b"Goal active" not in buffer and goal_submit_attempts < 6:
                if now >= goal_next_submit_at:
                    os.write(master_fd, b"\r")
                    os.write(master_fd, b"\n")
                    goal_submit_attempts += 1
                    goal_next_submit_at = now + 0.75

            if goal_typed and not prompt_pasted:
                if b"Goal active" in buffer:
                    _paste(master_fd, prompt)
                    prompt_pasted = True
                    prompt_next_submit_at = now + 0.25

            if prompt_pasted and prompt_submit_attempts < 6:
                if now >= prompt_next_submit_at:
                    os.write(master_fd, b"\r")
                    os.write(master_fd, b"\n")
                    prompt_submit_attempts += 1
                    prompt_next_submit_at = now + 0.75

            try:
                finished_pid, status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                return 0
            if finished_pid == pid:
                if os.WIFEXITED(status):
                    return os.WEXITSTATUS(status)
                if os.WIFSIGNALED(status):
                    return 128 + os.WTERMSIG(status)
                return 0
    finally:
        if old_attrs is not None:
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_attrs)
        try:
            os.kill(pid, signal.SIGHUP)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


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
        print_superset_outcome_details(outcomes, launch_config=launch_config)
        return PlanAgentLaunchResult(status="partial", reason="partial_failure", outcomes=tuple(outcomes))
    if failed:
        _print_launch_summary(f"Superset plan agent launch failed for {len(failed)} worktree(s).")
        print_superset_outcome_details(outcomes, launch_config=launch_config)
        return PlanAgentLaunchResult(status="failed", reason="launch_failed", outcomes=tuple(outcomes))
    _print_launch_summary(f"Superset plan agent launch started {len(launched)} workspace/agent run(s).")
    print_superset_outcome_details(outcomes, launch_config=launch_config)
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
    agent, prompt = _superset_agent_and_prompt(
        runtime,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
        prompt=prompt,
    )

    if launch_config.superset_workspace:
        command = [
            "superset",
            "agents",
            "run",
            "--workspace",
            launch_config.superset_workspace,
            "--agent",
            agent,
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
                agent,
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
        error = superset_completed_process_error_text(result)
        runtime._emit(
            "planning.agent_launch.failed",
            reason="superset_command_failed",
            transport="superset",
            worktree=worktree.name,
            error=error,
            **base_payload,
        )
        return PlanAgentLaunchOutcome(worktree.name, worktree.root, None, "failed", error)

    parsed = parse_superset_json_output(str(getattr(result, "stdout", "") or ""))
    if parsed is None:
        runtime._emit(
            "planning.agent_launch.superset_debug_output",
            transport="superset",
            worktree=worktree.name,
            stdout=str(getattr(result, "stdout", "") or "").strip(),
        )
        workspace_id = launch_config.superset_workspace or None
    else:
        workspace_id = workspace_id_from_superset_payload(parsed) or launch_config.superset_workspace or None
        runtime._emit(
            "planning.agent_launch.superset_result",
            transport="superset",
            worktree=worktree.name,
            workspace_id=workspace_id,
            project=launch_config.superset_project or None,
        )

    bridge_applied = False
    if workspace_id and parsed is not None:
        bridge_applied = bridge_superset_desktop_workspace(
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
            desktop_error = verify_superset_desktop_workspace(runtime, worktree=worktree, workspace_id=workspace_id)
            if desktop_error and bridge_applied and restart_superset_desktop(
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
                desktop_error = verify_superset_desktop_workspace(
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
    return prompt, None


def _superset_agent_and_prompt(
    runtime: Any,
    *,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
    prompt: str,
) -> tuple[str, str]:
    if launch_config.cli != "codex" or not launch_config.codex_goal_enable:
        return launch_config.cli, prompt
    goal_text = _codex_goal_text_for_worktree(
        worktree=worktree,
        preset=launch_config.preset,
        workflow_mode=workflow.mode,
        omx_workflow=launch_config.omx_workflow,
    )
    agent_id, error = _ensure_superset_codex_goal_agent(runtime, worktree=worktree)
    if error:
        _emit_codex_goal_event(
            runtime,
            "planning.agent_launch.codex_goal_fallback",
            cli=launch_config.cli,
            workflow=workflow,
            transport="superset",
            worktree=worktree,
            reason=error,
        )
        return launch_config.cli, prompt
    _emit_codex_goal_event(
        runtime,
        "planning.agent_launch.codex_goal_launcher_prepared",
        cli=launch_config.cli,
        workflow=workflow,
        transport="superset",
        worktree=worktree,
    )
    return agent_id, json.dumps({"version": 1, "goal": goal_text, "prompt": prompt}, separators=(",", ":"))


def _ensure_superset_codex_goal_agent(runtime: Any, *, worktree: CreatedPlanWorktree) -> tuple[str, str | None]:
    env = getattr(runtime, "env", {}) or {}
    home = str(env.get("HOME") or os.environ.get("HOME") or "").strip()
    if not home:
        return "", "superset_home_unavailable"
    launcher, launcher_error = _write_superset_codex_goal_launcher(Path(worktree.root))
    if launcher_error:
        return "", launcher_error
    host_db = _superset_host_agent_db(Path(home))
    if host_db is None:
        return "", "superset_host_db_unavailable"
    now_ms = int(time.time() * 1000)
    try:
        with sqlite3.connect(host_db, timeout=1.0) as connection:
            connection.execute("pragma busy_timeout=1000")
            row = connection.execute(
                "select display_order from host_agent_configs where id = ? limit 1",
                (_SUPERSET_CODEX_GOAL_AGENT_ID,),
            ).fetchone()
            if row:
                display_order = int(row[0] or 0)
            else:
                max_row = connection.execute(
                    "select coalesce(max(display_order), -1) from host_agent_configs"
                ).fetchone()
                display_order = int(max_row[0] if max_row else -1) + 1
            connection.execute(
                """
                insert or replace into host_agent_configs
                (
                    id, preset_id, label, command, args_json, prompt_transport,
                    prompt_args_json, env_json, display_order, created_at, updated_at
                )
                values (?, 'codex', 'Envctl Codex Goal', 'python3', ?, 'argv', '[]', '{}', ?, ?, ?)
                """,
                (
                    _SUPERSET_CODEX_GOAL_AGENT_ID,
                    json.dumps([str(launcher)]),
                    display_order,
                    now_ms,
                    now_ms,
                ),
            )
            connection.commit()
    except sqlite3.Error as exc:
        return "", f"superset_host_agent_config_failed: {exc}"
    return _SUPERSET_CODEX_GOAL_AGENT_ID, None


def _write_superset_codex_goal_launcher(worktree_root: Path) -> tuple[Path, str | None]:
    state_dir = worktree_root / ".envctl-state"
    launcher = state_dir / "superset-codex-goal-launcher.py"
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        current = launcher.read_text(encoding="utf-8") if launcher.exists() else ""
        if current != _SUPERSET_CODEX_GOAL_LAUNCHER:
            launcher.write_text(_SUPERSET_CODEX_GOAL_LAUNCHER, encoding="utf-8")
        launcher.chmod(0o700)
    except OSError as exc:
        return launcher, f"superset_codex_goal_launcher_write_failed: {exc}"
    return launcher, None


def _superset_host_agent_db(home: Path) -> Path | None:
    host_root = home / ".superset" / "host"
    if not host_root.exists():
        return None
    candidates = [path for path in host_root.glob("*/host.db") if path.exists()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


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
    error = superset_completed_process_error_text(result)
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


__all__ = tuple(name for name in globals() if not name.startswith("__"))
