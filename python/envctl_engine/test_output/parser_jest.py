"""Parser for Jest/Vitest test output format."""

from __future__ import annotations

import re
from typing import override
from .parser_base import TestOutputParser, TestResult, strip_ansi


class JestOutputParser(TestOutputParser):
    """Parses Jest/Vitest test output and extracts metrics."""

    def __init__(self) -> None:
        """Initialize Jest parser."""
        super().__init__()
        self._current_file: str | None = None
        self._in_test_section: bool = False
        self._lines: list[str] = []
        self._failed_files: list[str] = []

    @override
    def parse_line(self, line: str) -> None:
        """Parse a single line of Jest output.

        Args:
            line: Single line from Jest output.
        """
        # Strip ANSI escape codes
        clean_line = strip_ansi(line)
        self._lines.append(clean_line)

        # Check for file markers
        if clean_line.lstrip().startswith("PASS "):
            self._parse_pass_file(clean_line)
        elif clean_line.lstrip().startswith("FAIL "):
            self._parse_fail_file(clean_line)
        elif "✕" in clean_line or "✓" in clean_line:
            self._parse_test_result_line(clean_line)
        elif self._is_tests_summary_line(clean_line):
            self._parse_summary_line(clean_line)
        elif self._is_duration_line(clean_line):
            self._parse_time_line(clean_line)

    @override
    def finalize(self) -> TestResult:
        """Finalize parsing and return results.

        Returns:
            TestResult with final aggregated metrics.
        """
        if self.result.duration <= 0:
            self._backfill_duration_from_lines()
        if self.result.failed == 0:
            self.result.failed = len(self._failed_files)
        if self.result.total == 0:
            self.result.total = self.result.passed + self.result.failed + self.result.skipped
        if not self.result.failed_tests and self._failed_files:
            self.result.failed_tests.extend(self._failed_files)
        # Ensure failed suite files are represented when individual test names were captured.
        seen = set(self.result.failed_tests)
        for failed_file in self._failed_files:
            if failed_file not in seen:
                self.result.failed_tests.append(failed_file)
                seen.add(failed_file)
        self._populate_error_details()

        # Calculate total
        self.result.total = self.result.passed + self.result.failed + self.result.skipped
        return self.result

    def _parse_pass_file(self, line: str) -> None:
        """Parse a PASS file line.

        Args:
            line: Line starting with "PASS ".
        """
        # Format: "PASS src/components/Button.test.tsx"
        match = re.match(r"\s*PASS\s+(.+)$", line)
        if match:
            self._current_file = match.group(1)

    def _parse_fail_file(self, line: str) -> None:
        """Parse a FAIL file line.

        Args:
            line: Line starting with "FAIL ".
        """
        # Format: "FAIL src/components/Button.test.tsx"
        match = re.match(r"\s*FAIL\s+(.+)$", line)
        if match:
            failed_file = self._normalize_failed_file(match.group(1))
            self._current_file = failed_file
            if failed_file not in self._failed_files:
                self._failed_files.append(failed_file)

    def _parse_test_result_line(self, line: str) -> None:
        """Parse individual test result lines.

        Args:
            line: Line containing test result with ✕ or ✓ marker.
        """
        # Format: "✕ should render button" or "✓ should render button"
        if "✕" in line:
            # Extract test name after the ✕ marker
            match = re.search(r"✕\s+(.+?)(?:\s+\(|$)", line)
            if match:
                test_name = match.group(1).strip()
                if self._current_file:
                    full_name = f"{self._current_file}::{test_name}"
                else:
                    full_name = test_name
                if full_name not in self.result.failed_tests:
                    self.result.failed_tests.append(full_name)
        elif "✓" in line:
            # Count passed tests
            pass

    def _parse_summary_line(self, line: str) -> None:
        """Parse the summary line.

        Args:
            line: Summary line with test counts.
        """
        # Format variants:
        # - "Tests: 5 failed, 10 passed, 15 total"
        # - "Tests  43 passed | 1 skipped (44)" (vitest)
        # - "Test Files  2 passed (2)" (ignored for per-test metrics)

        # Extract counts
        self.result.counts_detected = True
        passed_match = re.search(r"(\d+)\s+passed", line)
        if passed_match:
            self.result.passed = int(passed_match.group(1))

        failed_match = re.search(r"(\d+)\s+failed", line)
        if failed_match:
            self.result.failed = int(failed_match.group(1))

        skipped_match = re.search(r"(\d+)\s+skipped", line)
        if skipped_match:
            self.result.skipped = int(skipped_match.group(1))

        total_match = re.search(r"(\d+)\s+total", line)
        if total_match:
            self.result.total = int(total_match.group(1))
        elif line.strip().lower().startswith("tests"):
            parenthesized_total = re.search(r"\((\d+)\)", line)
            if parenthesized_total:
                self.result.total = int(parenthesized_total.group(1))

    def _parse_time_line(self, line: str) -> None:
        """Parse the time line.

        Args:
            line: Line starting with "Time:".
        """
        # Formats:
        # - "Time: 5.123s"
        # - "Duration  3m 9s (...)"
        normalized = line.strip()
        second_match = re.search(r"(\d+(?:\.\d+)?)\s*s", normalized)
        minute_match = re.search(r"(\d+)\s*m", normalized)
        if minute_match and second_match:
            minutes = int(minute_match.group(1))
            seconds = float(second_match.group(1))
            self.result.duration = (minutes * 60.0) + seconds
            return
        if second_match:
            self.result.duration = float(second_match.group(1))

    @staticmethod
    def _normalize_failed_file(raw: str) -> str:
        text = raw.strip()
        text = re.sub(r"\s*\[.*\]$", "", text).strip()
        text = re.sub(r"\s*\(.*\)$", "", text).strip()
        return text

    def _backfill_duration_from_lines(self) -> None:
        for line in reversed(self._lines):
            minute_match = re.search(r"(\d+)\s*m", line)
            second_match = re.search(r"(\d+(?:\.\d+)?)\s*s", line)
            if minute_match and second_match:
                self.result.duration = (int(minute_match.group(1)) * 60.0) + float(second_match.group(1))
                return
            if second_match:
                self.result.duration = float(second_match.group(1))
                return

    @staticmethod
    def _is_tests_summary_line(line: str) -> bool:
        normalized = line.lstrip().lower()
        return normalized.startswith("tests:") or normalized.startswith("tests ")

    @staticmethod
    def _is_duration_line(line: str) -> bool:
        normalized = line.lstrip().lower()
        return normalized.startswith("time:") or normalized.startswith("duration ")

    def _populate_error_details(self) -> None:
        current_file: str | None = None
        current_message: str = ""
        capture_lines = 0
        pending = False

        def flush() -> None:
            nonlocal current_file, current_message
            if not current_file or not current_message.strip():
                return
            message = current_message.strip()
            self.result.error_details[current_file] = message
            for failed_test in self.result.failed_tests:
                if failed_test.startswith(f"{current_file}::") and failed_test not in self.result.error_details:
                    self.result.error_details[failed_test] = message

        for line in self._lines:
            if re.match(r"^\s*FAIL\s+", line):
                flush()
                match = re.match(r"^\s*FAIL\s+(.+)$", line)
                current_file = self._normalize_failed_file(match.group(1)) if match else None
                current_message = ""
                capture_lines = 0
                pending = True
                continue
            if current_file is None:
                continue
            stripped = line.strip()
            if not stripped:
                if capture_lines > 0:
                    capture_lines += 1
                continue
            if re.match(r"^\s*(PASS|FAIL)\s+", line) or re.match(r"^\s*Test (Suites|Files|Tests):", line):
                flush()
                current_file = None
                current_message = ""
                capture_lines = 0
                pending = False
                continue
            marker = re.match(r"^\s*●\s+(.+)$", line)
            if marker:
                current_message = marker.group(1).strip()
                capture_lines = 0
                pending = False
                continue
            if pending and re.search(
                r"(AssertionError:|TypeError:|ReferenceError:|SyntaxError:|Error:|Expected:|Received:|Cannot )",
                stripped,
            ):
                current_message = stripped
                capture_lines = 0
                pending = False
                continue
            if current_message and capture_lines < 18:
                if re.match(r"^\s*(at |>|\\||[0-9]+\\s*\\|)", line) or re.search(
                    r"(Expected:|Received:|AssertionError:|TypeError:|ReferenceError:|SyntaxError:|Error:)", stripped
                ):
                    current_message = f"{current_message}\n{line.rstrip()}"
                    capture_lines += 1
        flush()
