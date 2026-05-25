from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Sequence

from envctl_engine.ui.backend_selector_debug import (
    _debug_orch_groups as _debug_orch_groups,
    _debug_tty_group_enabled as _debug_tty_group_enabled,
    _debug_tty_groups as _debug_tty_groups,
    _emit_debug_tty_group as _emit_debug_tty_group,
    _emit_parent_selector_thread_snapshot as _emit_parent_selector_thread_snapshot,
    debug_tty_group_enabled,
    emit_debug_tty_group,
)
from envctl_engine.ui.backend_selector_subprocess import (
    _run_selector_subprocess as _run_selector_subprocess,
    run_selector_subprocess,
)
from envctl_engine.ui.backend_selector_tty import (
    _drain_stdin_escape_tail as _drain_stdin_escape_tail,
    _emit_selector_preflight as _emit_selector_preflight,
    _flush_pending_input as _flush_pending_input,
    _normalize_stdin_line_mode as _normalize_stdin_line_mode,
    _preserve_output_tty_state_for_selector as _preserve_output_tty_state_for_selector,
    _selector_launch_character_mode_enabled as _selector_launch_character_mode_enabled,
    _selector_preflight_flag as _selector_preflight_flag,
    _selector_subprocess_enabled as _selector_subprocess_enabled,
    _stdin_tty_fd as _stdin_tty_fd,
    _stdout_tty_fd as _stdout_tty_fd,
    drain_stdin_escape_tail,
    emit_selector_preflight,
    flush_pending_input,
    normalize_stdin_line_mode,
    preserve_output_tty_state_for_selector,
    selector_launch_character_mode_enabled,
    selector_preflight_flag,
    selector_subprocess_enabled,
    stdin_tty_fd,
    stdout_tty_fd,  # noqa: F401 - compatibility re-export for legacy patch/import callers.
)
from envctl_engine.ui.selection_types import TargetSelection


def select_project_targets_via_textual(
    *,
    prompt: str,
    projects: Sequence[object],
    allow_all: bool,
    allow_untested: bool,
    multi: bool,
    initial_project_names: Sequence[str] | None,
    exclusive_project_name: str | None,
    runtime: Any,
) -> TargetSelection:
    run_subprocess = selector_subprocess_enabled(runtime)
    run_selector_preflight(runtime, selector_kind="project", prompt=prompt, multi=multi)
    if run_subprocess:
        return run_selector_subprocess(
            runtime=runtime,
            payload={
                "kind": "project",
                "prompt": prompt,
                "project_names": [str(getattr(project, "name", "")).strip() for project in projects],
                "allow_all": bool(allow_all),
                "allow_untested": bool(allow_untested),
                "multi": bool(multi),
                "initial_project_names": [str(name) for name in (initial_project_names or [])],
                "exclusive_project_name": str(exclusive_project_name or ""),
            },
        )
    from .terminal_session import temporary_tty_character_mode

    tty_fd = stdin_tty_fd()
    launch_mode = (
        temporary_tty_character_mode(fd=tty_fd, emit=getattr(runtime, "_emit", None))
        if tty_fd is not None and selector_launch_character_mode_enabled()
        else nullcontext(False)
    )
    with launch_mode:
        from .textual.screens.selector import select_project_targets_textual

        return select_project_targets_textual(
            prompt=prompt,
            projects=projects,
            allow_all=allow_all,
            allow_untested=allow_untested,
            multi=multi,
            initial_project_names=initial_project_names,
            exclusive_project_name=exclusive_project_name,
            emit=getattr(runtime, "_emit", None),
        )


