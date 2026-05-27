from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from envctl_engine.runtime.help_metadata import default_interactivity


@dataclass(frozen=True, slots=True)
class CommandHelpTopic:
    command: str
    summary: str
    usage: tuple[str, ...]
    what_it_does: tuple[str, ...]
    examples: tuple[str, ...]
    flags: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    related: tuple[str, ...] = ()


def render_command_help(topic: CommandHelpTopic) -> str:
    lines: list[str] = [f"envctl {topic.command} - {topic.summary}", ""]
    _extend_section(lines, "Usage:", topic.usage, bullet=False)
    _extend_section(lines, "What it does:", topic.what_it_does)
    lines.extend(["Default interactivity:", f"  {default_interactivity(topic.command)}", ""])
    if topic.flags:
        _extend_section(lines, "Common flags:", topic.flags, bullet=False)
    if topic.notes:
        _extend_section(lines, "Notes:", topic.notes)
    _extend_section(lines, "Examples:", topic.examples, bullet=False)
    if topic.aliases:
        lines.extend(["Aliases:", f"  {_join_commands(topic.aliases)}", ""])
    if topic.related:
        lines.extend(["Related commands:", f"  {_join_commands(topic.related)}", ""])
    lines.append("Tip: use `envctl --help` for the full command map and global flags.")
    return "\n".join(lines).rstrip()


def _extend_section(lines: list[str], heading: str, values: Iterable[str], *, bullet: bool = True) -> None:
    materialized = tuple(values)
    if not materialized:
        return
    lines.append(heading)
    prefix = "  - " if bullet else "  "
    for value in materialized:
        lines.append(f"{prefix}{value}")
    lines.append("")


def _join_commands(commands: Iterable[str]) -> str:
    return ", ".join(commands)
