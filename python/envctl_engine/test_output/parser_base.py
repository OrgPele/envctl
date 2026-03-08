"""Abstract base classes and data structures for test output parsing."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import re


@dataclass(slots=True)
class TestResult:
    """Aggregated test execution results."""

    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    total: int = 0
    duration: float = 0.0
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
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return ansi_escape.sub("", text)
