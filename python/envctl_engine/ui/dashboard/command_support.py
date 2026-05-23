from __future__ import annotations

from pathlib import Path
from collections.abc import Callable
from typing import Any, cast

from envctl_engine.runtime.command_policy import DASHBOARD_ALWAYS_HIDDEN_COMMANDS
from envctl_engine.runtime.command_router import Route, parse_route
from envctl_engine.state.models import RunState
from envctl_engine.ui.command_aliases import normalize_interactive_command
from envctl_engine.ui.command_parsing import (
    parse_interactive_command as parse_interactive_command_tokens,
    recover_single_letter_command_from_escape_fragment as recover_single_letter_command,
    sanitize_interactive_input as sanitize_command_input,
    tokens_set_mode as command_tokens_set_mode,
)
from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI
from envctl_engine.ui.debug_anomaly_rules import detect_dispatch_anomaly
from envctl_engine.ui.selector_model import SelectorItem
from envctl_engine.ui.textual.screens.selector import _run_selector_with_impl
from envctl_engine.ui.textual.screens.text_input_dialog import run_text_input_dialog_textual


RETURN_TO_DASHBOARD_PROMPT = "Press Enter to return to dashboard (manual confirmation required): "
PAUSE_BEFORE_DASHBOARD_COMMANDS = {"test", "review", "logs", "errors", "health", "clear-logs"}


def run_interactive_command(owner: Any, raw: str, state: RunState, rt: object) -> tuple[bool, RunState]:
    runtime_any = cast(Any, rt)
    raw_input = raw
    raw = owner._sanitize_interactive_input(raw)
    recovered_command = owner._recover_single_letter_command_from_escape_fragment(raw_input)
    if not raw and not recovered_command:
        return True, state

    command_tokens = owner._parse_interactive_command(raw)
    if command_tokens is None:
        return True, state
    if not command_tokens:
        if recovered_command:
            command_tokens = [recovered_command]
        else:
            return True, state

    if not command_tokens:
        return True, state

    command = command_tokens[0]
    if recovered_command:
        command = recovered_command
        command_tokens[0] = recovered_command
    if command in {"q", "quit", "exit"}:
        return False, state
    if command in {"help", "?"}:
        return True, state
    if command in {"session", "sessions"}:
        print("AI sessions are shown inline under each worktree. Use 'k' to kill AI sessions.")
        return True, state
    if command in {"k", "kill", "kill-session", "kill-sessions"}:
        owner._dispatch_kill_session(runtime_any)
        return True, state

    normalized = normalize_interactive_command(command)
    command_tokens[0] = normalized

    try:
        route = parse_route(command_tokens, env={**runtime_any.config.raw, **runtime_any.env})
    except Exception as exc:
        runtime_any._emit(
            "ui.command.parse.failed",
            component="dashboard_orchestrator",
            error=str(exc),
            raw=raw,
        )
        anomaly = detect_dispatch_anomaly(parse_failed=True, raw=raw, sanitized=raw)
        if anomaly is not None:
            runtime_any._emit(anomaly["event"], component="dashboard_orchestrator", **anomaly)
        print(f"Invalid command: {exc}")
        return True, state

    if not owner._tokens_set_mode(command_tokens):
        route = Route(
            command=route.command,
            mode=state.mode,
            raw_args=route.raw_args,
            passthrough_args=route.passthrough_args,
            projects=route.projects,
            flags=route.flags,
        )
    if route.command != "blast-all":
        route.flags = {**route.flags, "batch": True, "interactive_command": True}

    route = owner._apply_interactive_target_selection(route, state, rt)
    if route is None:
        return True, state

    if route.command == "stop":
        route = owner._apply_stop_scope_selection(route, state, rt)
        if route is None:
            return True, state

    if route.command == "pr":
        route = owner._dedupe_route_projects_by_git_root(route, state, rt)
        route, state = owner._maybe_prepare_pr_commit(route, state, rt)
        if route is None:
            return True, state

    if route.command == "restart":
        route = owner._apply_restart_selection(route, state, rt)
        if route is None:
            return True, state

    if route.command == "dashboard":
        runtime_any._print_dashboard_snapshot(state)
        return True, state

    hidden_commands = owner._dashboard_hidden_commands(state)
    if route.command in hidden_commands:
        if route.command in DASHBOARD_ALWAYS_HIDDEN_COMMANDS:
            print(f"Command '{route.command}' is not available in this dashboard context.")
            return True, state
        print(
            f"Command '{route.command}' is not available in this dashboard "
            "because envctl runs are disabled for this mode."
        )
        return True, state

    try:
        code = runtime_any.dispatch(route)
    except KeyboardInterrupt:
        code = 2
    runtime_any._emit(
        "ui.command.dispatch.result",
        component="dashboard_orchestrator",
        command=route.command,
        code=code,
    )
    refreshed = runtime_any._try_load_existing_state(mode=state.mode, strict_mode_match=True)
    if code in {2, 130} and refreshed is None:
        refreshed = state
    printed_interactive_result = False
    if route.command == "migrate":
        printed_interactive_result = owner._print_project_action_failure_details(
            route,
            state if refreshed is None else refreshed,
        )
    if code not in {0, 2, 130} and not printed_interactive_result:
        owner._print_interactive_failure_details(route, state if refreshed is None else refreshed, code=code)
    next_state = refreshed if refreshed is not None else state
    if code == 0 and route.command == "review":
        owner._maybe_offer_review_tab_launch(route, next_state, rt)
    if route.command in PAUSE_BEFORE_DASHBOARD_COMMANDS:
        if bool(getattr(runtime_any, "_dashboard_command_loop_active", False)):
            owner._queue_return_to_dashboard_prompt(runtime_any, RETURN_TO_DASHBOARD_PROMPT)
        else:
            owner._read_interactive_line(runtime_any, RETURN_TO_DASHBOARD_PROMPT)
    if route.command in {"stop-all", "blast-all"}:
        return False, state
    if refreshed is None:
        return False, state
    return True, refreshed


