from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol, cast

from envctl_engine.runtime.command_router import Route


_ACTION_HANDLER_NAMES = {
    "test": "run_test_action",
    "test-focused": "run_test_plan_action",
    "pr": "run_pr_action",
    "commit": "run_commit_action",
    "ship": "run_ship_action",
    "review": "run_review_action",
    "migrate": "run_migrate_action",
}

_BULK_MUTATING_COMMANDS = frozenset({"commit", "migrate", "pr", "ship"})


class ActionSpinner(Protocol):
    def start(self) -> None: ...

    def succeed(self, message: str) -> None: ...

    def fail(self, message: str) -> None: ...


ActionHandler = Callable[[Route, list[object]], int]


@dataclass(slots=True)
class ActionCommandExecutionDependencies:
    spinner_factory: Callable[..., AbstractContextManager[ActionSpinner]]
    resolve_spinner_policy: Callable[[dict[str, str]], object]
    emit_spinner_policy: Callable[..., None]
    use_spinner_policy: Callable[..., AbstractContextManager[object]]


@dataclass(slots=True)
class ActionCommandExecutor:
    orchestrator: Any
    route: Route
    dependencies: ActionCommandExecutionDependencies

    @property
    def runtime(self) -> Any:
        return self.orchestrator.runtime

    def execute(self) -> int:
        special_code = self._execute_special_worktree_command()
        if special_code is not None:
            return special_code

        targets, error = self.orchestrator.resolve_targets(self.route, trees_only=False)
        if error is not None:
            print(error)
            self._emit_finish(1, error=error)
            return 1

        bulk_confirmation_error = self._bulk_confirmation_error(targets)
        if bulk_confirmation_error is not None:
            print(bulk_confirmation_error)
            self._emit_finish(1, error=bulk_confirmation_error)
            return 1

        handler = self._handler()
        if handler is None:
            return self.runtime.unsupported_command(self.route.command)

        self.orchestrator._deferred_post_action_output = None
        code = self._execute_targeted_handler(handler, targets)
        self._flush_deferred_output()
        if not bool(self.route.flags.get("json")):
            self._emit_finish(code)
        return code

    def _bulk_confirmation_error(self, targets: list[object]) -> str | None:
        if self.route.command not in _BULK_MUTATING_COMMANDS:
            return None
        if not bool(self.route.flags.get("all")) or len(targets) <= 1:
            return None
        if bool(self.route.flags.get("yes")) or bool(self.route.flags.get("force")):
            return None
        return f"{self.route.command} --all targets {len(targets)} projects and requires --yes or --force"

    def _execute_special_worktree_command(self) -> int | None:
        if self.route.command == "self-destruct-worktree":
            code = self.orchestrator.run_self_destruct_worktree_action(self.route)
            self._emit_finish(code)
            return code
        if self.route.command in {"delete-worktree", "blast-worktree"}:
            code = self.orchestrator.run_delete_worktree_action(self.route)
            self._emit_finish(code)
            return code
        return None

    def _handler(self) -> ActionHandler | None:
        handler_name = _ACTION_HANDLER_NAMES.get(self.route.command)
        if handler_name is None:
            return None
        handler = getattr(self.orchestrator, handler_name, None)
        return cast(ActionHandler, handler) if callable(handler) else None

    def _execute_targeted_handler(self, handler: ActionHandler, targets: list[object]) -> int:
        spinner_policy = self.dependencies.resolve_spinner_policy(getattr(self.runtime, "env", {}))
        op_id = f"action.{self.route.command}"
        start_status = self.orchestrator._command_start_status(self.route.command, targets)
        spinner_enabled = bool(getattr(spinner_policy, "enabled", False)) and not self._suppress_spinner()
        self._emit_spinner_policy(spinner_policy, op_id=op_id)
        self._emit_spinner_suppressed(op_id=op_id)
        self.runtime.emit("action.command.start", command=self.route.command, mode=self.route.mode)
        self.orchestrator._emit_status(start_status)

        with (
            self.dependencies.use_spinner_policy(spinner_policy),
            self.dependencies.spinner_factory(
                start_status,
                enabled=spinner_enabled,
                start_immediately=False,
            ) as active_spinner,
        ):
            self._start_spinner(active_spinner, enabled=spinner_enabled, op_id=op_id, message=start_status)
            restore_spinner_bridge = self._install_spinner_bridge(active_spinner, enabled=spinner_enabled, op_id=op_id)
            try:
                try:
                    code = handler(self.route, targets)
                finally:
                    restore_spinner_bridge()
            except KeyboardInterrupt:
                self._fail_interrupted(active_spinner, enabled=spinner_enabled, op_id=op_id)
                self._emit_finish(2)
                raise
            self._finish_spinner(active_spinner, enabled=spinner_enabled, op_id=op_id, code=code)
            return code

    def _suppress_spinner(self) -> bool:
        return bool(self.route.flags.get("interactive_command")) or bool(self.route.flags.get("json"))

    def _emit_spinner_policy(self, spinner_policy: object, *, op_id: str) -> None:
        self.dependencies.emit_spinner_policy(
            getattr(self.runtime.raw_runtime, "_emit", None),
            spinner_policy,
            context={"component": "action.command", "command": self.route.command, "op_id": op_id},
        )

    def _emit_spinner_suppressed(self, *, op_id: str) -> None:
        if not self._suppress_spinner():
            return
        self.runtime.emit(
            "ui.spinner.disabled",
            component="action.command",
            command=self.route.command,
            op_id=op_id,
            reason="interactive_command_spinner_suppressed",
        )

    def _start_spinner(self, active_spinner: ActionSpinner, *, enabled: bool, op_id: str, message: str) -> None:
        if not enabled:
            return
        active_spinner.start()
        self._emit_spinner_lifecycle(op_id=op_id, state="start", message=message)

    def _install_spinner_bridge(
        self,
        active_spinner: ActionSpinner,
        *,
        enabled: bool,
        op_id: str,
    ) -> Callable[[], None]:
        if not enabled:
            return self.orchestrator._noop_restore
        return self.orchestrator._install_action_spinner_status_bridge(
            command=self.route.command,
            op_id=op_id,
            active_spinner=active_spinner,
        )

    def _fail_interrupted(self, active_spinner: ActionSpinner, *, enabled: bool, op_id: str) -> None:
        if not enabled:
            return
        interrupted = f"{self.route.command} interrupted"
        active_spinner.fail(interrupted)
        self._emit_spinner_lifecycle(op_id=op_id, state="fail", message=interrupted)
        self._emit_spinner_lifecycle(op_id=op_id, state="stop")

    def _finish_spinner(self, active_spinner: ActionSpinner, *, enabled: bool, op_id: str, code: int) -> None:
        if not enabled:
            return
        if code == 0:
            completion = f"{self.route.command} completed"
            active_spinner.succeed(completion)
            self._emit_spinner_lifecycle(op_id=op_id, state="success", message=completion)
        else:
            failure = f"{self.route.command} failed"
            active_spinner.fail(failure)
            self._emit_spinner_lifecycle(op_id=op_id, state="fail", message=failure)
        self._emit_spinner_lifecycle(op_id=op_id, state="stop")

    def _emit_spinner_lifecycle(self, *, op_id: str, state: str, message: str | None = None) -> None:
        payload: dict[str, object] = {
            "component": "action.command",
            "command": self.route.command,
            "op_id": op_id,
            "state": state,
        }
        if message is not None:
            payload["message"] = message
        self.runtime.emit("ui.spinner.lifecycle", **payload)

    def _flush_deferred_output(self) -> None:
        deferred_output = self.orchestrator._deferred_post_action_output
        self.orchestrator._deferred_post_action_output = None
        if deferred_output is not None:
            deferred_output()

    def _emit_finish(self, code: int, **extra: object) -> None:
        self.runtime.emit("action.command.finish", command=self.route.command, code=code, **extra)


def execute_action_command(
    orchestrator: Any,
    route: Route,
    *,
    spinner_factory: Callable[..., AbstractContextManager[ActionSpinner]],
    resolve_spinner_policy_fn: Callable[[dict[str, str]], object],
    emit_spinner_policy_fn: Callable[..., None],
    use_spinner_policy_fn: Callable[..., AbstractContextManager[object]],
) -> int:
    dependencies = ActionCommandExecutionDependencies(
        spinner_factory=spinner_factory,
        resolve_spinner_policy=resolve_spinner_policy_fn,
        emit_spinner_policy=emit_spinner_policy_fn,
        use_spinner_policy=use_spinner_policy_fn,
    )
    return ActionCommandExecutor(orchestrator=orchestrator, route=route, dependencies=dependencies).execute()
