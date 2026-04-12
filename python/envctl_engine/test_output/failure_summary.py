from __future__ import annotations

from pathlib import Path
import re
from typing import Mapping

from envctl_engine.test_output.parser_base import strip_ansi


def extract_failure_summary_excerpt(summary_text: str, *, max_lines: int = 4) -> list[str]:
    if max_lines <= 0:
        return []
    lines = [strip_ansi(raw).strip() for raw in str(summary_text or "").splitlines()]
    lines = [line for line in lines if line and not line.startswith("#")]
    if not lines or "No failed tests." in lines:
        return []

    sections: list[str] = []
    failures: list[str] = []
    details: list[str] = []
    fallback: list[str] = []

    for line in lines:
        normalized = _normalize_summary_line(line)
        if not normalized:
            continue
        if normalized.startswith("[") and normalized.endswith("]"):
            if normalized not in sections:
                sections.append(normalized)
            if normalized not in fallback:
                fallback.append(normalized)
            continue
        if normalized not in fallback:
            fallback.append(normalized)
        if line.lstrip().startswith("- "):
            if normalized not in failures:
                failures.append(normalized)
            continue
        if _is_low_signal_detail(normalized):
            continue
        if normalized not in details:
            details.append(normalized)

    excerpt: list[str] = []
    for bucket in (sections, failures, details, fallback):
        for line in bucket:
            if line in excerpt:
                continue
            excerpt.append(line)
            if len(excerpt) >= max_lines:
                return excerpt
    return excerpt[:max_lines]


def summary_excerpt_from_entry(entry: Mapping[str, object], *, max_lines: int = 4) -> list[str]:
    raw_excerpt = entry.get("summary_excerpt")
    if isinstance(raw_excerpt, list):
        rendered = [str(line).strip() for line in raw_excerpt if str(line).strip()]
        if rendered:
            return rendered[:max_lines]
    for key in ("short_summary_path", "summary_path"):
        raw_path = str(entry.get(key, "") or "").strip()
        if not raw_path:
            continue
        path = Path(raw_path).expanduser()
        if not path.is_file():
            continue
        try:
            return extract_failure_summary_excerpt(path.read_text(encoding="utf-8", errors="ignore"), max_lines=max_lines)
        except OSError:
            continue
    return []


def _normalize_summary_line(line: str) -> str:
    text = strip_ansi(line).strip()
    if not text:
        return ""
    if text.startswith("- "):
        text = text[2:].strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _is_low_signal_detail(line: str) -> bool:
    lowered = line.lower()
    if line == "Traceback (most recent call last):":
        return True
    if line.startswith('File "') or lowered.startswith("file "):
        return True
    if lowered.startswith("line ") and " in " in lowered:
        return True
    return line in {"^", "..."}
