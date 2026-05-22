from __future__ import annotations

from typing import Any, Callable

from envctl_engine.runtime.command_router import Route


def execute_action_command(
    orchestrator: Any,
    route: Route,
    *,
    spinner_factory: Callable[..., object],
    resolve_spinner_policy_fn: Callable[[dict[str, str]], object],
    emit_spinner_policy_fn: Callable[..., None],
    use_spinner_policy_fn: Callable[..., object],
) -> int:
    runtime = orchestrator.runtime
    if route.command == "self-destruct-worktree":
        code = orchestrator.run_self_destruct_worktree_action(route)
        runtime.emit("action.command.finish", command=route.command, code=code)
        return code
    if route.command in {"delete-worktree", "blast-worktree"}:
        code = orchestrator.run_delete_worktree_action(route)
        runtime.emit("action.command.finish", command=route.command, code=code)
        return code

    targets, error = orchestrator.resolve_targets(route, trees_only=False)
    if error is not None:
        print(error)
        runtime.emit("action.command.finish", command=route.command, code=1, error=error)
        return 1

    handler_name = {
        "test": "run_test_action",
        "test-focused": "run_test_plan_action",
        "pr": "run_pr_action",
        "commit": "run_commit_action",
        "ship": "run_ship_action",
        "review": "run_review_action",
        "migrate": "run_migrate_action",
    }.get(route.command)
    handler = getattr(orchestrator, handler_name, None) if handler_name is not None else None
    if handler is None:
        return runtime.unsupported_command(route.command)

    orchestrator._deferred_post_action_output = None
    spinner_policy = resolve_spinner_policy_fn(getattr(runtime, "env", {}))
    op_id = f"action.{route.command}"
    start_status = orchestrator._command_start_status(route.command, targets)
    suppress_action_spinner = bool(route.flags.get("interactive_command")) or bool(route.flags.get("json"))
    action_spinner_enabled = bool(getattr(spinner_policy, "enabled", False)) and not suppress_action_spinner
    emit_spinner_policy_fn(
        getattr(runtime.raw_runtime, "_emit", None),
        spinner_policy,
        context={"component": "action.command", "command": route.command, "op_id": op_id},
    )
    if suppress_action_spinner:
        runtime.emit(
            "ui.spinner.disabled",
            component="action.command",
            command=route.command,
            op_id=op_id,
            reason="interactive_command_spinner_suppressed",
        )

    runtime.emit("action.command.start", command=route.command, mode=route.mode)
    orchestrator._emit_status(start_status)
    with (
        use_spinner_policy_fn(spinner_policy),
        spinner_factory(
            start_status,
            enabled=action_spinner_enabled,
            start_immediately=False,
        ) as active_spinner,
    ):
        if action_spinner_enabled:
            active_spinner.start()
            runtime.emit(
                "ui.spinner.lifecycle",
                component="action.command",
                command=route.command,
                op_id=op_id,
                state="start",
                message=start_status,
            )
        restore_spinner_bridge = orchestrator._noop_restore
        if action_spinner_enabled:
            restore_spinner_bridge = orchestrator._install_action_spinner_status_bridge(
                command=route.command,
                op_id=op_id,
                active_spinner=active_spinner,
            )
        try:
            try:
                code = handler(route, targets)
            finally:
                restore_spinner_bridge()
        except KeyboardInterrupt:
            if action_spinner_enabled:
                interrupted = f"{route.command} interrupted"
                active_spinner.fail(interrupted)
                runtime.emit(
                    "ui.spinner.lifecycle",
                    component="action.command",
                    command=route.command,
                    op_id=op_id,
                    state="fail",
                    message=interrupted,
                )
                runtime.emit(
                    "ui.spinner.lifecycle",
                    component="action.command",
                    command=route.command,
                    op_id=op_id,
                    state="stop",
                )
            runtime.emit("action.command.finish", command=route.command, code=2)
            raise
        if action_spinner_enabled:
            if code == 0:
                completion = f"{route.command} completed"
                active_spinner.succeed(completion)
                runtime.emit(
                    "ui.spinner.lifecycle",
                    component="action.command",
                    command=route.command,
                    op_id=op_id,
                    state="success",
                    message=completion,
                )
            else:
                failure = f"{route.command} failed"
                active_spinner.fail(failure)
                runtime.emit(
                    "ui.spinner.lifecycle",
                    component="action.command",
                    command=route.command,
                    op_id=op_id,
                    state="fail",
                    message=failure,
                )
            runtime.emit(
                "ui.spinner.lifecycle",
                component="action.command",
                command=route.command,
                op_id=op_id,
                state="stop",
            )
    deferred_output = orchestrator._deferred_post_action_output
    orchestrator._deferred_post_action_output = None
    if deferred_output is not None:
        deferred_output()
    if not bool(route.flags.get("json")):
        runtime.emit("action.command.finish", command=route.command, code=code)
    return code
