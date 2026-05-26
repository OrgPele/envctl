from __future__ import annotations

from contextlib import suppress
import shlex
import sys
from typing import Any, Callable, Mapping, cast
import uuid

from ..debug.debug_utils import hash_command
from ..runtime.command_policy import DASHBOARD_ALWAYS_HIDDEN_COMMANDS
from ..state.models import RunState
from .color_policy import colors_enabled
from .command_aliases import normalize_interactive_command
from . import command_loop_spinner as _spinner_support
from .debug_anomaly_rules import detect_input_anomalies, detect_spinner_anomaly
from .spinner import spinner, spinner_enabled, use_spinner_policy
from .spinner_service import emit_spinner_policy, resolve_spinner_policy
from .debug_snapshot import emit_plan_handoff_snapshot, snapshot_enabled
from .terminal_session import TerminalSession, _restore_stdin_terminal_sane

_SpinnerTracker = _spinner_support.CommandSpinnerTracker
_coerce_int = _spinner_support.coerce_int
_command_label = _spinner_support.command_label
_command_spinner_message = _spinner_support.command_spinner_message
_command_success_message = _spinner_support.command_success_message
_command_supports_spinner = _spinner_support.command_supports_spinner
_install_spinner_event_bridge = _spinner_support.install_spinner_event_bridge
_noop_restore = _spinner_support.noop_restore
_payload_count = _spinner_support.payload_count
_payload_text = _spinner_support.payload_text
_render_spinner_message = _spinner_support.render_spinner_message
_service_count_label = _spinner_support.service_count_label
_spinner_end = _spinner_support.spinner_end
_spinner_failure_message_for_event = _spinner_support.spinner_failure_message_for_event
_spinner_message_for_event = _spinner_support.spinner_message_for_event
_spinner_starts_for_event = _spinner_support.spinner_starts_for_event
_state_action_progress_message = _spinner_support.state_action_progress_message
_suite_spinner_group_enabled_event = _spinner_support.suite_spinner_group_enabled_event


