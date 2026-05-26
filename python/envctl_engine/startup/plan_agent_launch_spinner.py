from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, ClassVar

from envctl_engine.planning.plan_agent.launch import launch_plan_agent_terminals
from envctl_engine.ui.spinner import spinner, use_spinner_policy
from envctl_engine.ui.spinner_service import emit_spinner_policy, resolve_spinner_policy


def plan_agent_launch_spinner_label(launch_config: object) -> str:
    transport = str(getattr(launch_config, "transport", "")).strip().lower()
    cli = str(getattr(launch_config, "cli", "")).strip().lower()
    if transport == "omx":
        return "OMX-managed Codex"
    if cli == "opencode":
        return "OpenCode"
    if cli == "codex":
        return "Codex"
    return "AI"


def plan_agent_launch_spinner_message(launch_config: object, *, count: int) -> str:
    label = plan_agent_launch_spinner_label(launch_config)
    noun = "session" if count == 1 else "sessions"
    return f"Launching {label} AI {noun}..."


def plan_agent_launch_spinner_success_message(launch_config: object, *, count: int) -> str:
    label = plan_agent_launch_spinner_label(launch_config)
    noun = "session" if count == 1 else "sessions"
    return f"{label} AI {noun} ready"


@dataclass(frozen=True, slots=True)
class PlanAgentLaunchSpinner:
    __test__: ClassVar[bool] = False

    runtime: Any
    route: object
    created_worktrees: tuple[object, ...]
    launch_config: object
    suppress_progress_output: bool
    launch_fn: Callable[..., object] = launch_plan_agent_terminals
    resolve_spinner_policy_fn: Callable[..., object] = resolve_spinner_policy
    emit_spinner_policy_fn: Callable[..., None] = emit_spinner_policy
    spinner_fn: Callable[..., AbstractContextManager[Any]] = spinner
    use_spinner_policy_fn: Callable[..., AbstractContextManager[Any]] = use_spinner_policy

    def launch(self) -> object:
        spinner_policy = self.resolve_spinner_policy_fn(dict(self.runtime.env))
        self.emit_spinner_policy_fn(
            self.runtime._emit,
            spinner_policy,
            context={"component": "startup_orchestrator", "op_id": "plan_agent.launch"},
        )
        if not self._use_launch_spinner(spinner_policy):
            return self._launch()

        launch_message = plan_agent_launch_spinner_message(self.launch_config, count=len(self.created_worktrees))
        with (
            self.use_spinner_policy_fn(spinner_policy),
            self.spinner_fn(launch_message, enabled=True) as active_spinner,
        ):
            self._emit_lifecycle(state="start", message=launch_message)
            try:
                launch_result = self._launch()
            except Exception:
                self._fail(active_spinner)
                raise
            if str(getattr(launch_result, "status", "")).strip().lower() == "failed":
                self._fail(active_spinner)
            else:
                success_message = plan_agent_launch_spinner_success_message(
                    self.launch_config,
                    count=len(self.created_worktrees),
                )
                active_spinner.succeed(success_message)
                self._emit_lifecycle(state="success", message=success_message)
            self._emit_lifecycle(state="stop")
        return launch_result

    def _use_launch_spinner(self, spinner_policy: object) -> bool:
        return (
            bool(getattr(spinner_policy, "enabled", False))
            and bool(getattr(self.launch_config, "enabled", False))
            and bool(self.created_worktrees)
            and not self.suppress_progress_output
        )

    def _launch(self) -> object:
        return self.launch_fn(
            self.runtime,
            route=self.route,
            created_worktrees=self.created_worktrees,
        )

    def _fail(self, active_spinner: Any) -> None:
        failure_message = "AI session launch failed"
        active_spinner.fail(failure_message)
        self._emit_lifecycle(state="fail", message=failure_message)
        self._emit_lifecycle(state="stop")

    def _emit_lifecycle(self, *, state: str, message: str | None = None) -> None:
        payload: dict[str, object] = {
            "component": "startup_orchestrator",
            "op_id": "plan_agent.launch",
            "state": state,
        }
        if message is not None:
            payload["message"] = message
        self.runtime._emit("ui.spinner.lifecycle", **payload)


def launch_plan_agent_terminals_with_spinner(
    runtime: Any,
    *,
    route: object,
    created_worktrees: tuple[object, ...],
    launch_config: object,
    suppress_progress_output: bool,
    launch_fn: Callable[..., object] = launch_plan_agent_terminals,
    resolve_spinner_policy_fn: Callable[..., object] = resolve_spinner_policy,
    emit_spinner_policy_fn: Callable[..., None] = emit_spinner_policy,
    spinner_fn: Callable[..., AbstractContextManager[Any]] = spinner,
    use_spinner_policy_fn: Callable[..., AbstractContextManager[Any]] = use_spinner_policy,
) -> object:
    return PlanAgentLaunchSpinner(
        runtime=runtime,
        route=route,
        created_worktrees=created_worktrees,
        launch_config=launch_config,
        suppress_progress_output=suppress_progress_output,
        launch_fn=launch_fn,
        resolve_spinner_policy_fn=resolve_spinner_policy_fn,
        emit_spinner_policy_fn=emit_spinner_policy_fn,
        spinner_fn=spinner_fn,
        use_spinner_policy_fn=use_spinner_policy_fn,
    ).launch()
