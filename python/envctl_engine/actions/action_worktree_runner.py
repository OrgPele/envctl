from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from envctl_engine.actions.actions_worktree import delete_worktree_path
from envctl_engine.runtime.command_router import Route
from envctl_engine.ui.spinner import spinner, use_spinner_policy
from envctl_engine.ui.spinner_service import emit_spinner_policy, resolve_spinner_policy


def run_delete_worktree_action(orchestrator: Any, route: Route) -> int:
    rt = orchestrator.runtime
    command_name = route.command if route.command in {"delete-worktree", "blast-worktree"} else "delete-worktree"
    interactive_command = bool(route.flags.get("interactive_command"))
    if bool(route.flags.get("all")) and not bool(route.flags.get("yes")):
        print(f"{command_name} --all requires --yes")
        return 1

    targets, error = orchestrator.resolve_targets(route, trees_only=True)
    if error is not None:
        print(error)
        return 1

    rt._emit("action.command.start", command=route.command, mode=route.mode)  # type: ignore[attr-defined]
    orchestrator._emit_status(orchestrator._command_start_status(command_name, targets))
    spinner_policy = resolve_spinner_policy(getattr(rt, "env", {}))
    op_id = f"action.{command_name}"
    emit_spinner_policy(
        getattr(rt, "_emit", None),
        spinner_policy,
        context={"component": "action.command", "command": route.command, "op_id": op_id},
    )

    dry_run = bool(route.flags.get("dry_run"))
    failures = 0
    total = max(len(targets), 1)
    spinner_message = (
        "Blasting selected worktrees..."
        if command_name == "blast-worktree"
        else "Deleting selected worktrees..."
    )
    with use_spinner_policy(spinner_policy), spinner(
        spinner_message,
        enabled=spinner_policy.enabled,
        start_immediately=False,
    ) as active_spinner:
        if spinner_policy.enabled:
            active_spinner.start()
            rt._emit(  # type: ignore[attr-defined]
                "ui.spinner.lifecycle",
                component="action.command",
                command=route.command,
                op_id=op_id,
                state="start",
                message=spinner_message,
            )
        for index, target in enumerate(targets, start=1):
            target_root = Path(str(getattr(target, "root")))
            target_name = str(getattr(target, "name", target_root.name))
            progress = f"Deleting worktree {target_name} ({index}/{total})..."
            orchestrator._emit_status(progress)
            if spinner_policy.enabled:
                active_spinner.update(progress)
                rt._emit(  # type: ignore[attr-defined]
                    "ui.spinner.lifecycle",
                    component="action.command",
                    command=route.command,
                    op_id=op_id,
                    state="update",
                    message=progress,
                )
            _run_cleanup(
                runtime=rt,
                command_name=command_name,
                interactive_command=interactive_command,
                dry_run=dry_run,
                target_name=target_name,
                target_root=target_root,
                emit_status=orchestrator._emit_status,
            )
            result = delete_worktree_path(
                repo_root=rt.config.base_dir,  # type: ignore[attr-defined]
                trees_root=rt._trees_root_for_worktree(target_root),  # type: ignore[attr-defined]
                worktree_root=target_root,
                process_runner=rt.process_runner,  # type: ignore[attr-defined]
                dry_run=dry_run,
            )
            if not interactive_command:
                print(result.message)
            if not result.success:
                orchestrator._emit_status(f"{command_name} failed for {target_name}")
                failures += 1
            else:
                orchestrator._emit_status(f"{command_name} succeeded for {target_name}")
        if spinner_policy.enabled:
            if failures == 0:
                active_spinner.succeed(f"{command_name} completed")
                rt._emit(  # type: ignore[attr-defined]
                    "ui.spinner.lifecycle",
                    component="action.command",
                    command=route.command,
                    op_id=op_id,
                    state="success",
                    message=f"{command_name} completed",
                )
            else:
                active_spinner.fail(f"{command_name} failed")
                rt._emit(  # type: ignore[attr-defined]
                    "ui.spinner.lifecycle",
                    component="action.command",
                    command=route.command,
                    op_id=op_id,
                    state="fail",
                    message=f"{command_name} failed",
                )
            rt._emit(  # type: ignore[attr-defined]
                "ui.spinner.lifecycle",
                component="action.command",
                command=route.command,
                op_id=op_id,
                state="stop",
            )
    return 0 if failures == 0 else 1


def _run_cleanup(
    *,
    runtime: Any,
    command_name: str,
    interactive_command: bool,
    dry_run: bool,
    target_name: str,
    target_root: Path,
    emit_status: Callable[[str], None],
) -> None:
    if dry_run:
        return
    blast_cleanup = getattr(runtime, "_blast_worktree_before_delete", None)
    if not callable(blast_cleanup):
        return
    cleanup_warnings = blast_cleanup(
        project_name=target_name,
        project_root=target_root,
        source_command=command_name,
    )
    for warning in cleanup_warnings:
        emit_status(warning)
        if not interactive_command:
            print(f"Warning: {warning}")