def select_grouped_targets_via_textual(
    *,
    prompt: str,
    projects: Sequence[object],
    services: Sequence[str],
    allow_all: bool,
    multi: bool,
    runtime: Any,
) -> TargetSelection:
    run_subprocess = selector_subprocess_enabled(runtime)
    run_selector_preflight(runtime, selector_kind="grouped", prompt=prompt, multi=multi)
    if run_subprocess:
        return run_selector_subprocess(
            runtime=runtime,
            payload={
                "kind": "grouped",
                "prompt": prompt,
                "project_names": [str(getattr(project, "name", "")).strip() for project in projects],
                "services": list(services),
                "allow_all": bool(allow_all),
                "multi": bool(multi),
            },
        )
    from .terminal_session import temporary_tty_character_mode

    tty_fd = stdin_tty_fd()
    launch_mode = (
        temporary_tty_character_mode(fd=tty_fd, emit=getattr(runtime, "_emit", None))
        if tty_fd is not None and selector_launch_character_mode_enabled()
        else nullcontext(False)
    )
    with launch_mode:
        from .textual.screens.selector import select_grouped_targets_textual

        return select_grouped_targets_textual(
            prompt=prompt,
            projects=projects,
            services=list(services),
            allow_all=allow_all,
            multi=multi,
            emit=getattr(runtime, "_emit", None),
        )


def run_selector_preflight(
    runtime: Any,
    *,
    selector_kind: str,
    prompt: str,
    multi: bool,
) -> None:
    from .terminal_session import normalize_standard_tty_state

    emit = getattr(runtime, "_emit", None)
    termios_enabled = debug_tty_group_enabled(runtime, "termios")
    reader_enabled = debug_tty_group_enabled(runtime, "reader")
    emit_debug_tty_group(
        runtime,
        group="termios",
        action="normalize_standard_tty_state",
        enabled=termios_enabled,
        detail=f"selector_preflight:{selector_kind}",
    )
    emit_debug_tty_group(
        runtime,
        group="reader",
        action="stdin_restore_and_drain",
        enabled=reader_enabled,
        detail=f"selector_preflight:{selector_kind}",
    )
    preserve_output_tty_state = preserve_output_tty_state_for_selector(runtime)
    if termios_enabled and not preserve_output_tty_state:
        normalize_standard_tty_state(emit=emit, component="ui.backend")
    emit_selector_preflight(emit, stage="begin", selector_kind=selector_kind, prompt=prompt, multi=multi)
    flush_enabled = reader_enabled and selector_preflight_flag(
        runtime=runtime,
        key="ENVCTL_UI_SELECTOR_PREFLIGHT_FLUSH",
        default=False,
    )
    if flush_enabled:
        flush_pending_input(runtime)

    fd = stdin_tty_fd()
    if fd is None:
        emit_selector_preflight(
            emit,
            stage="end",
            selector_kind=selector_kind,
            prompt=prompt,
            multi=multi,
            tty=False,
            flushed=flush_enabled,
            drained_bytes=0,
        )
        return

    normalized = normalize_stdin_line_mode(fd) if reader_enabled else False
    if callable(emit):
        emit(
            "ui.tty.transition",
            component="ui.backend",
            action="selector_preflight_restore_line_mode",
            method="terminal_session.ensure_tty_line_mode",
            success=normalized,
            selector_kind=selector_kind,
            skipped=not reader_enabled,
        )
    drain_enabled = reader_enabled and selector_preflight_flag(
        runtime=runtime,
        key="ENVCTL_UI_SELECTOR_PREFLIGHT_DRAIN",
        default=False,
    )
    drained_bytes = drain_stdin_escape_tail(fd=fd, max_window_seconds=0.03, max_bytes=64) if drain_enabled else 0
    emit_selector_preflight(
        emit,
        stage="end",
        selector_kind=selector_kind,
        prompt=prompt,
        multi=multi,
        tty=True,
        normalized=normalized,
        preserved_output_tty_state=preserve_output_tty_state,
        flushed=flush_enabled,
        drain_enabled=drain_enabled,
        drained_bytes=drained_bytes,
    )


_run_selector_preflight = run_selector_preflight
_select_grouped_targets_via_textual = select_grouped_targets_via_textual
_select_project_targets_via_textual = select_project_targets_via_textual