def read_interactive_line(runtime: Any, prompt: str) -> str:
    reader = getattr(runtime, "_read_interactive_command_line", None)
    if callable(reader):
        return str(reader(prompt))
    env = getattr(runtime, "env", {})
    return str(RuntimeTerminalUI.read_interactive_command_line(prompt, env))


def queue_return_to_dashboard_prompt(runtime: Any, prompt: str) -> None:
    try:
        setattr(runtime, "_dashboard_return_prompt", str(prompt))
    except Exception:
        return


def prompt_text_dialog(
    runtime: Any,
    *,
    title: str,
    help_text: str,
    placeholder: str,
    default_button_label: str,
) -> str | None:
    dialog = getattr(runtime, "_prompt_text_input", None)
    if callable(dialog):
        result = dialog(
            title=title,
            help_text=help_text,
            placeholder=placeholder,
            initial_value="",
            default_button_label=default_button_label,
        )
        if result is None:
            return None
        return str(result)
    result = run_text_input_dialog_textual(
        title=title,
        help_text=help_text,
        placeholder=placeholder,
        initial_value="",
        default_button_label=default_button_label,
        emit=getattr(runtime, "_emit", None),
    )
    if result is None:
        return None
    return str(result)


def prompt_commit_message(runtime: Any) -> str | None:
    return prompt_text_dialog(
        runtime,
        title="Commit Message",
        help_text="Commit message (leave blank to use the envctl commit log).",
        placeholder="Type a commit message",
        default_button_label="Use envctl commit log",
    )


def prompt_pr_message(runtime: Any) -> str | None:
    return prompt_text_dialog(
        runtime,
        title="PR Message",
        help_text="PR message (leave blank to use MAIN_TASK.md).",
        placeholder="Type a PR message",
        default_button_label="Use MAIN_TASK.md",
    )


def repo_root_for_project(project_root: Path) -> Path | None:
    current = Path(project_root).expanduser().resolve(strict=False)
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists() or (candidate / "todo").is_dir():
            return candidate
    return None


def dispatch_kill_session(
    runtime_any: Any,
    *,
    selector_fn: Callable[..., list[str] | None] = _run_selector_with_impl,
) -> None:
    try:
        from envctl_engine.runtime.session_management import kill_session  # noqa: PLC0415
        from envctl_engine.runtime.session_management import list_tmux_sessions  # noqa: PLC0415

        sessions = list_tmux_sessions()
        if not sessions:
            print("No active sessions to kill.")
            return
        values = selector_fn(
            prompt="Select sessions to kill:",
            options=[
                SelectorItem(
                    id=f"tmux-session:{session['name']}",
                    label=f"{session['name']} (windows: {session['windows']})",
                    kind="tmux_session",
                    token=session["name"],
                    scope_signature=(f"tmux_session:{session['name']}",),
                    section="AI Sessions",
                )
                for session in sessions
            ],
            multi=True,
            emit=getattr(runtime_any, "_emit", None),
        )
        if not values:
            return
        any_failed = False
        for raw_name in values:
            name = str(raw_name).strip()
            if not name:
                continue
            print(f"Killing: {name}")
            if not kill_session(name):
                any_failed = True
        if any_failed:
            print("Finished with session kill errors.")
        else:
            print("Done.")
    except Exception as exc:
        print(f"Error: {exc}")


def sanitize_interactive_input(raw: str) -> str:
    return sanitize_command_input(raw)


def recover_single_letter_command_from_escape_fragment(raw: str) -> str:
    return recover_single_letter_command(raw)


def parse_interactive_command(raw: str) -> list[str] | None:
    return parse_interactive_command_tokens(raw)


def tokens_set_mode(tokens: list[str]) -> bool:
    return command_tokens_set_mode(tokens)
