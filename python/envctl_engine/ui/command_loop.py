from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import shlex
import sys
from typing import Any, Callable, cast
import uuid

from ..debug.debug_utils import hash_command
from ..state.models import RunState
from .color_policy import colors_enabled
from .command_aliases import normalize_interactive_command
from .debug_anomaly_rules import detect_dispatch_anomaly, detect_input_anomalies, detect_spinner_anomaly
from .spinner import Spinner, spinner, spinner_enabled, use_spinner_policy
from .spinner_service import emit_spinner_policy, resolve_spinner_policy
from .debug_snapshot import emit_plan_handoff_snapshot, snapshot_enabled
from .terminal_session import TerminalSession, _restore_stdin_terminal_sane


def _debug_plan_broad_group(runtime: object) -> str:
    rt = cast(Any, runtime)
    raw = ""
    env = getattr(rt, "env", None)
    if isinstance(env, Mapping):
        raw = str(env.get("ENVCTL_DEBUG_PLAN_BROAD_GROUP", "")).strip().lower()
    if raw in {"dashboard_loop_entry", "prompt_cycle", "selector_handoff"}:
        return raw
    return ""


def _debug_plan_tail_group(runtime: object) -> str:
    rt = cast(Any, runtime)
    raw = ""
    env = getattr(rt, "env", None)
    if isinstance(env, Mapping):
        raw = str(env.get("ENVCTL_DEBUG_PLAN_TAIL_GROUP", "")).strip().lower()
    if raw in {"dashboard_entry", "command_read", "selector_launch"}:
        return raw
    broad_group = _debug_plan_broad_group(runtime)
    if broad_group == "dashboard_loop_entry":
        return "dashboard_entry"
    if broad_group == "prompt_cycle":
        return "command_read"
    if broad_group == "selector_handoff":
        return "selector_launch"
    return ""


def _debug_plan_command_group(runtime: object) -> str:
    rt = cast(Any, runtime)
    raw = ""
    env = getattr(rt, "env", None)
    if isinstance(env, Mapping):
        raw = str(env.get("ENVCTL_DEBUG_PLAN_COMMAND_GROUP", "")).strip().lower()
    if raw in {"reload", "render", "prelude"}:
        return raw
    return ""


def _debug_plan_command_common_group(runtime: object) -> str:
    rt = cast(Any, runtime)
    raw = ""
    env = getattr(rt, "env", None)
    if isinstance(env, Mapping):
        raw = str(env.get("ENVCTL_DEBUG_PLAN_COMMAND_COMMON_GROUP", "")).strip().lower()
    if raw in {"session", "writes", "read"}:
        return raw
    return ""


def _debug_plan_command_always_group(runtime: object) -> str:
    rt = cast(Any, runtime)
    raw = ""
    env = getattr(rt, "env", None)
    if isinstance(env, Mapping):
        raw = str(env.get("ENVCTL_DEBUG_PLAN_COMMAND_ALWAYS_GROUP", "")).strip().lower()
    if raw in {"banner", "spinner", "state"}:
        return raw
    return ""


def _debug_plan_entry_group(runtime: object) -> str:
    rt = cast(Any, runtime)
    raw = ""
    env = getattr(rt, "env", None)
    if isinstance(env, Mapping):
        raw = str(env.get("ENVCTL_DEBUG_PLAN_ENTRY_GROUP", "")).strip().lower()
    if raw in {"bootstrap", "render", "dispatch"}:
        return raw
    return ""


def _debug_plan_postloop_group(runtime: object) -> str:
    rt = cast(Any, runtime)
    raw = ""
    env = getattr(rt, "env", None)
    if isinstance(env, Mapping):
        raw = str(env.get("ENVCTL_DEBUG_PLAN_POSTLOOP_GROUP", "")).strip().lower()
    if raw in {"direct_selector", "dashboard_only", "dashboard_selector"}:
        return raw
    return ""


