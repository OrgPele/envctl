"""Parser for pytest test output format."""

from __future__ import annotations

import re
from typing import override
from .parser_base import TestOutputParser, TestResult, strip_ansi


class PytestOutputParser(TestOutputParser):
    """Parses pytest test output and extracts metrics."""

    def __init__(self) -> None:
        """Initialize pytest parser."""
        super().__init__()
        self._lines: list[str] = []

    @staticmethod
    def _is_valid_pytest_nodeid(value: str) -> bool:
        candidate = value.strip()
        if not candidate:
            return False
        if " - " in candidate:
            return False
        if "\n" in candidate or "\r" in candidate:
            return False
        if ".py" not in candidate:
            return False
        if "::" not in candidate:
            return False
        if candidate.startswith("file or directory not found:"):
            return False
        suffix = candidate.split(".py", 1)[1]
        if not suffix.startswith("::"):
            return False
        return True

    @override
    def parse_line(self, line: str) -> None:
        """Parse a single line of pytest output.

        Args:
            line: Single line from pytest output.
        """
        # Strip ANSI escape codes
        clean_line = strip_ansi(line)
        self._lines.append(clean_line)

        # Check for section markers
        if clean_line.startswith("FAILED "):
            self._parse_failed_line(clean_line)
        elif clean_line.startswith("ERROR "):
            self._parse_error_line(clean_line)
        elif clean_line.startswith("=") and ("passed" in clean_line or "failed" in clean_line):
            self._parse_summary_line(clean_line)
        elif clean_line.startswith("coverage:"):
            self._parse_coverage_line(clean_line)

    @override
    def finalize(self) -> TestResult:
        """Finalize parsing and return results.

        Returns:
            TestResult with final aggregated metrics.
        """
        self._populate_error_details_from_sections()
        if self.result.failed == 0 and self.result.failed_tests:
            self.result.failed = len(self.result.failed_tests)

        # Calculate total
        self.result.total = self.result.passed + self.result.failed + self.result.errors + self.result.skipped
        return self.result

    def _parse_failed_line(self, line: str) -> None:
        """Parse a FAILED line.

        Args:
            line: Line starting with "FAILED ".
        """
        # Format: "FAILED tests/test_auth.py::test_login - AssertionError"
        match = re.match(r"FAILED\s+(.+?)\s*(?:-\s*(.+))?$", line)
        if match:
            test_name = match.group(1).strip()
            if not self._is_valid_pytest_nodeid(test_name):
                return
            error_msg = match.group(2) or "Unknown error"
            if test_name not in self.result.failed_tests:
                self.result.failed_tests.append(test_name)
            if test_name not in self.result.error_details:
                self.result.error_details[test_name] = error_msg

    def _parse_error_line(self, line: str) -> None:
        """Parse an ERROR line.

        Args:
            line: Line starting with "ERROR ".
        """
        # Format: "ERROR tests/test_setup.py::setup_module"
        match = re.match(r"ERROR\s+(.+?)(?:\s*-\s*(.+))?$", line)
        if match:
            test_name = match.group(1).strip()
            if not self._is_valid_pytest_nodeid(test_name):
                return
            if test_name not in self.result.failed_tests:
                self.result.failed_tests.append(test_name)
            if test_name not in self.result.error_details:
                self.result.error_details[test_name] = "Test error"

    def _parse_summary_line(self, line: str) -> None:
        """Parse the summary line.

        Args:
            line: Summary line with test counts.
        """
        # Format: "=== 3 failed, 297 passed in 10.5s ==="
        # Also handles: "=== 297 passed in 10.5s ==="
        # Also handles: "=== 3 failed, 2 error, 297 passed, 5 skipped in 10.5s ==="

        # Extract duration
        duration_match = re.search(r"(\d+\.\d+)s", line)
        if duration_match:
            self.result.duration = float(duration_match.group(1))
        self.result.counts_detected = True

        # Extract counts
        passed_match = re.search(r"(\d+)\s+passed", line)
        if passed_match:
            self.result.passed = int(passed_match.group(1))

        failed_match = re.search(r"(\d+)\s+failed", line)
        if failed_match:
            self.result.failed = int(failed_match.group(1))

        error_match = re.search(r"(\d+)\s+error", line)
        if error_match:
            self.result.errors = int(error_match.group(1))

        skipped_match = re.search(r"(\d+)\s+skipped", line)
        if skipped_match:
            self.result.skipped = int(skipped_match.group(1))

    def _parse_coverage_line(self, line: str) -> None:
        """Parse coverage information.

        Args:
            line: Line containing coverage data.
        """
        # Format: "coverage: 85.5%"
        match = re.search(r"(\d+(?:\.\d+)?)\s*%", line)
        if match:
            self.result.coverage_percent = float(match.group(1))

    @staticmethod
    def _summary_header_keys(full_path: str) -> set[str]:
        keys: set[str] = {full_path}
        if "::" not in full_path:
            return keys
        parts = full_path.split("::")
        test_name = parts[-1]
        keys.add(test_name)
        if len(parts) >= 3:
            keys.add(f"{parts[-2]}.{parts[-1]}")
        return keys

    def _build_header_to_path_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for line in self._lines:
            failed_match = re.match(r"^FAILED\s+(.+?)\s*(?:-\s*(.+))?$", line)
            if failed_match:
                full_path = failed_match.group(1).strip()
                for key in self._summary_header_keys(full_path):
                    mapping[key] = full_path
                continue
            error_match = re.match(r"^ERROR\s+(.+?)(?:\s*-\s*(.+))?$", line)
            if error_match:
                full_path = error_match.group(1).strip()
                for key in self._summary_header_keys(full_path):
                    mapping[key] = full_path
        return mapping

    def _populate_error_details_from_sections(self) -> None:
        header_to_path = self._build_header_to_path_map()
        in_section = False
        current_header: str | None = None
        current_lines: list[str] = []

        def flush() -> None:
            nonlocal current_header, current_lines
            if not current_header:
                return
            cleaned = [line.rstrip() for line in current_lines if line.strip()]
            if not cleaned:
                current_header = None
                current_lines = []
                return
            message = "\n".join(cleaned[:20])
            key = self._resolve_failure_key(current_header, header_to_path)
            self.result.error_details[key] = message
            current_header = None
            current_lines = []

        for line in self._lines:
            if re.match(r"^=+\s*(FAILURES|ERRORS)\s*=+$", line):
                flush()
                in_section = True
                continue
            if not in_section:
                continue
            if re.match(r"^=+\s*short test summary info\s*=+$", line) or re.match(r"^=+\s*\d+ .* in .*=+$", line):
                flush()
                in_section = False
                continue
            header_match = re.match(r"^_{2,}\s*(.*?)\s*_{2,}\s*$", line)
            if header_match:
                flush()
                current_header = header_match.group(1).strip()
                continue
            if current_header:
                current_lines.append(line)
        flush()

    def _resolve_failure_key(self, header: str, header_to_path: dict[str, str]) -> str:
        if header in header_to_path:
            return header_to_path[header]

        normalized = header.replace(" ", "")
        if normalized in header_to_path:
            return header_to_path[normalized]

        for failed_test in self.result.failed_tests:
            if failed_test.endswith(f"::{header}") or failed_test.endswith(f"::{normalized}"):
                return failed_test
            if "." in header:
                class_name, method = header.split(".", 1)
                if failed_test.endswith(f"::{class_name}::{method}"):
                    return failed_test

        return header
