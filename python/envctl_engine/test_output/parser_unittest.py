"""Parser for Python unittest output format."""

from __future__ import annotations

import re
from typing import override

from .parser_base import TestOutputParser, TestResult, strip_ansi


class UnittestOutputParser(TestOutputParser):
    """Parses unittest discovery output and extracts metrics."""

    def __init__(self) -> None:
        super().__init__()
        self._lines: list[str] = []

    @override
    def parse_line(self, line: str) -> None:
        clean_line = strip_ansi(line)
        self._lines.append(clean_line)

        ran_match = re.match(r"^Ran\s+(\d+)\s+tests?\s+in\s+([0-9.]+)s$", clean_line.strip())
        if ran_match:
            self.result.total = int(ran_match.group(1))
            self.result.duration = float(ran_match.group(2))
            self.result.counts_detected = True
            return

        status_line = clean_line.strip()
        if status_line == "OK" or status_line.startswith("OK (") or status_line.startswith("FAILED ("):
            self._parse_status_line(status_line)
            return

        failure_match = re.match(r"^(FAIL|ERROR):\s+(.+)$", status_line)
        if failure_match:
            kind = failure_match.group(1)
            test_name = self._normalize_test_name(failure_match.group(2).strip())
            if test_name not in self.result.failed_tests:
                self.result.failed_tests.append(test_name)
            if test_name not in self.result.error_details:
                self.result.error_details[test_name] = kind.title()

    @override
    def finalize(self) -> TestResult:
        self._populate_error_details()
        if self.result.total > 0:
            self.result.passed = max(
                0,
                self.result.total - self.result.failed - self.result.errors - self.result.skipped,
            )
        elif self.result.failed_tests and self.result.failed == 0 and self.result.errors == 0:
            self.result.failed = len(self.result.failed_tests)
        return self.result

    def _parse_status_line(self, line: str) -> None:
        self.result.counts_detected = True
        failures_match = re.search(r"failures=(\d+)", line)
        if failures_match:
            self.result.failed = int(failures_match.group(1))
        errors_match = re.search(r"errors=(\d+)", line)
        if errors_match:
            self.result.errors = int(errors_match.group(1))
        skipped_match = re.search(r"skipped=(\d+)", line)
        if skipped_match:
            self.result.skipped = int(skipped_match.group(1))

    def _populate_error_details(self) -> None:
        current_test: str | None = None
        current_lines: list[str] = []

        def flush() -> None:
            nonlocal current_test, current_lines
            if not current_test:
                return
            message = "\n".join(line.rstrip() for line in current_lines if line.strip()).strip()
            if message:
                self.result.error_details[current_test] = message
            current_test = None
            current_lines = []

        for line in self._lines:
            stripped = line.strip()
            header_match = re.match(r"^(FAIL|ERROR):\s+(.+)$", stripped)
            if header_match:
                flush()
                current_test = self._normalize_test_name(header_match.group(2).strip())
                continue
            if current_test is None:
                continue
            if (
                stripped.startswith("Ran ")
                or stripped == "OK"
                or stripped.startswith("OK (")
                or stripped.startswith("FAILED (")
            ):
                flush()
                continue
            if re.match(r"^(FAIL|ERROR):\s+(.+)$", stripped):
                flush()
                continue
            if (
                stripped.startswith("----------------------------------------------------------------------")
                and current_lines
            ):
                flush()
                continue
            current_lines.append(line)
        flush()

    @staticmethod
    def _normalize_test_name(raw: str) -> str:
        candidate = raw.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+", candidate):
            return candidate
        display_match = re.fullmatch(
            r"[^()]+\s+\(([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\)",
            candidate,
        )
        if display_match:
            return display_match.group(1)
        return candidate
