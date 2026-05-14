from __future__ import annotations

import re

from envctl_engine.debug.debug_utils import scrub_sensitive_text
from envctl_engine.planning.plan_agent.models import AiCliReadyResult

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CODEX_READY_PROMPT_RE = re.compile(r"^[ \t]*[>›][ \t]*.*$")
_CODEX_LOADING_MARKERS = (
    "booting mcp server",
    "starting mcp server",
    "model:     loading",
    "model: loading",
)
_CODEX_READY_MARKERS = (
    "openai codex",
    "model:",
    "directory:",
)
_OPENCODE_LOADING_MARKERS = (
    "loading",
    "starting",
    "initializing",
    "please wait",
)
_OPENCODE_READY_MARKERS = (
    "ask anything",
    "ctrl+p commands",
    "/status",
)
_AI_CLI_SHELL_FAILURE_MARKERS = (
    "command not found",
    "not recognized",
    "no such file",
    "traceback",
)


def _prompt_picker_screen_looks_ready(cli: str, screen: str, prompt_text: str) -> bool:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli not in {"codex", "opencode"}:
        return True
    cleaned = _strip_ansi_sequences(screen)
    lower_text = cleaned.lower()
    if "unrecognized command" in lower_text or "no matching items" in lower_text:
        return False
    normalized_prompt = str(prompt_text).strip().lower()
    if not normalized_prompt:
        return False
    return lower_text.count(normalized_prompt) > 1


def _prompt_submit_screen_looks_ready(cli: str, screen: str, prompt_text: str) -> bool:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli not in {"codex", "opencode"}:
        return True
    cleaned = _strip_ansi_sequences(screen)
    lower_text = cleaned.lower()
    if "no matching items" in lower_text:
        return False
    normalized_prompt = str(prompt_text).strip().lower()
    if not normalized_prompt:
        return True
    prompt_lines = [line.strip().lower() for line in str(prompt_text).splitlines() if line.strip()]
    if not prompt_lines:
        return True
    matched_lines = sum(1 for line in prompt_lines if line in lower_text)
    if matched_lines != len(prompt_lines):
        return False
    if len(prompt_lines) == 1:
        return lower_text.count(prompt_lines[0]) == 1
    return True


def _post_submit_screen_looks_accepted(cli: str, screen: str, prompt_text: str) -> bool:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli != "opencode":
        return True
    cleaned = _strip_ansi_sequences(screen)
    lower_text = cleaned.lower()
    if "no matching items" in lower_text or "unrecognized command" in lower_text:
        return False
    if "ask anything" in lower_text and "/status" in lower_text:
        return True
    if _screen_looks_active(normalized_cli, screen):
        return True
    prompt_lines = [line.strip().lower() for line in str(prompt_text).splitlines() if line.strip()]
    if prompt_lines and all(line in lower_text for line in prompt_lines):
        return False
    return False


def _screen_looks_active(cli: str, screen: str) -> bool:
    normalized_cli = str(cli).strip().lower()
    cleaned = _strip_ansi_sequences(screen)
    lower_text = cleaned.lower()
    if normalized_cli in {"opencode", "codex"}:
        return "esc to interrupt" in lower_text and ("working" in lower_text or "ctrl+c" in lower_text)
    return False


def _screen_looks_ready(cli: str, screen: str) -> bool:
    normalized_cli = str(cli).strip().lower()
    cleaned = _strip_ansi_sequences(screen)
    if normalized_cli == "codex":
        lower_text = cleaned.lower()
        if any(marker in lower_text for marker in _CODEX_LOADING_MARKERS):
            return False
        if not all(marker in lower_text for marker in _CODEX_READY_MARKERS):
            return False
        lines = [line.rstrip() for line in cleaned.splitlines() if line.strip()]
        for line in lines[-6:]:
            if _CODEX_READY_PROMPT_RE.match(line):
                return True
        return False
    if normalized_cli != "opencode":
        return False
    lower_text = _screen_tail_text(cleaned).lower()
    if any(marker in lower_text for marker in _AI_CLI_SHELL_FAILURE_MARKERS):
        return False
    if any(marker in lower_text for marker in _OPENCODE_LOADING_MARKERS):
        return False
    if all(marker in lower_text for marker in _OPENCODE_READY_MARKERS):
        return True
    return False


def _strip_ansi_sequences(raw: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", str(raw or "")).replace("\r", "")


def _screen_tail_text(cleaned: str, *, line_count: int = 12) -> str:
    lines = [line.rstrip() for line in str(cleaned or "").splitlines() if line.strip()]
    return "\n".join(lines[-line_count:])


def _screen_excerpt(raw: str, *, limit: int = 600) -> str:
    cleaned = _strip_ansi_sequences(raw).strip()
    if not cleaned:
        return ""
    lines = [line.rstrip() for line in cleaned.splitlines() if line.strip()]
    excerpt = scrub_sensitive_text("\n".join(lines[-8:]).strip())
    if len(excerpt) <= limit:
        return excerpt
    return excerpt[-limit:]


def _format_ai_cli_ready_failure(result: AiCliReadyResult) -> str:
    reason = str(result.reason or "ai_cli_ready_timeout").strip() or "ai_cli_ready_timeout"
    excerpt = str(result.screen_excerpt or "").strip()
    if excerpt:
        return f"{reason}: {excerpt}"
    return reason


def _normalized_screen_text(raw: str) -> str:
    cleaned = _strip_ansi_sequences(raw).lower()
    return " ".join(cleaned.split())
