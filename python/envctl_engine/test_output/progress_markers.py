from __future__ import annotations

import re
from dataclasses import dataclass


PROGRESS_MARKER_PREFIX = "ENVCTL_TEST_PROGRESS:"
TOTAL_MARKER_PREFIX = "ENVCTL_TEST_TOTAL:"
DISCOVERED_MARKER_PREFIX = "ENVCTL_TEST_DISCOVERED:"
COMPLETE_MARKER_PREFIX = "ENVCTL_TEST_COMPLETE:"

_PROGRESS_RE = re.compile(r"ENVCTL_TEST_PROGRESS:(\d+)/(\d+)")
_TOTAL_RE = re.compile(r"ENVCTL_TEST_TOTAL:(\d+)")
_DISCOVERED_RE = re.compile(r"ENVCTL_TEST_DISCOVERED:(\d+)")
_COMPLETE_RE = re.compile(r"ENVCTL_TEST_COMPLETE:(\d+)")


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
    complete_match = _COMPLETE_RE.search(line)
    if complete_match:
        return TestProgressUpdate(current=int(complete_match.group(1)), total=0)
    total_match = _TOTAL_RE.search(line)
    if total_match:
        return TestProgressUpdate(current=0, total=int(total_match.group(1)))
    discovered_match = _DISCOVERED_RE.search(line)
    if discovered_match:
        return TestProgressUpdate(current=-1, total=int(discovered_match.group(1)))
    return None


def is_progress_marker(line: str) -> bool:
    return any(
        marker in line
        for marker in (
            PROGRESS_MARKER_PREFIX,
            TOTAL_MARKER_PREFIX,
            DISCOVERED_MARKER_PREFIX,
            COMPLETE_MARKER_PREFIX,
        )
    )


def strip_progress_markers(line: str) -> str:
    cleaned = _PROGRESS_RE.sub("", line)
    cleaned = _TOTAL_RE.sub("", cleaned)
    cleaned = _DISCOVERED_RE.sub("", cleaned)
    cleaned = _COMPLETE_RE.sub("", cleaned)
    return cleaned
