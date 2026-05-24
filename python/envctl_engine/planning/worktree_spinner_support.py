from __future__ import annotations

from typing import Any

from envctl_engine.ui.spinner_service import SpinnerPolicy, emit_spinner_policy, resolve_spinner_policy


def worktree_spinner_policy(runtime: Any, *, op_id: str) -> SpinnerPolicy:
    policy = resolve_spinner_policy(getattr(runtime, "env", {}))
    emit_spinner_policy(
        getattr(runtime, "_emit", None),
        policy,
        context={"component": "worktree_planning", "op_id": op_id},
    )
    return policy


def worktree_spinner_update(
    runtime: Any,
    *,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    message: str,
    terminal_message: str | None = None,
) -> None:
    if enabled:
        active_spinner.update(terminal_message or message)
        runtime._emit(  # type: ignore[attr-defined]
            "ui.spinner.lifecycle",
            component="worktree_planning",
            op_id=op_id,
            state="update",
            message=message,
        )
        return
    print(terminal_message or message)


def worktree_spinner_start(
    runtime: Any,
    *,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    message: str,
) -> None:
    if not enabled:
        import sys  # noqa: PLC0415

        print(f"  {message}", file=sys.stderr, flush=True)
        return
    active_spinner.start()
    runtime._emit(  # type: ignore[attr-defined]
        "ui.spinner.lifecycle",
        component="worktree_planning",
        op_id=op_id,
        state="start",
        message=message,
    )


def worktree_spinner_finish(
    runtime: Any,
    *,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    message: str,
) -> None:
    if not enabled:
        import sys  # noqa: PLC0415

        print(f"\u2713 {message}", file=sys.stderr, flush=True)
        return
    active_spinner.succeed(message)
    runtime._emit(  # type: ignore[attr-defined]
        "ui.spinner.lifecycle",
        component="worktree_planning",
        op_id=op_id,
        state="success",
        message=message,
    )


def worktree_spinner_fail(
    runtime: Any,
    *,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    message: str,
) -> None:
    if not enabled:
        import sys  # noqa: PLC0415

        print(f"\u2717 {message}", file=sys.stderr, flush=True)
        return
    active_spinner.fail(message)
    runtime._emit(  # type: ignore[attr-defined]
        "ui.spinner.lifecycle",
        component="worktree_planning",
        op_id=op_id,
        state="fail",
        message=message,
    )


def worktree_spinner_stop(runtime: Any, *, enabled: bool, op_id: str) -> None:
    if not enabled:
        return
    runtime._emit(  # type: ignore[attr-defined]
        "ui.spinner.lifecycle",
        component="worktree_planning",
        op_id=op_id,
        state="stop",
    )