def _debug_plan_selector_group(runtime: object) -> str:
    rt = cast(Any, runtime)
    raw = ""
    env = getattr(rt, "env", None)
    if isinstance(env, Mapping):
        raw = str(env.get("ENVCTL_DEBUG_PLAN_SELECTOR_GROUP", "")).strip().lower()
    if raw in {"context", "backend", "child", "minimal_direct", "state_direct", "helper_real", "standalone_child"}:
        return raw
    return ""


def _open_debug_grouped_selector_minimal(runtime: object) -> bool:
    from types import SimpleNamespace
    from .textual.screens.selector import select_grouped_targets_textual

    rt = cast(Any, runtime)
    projects = [
        SimpleNamespace(name="Project A"),
        SimpleNamespace(name="Project B"),
    ]
    services = [
        "Project A Backend",
        "Project A Frontend",
        "Project B Backend",
        "Project B Frontend",
    ]
    selection = select_grouped_targets_textual(
        prompt="Debug direct selector",
        projects=projects,
        services=services,
        allow_all=True,
        multi=True,
        emit=getattr(rt, "_emit", None),
    )
    if selection.cancelled:
        print("No test target selected.")
        return True
    print("Debug selector returned selection.")
    return True


def _open_debug_grouped_selector_state_direct(runtime: object, state: RunState) -> bool:
    from types import SimpleNamespace
    from .textual.screens.selector import select_grouped_targets_textual

    rt = cast(Any, runtime)
    project_names = sorted({name.rsplit(" ", 1)[0] for name in state.services if name.endswith(("Backend", "Frontend"))})
    if not project_names:
        project_names = sorted(state.requirements.keys())
    projects = [SimpleNamespace(name=name) for name in project_names]
    services = sorted(state.services.keys())
    selection = select_grouped_targets_textual(
        prompt="Debug state-direct selector",
        projects=projects,
        services=services,
        allow_all=True,
        multi=True,
        emit=getattr(rt, "_emit", None),
    )
    if selection.cancelled:
        print("No test target selected.")
        return True
    print("Debug selector returned selection.")
    return True


