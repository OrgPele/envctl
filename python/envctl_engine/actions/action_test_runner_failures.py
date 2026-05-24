from __future__ import annotations

from envctl_engine.test_output.parser_base import strip_ansi
from envctl_engine.test_output.progress_markers import strip_progress_markers


def clean_failure_lines(raw: object) -> list[str]:
    if not isinstance(raw, str):
        return []
    cleaned_lines: list[str] = []
    for line in raw.splitlines():
        cleaned = strip_ansi(strip_progress_markers(line)).strip()
        if cleaned:
            cleaned_lines.append(cleaned)
    return cleaned_lines


def format_failure_output_for_artifact(*, stdout: object, stderr: object, returncode: int) -> str:
    stderr_lines = clean_failure_lines(stderr)
    stdout_lines = clean_failure_lines(stdout)
    if stderr_lines and stdout_lines:
        return "\n".join(
            [
                "stderr:",
                *stderr_lines,
                "",
                "stdout:",
                *stdout_lines,
            ]
        )
    lines = stderr_lines or stdout_lines
    if not lines:
        return f"exit:{returncode}"
    return "\n".join(lines)


def summarize_failure_output(*, stdout: object, stderr: object, returncode: int) -> str:
    chunks = clean_failure_lines(stderr)
    if not chunks:
        chunks = clean_failure_lines(stdout)
    if not chunks:
        return f"exit:{returncode}"
    snippet = " | ".join(chunks[:3])
    if len(chunks) > 3:
        snippet += f" | +{len(chunks) - 3} more lines"
    return snippet


def failed_summary_artifact_available(
    *,
    summary_metadata: dict[str, dict[str, object]] | None,
    project_name: str,
) -> bool:
    if not isinstance(summary_metadata, dict):
        return False
    entry = summary_metadata.get(project_name)
    if not isinstance(entry, dict):
        return False
    status = str(entry.get("status", "")).strip().lower()
    if status and status != "failed":
        return False
    return bool(
        str(entry.get("short_summary_path", "") or "").strip() or str(entry.get("summary_path", "") or "").strip()
    )
