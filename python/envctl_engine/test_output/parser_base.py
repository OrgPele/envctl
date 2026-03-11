"""Abstract base classes and data structures for test output parsing."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


_ANSI_CSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
_ANSI_OSC_RE = re.compile(r"\x1B\].*?(?:\x07|\x1B\\)", re.DOTALL)
_ANSI_STANDING_ESCAPE_RE = re.compile(r"\x1B[@-Z\\-_]")
_ANSI_DCS_PM_APC_RE = re.compile(r"\x1B[P^_X].*?\x1B\\", re.DOTALL)
_LITERAL_CSI_RE = re.compile(r"(?:\\x1b|\\033)\[[0-?]*[ -/]*[@-~]", re.IGNORECASE)
_LITERAL_OSC_RE = re.compile(r"(?:\\x1b|\\033)\].*?(?:\\x07|(?:\\x1b|\\033)\\\\)", re.IGNORECASE | re.DOTALL)
_LITERAL_DCS_PM_APC_RE = re.compile(r"(?:\\x1b|\\033)[P^_X].*?(?:\\x1b|\\033)\\\\", re.IGNORECASE | re.DOTALL)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


@dataclass(slots=True)
class TestResult:
    """Aggregated test execution results."""

    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    total: int = 0
    duration: float = 0.0
    counts_detected: bool = False
    failed_tests: list[str] = field(default_factory=list)
    error_details: dict[str, str] = field(default_factory=dict)
    coverage_path: str | None = None
    coverage_percent: float | None = None

    def success_rate(self) -> float:
        """Calculate success rate as percentage.

        Returns:
            Percentage of passed tests (0-100), or 0 if no tests.
        """
        if self.total == 0:
            return 0.0
        return (self.passed / self.total) * 100


class TestOutputParser(ABC):
    """Abstract base class for parsing test output formats."""

    result: TestResult

    def __init__(self) -> None:
        """Initialize parser."""
        self.result = TestResult()

    @abstractmethod
    def parse_line(self, line: str) -> None:
        """Parse a single line of test output.

        Args:
            line: Single line from test output.
        """
        pass

    def parse_output(self, output: str) -> TestResult:
        """Parse complete test output.

        Args:
            output: Full test output string.

        Returns:
            TestResult with aggregated metrics.
        """
        for line in output.splitlines():
            self.parse_line(line)
        return self.finalize()

    @abstractmethod
    def finalize(self) -> TestResult:
        """Finalize parsing and return results.

        Returns:
            TestResult with final aggregated metrics.
        """
        pass


def strip_ansi(text: str) -> str:
    cleaned = _ANSI_OSC_RE.sub("", text)
    cleaned = _ANSI_DCS_PM_APC_RE.sub("", cleaned)
    cleaned = _ANSI_CSI_RE.sub("", cleaned)
    cleaned = _ANSI_STANDING_ESCAPE_RE.sub("", cleaned)
    cleaned = _LITERAL_OSC_RE.sub("", cleaned)
    cleaned = _LITERAL_DCS_PM_APC_RE.sub("", cleaned)
    cleaned = _LITERAL_CSI_RE.sub("", cleaned)
    cleaned = cleaned.replace("\r", "")
    return _CONTROL_RE.sub("", cleaned)