def _open_debug_grouped_selector(runtime: object, state: RunState) -> bool:
    rt = cast(Any, runtime)
    selector_group = _debug_plan_selector_group(rt)
    rt._emit(
        "startup.debug_selector_group",
        component="ui.command_loop",
        group=selector_group or "child",
        action="enter",
    )
    if selector_group == "minimal_direct":
        return _open_debug_grouped_selector_minimal(rt)
    if selector_group == "state_direct":
        return _open_debug_grouped_selector_state_direct(rt, state)
    services = sorted(state.services.keys())
    dashboard_orchestrator = getattr(rt, "dashboard_orchestrator", None)
    if dashboard_orchestrator is None:
        from .dashboard.orchestrator import DashboardOrchestrator
        dashboard_orchestrator = DashboardOrchestrator(rt)
    project_builder = getattr(dashboard_orchestrator, "_project_names_from_state", None)
    prompt_builder = getattr(dashboard_orchestrator, "_interactive_target_prompt", None)
    projects = project_builder(state, rt) if callable(project_builder) else []
    prompt = prompt_builder("test") if callable(prompt_builder) else "Run tests for"
    if selector_group == "standalone_child":
        from .backend import _run_selector_subprocess

        payload = {
            "kind": "grouped",
            "prompt": prompt,
            "project_names": [str(getattr(project, "name", "")) for project in projects],
            "services": services,
            "allow_all": True,
            "multi": True,
        }
        selection = _run_selector_subprocess(runtime=rt, payload=payload)
        if selection.cancelled:
            print("No test target selected.")
            return True
        print("Debug selector returned selection.")
        return True
    if selector_group == "context":
        from .textual.screens.selector import select_grouped_targets_textual

        selection = select_grouped_targets_textual(
            prompt=prompt,
            projects=projects,
            services=services,
            allow_all=True,
            multi=True,
            emit=getattr(rt, "_emit", None),
        )
    else:
        env = getattr(rt, "env", None)
        previous_common = ""
        if isinstance(env, dict):
            previous_common = str(env.get("ENVCTL_DEBUG_PLAN_TTY_COMMON_GROUP", ""))
            if selector_group == "backend":
                env["ENVCTL_DEBUG_PLAN_TTY_COMMON_GROUP"] = "preflight"
            elif selector_group == "child":
                env.pop("ENVCTL_DEBUG_PLAN_TTY_COMMON_GROUP", None)
        try:
            selection = rt._select_grouped_targets(
                prompt=prompt,
                projects=projects,
                services=services,
                allow_all=True,
                multi=True,
            )
        finally:
            if isinstance(env, dict):
                if selector_group == "backend":
                    if previous_common:
                        env["ENVCTL_DEBUG_PLAN_TTY_COMMON_GROUP"] = previous_common
                    else:
                        env.pop("ENVCTL_DEBUG_PLAN_TTY_COMMON_GROUP", None)
    if selection.cancelled:
        print("No test target selected.")
        return True
    print("Debug selector returned selection.")
    return True


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

    debug_command_common_group = _debug_plan_command_common_group(rt)
    debug_entry_group = _debug_plan_entry_group(rt)
    debug_postloop_group = _debug_plan_postloop_group(rt)
    use_session_bootstrap = not debug_command_common_group or debug_command_common_group == "session"
    use_prompt_writes = not debug_command_common_group or debug_command_common_group == "writes"
    use_real_read = not debug_command_common_group or debug_command_common_group == "read"
    if _debug_plan_tail_group(rt) == "dashboard_entry" and debug_entry_group:
        use_session_bootstrap = debug_entry_group == "bootstrap"
        use_prompt_writes = debug_entry_group == "render"
        use_real_read = False

    session: TerminalSession | None = None
    if use_session_bootstrap or use_real_read:
        session = TerminalSession(
            getattr(rt, "env", {}),
            input_provider=input_provider,
            emit=getattr(rt, "_emit", None),
            debug_recorder=getattr(rt, "_debug_recorder", None),
        )
    if use_session_bootstrap:
        rt._emit("ui.input.backend_policy", component="ui.command_loop", policy="prefer_basic_input")
    if debug_command_common_group:
        rt._emit(
            "startup.debug_command_common_group",
            component="ui.command_loop",
            group=debug_command_common_group,
            use_session_bootstrap=use_session_bootstrap,
            use_prompt_writes=use_prompt_writes,
            use_real_read=use_real_read,
        )
    use_color = colors_enabled(getattr(rt, "env", {}), stream=sys.stdout, interactive_tty=True)
    reset = "" if not use_color else "\033[0m"
    cyan = "" if not use_color else "\033[36m"
    yellow = "" if not use_color else "\033[33m"
    magenta = "" if not use_color else "\033[35m"

    minimal_dashboard = str(getattr(rt, 'env', {}).get('ENVCTL_DEBUG_MINIMAL_DASHBOARD', '')).strip().lower() in {'1', 'true', 'yes', 'on'}
    debug_plan_snapshot = snapshot_enabled(getattr(rt, "env", {}))
    debug_broad_group = _debug_plan_broad_group(rt)
    debug_tail_group = _debug_plan_tail_group(rt)
    debug_command_group = _debug_plan_command_group(rt)
    debug_command_always_group = _debug_plan_command_always_group(rt)
    use_always_banner = not debug_command_always_group or debug_command_always_group == "banner"
    use_always_spinner = not debug_command_always_group or debug_command_always_group == "spinner"
    use_always_state = not debug_command_always_group or debug_command_always_group == "state"
    if debug_tail_group == "dashboard_entry" and debug_entry_group:
        use_always_banner = debug_entry_group == "bootstrap"
        use_always_spinner = debug_entry_group == "bootstrap"
        use_always_state = debug_entry_group == "bootstrap"
        rt._emit(
            "startup.debug_entry_group",
            component="ui.command_loop",
            group=debug_entry_group,
            use_always_banner=use_always_banner,
            use_always_spinner=use_always_spinner,
            use_always_state=use_always_state,
            use_session_bootstrap=use_session_bootstrap,
            use_prompt_writes=use_prompt_writes,
        )
    if debug_command_always_group:
        rt._emit(
            "startup.debug_command_always_group",
            component="ui.command_loop",
            group=debug_command_always_group,
            use_always_banner=use_always_banner,
            use_always_spinner=use_always_spinner,
            use_always_state=use_always_state,
        )
    if use_always_state:
        rt._emit("ui.command_loop.enter", minimal=minimal_dashboard)
    if debug_broad_group:
        rt._emit(
            "startup.debug_broad_group",
            component="ui.command_loop",
            group=debug_broad_group,
            mapped_tail_group=debug_tail_group,
            action="enter",
            enabled=True,
        )
    if debug_tail_group:
        rt._emit(
            "startup.debug_tail_group",
            component="ui.command_loop",
            group=debug_tail_group,
            action="enter",
            enabled=True,
        )
    if use_always_banner:
        print("")
        print(f"{cyan}Interactive mode enabled. Services continue running until you stop them.{reset}")
        print(f"{cyan}Type 'help' for commands. Type 'q' to quit interactive mode.{reset}")
    base_spinner_policy = resolve_spinner_policy(getattr(rt, "env", {}))
    if use_always_spinner:
        rt._emit("ui.spinner.backend", backend=base_spinner_policy.backend)
        emit_spinner_policy(
            getattr(rt, "_emit", None),
            base_spinner_policy,
            context={"component": "ui.command_loop", "scope": "interactive_loop"},
        )
    if use_session_bootstrap:
        _call_or_default_flush(flush_pending_input)

    if debug_postloop_group:
        rt._emit(
            "startup.debug_postloop_group",
            component="ui.command_loop",
            group=debug_postloop_group,
            enabled=True,
        )

    current_state = state
    first_dashboard_render = True
    try:
        if debug_postloop_group == "direct_selector":
            _open_debug_grouped_selector(rt, current_state)
            return 0

        while True:
            if use_prompt_writes and not minimal_dashboard:
                if not debug_command_group or debug_command_group == "reload":
                    rt._emit(
                        "startup.debug_command_group",
                        component="ui.command_loop",
                        group=debug_command_group or "all",
                        action="state_reload",
                        enabled=True,
                    )
                    refreshed = rt._try_load_existing_state(
                        mode=current_state.mode,
                        strict_mode_match=True,
                    )
                    if refreshed is not None:
                        current_state = refreshed
                if not debug_command_group or debug_command_group == "render":
                    rt._emit(
                        "startup.debug_command_group",
                        component="ui.command_loop",
                        group=debug_command_group or "all",
                        action="dashboard_render",
                        enabled=True,
                    )
                    print("")
                    rt._print_dashboard_snapshot(current_state)
                    print(f"{magenta}Commands:{reset} (q)uit")
                    print(
                        f"  {magenta}Lifecycle:{reset} (s)top | (r)estart | stop-all | blast-all"
                    )
                    print(
                        f"  {magenta}Actions:{reset} (t)est | (p)r | (c)ommit | (a)nalyze | (m)igrate"
                    )
                    print(
                        f"  {magenta}Inspect:{reset} (l)ogs | (x) clear-logs | (h)ealth | (e)rrors | confi(g)"
                    )
            elif use_prompt_writes:
                print("")
                print(f"{cyan}Minimal interactive mode (debug). Type commands or q to quit.{reset}")
            if use_prompt_writes and first_dashboard_render and debug_plan_snapshot:
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
            if debug_command_group:
                rt._emit(
                    "startup.debug_command_group",
                    component="ui.command_loop",
                    group=debug_command_group,
                    action="prompt_prelude",
                    enabled=debug_command_group == "prelude",
                )
            rt._emit("ui.input.read.begin", component="ui.command_loop")
            try:
                if debug_tail_group == "dashboard_entry" and debug_entry_group in {"bootstrap", "render"}:
                    rt._emit(
                        "startup.debug_entry_group",
                        component="ui.command_loop",
                        group=debug_entry_group,
                        action="direct_selector_open",
                    )
                    _open_debug_grouped_selector(rt, current_state)
                    raw = "q"
                elif debug_tail_group == "dashboard_entry":
                    raw = "t"
                    rt._emit(
                        "startup.debug_tail_group",
                        component="ui.command_loop",
                        group=debug_tail_group,
                        action="inject_command",
                        enabled=True,
                        value="t",
                    )
                elif debug_command_common_group in {"session", "writes"}:
                    raw = "t"
                    rt._emit(
                        "startup.debug_command_common_group",
                        component="ui.command_loop",
                        group=debug_command_common_group,
                        action="inject_command",
                        value="t",
                    )
                elif debug_postloop_group in {"dashboard_only", "dashboard_selector"}:
                    raw = "t"
                    rt._emit(
                        "startup.debug_postloop_group",
                        component="ui.command_loop",
                        group=debug_postloop_group,
                        action="inject_command",
                        value="t",
                    )
                elif read_command_line is not None:
                    raw = read_command_line("Enter command: ")
                else:
                    raw = (session or TerminalSession(
                        getattr(rt, "env", {}),
                        input_provider=input_provider,
                        emit=getattr(rt, "_emit", None),
                        debug_recorder=getattr(rt, "_debug_recorder", None),
                    )).read_command_line("Enter command: ")
                rt._emit("ui.input.read.end", component="ui.command_loop", bytes_read=len(raw.encode("utf-8", errors="ignore")))
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
            if debug_postloop_group == "dashboard_only" and normalized_command == "test":
                rt._emit(
                    "startup.debug_postloop_group",
                    component="ui.command_loop",
                    group=debug_postloop_group,
                    action="suppress_selector",
                    enabled=True,
                )
                print('Debug dashboard-only mode: selector suppressed.')
                continue
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
            with use_spinner_policy(command_spinner_policy), spinner(
                _command_spinner_message(normalized_command),
                enabled=show_command_spinner,
                start_immediately=False,
            ) as active_spinner:
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
                rt._emit(spinner_anomaly["event"], component="ui.command_loop", **spinner_anomaly, command_id=command_id)
                if str(spinner_anomaly.get("severity", "")).lower() in {"high", "critical"}:
                    _emit_auto_pack(rt, reason="spinner_anomaly")

            if not should_continue:
                print("Exiting interactive mode (services continue running).")
                rt._emit("ui.command_loop.exit", reason="user_exit")
                return 0
    finally:
        _restore_terminal_on_loop_exit(rt)


