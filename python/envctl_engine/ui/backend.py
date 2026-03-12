from __future__ import annotations

from dataclasses import dataclass
import os
import json
import subprocess
import select
import sys
import tempfile
import threading
import traceback
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from ..state.models import RunState
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


def _debug_orch_groups(runtime: Any) -> set[str]:
    raw = ""
    env = getattr(runtime, "env", None)
    if isinstance(env, Mapping):
        raw = str(env.get("ENVCTL_DEBUG_PLAN_ORCH_GROUP", "")).strip().lower()
    if not raw:
        raw = str(os.environ.get("ENVCTL_DEBUG_PLAN_ORCH_GROUP", "")).strip().lower()
    return {token.strip() for token in raw.replace("+", ",").split(",") if token.strip()}


def _debug_tty_groups(runtime: Any) -> set[str]:
    orch_groups = _debug_orch_groups(runtime)
    if orch_groups and "tty" not in orch_groups:
        return set()
    raw = ""
    env = getattr(runtime, "env", None)
    if isinstance(env, Mapping):
        raw = str(env.get("ENVCTL_DEBUG_PLAN_TTY_GROUP", "")).strip().lower()
    if not raw:
        raw = str(os.environ.get("ENVCTL_DEBUG_PLAN_TTY_GROUP", "")).strip().lower()
    return {token.strip() for token in raw.replace("+", ",").split(",") if token.strip()}


def _debug_tty_group_enabled(runtime: Any, name: str) -> bool:
    groups = _debug_tty_groups(runtime)
    if not groups:
        return True
    return name in groups


def _emit_debug_tty_group(runtime: Any, *, group: str, action: str, enabled: bool, detail: str) -> None:
    emit = getattr(runtime, "_emit", None)
    if not callable(emit):
        return
    emit(
        "startup.debug_tty_group",
        component="ui.backend",
        group=group,
        action=action,
        enabled=enabled,
        detail=detail,
    )


