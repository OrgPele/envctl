from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from ..state.models import RunState
from .backend_selector_support import (
    _debug_orch_groups as _debug_orch_groups,
    _debug_tty_group_enabled as _debug_tty_group_enabled,
    _debug_tty_groups as _debug_tty_groups,
    _drain_stdin_escape_tail as _drain_stdin_escape_tail,
    _emit_debug_tty_group as _emit_debug_tty_group,
    _emit_parent_selector_thread_snapshot as _emit_parent_selector_thread_snapshot,
    _emit_selector_preflight as _emit_selector_preflight,
    _flush_pending_input as _flush_pending_input,
    _normalize_stdin_line_mode as _normalize_stdin_line_mode,
    _preserve_output_tty_state_for_selector as _preserve_output_tty_state_for_selector,
    _run_selector_preflight as _run_selector_preflight,
    _run_selector_subprocess as _run_selector_subprocess,
    _select_grouped_targets_via_textual as _select_grouped_targets_via_textual,
    _select_project_targets_via_textual as _select_project_targets_via_textual,
    _selector_launch_character_mode_enabled as _selector_launch_character_mode_enabled,
    _selector_preflight_flag as _selector_preflight_flag,
    _selector_subprocess_enabled as _selector_subprocess_enabled,
    _stdin_tty_fd as _stdin_tty_fd,
    _stdout_tty_fd as _stdout_tty_fd,
)
from .backend_resolver import UiBackendResolution
from .dashboard_loop_support import run_legacy_dashboard_loop
from .selection_types import TargetSelection


class InteractiveBackend(Protocol):
    def run_dashboard_loop(self, *, state: RunState, runtime: Any) -> int: ...

    def select_project_targets(
        self,
        *,
        prompt: str,
        projects: Sequence[object],
        allow_all: bool,
        allow_untested: bool,
        multi: bool,
        initial_project_names: Sequence[str] | None = None,
        exclusive_project_name: str | None = None,
        runtime: Any,
    ) -> TargetSelection: ...

    def select_grouped_targets(
        self,
        *,
        prompt: str,
        projects: Sequence[object],
        services: Sequence[str],
        allow_all: bool,
        multi: bool,
        runtime: Any,
    ) -> TargetSelection: ...


@dataclass(slots=True)
class LegacyInteractiveBackend:
    def run_dashboard_loop(self, *, state: RunState, runtime: Any) -> int:
        return run_legacy_dashboard_loop(
            state=state,
            runtime=runtime,
            sanitize=getattr(runtime, "_sanitize_interactive_input"),
        )

    def select_project_targets(
        self,
        *,
        prompt: str,
        projects: Sequence[object],
        allow_all: bool,
        allow_untested: bool,
        multi: bool,
        initial_project_names: Sequence[str] | None = None,
        exclusive_project_name: str | None = None,
        runtime: Any,
    ) -> TargetSelection:
        return _select_project_targets_via_textual(
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
        self,
        *,
        prompt: str,
        projects: Sequence[object],
        services: Sequence[str],
        allow_all: bool,
        multi: bool,
        runtime: Any,
    ) -> TargetSelection:
        return _select_grouped_targets_via_textual(
            prompt=prompt,
            projects=projects,
            services=list(services),
            allow_all=allow_all,
            multi=multi,
            runtime=runtime,
        )


@dataclass(slots=True)
class TextualInteractiveBackend:
    def run_dashboard_loop(self, *, state: RunState, runtime: Any) -> int:
        from .textual.app import run_textual_dashboard_loop

        return run_textual_dashboard_loop(
            state=state,
            runtime=runtime,
            handle_command=getattr(runtime, "_run_interactive_command"),
            sanitize=getattr(runtime, "_sanitize_interactive_input"),
        )

    def select_project_targets(
        self,
        *,
        prompt: str,
        projects: Sequence[object],
        allow_all: bool,
        allow_untested: bool,
        multi: bool,
        initial_project_names: Sequence[str] | None = None,
        exclusive_project_name: str | None = None,
        runtime: Any,
    ) -> TargetSelection:
        return _select_project_targets_via_textual(
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
        self,
        *,
        prompt: str,
        projects: Sequence[object],
        services: Sequence[str],
        allow_all: bool,
        multi: bool,
        runtime: Any,
    ) -> TargetSelection:
        return _select_grouped_targets_via_textual(
            prompt=prompt,
            projects=projects,
            services=services,
            allow_all=allow_all,
            multi=multi,
            runtime=runtime,
        )


@dataclass(slots=True)
class NonInteractiveBackend:
    reason: str = "non_tty"

    def run_dashboard_loop(self, *, state: RunState, runtime: Any) -> int:
        emit = getattr(runtime, "_emit", None)
        if callable(emit):
            emit("ui.fallback.non_interactive", reason=self.reason, command="dashboard")
        runtime._print_dashboard_snapshot(state)
        return 0

    def select_project_targets(
        self,
        *,
        prompt: str,
        projects: Sequence[object],
        allow_all: bool,
        allow_untested: bool,
        multi: bool,
        initial_project_names: Sequence[str] | None = None,
        exclusive_project_name: str | None = None,
        runtime: Any,
    ) -> TargetSelection:
        _ = prompt, projects, allow_all, allow_untested, multi, initial_project_names, exclusive_project_name
        emit = getattr(runtime, "_emit", None)
        if callable(emit):
            emit("ui.fallback.non_interactive", reason=self.reason, command="selection.project")
        return TargetSelection(cancelled=True)

    def select_grouped_targets(
        self,
        *,
        prompt: str,
        projects: Sequence[object],
        services: Sequence[str],
        allow_all: bool,
        multi: bool,
        runtime: Any,
    ) -> TargetSelection:
        _ = prompt, projects, services, allow_all, multi
        emit = getattr(runtime, "_emit", None)
        if callable(emit):
            emit("ui.fallback.non_interactive", reason=self.reason, command="selection.grouped")
        return TargetSelection(cancelled=True)


def build_interactive_backend(resolution: UiBackendResolution) -> InteractiveBackend:
    if resolution.backend == "textual":
        return TextualInteractiveBackend()
    if resolution.backend == "legacy":
        return LegacyInteractiveBackend()
    return NonInteractiveBackend(reason=resolution.reason)
