from __future__ import annotations

from envctl_engine.runtime.command_router import Route, parse_route
from envctl_engine.runtime.help_topic_catalog import COMMAND_HELP_TOPICS
from envctl_engine.runtime.help_topic_rendering import CommandHelpTopic, render_command_help


def help_text_for_route(route: Route | None) -> str | None:
    target = _help_target_command(route)
    if target is not None:
        topic = COMMAND_HELP_TOPICS.get(target)
        if topic is not None:
            return render_command_help(topic)
    return None


def _help_target_command(route: Route | None) -> str | None:
    if route is None:
        return None
    raw_args = [str(token) for token in list(getattr(route, "raw_args", []) or []) if str(token).strip()]
    filtered = [token for token in raw_args if token not in {"--help", "-h", "help"}]
    if not filtered:
        return None
    direct_target = filtered[0]
    if direct_target in COMMAND_HELP_TOPICS:
        return direct_target
    if direct_target.startswith("--") and direct_target[2:] in COMMAND_HELP_TOPICS:
        return direct_target[2:]
    try:
        resolved = parse_route(filtered, env={})
    except Exception:
        return None
    command = str(getattr(resolved, "command", "")).strip()
    return command if command and command != "help" else None


__all__ = [
    "COMMAND_HELP_TOPICS",
    "CommandHelpTopic",
    "_help_target_command",
    "help_text_for_route",
    "render_command_help",
]