def run_dashboard_command_loop(
    *,
    state: RunState,
    runtime: object,
    handle_command: Callable[[str, RunState, object], tuple[bool, RunState]],
    sanitize: Callable[[str], str],
    input_provider: Callable[[str], str] | None = None,
    can_interactive_tty: Callable[[], bool] | None = None,
    read_command_line: Callable[[str], str] | None = None,
    flush_pending_input: Callable[[], None] | None = None,
) -> int:
    rt = cast(Any, runtime)
    if not _call_or_default_can_interactive_tty(can_interactive_tty):
        rt._print_dashboard_snapshot(state)
        return 0
    setattr(rt, "_dashboard_command_loop_active", True)

    session = TerminalSession(
        getattr(rt, "env", {}),
        input_provider=input_provider,
        emit=getattr(rt, "_emit", None),
        debug_recorder=getattr(rt, "_debug_recorder", None),
    )
    rt._emit("ui.input.backend_policy", component="ui.command_loop", policy="prefer_basic_input")
    use_color = colors_enabled(getattr(rt, "env", {}), stream=sys.stdout, interactive_tty=True)
    reset = "" if not use_color else "\033[0m"
    cyan = "" if not use_color else "\033[36m"
    yellow = "" if not use_color else "\033[33m"
    magenta = "" if not use_color else "\033[35m"

    minimal_dashboard = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_MINIMAL_DASHBOARD", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    debug_plan_snapshot = snapshot_enabled(getattr(rt, "env", {}))
    rt._emit("ui.command_loop.enter", minimal=minimal_dashboard)
    print("")
    print(f"{cyan}Interactive mode enabled. Services continue running until you stop them.{reset}")
    print(f"{cyan}Type 'help' for commands. Type 'q' to quit interactive mode.{reset}")
    base_spinner_policy = resolve_spinner_policy(getattr(rt, "env", {}))
    rt._emit("ui.spinner.backend", backend=base_spinner_policy.backend)
    emit_spinner_policy(
        getattr(rt, "_emit", None),
        base_spinner_policy,
        context={"component": "ui.command_loop", "scope": "interactive_loop"},
    )
    _call_or_default_flush(flush_pending_input)

    current_state = state
    first_dashboard_render = True
    try:
        while True:
            hidden_commands = _dashboard_hidden_commands(current_state)
            if not minimal_dashboard:
                refreshed = rt._try_load_existing_state(
                    mode=current_state.mode,
                    strict_mode_match=True,
                )
                if refreshed is not None:
                    current_state = refreshed
                    hidden_commands = _dashboard_hidden_commands(current_state)
                print("")
                rt._print_dashboard_snapshot(current_state)
                print(f"{magenta}Commands:{reset} (q)uit")
                lifecycle_commands = [("(s)top services/deps", "stop"), ("(r)estart services", "restart")]
                visible_lifecycle = [label for label, command in lifecycle_commands if command not in hidden_commands]
                if visible_lifecycle:
                    print(f"  {magenta}Lifecycle:{reset} " + " | ".join(visible_lifecycle))
                action_commands = [
                    ("(t)est", "test"),
                    ("(p)r", "pr"),
                    ("(c)ommit", "commit"),
                    ("re(v)iew", "review"),
                    ("(m)igrate", "migrate"),
                ]
                visible_actions = [label for label, command in action_commands if command not in hidden_commands]
                if visible_actions:
                    print(f"  {magenta}Actions:{reset} " + " | ".join(visible_actions))
                session_commands = [
                    ("(k)ill AI sessions", "kill-session"),
                ]
                print(f"  {magenta}AI Sessions:{reset} " + " | ".join(label for label, _ in session_commands))
                inspect_commands = [
                    ("(l)ogs", "logs"),
                    ("(x) clear-logs", "clear-logs"),
                    ("(h)ealth", "health"),
                    ("(e)rrors", "errors"),
                ]
                visible_inspect = [label for label, command in inspect_commands if command not in hidden_commands]
                if visible_inspect:
                    print(f"  {magenta}Inspect:{reset} " + " | ".join(visible_inspect))
            else:
                print("")
                print(f"{cyan}Minimal interactive mode (debug). Type commands or q to quit.{reset}")
            if first_dashboard_render and debug_plan_snapshot:
                emit_plan_handoff_snapshot(
                    getattr(rt, "_emit", None),
                    env=getattr(rt, "env", {}),
                    checkpoint="after_first_dashboard_render",
                    extra={
                        "minimal_dashboard": minimal_dashboard,
                        "service_count": len(current_state.services),
                        "requirement_count": len(current_state.requirements),
                    },
                )
                first_dashboard_render = False
            rt._emit("ui.spinner.disabled", component="ui.command_loop", reason="input_phase_guard", phase="input")
            rt._emit("ui.input.read.begin", component="ui.command_loop")
            try:
                if read_command_line is not None:
                    raw = read_command_line("Enter command: ")
                else:
                    raw = session.read_command_line("Enter command: ")
                rt._emit(
                    "ui.input.read.end",
                    component="ui.command_loop",
                    bytes_read=len(raw.encode("utf-8", errors="ignore")),
                )
            except EOFError:
                print(f"{yellow}No interactive TTY input available; leaving interactive mode.{reset}")
                rt._emit("ui.command_loop.exit", reason="eof")
                return 0
            except KeyboardInterrupt:
                print("")
                raw = "q"
                rt._emit("ui.input.read.end", component="ui.command_loop", interrupted=True)

            rt._emit("ui.input.sanitize.before", component="ui.command_loop", len_before=len(raw))
            raw_before = raw
            raw = sanitize(raw)
            rt._emit("ui.input.sanitize.after", component="ui.command_loop", len_after=len(raw))

            backend = _latest_input_backend(rt)
            anomalies = detect_input_anomalies(
                raw=raw_before,
                sanitized=raw,
                backend=backend,
                bytes_read=len(raw_before.encode("utf-8", errors="ignore")),
            )
            for anomaly in anomalies:
                rt._emit(anomaly.get("event", "ui.anomaly.unknown"), component="ui.command_loop", **anomaly)
                recorder = getattr(rt, "_debug_recorder", None)
                if recorder is not None:
                    try:
                        recorder.append_anomaly(dict(anomaly))
                    except Exception:
                        pass
                if str(anomaly.get("severity", "")).lower() in {"high", "critical"}:
                    _emit_auto_pack(rt, reason="input_anomaly")

            if not raw:
                _call_or_default_flush(flush_pending_input)
                continue

            normalized_command = _normalize_interactive_command(raw)
            command_id = f"cmd-{uuid.uuid4().hex[:12]}"
            salt = str(getattr(rt, "_debug_hash_salt", "interactive"))
            command_hash, command_length = hash_command(raw, salt)
            rt._emit(
                "ui.input.submit",
                command_id=command_id,
                command_hash=command_hash,
                command_length=command_length,
                normalized_command=normalized_command,
            )
            setattr(rt, "_active_command_id", command_id)
            rt._emit(
                "ui.input.dispatch.begin",
                component="ui.command_loop",
                normalized_command=normalized_command,
                command_id=command_id,
            )
            command_spinner_policy = resolve_spinner_policy(getattr(rt, "env", {}))
            emit_spinner_policy(
                getattr(rt, "_emit", None),
                command_spinner_policy,
                context={"component": "ui.command_loop", "scope": "interactive_command", "command_id": command_id},
            )
            show_command_spinner = bool(
                normalized_command is not None
                and _command_supports_spinner(normalized_command)
                and spinner_enabled(getattr(rt, "env", {}))
            )
            tracker = _SpinnerTracker()
            with (
                use_spinner_policy(command_spinner_policy),
                spinner(
                    _command_spinner_message(normalized_command),
                    enabled=show_command_spinner,
                    start_immediately=False,
                ) as active_spinner,
            ):
                restore_emit = _install_spinner_event_bridge(
                    runtime=rt,
                    active_spinner=active_spinner,
                    tracker=tracker,
                    command_id=command_id,
                )
                try:
                    should_continue, current_state = handle_command(raw, current_state, runtime)
                except Exception:
                    if show_command_spinner and tracker.started and not tracker.failed:
                        active_spinner.fail(f"{_command_label(normalized_command)} failed")
                    _emit_auto_pack(rt, reason="interactive_exception")
                    raise
                finally:
                    restore_emit()
                    rt._emit(
                        "ui.input.dispatch.end",
                        component="ui.command_loop",
                        normalized_command=normalized_command,
                        command_id=command_id,
                    )
                    setattr(rt, "_active_command_id", None)

                if show_command_spinner and tracker.started:
                    rt._emit("ui.spinner.state", spinner_state="start", command_id=command_id)
                    if tracker.failed:
                        active_spinner.fail(tracker.failure_message or f"{_command_label(normalized_command)} failed")
                        rt._emit(
                            "ui.spinner.state",
                            spinner_state="fail",
                            command_id=command_id,
                            message=tracker.failure_message or f"{_command_label(normalized_command)} failed",
                        )
                    else:
                        success_message = _command_success_message(normalized_command, exiting=not should_continue)
                        if success_message:
                            active_spinner.succeed(success_message)
                        rt._emit(
                            "ui.spinner.state",
                            spinner_state="success",
                            command_id=command_id,
                        )

            spinner_anomaly = detect_spinner_anomaly(
                command_activity_seen=tracker.started,
                spinner_started=show_command_spinner,
            )
            if spinner_anomaly is not None:
                rt._emit(
                    spinner_anomaly["event"], component="ui.command_loop", **spinner_anomaly, command_id=command_id
                )
                if str(spinner_anomaly.get("severity", "")).lower() in {"high", "critical"}:
                    _emit_auto_pack(rt, reason="spinner_anomaly")

            _consume_post_dashboard_prompt(
                runtime=rt,
                session=session,
                read_command_line=read_command_line,
            )

            if not should_continue:
                print(_interactive_exit_message(normalized_command))
                rt._emit("ui.command_loop.exit", reason="user_exit")
                return 0
    finally:
        with suppress(Exception):
            setattr(rt, "_dashboard_command_loop_active", False)
            setattr(rt, "_dashboard_return_prompt", None)
        _restore_terminal_on_loop_exit(rt)