def _call_or_default_can_interactive_tty(candidate: Callable[[], bool] | None) -> bool:
    if callable(candidate):
        return bool(candidate())
    from .dashboard.terminal_ui import RuntimeTerminalUI

    return RuntimeTerminalUI._can_interactive_tty()


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


@dataclass
class _SpinnerTracker:
    started: bool = False
    failed: bool = False
    failure_message: str = ""
    suppressed_by_suite_group: bool = False


def _normalize_interactive_command(raw: str) -> str | None:
    try:
        tokens = shlex.split(raw)
    except ValueError:
        return None
    if not tokens:
        return None
    command = tokens[0].strip().lower()
    return normalize_interactive_command(command)


def _command_supports_spinner(command: str) -> bool:
    return command in {
        "stop",
        "restart",
        "test",
        "pr",
        "commit",
        "analyze",
        "migrate",
        "config",
        "logs",
        "clear-logs",
        "health",
        "errors",
        "stop-all",
        "blast-all",
        "blast-worktree",
    }


def _command_spinner_message(command: str | None) -> str:
    messages = {
        "stop": "Stopping selected services...",
        "restart": "Preparing restart...",
        "test": "Preparing tests...",
        "pr": "Preparing pull request workflow...",
        "commit": "Preparing commit workflow...",
        "analyze": "Preparing analysis...",
        "migrate": "Preparing migrations...",
        "config": "Opening configuration...",
        "logs": "Loading logs...",
        "clear-logs": "Clearing logs...",
        "health": "Checking service health...",
        "errors": "Inspecting runtime errors...",
        "stop-all": "Stopping all services...",
        "blast-all": "Blasting all runtime processes...",
        "blast-worktree": "Blasting selected worktree...",
    }
    if command is None:
        return "Running command..."
    return messages.get(command, f"Running {command}...")


