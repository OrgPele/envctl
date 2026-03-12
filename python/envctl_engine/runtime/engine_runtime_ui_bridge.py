from __future__ import annotations

from typing import Any

from envctl_engine.ui.dashboard.orchestrator import DashboardOrchestrator
from envctl_engine.state.models import RunState
from envctl_engine.shared.parsing import parse_bool
from envctl_engine.ui.command_parsing import (
    parse_interactive_command as shared_parse_interactive_command,
    recover_single_letter_command_from_escape_fragment as shared_recover_single_letter_command_from_escape_fragment,
    sanitize_interactive_input as shared_sanitize_interactive_input,
)
from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI
from envctl_engine.ui.backend import build_interactive_backend
from envctl_engine.ui.backend_resolver import resolve_ui_backend_with_capabilities


def dashboard(route_runtime: Any, route: object) -> int:
    return route_runtime.dashboard_orchestrator.execute(route)


def run_interactive_dashboard_loop(runtime: Any, state: RunState) -> int:
    return current_ui_backend(runtime).run_dashboard_loop(state=state, runtime=runtime)


def run_interactive_command(runtime: Any, raw: str, state: RunState) -> tuple[bool, RunState]:
    orchestrator = getattr(runtime, "dashboard_orchestrator", None)
    if orchestrator is not None and hasattr(orchestrator, "_run_interactive_command"):
        return orchestrator._run_interactive_command(raw, state, runtime)
    return DashboardOrchestrator(runtime)._run_interactive_command(raw, state, runtime)


def sanitize_interactive_input(raw: str) -> str:
    return shared_sanitize_interactive_input(raw)


def recover_single_letter_command_from_escape_fragment(raw: str) -> str:
    return shared_recover_single_letter_command_from_escape_fragment(raw)


def parse_interactive_command(raw: str) -> list[str] | None:
    return shared_parse_interactive_command(raw)


def flush_pending_interactive_input() -> None:
    RuntimeTerminalUI.flush_pending_interactive_input()


def read_interactive_command_line(runtime: Any, prompt: str) -> str:
    from envctl_engine.ui.terminal_session import TerminalSession

    prefer_basic_input = parse_bool(runtime.env.get("ENVCTL_UI_BASIC_INPUT"), True)
    return TerminalSession(
        runtime.env,
        prefer_basic_input=prefer_basic_input,
        emit=runtime._emit,
        debug_recorder=runtime._debug_recorder,
    ).read_command_line(prompt)


def select_project_targets(
    runtime: Any,
    *,
    prompt: str,
    projects: list[object],
    allow_all: bool,
    allow_untested: bool,
    multi: bool,
    initial_project_names: list[str] | None = None,
    exclusive_project_name: str | None = None,
):
    return current_ui_backend(runtime).select_project_targets(
        prompt=prompt,
        projects=projects,
        allow_all=allow_all,
        allow_untested=allow_untested,
        multi=multi,
        initial_project_names=initial_project_names,
        exclusive_project_name=exclusive_project_name,
        runtime=runtime,
    )


def select_grouped_targets(
    runtime: Any,
    *,
    prompt: str,
    projects: list[object],
    services: list[str],
    allow_all: bool,
    multi: bool,
):
    return current_ui_backend(runtime).select_grouped_targets(
        prompt=prompt,
        projects=projects,
        services=services,
        allow_all=allow_all,
        multi=multi,
        runtime=runtime,
    )


def current_ui_backend(runtime: Any):
    backend = getattr(runtime, "ui_backend", None)
    module_name = str(getattr(getattr(backend, "__class__", object), "__module__", ""))
    if module_name.startswith("envctl_engine.ui.backend"):
        resolution = resolve_ui_backend_with_capabilities(
            runtime.env,
            interactive_tty=runtime._can_interactive_tty(),
        )
        if (
            resolution.backend != runtime.ui_backend_resolution.backend
            or resolution.reason != runtime.ui_backend_resolution.reason
            or resolution.interactive != runtime.ui_backend_resolution.interactive
        ):
            runtime.ui_backend_resolution = resolution
            runtime.ui_backend = build_interactive_backend(resolution)
            runtime._emit(
                "ui.backend.selected",
                backend=resolution.backend,
                requested_mode=resolution.requested_mode,
                interactive=resolution.interactive,
                reason=resolution.reason,
            )
    return runtime.ui_backend
