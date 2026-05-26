from __future__ import annotations

import re
from typing import Callable, Mapping

from envctl_engine.actions.action_test_summary_support import (
    format_summary_error_lines as default_format_summary_error_lines,
)
from envctl_engine.test_output.parser_base import strip_ansi


def project_action_failure_summary_lines(
    *,
    command_name: str,
    error_output: str,
    migrate_env_metadata: Mapping[str, object] | None = None,
    format_summary_error_lines: Callable[[str], list[str]] = default_format_summary_error_lines,
) -> list[str]:
    lines = format_summary_error_lines(error_output)
    if command_name != "migrate":
        return lines
    headline = migrate_failure_headline_from_lines(lines)
    hint_lines = migrate_failure_hint_lines(error_output)
    env_lines = migrate_env_source_hint_lines(migrate_env_metadata)
    merged: list[str] = []
    if headline:
        merged.append(headline)
    seen = set(merged)
    for line in lines:
        if line in seen:
            continue
        merged.append(line)
        seen.add(line)
    for hint in [*hint_lines, *env_lines]:
        if hint in seen:
            continue
        merged.append(hint)
        seen.add(hint)
    return merged


def migrate_failure_headline(
    error_output: str,
    *,
    format_summary_error_lines: Callable[[str], list[str]] = default_format_summary_error_lines,
) -> str:
    lines = format_summary_error_lines(error_output)
    headline = migrate_failure_headline_from_lines(lines)
    return headline or "Command failed."


def migrate_failure_headline_from_lines(lines: list[str]) -> str:
    if not lines:
        return ""
    has_exception = any(is_exception_start(line) for line in lines)
    for line in lines:
        if is_exception_start(line):
            return line
    for line in lines:
        if line == "Traceback (most recent call last):":
            continue
        if has_exception and line.startswith('File "'):
            continue
        if is_captured_output_header(line):
            continue
        if is_exception_context_marker(line):
            continue
        return line
    return lines[0]


def is_exception_start(line: str) -> bool:
    return bool(
        re.match(
            r"^(?:AssertionError|[A-Za-z_][\w.]*(?:Error|Exception|Failure|Exit|Interrupt|Warning))(?:\b|:)",
            line,
        )
    )


def is_exception_context_marker(line: str) -> bool:
    lowered = line.strip().lower()
    return "during handling of the above exception" in lowered or "the above exception was the direct cause" in lowered


def is_captured_output_header(line: str) -> bool:
    lowered = line.strip().lower()
    return (
        lowered.startswith("captured stdout")
        or lowered.startswith("captured stderr")
        or lowered.startswith("captured log")
        or lowered in {"stdout:", "stderr:"}
    )


def migrate_failure_hint_lines(error_output: str) -> list[str]:
    cleaned = strip_ansi(error_output)
    normalized = cleaned.replace("\\", "/").lower()
    if "alembic/env.py" not in normalized:
        return []
    if "validationerror" not in normalized and "field required" not in normalized and "type=missing" not in normalized:
        return []

    missing_vars = [
        name
        for name in ("DATABASE_URL", "REDIS_URL", "DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME")
        if re.search(rf"(?m)^{re.escape(name)}\s*$", cleaned)
    ]
    if not missing_vars:
        return []
    joined_vars = ", ".join(missing_vars)
    return [
        "hint: migrate failed before Alembic reached revisions because required env vars "
        f"were missing ({joined_vars}).",
        "hint: envctl migrate loads backend env from backend/.env by default.",
        "hint: BACKEND_ENV_FILE_OVERRIDE or MAIN_ENV_FILE_PATH can redirect the env file.",
        "hint: APP_ENV_FILE is exported when an env file is found, and running projects "
        "reuse current dependency URLs when available.",
    ]


def migrate_env_source_hint_lines(migrate_env_metadata: Mapping[str, object] | None) -> list[str]:
    if not isinstance(migrate_env_metadata, Mapping):
        return []
    source = str(migrate_env_metadata.get("env_file_source", "")).strip()
    if not source:
        return []
    parts = [f"hint: backend env source: {source}"]
    env_file_path_raw = migrate_env_metadata.get("env_file_path")
    env_file_path = str(env_file_path_raw).strip() if isinstance(env_file_path_raw, str) else ""
    if env_file_path:
        parts.append(env_file_path)
    if bool(migrate_env_metadata.get("override_requested")):
        resolution = str(migrate_env_metadata.get("override_resolution", "")).strip()
        if resolution:
            parts.append(f"override_resolution={resolution}")
    return [" | ".join(parts)]