def _command_success_message(command: str | None, *, exiting: bool) -> str | None:
    if exiting:
        return "Command finished; leaving interactive mode..."
    if command is None:
        return "Command complete"
    if command == "pr":
        # PR output already includes concise status lines; suppress redundant
        # spinner success footer ("+ pr complete").
        return None
    return f"{command} complete"


def _command_label(command: str | None) -> str:
    if not command:
        return "Command"
    return command


def _install_spinner_event_bridge(
    *,
    runtime: Any,
    active_spinner: Spinner,
    tracker: _SpinnerTracker,
    command_id: str,
) -> Callable[[], None]:
    add_listener = getattr(runtime, "add_emit_listener", None)
    if callable(add_listener):
        def listener(event_name: str, payload: Mapping[str, object]) -> None:
            if _suite_spinner_group_enabled_event(event_name, payload):
                tracker.suppressed_by_suite_group = True
                if tracker.started:
                    _spinner_end(active_spinner)
                    tracker.started = False
                return
            if tracker.suppressed_by_suite_group and event_name == "ui.status":
                return
            if _spinner_starts_for_event(event_name) and not tracker.started:
                active_spinner.start()
                tracker.started = True
            message = _spinner_message_for_event(event_name, payload)
            if message and tracker.started:
                active_spinner.update(message)
            failure_message = _spinner_failure_message_for_event(event_name, payload)
            if failure_message and not tracker.failed:
                tracker.failed = True
                tracker.failure_message = failure_message
                if tracker.started:
                    active_spinner.update(failure_message)

        remove = add_listener(listener)
        if callable(remove):
            def restore_from_listener() -> None:
                remove()

            return restore_from_listener
        return _noop_restore

    emit = getattr(runtime, "_emit", None)
    if not callable(emit):
        return _noop_restore

    def bridged_emit(event_name: str, **payload: object) -> None:
        emit(event_name, **payload)
        if _suite_spinner_group_enabled_event(event_name, payload):
            tracker.suppressed_by_suite_group = True
            if tracker.started:
                _spinner_end(active_spinner)
                tracker.started = False
            return
        if tracker.suppressed_by_suite_group and event_name == "ui.status":
            return
        if _spinner_starts_for_event(event_name) and not tracker.started:
            active_spinner.start()
            tracker.started = True
        message = _spinner_message_for_event(event_name, payload)
        if message and tracker.started:
            active_spinner.update(message)
        failure_message = _spinner_failure_message_for_event(event_name, payload)
        if failure_message and not tracker.failed:
            tracker.failed = True
            tracker.failure_message = failure_message
            if tracker.started:
                active_spinner.update(failure_message)

    try:
        setattr(runtime, "_emit", bridged_emit)
    except Exception:
        return _noop_restore

    def restore() -> None:
        try:
            setattr(runtime, "_emit", emit)
        except Exception:
            pass

    return restore