def _select_project_targets_via_textual(
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
    run_subprocess = _selector_subprocess_enabled(runtime)
    _run_selector_preflight(
        runtime,
        selector_kind="project",
        prompt=prompt,
        multi=multi,
    )
    if run_subprocess:
        return _run_selector_subprocess(
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

    tty_fd = _stdin_tty_fd()
    launch_mode = (
        temporary_tty_character_mode(fd=tty_fd, emit=getattr(runtime, "_emit", None))
        if tty_fd is not None and _selector_launch_character_mode_enabled()
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


def _select_grouped_targets_via_textual(
    *,
    prompt: str,
    projects: Sequence[object],
    services: Sequence[str],
    allow_all: bool,
    multi: bool,
    runtime: Any,
) -> TargetSelection:
    run_subprocess = _selector_subprocess_enabled(runtime)
    _run_selector_preflight(
        runtime,
        selector_kind="grouped",
        prompt=prompt,
        multi=multi,
    )
    if run_subprocess:
        return _run_selector_subprocess(
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

    tty_fd = _stdin_tty_fd()
    launch_mode = (
        temporary_tty_character_mode(fd=tty_fd, emit=getattr(runtime, "_emit", None))
        if tty_fd is not None and _selector_launch_character_mode_enabled()
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


def _selector_subprocess_enabled(runtime: Any) -> bool:
    raw = ""
    env = getattr(runtime, "env", None)
    if isinstance(env, Mapping):
        raw = str(env.get("ENVCTL_UI_TEXTUAL_SELECTOR_SUBPROCESS", "")).strip().lower()
    if not raw:
        raw = str(os.environ.get("ENVCTL_UI_TEXTUAL_SELECTOR_SUBPROCESS", "")).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return str(os.environ.get("TERM_PROGRAM", "")).strip() == "Apple_Terminal"


def _run_selector_subprocess(*, runtime: Any, payload: Mapping[str, object]) -> TargetSelection:
    from .terminal_session import temporary_standard_output_pendin

    emit = getattr(runtime, "_emit", None)
    session_id_getter = getattr(runtime, "_current_session_id", None)
    session_id = session_id_getter() if callable(session_id_getter) else None
    if callable(emit):
        emit(
            "ui.selector.subprocess",
            component="ui.backend",
            enabled=True,
            kind=str(payload.get("kind", "")).strip().lower(),
            session_id=session_id if isinstance(session_id, str) else None,
        )
    with tempfile.TemporaryDirectory(prefix="envctl-selector-") as tmpdir:
        payload_path = Path(tmpdir) / "payload.json"
        result_path = Path(tmpdir) / "result.json"
        payload_path.write_text(json.dumps(dict(payload)), encoding="utf-8")
        command = [
            sys.executable,
            "-m",
            "envctl_engine.ui.textual.selector_subprocess_entry",
            str(payload_path),
            str(result_path),
        ]
        env = os.environ.copy()
        runtime_env = getattr(runtime, "env", None)
        if isinstance(runtime_env, Mapping):
            env.update({str(key): str(value) for key, value in runtime_env.items()})
        if isinstance(session_id, str) and session_id.strip():
            debug_path = (
                runtime.runtime_root
                / "debug"
                / session_id.strip()
                / (f"selector-subprocess-{str(payload.get('kind', 'unknown')).strip().lower()}.jsonl")
            )
            try:
                debug_path.parent.mkdir(parents=True, exist_ok=True)
                env["ENVCTL_UI_SELECTOR_SUBPROCESS_DEBUG_PATH"] = str(debug_path)
                if callable(emit):
                    emit(
                        "ui.selector.subprocess",
                        component="ui.backend",
                        enabled=True,
                        kind=str(payload.get("kind", "")).strip().lower(),
                        debug_path=str(debug_path),
                    )
            except OSError:
                pass
        apple_terminal = str(os.environ.get("TERM_PROGRAM", "")).strip() == "Apple_Terminal"
        reader_enabled = _debug_tty_group_enabled(runtime, "reader")
        termios_enabled = _debug_tty_group_enabled(runtime, "termios")
        _emit_debug_tty_group(
            runtime,
            group="reader",
            action="parent_thread_snapshot",
            enabled=reader_enabled,
            detail="selector_subprocess",
        )
        _emit_debug_tty_group(
            runtime,
            group="termios",
            action="temporary_standard_output_pendin",
            enabled=termios_enabled,
            detail="selector_subprocess",
        )
        if reader_enabled:
            _emit_parent_selector_thread_snapshot(emit=emit, stage="before_subprocess_launch")
        pendin_mode = (
            temporary_standard_output_pendin(emit=emit, component="ui.backend")
            if apple_terminal and termios_enabled
            else nullcontext()
        )
        with pendin_mode:
            subprocess.run(command, check=True, env=env)
        if reader_enabled:
            _emit_parent_selector_thread_snapshot(emit=emit, stage="after_subprocess_exit")
        result = json.loads(result_path.read_text(encoding="utf-8"))
    return TargetSelection(
        all_selected=bool(result.get("all_selected", False)),
        untested_selected=bool(result.get("untested_selected", False)),
        project_names=[str(name) for name in result.get("project_names", [])],
        service_names=[str(name) for name in result.get("service_names", [])],
        cancelled=bool(result.get("cancelled", False)),
    )


def _emit_parent_selector_thread_snapshot(*, emit: Any, stage: str) -> None:
    if not callable(emit):
        return
    try:
        current_frames = sys._current_frames()
    except Exception:
        current_frames = {}
    threads: list[dict[str, object]] = []
    for thread in threading.enumerate():
        frame = current_frames.get(thread.ident) if thread.ident is not None else None
        stack: list[str] = []
        if frame is not None:
            try:
                stack = [f"{item.filename}:{item.lineno}:{item.name}" for item in traceback.extract_stack(frame)[-12:]]
            except Exception:
                stack = []
        threads.append(
            {
                "name": thread.name,
                "ident": thread.ident,
                "daemon": thread.daemon,
                "alive": thread.is_alive(),
                "stack": stack,
            }
        )
    emit(
        "ui.selector.subprocess.parent_threads",
        component="ui.backend",
        stage=stage,
        thread_count=len(threads),
        threads=threads,
    )


def _flush_pending_input(runtime: Any) -> None:
    flush = getattr(runtime, "_flush_pending_interactive_input", None)
    if callable(flush):
        flush()


def _run_selector_preflight(
    runtime: Any,
    *,
    selector_kind: str,
    prompt: str,
    multi: bool,
) -> None:
    from .terminal_session import normalize_standard_tty_state

    emit = getattr(runtime, "_emit", None)
    termios_enabled = _debug_tty_group_enabled(runtime, "termios")
    reader_enabled = _debug_tty_group_enabled(runtime, "reader")
    _emit_debug_tty_group(
        runtime,
        group="termios",
        action="normalize_standard_tty_state",
        enabled=termios_enabled,
        detail=f"selector_preflight:{selector_kind}",
    )
    _emit_debug_tty_group(
        runtime,
        group="reader",
        action="stdin_restore_and_drain",
        enabled=reader_enabled,
        detail=f"selector_preflight:{selector_kind}",
    )
    preserve_output_tty_state = _preserve_output_tty_state_for_selector(runtime)
    if termios_enabled and not preserve_output_tty_state:
        normalize_standard_tty_state(emit=emit, component="ui.backend")
    _emit_selector_preflight(
        emit,
        stage="begin",
        selector_kind=selector_kind,
        prompt=prompt,
        multi=multi,
    )
    flush_enabled = reader_enabled and _selector_preflight_flag(
        runtime=runtime,
        key="ENVCTL_UI_SELECTOR_PREFLIGHT_FLUSH",
        default=False,
    )
    if flush_enabled:
        _flush_pending_input(runtime)

    fd = _stdin_tty_fd()
    if fd is None:
        _emit_selector_preflight(
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

    normalized = _normalize_stdin_line_mode(fd) if reader_enabled else False
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
    drain_enabled = reader_enabled and _selector_preflight_flag(
        runtime=runtime,
        key="ENVCTL_UI_SELECTOR_PREFLIGHT_DRAIN",
        default=False,
    )
    drained_bytes = _drain_stdin_escape_tail(fd=fd, max_window_seconds=0.03, max_bytes=64) if drain_enabled else 0
    _emit_selector_preflight(
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


def _selector_preflight_flag(*, runtime: Any, key: str, default: bool) -> bool:
    raw = ""
    env = getattr(runtime, "env", None)
    if isinstance(env, Mapping):
        raw = str(env.get(key, "")).strip().lower()
    if not raw:
        raw = str(os.environ.get(key, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _selector_launch_character_mode_enabled() -> bool:
    raw = str(os.environ.get("ENVCTL_UI_SELECTOR_CHARACTER_MODE", "")).strip().lower()
    if not raw:
        return False
    return raw in {"1", "true", "yes", "on"}


def _preserve_output_tty_state_for_selector(runtime: Any) -> bool:
    if not _debug_tty_group_enabled(runtime, "termios"):
        return True
    if str(os.environ.get("TERM_PROGRAM", "")).strip() != "Apple_Terminal":
        return False
    if not _selector_subprocess_enabled(runtime):
        return False
    return True


def _emit_selector_preflight(emit: Any, **payload: object) -> None:
    if callable(emit):
        emit("ui.selector.preflight", component="ui.backend", **payload)


def _stdin_tty_fd() -> int | None:
    if not sys.stdin.isatty():
        return None
    try:
        return sys.stdin.fileno()
    except (OSError, ValueError):
        return None


def _stdout_tty_fd() -> int | None:
    stream = getattr(sys, "stdout", None)
    if stream is None:
        return None
    try:
        fd = int(stream.fileno())
    except (OSError, ValueError, TypeError):
        return None
    try:
        if not os.isatty(fd):
            return None
    except Exception:
        return None
    return fd


def _normalize_stdin_line_mode(fd: int) -> bool:
    try:
        import termios

        state = termios.tcgetattr(fd)
        if len(state) > 3 and (int(state[3]) & int(termios.ICANON)) == 0:
            return True
    except Exception:
        pass
    try:
        from .terminal_session import _ensure_tty_line_mode  # noqa: PLC2701

        _ensure_tty_line_mode(fd=fd)
        return True
    except Exception:
        return False


def _drain_stdin_escape_tail(*, fd: int, max_window_seconds: float, max_bytes: int) -> int:
    if max_window_seconds <= 0 or max_bytes <= 0:
        return 0
    max_polls = max(1, int(max_window_seconds * 1000))
    polls = 0
    drained = 0
    while drained < max_bytes:
        if polls >= max_polls:
            break
        polls += 1
        try:
            # Nonblocking only: do not wait for fresh user keypresses.
            ready, _, _ = select.select([fd], [], [], 0)
        except Exception:
            break
        if not ready:
            break
        try:
            chunk = os.read(fd, 1)
        except Exception:
            break
        if not chunk:
            break
        drained += len(chunk)
    return drained
