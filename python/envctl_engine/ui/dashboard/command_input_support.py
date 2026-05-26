from __future__ import annotations

from pathlib import Path
from collections.abc import Callable
from typing import Any

from envctl_engine.ui.command_parsing import (
    parse_interactive_command as parse_interactive_command_tokens,
    recover_single_letter_command_from_escape_fragment as recover_single_letter_command,
    sanitize_interactive_input as sanitize_command_input,
    tokens_set_mode as command_tokens_set_mode,
)
from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI
from envctl_engine.ui.selector_model import SelectorItem
from envctl_engine.ui.textual.screens.selector import _run_selector_with_impl
from envctl_engine.ui.textual.screens.text_input_dialog import run_text_input_dialog_textual


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