def _spinner_message_for_event(event_name: str, payload: Mapping[str, object]) -> str | None:
    if event_name == "ui.status":
        message = _payload_text(payload, "message")
        return message or None
    if event_name == "startup.execution":
        mode = _payload_text(payload, "mode")
        project_count = _payload_count(payload, "projects")
        workers = _payload_text(payload, "workers")
        if project_count is not None and mode and workers:
            return f"Starting {project_count} project(s) in {mode} mode ({workers} workers)..."
        if project_count is not None and mode:
            return f"Starting {project_count} project(s) in {mode} mode..."
        return f"Starting services ({mode})..." if mode else "Starting services..."
    if event_name == "planning.projects.start":
        project_count = _payload_count(payload, "projects")
        if project_count is None:
            return "Preparing planning PRs..."
        return f"Preparing planning PRs for {project_count} project(s)..."
    if event_name == "state.resume":
        return "Resuming previous runtime state..."
    if event_name == "requirements.start":
        service = _payload_text(payload, "service") or "dependency"
        project = _payload_text(payload, "project")
        port = _payload_text(payload, "port")
        if project and port:
            return f"Starting {service} for {project} on port {port}..."
        return f"Starting {service} for {project}..." if project else f"Starting {service}..."
    if event_name == "requirements.healthy":
        service = _payload_text(payload, "service") or "dependency"
        project = _payload_text(payload, "project")
        return f"{service} healthy for {project}..." if project else f"{service} healthy..."
    if event_name == "service.bootstrap":
        service = _payload_text(payload, "service") or "service"
        step = _payload_text(payload, "step")
        if step:
            return f"Bootstrapping {service} ({step})..."
        return f"Bootstrapping {service}..."
    if event_name == "service.start":
        service = _payload_text(payload, "service") or "service"
        project = _payload_text(payload, "project")
        port = _payload_text(payload, "port")
        retry = _payload_text(payload, "retry").lower() in {"1", "true", "yes", "on"}
        prefix = "Retrying" if retry else "Starting"
        if project and port:
            return f"{prefix} {service} for {project} on port {port}..."
        return f"{prefix} {service} for {project}..." if project else f"{prefix} {service}..."
    if event_name == "service.bind.actual":
        service = _payload_text(payload, "service") or "service"
        port = _payload_text(payload, "actual_port")
        if port:
            return f"{service} bound on port {port}..."
        return f"Binding {service}..."
    if event_name == "cleanup.stop":
        return "Stopping selected services..."
    if event_name == "cleanup.stop_all":
        return "Stopping all services..."
    if event_name == "cleanup.blast":
        return "Blasting all services and containers..."
    if event_name == "cleanup.stop_all.remove_volumes":
        return "Removing Docker volumes..."
    if event_name == "action.command.start":
        command = _payload_text(payload, "command")
        return f"Running {command}..." if command else "Running command..."
    if event_name == "action.command.finish":
        command = _payload_text(payload, "command")
        code = _coerce_int(payload.get("code"))
        if code == 0:
            return f"{command} completed..." if command else "Command completed..."
    return None


