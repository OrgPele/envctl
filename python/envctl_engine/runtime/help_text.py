from __future__ import annotations

from collections.abc import Iterable

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.help_general import render_general_help
from envctl_engine.runtime.help_metadata import default_interactivity, ordered_known_commands
from envctl_engine.runtime.help_topics import (
    COMMAND_HELP_TOPICS as _COMMAND_HELP_TOPICS,
    CommandHelpTopic,
    _help_target_command as _topic_help_target_command,
    help_text_for_route,
    render_command_help,
)

COMMAND_HELP_TOPICS = _COMMAND_HELP_TOPICS


def render_help_text(route: Route | None) -> str:
    return help_text_for_route(route) or render_general_help()


def _default_interactivity(command: str) -> str:
    return default_interactivity(command)


def _help_target_command(route: Route | None) -> str | None:
    return _topic_help_target_command(route)


def _render_command_help(topic: CommandHelpTopic) -> str:
    return render_command_help(topic)


def _join_commands(commands: Iterable[str]) -> str:
    return ", ".join(commands)


def _ordered_known_commands(preferred_order: Iterable[str], commands: Iterable[str]) -> tuple[str, ...]:
    return ordered_known_commands(preferred_order, commands)
