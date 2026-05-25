from __future__ import annotations

from pathlib import Path
from typing import Any

import envctl_engine.ui.dashboard.command_support as command_support
from envctl_engine.state.models import RunState
from envctl_engine.ui.textual.screens.selector import _run_selector_with_impl


class DashboardCommandMixin:
    def _run_interactive_command(self, raw: str, state: RunState, rt: object) -> tuple[bool, RunState]:
        return command_support.run_interactive_command(self, raw, state, rt)

    @staticmethod
    def _dashboard_hidden_commands(state: RunState) -> set[str]:
        return command_support.dashboard_hidden_commands(state)

    @staticmethod
    def _read_interactive_line(runtime: Any, prompt: str) -> str:
        return command_support.read_interactive_line(runtime, prompt)

    @staticmethod
    def _queue_return_to_dashboard_prompt(runtime: Any, prompt: str) -> None:
        command_support.queue_return_to_dashboard_prompt(runtime, prompt)

    @staticmethod
    def _prompt_text_dialog(
        runtime: Any,
        *,
        title: str,
        help_text: str,
        placeholder: str,
        default_button_label: str,
    ) -> str | None:
        return command_support.prompt_text_dialog(
            runtime,
            title=title,
            help_text=help_text,
            placeholder=placeholder,
            default_button_label=default_button_label,
        )

    @staticmethod
    def _prompt_commit_message(runtime: Any) -> str | None:
        return command_support.prompt_commit_message(runtime)

    @staticmethod
    def _prompt_pr_message(runtime: Any) -> str | None:
        return command_support.prompt_pr_message(runtime)

    @staticmethod
    def _sanitize_interactive_input(raw: str) -> str:
        return command_support.sanitize_interactive_input(raw)

    @staticmethod
    def _repo_root_for_project(project_root: Path) -> Path | None:
        return command_support.repo_root_for_project(project_root)

    def _dispatch_kill_session(self, runtime_any: Any) -> None:
        command_support.dispatch_kill_session(runtime_any, selector_fn=_run_selector_with_impl)

    @staticmethod
    def _recover_single_letter_command_from_escape_fragment(raw: str) -> str:
        return command_support.recover_single_letter_command_from_escape_fragment(raw)

    @staticmethod
    def _parse_interactive_command(raw: str) -> list[str] | None:
        return command_support.parse_interactive_command(raw)

    @staticmethod
    def _tokens_set_mode(tokens: list[str]) -> bool:
        return command_support.tokens_set_mode(tokens)