def _spinner_starts_for_event(event_name: str) -> bool:
    return event_name in {
        "ui.status",
        "action.command.start",
        "startup.execution",
        "state.resume",
        "requirements.start",
        "service.bootstrap",
        "service.start",
        "cleanup.stop",
        "cleanup.stop_all",
        "cleanup.blast",
        "cleanup.stop_all.remove_volumes",
    }


def _spinner_failure_message_for_event(event_name: str, payload: Mapping[str, object]) -> str | None:
    if event_name == "action.command.finish":
        code = _coerce_int(payload.get("code"))
        if code is not None and code != 0:
            command = _payload_text(payload, "command") or "command"
            return f"{command} failed (exit {code})"
    if event_name == "planning.projects.finish":
        code = _coerce_int(payload.get("code"))
        if code is not None and code != 0:
            return f"Planning PR workflow failed (exit {code})"
    if event_name == "planning.projects.duplicate":
        return "Planning project selection failed"
    if event_name == "startup.failed":
        return "Startup failed"
    return None


def _suite_spinner_group_enabled_event(event_name: str, payload: Mapping[str, object]) -> bool:
    if event_name != "test.suite_spinner_group.policy":
        return False
    enabled = payload.get("enabled")
    if isinstance(enabled, bool):
        return enabled
    text = str(enabled).strip().lower()
    return text in {"1", "true", "yes", "on"}


def _spinner_end(active_spinner: Spinner) -> None:
    try:
        end = getattr(active_spinner, "end", None)
        if callable(end):
            end()
    except Exception:
        return


def _payload_text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if value is None:
        return ""
    return str(value).strip()


def _payload_count(payload: Mapping[str, object], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, list):
        return len(value)
    if isinstance(value, tuple):
        return len(value)
    return None


def _coerce_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit() or (stripped.startswith("-") and stripped[1:].isdigit()):
            return int(stripped)
    return None


def _noop_restore() -> None:
    return None


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