def _call_or_default_can_interactive_tty(candidate: Callable[[], bool] | None) -> bool:
    if callable(candidate):
        return bool(candidate())
    from .dashboard.terminal_ui import RuntimeTerminalUI

    return RuntimeTerminalUI._can_interactive_tty()


def _dashboard_hidden_commands(state: RunState) -> set[str]:
    raw = state.metadata.get("dashboard_hidden_commands")
    hidden = (
        {str(command).strip().lower() for command in raw if str(command).strip()} if isinstance(raw, list) else set()
    )
    hidden.update(DASHBOARD_ALWAYS_HIDDEN_COMMANDS)
    if not state.services:
        hidden.add("migrate")
    return hidden


def _restore_terminal_on_loop_exit(runtime: object) -> None:
    rt = cast(Any, runtime)
    try:
        _restore_stdin_terminal_sane(emit=getattr(rt, "_emit", None))
    except Exception:
        return


def _call_or_default_flush(candidate: Callable[[], None] | None) -> None:
    if callable(candidate):
        candidate()
        return
    from .dashboard.terminal_ui import RuntimeTerminalUI

    RuntimeTerminalUI.flush_pending_interactive_input()


def _consume_post_dashboard_prompt(
    *,
    runtime: Any,
    session: Any,
    read_command_line: Callable[[str], str] | None,
) -> None:
    prompt = str(getattr(runtime, "_dashboard_return_prompt", "") or "").strip()
    if not prompt:
        return
    with suppress(Exception):
        setattr(runtime, "_dashboard_return_prompt", None)
    runtime._emit(
        "ui.spinner.disabled", component="ui.command_loop", reason="input_phase_guard", phase="post_command_input"
    )
    runtime._emit("ui.input.read.begin", component="ui.command_loop", prompt_kind="post_command")
    try:
        if read_command_line is not None:
            raw = read_command_line(prompt)
        else:
            raw = session.read_command_line(prompt)
        runtime._emit(
            "ui.input.read.end",
            component="ui.command_loop",
            prompt_kind="post_command",
            bytes_read=len(raw.encode("utf-8", errors="ignore")),
        )
    except EOFError:
        runtime._emit("ui.input.read.end", component="ui.command_loop", prompt_kind="post_command", eof=True)
    except KeyboardInterrupt:
        print("")
        runtime._emit("ui.input.read.end", component="ui.command_loop", prompt_kind="post_command", interrupted=True)


def _normalize_interactive_command(raw: str) -> str | None:
    try:
        tokens = shlex.split(raw)
    except ValueError:
        return None
    if not tokens:
        return None
    command = tokens[0].strip().lower()
    return normalize_interactive_command(command)


def _interactive_exit_message(command: str | None) -> str:
    if command in {"stop-all", "blast-all"}:
        return "Exiting interactive mode."
    return "Exiting interactive mode (services continue running)."


def _spinner_backend_name(env: Mapping[str, str]) -> str:
    return "rich" if spinner_enabled(dict(env)) else "legacy"


def _latest_input_backend(runtime: Any) -> str:
    events = getattr(runtime, "events", [])
    if not isinstance(events, list):
        return "unknown"
    for event in reversed(events[-40:]):
        if not isinstance(event, Mapping):
            continue
        if str(event.get("event", "")) != "ui.input.backend":
            continue
        backend = event.get("backend")
        if isinstance(backend, str) and backend:
            return backend
    return "unknown"


def _emit_auto_pack(runtime: Any, *, reason: str) -> None:
    maybe = getattr(runtime, "_auto_debug_pack", None)
    if callable(maybe):
        try:
            maybe(reason=reason)
        except Exception:
            return
