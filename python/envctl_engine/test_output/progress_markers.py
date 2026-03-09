from __future__ import annotations

import re
from dataclasses import dataclass


PROGRESS_MARKER_PREFIX = "ENVCTL_TEST_PROGRESS:"
TOTAL_MARKER_PREFIX = "ENVCTL_TEST_TOTAL:"

_PROGRESS_RE = re.compile(r"ENVCTL_TEST_PROGRESS:(\d+)/(\d+)")
_TOTAL_RE = re.compile(r"ENVCTL_TEST_TOTAL:(\d+)")


@dataclass(frozen=True, slots=True)
class TestProgressUpdate:
    current: int
    total: int


def parse_progress_marker(line: str) -> TestProgressUpdate | None:
    progress_match = _PROGRESS_RE.search(line)
    if progress_match:
        return TestProgressUpdate(
            current=int(progress_match.group(1)),
            total=int(progress_match.group(2)),
        )
    total_match = _TOTAL_RE.search(line)
    if total_match:
        return TestProgressUpdate(current=0, total=int(total_match.group(1)))
    return None


def is_progress_marker(line: str) -> bool:
    return PROGRESS_MARKER_PREFIX in line or TOTAL_MARKER_PREFIX in line


def strip_progress_markers(line: str) -> str:
    cleaned = _PROGRESS_RE.sub("", line)
    cleaned = _TOTAL_RE.sub("", cleaned)
    return cleaned
