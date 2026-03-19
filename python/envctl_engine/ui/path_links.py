from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import re
import sys
from typing import Mapping, TextIO, TypeVar


_SUPPORTED_TERM_PROGRAMS = {"apple_terminal", "iterm.app", "wezterm", "vscode", "hyper"}
_SUPPORTED_TERM_TOKENS = ("kitty", "wezterm", "vte", "konsole", "foot", "ghostty")
_ABSOLUTE_PATH_FRAGMENT_RE = re.compile(r"(?P<path>/(?:[^\s;,)])+)")


@dataclass(frozen=True, slots=True)
class PathLink:
    display_text: str
    uri: str | None
    enabled: bool


def normalize_local_path_text(path: object) -> str:
    text = str(path or "")
    if text == "/private/tmp":
        return "/tmp"
    if text.startswith("/private/tmp/"):
        return "/tmp/" + text[len("/private/tmp/") :]
    return text


def resolve_path_link(
    path: object,
    *,
    env: Mapping[str, str] | None = None,
    stream: TextIO | None = None,
    interactive_tty: bool | None = None,
) -> PathLink:
    display_text = normalize_local_path_text(path)
    enabled = _hyperlinks_enabled(env=env, stream=stream, interactive_tty=interactive_tty)
    uri = _file_uri(display_text) if enabled and display_text else None
    return PathLink(display_text=display_text, uri=uri, enabled=bool(enabled and uri))


def render_path_for_terminal(
    path: object,
    *,
    env: Mapping[str, str] | None = None,
    stream: TextIO | None = None,
    interactive_tty: bool | None = None,
) -> str:
    return render_path_fragment_for_terminal(
        path,
        env=env,
        stream=stream,
        interactive_tty=interactive_tty,
    )


def render_path_fragment_for_terminal(
    path: object,
    *,
    display_text: str | None = None,
    env: Mapping[str, str] | None = None,
    stream: TextIO | None = None,
    interactive_tty: bool | None = None,
) -> str:
    link = resolve_path_link(path, env=env, stream=stream, interactive_tty=interactive_tty)
    visible_text = link.display_text if display_text is None else str(display_text)
    if not link.enabled or not link.uri:
        return visible_text
    return f"\x1b]8;;{link.uri}\x1b\\{visible_text}\x1b]8;;\x1b\\"


def render_paths_in_terminal_text(
    text: str,
    *,
    paths: Sequence[object],
    env: Mapping[str, str] | None = None,
    stream: TextIO | None = None,
    interactive_tty: bool | None = None,
) -> str:
    rendered = str(text)
    replacements: list[tuple[str, str]] = []
    seen: set[str] = set()
    for path in paths:
        raw_text = str(path or "")
        for candidate in _path_display_candidates(raw_text):
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            fragment = render_path_fragment_for_terminal(
                candidate,
                display_text=candidate,
                env=env,
                stream=stream,
                interactive_tty=interactive_tty,
            )
            if fragment == candidate:
                continue
            replacements.append((candidate, fragment))
    for raw_text, fragment in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        rendered = rendered.replace(raw_text, fragment)
    return rendered


_TextT = TypeVar("_TextT")


def rich_path_text(
    path: object,
    *,
    text_cls: type[_TextT],
    env: Mapping[str, str] | None = None,
    stream: TextIO | None = None,
    interactive_tty: bool | None = None,
) -> _TextT:
    link = resolve_path_link(path, env=env, stream=stream, interactive_tty=interactive_tty)
    style = f"link {link.uri}" if link.enabled and link.uri else None
    return text_cls(link.display_text, style=style)


def local_paths_in_text(text: str) -> tuple[str, ...]:
    candidates: list[str] = []
    for match in _ABSOLUTE_PATH_FRAGMENT_RE.finditer(str(text)):
        candidate = _trim_extracted_path(match.group("path").strip())
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return tuple(candidates)


def _trim_extracted_path(candidate: str) -> str:
    if candidate.startswith("//"):
        return ""
    trimmed = candidate.rstrip(":")
    if trimmed.endswith("..."):
        trimmed = trimmed[:-3]
    return trimmed


def _file_uri(display_text: str) -> str | None:
    normalized = display_text.strip()
    if not normalized:
        return None
    try:
        candidate = Path(normalized).expanduser()
    except (OSError, RuntimeError, ValueError):
        return None
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    try:
        return candidate.as_uri()
    except ValueError:
        return None


def _path_display_candidates(raw_text: str) -> tuple[str, ...]:
    candidates: list[str] = []
    for candidate in (
        raw_text,
        _resolved_path_text(raw_text),
        _private_var_alias(raw_text),
    ):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return tuple(candidates)


def _resolved_path_text(raw_text: str) -> str:
    normalized = raw_text.strip()
    if not normalized:
        return ""
    try:
        return str(Path(normalized).resolve())
    except (OSError, RuntimeError, ValueError):
        return ""


def _private_var_alias(raw_text: str) -> str:
    if raw_text.startswith("/private/var/"):
        return raw_text[len("/private") :]
    if raw_text.startswith("/var/"):
        return "/private" + raw_text
    return ""


def _hyperlinks_enabled(
    *,
    env: Mapping[str, str] | None,
    stream: TextIO | None,
    interactive_tty: bool | None,
) -> bool:
    merged = dict(os.environ)
    if env:
        merged.update({str(key): str(value) for key, value in env.items()})

    mode_raw = str(merged.get("ENVCTL_UI_HYPERLINK_MODE", "auto")).strip().lower()
    mode = mode_raw if mode_raw in {"auto", "on", "off"} else "auto"
    if mode == "off":
        return False

    if interactive_tty is None:
        output = stream or sys.stdout
        is_tty = bool(getattr(output, "isatty", lambda: False)())
    else:
        is_tty = interactive_tty
    if not is_tty:
        return False

    if str(merged.get("TERM", "")).strip().lower() == "dumb":
        return False
    if mode == "on":
        return True
    return _terminal_supports_hyperlinks(merged)


def _terminal_supports_hyperlinks(env: Mapping[str, str]) -> bool:
    term_program = str(env.get("TERM_PROGRAM", "")).strip().lower()
    if term_program in _SUPPORTED_TERM_PROGRAMS:
        return True
    if any(str(env.get(key, "")).strip() for key in ("WT_SESSION", "VTE_VERSION", "KONSOLE_VERSION", "DOMTERM")):
        return True
    if str(env.get("KITTY_WINDOW_ID", "")).strip():
        return True
    term = str(env.get("TERM", "")).strip().lower()
    return any(token in term for token in _SUPPORTED_TERM_TOKENS)
