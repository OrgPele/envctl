"""Test summary formatting and output."""

from __future__ import annotations

from .colors import TerminalColors
from .parser_base import TestResult
from .symbols import CHECK_MARK, CROSS_MARK, format_duration


class TestSummaryFormatter:
    """Formats and prints test execution summaries with colors and symbols."""

    colors: TerminalColors
    detailed: bool

    def __init__(
        self,
        colors: TerminalColors | None = None,
        detailed: bool = False,
    ) -> None:
        """Initialize summary formatter.

        Args:
            colors: TerminalColors instance for styling. If None, uses default.
            detailed: Show detailed test results including failed tests.
        """
        self.colors = colors or TerminalColors.get_colors()
        self.detailed = detailed

    def print_summary(self, result: TestResult, returncode: int, *, test_type: str | None = None) -> None:
        """Print complete test summary.

        Args:
            result: Test result metrics.
            returncode: Process return code.
        """
        self.print_banner()
        self.print_counts(result)

        if self.detailed and result.failed_tests:
            self.print_failed_tests(result, test_type=test_type)

        if result.coverage_percent is not None:
            self.print_coverage(result)

        self._print_footer()

    def print_banner(self) -> None:
        """Print test results banner."""
        banner = "═" * 70
        print(f"\n{self.colors.CYAN}{banner}{self.colors.NC}")
        print(f"{self.colors.BOLD}{self.colors.CYAN}Test Results{self.colors.NC}")
        print(f"{self.colors.CYAN}{banner}{self.colors.NC}\n")

    def print_counts(self, result: TestResult) -> None:
        """Print test counts summary.

        Args:
            result: Test result metrics.
        """
        # Status line
        if result.failed == 0 and result.errors == 0:
            status = f"{self.colors.GREEN}{CHECK_MARK} PASSED{self.colors.NC}"
        else:
            status = f"{self.colors.RED}{CROSS_MARK} FAILED{self.colors.NC}"

        print(f"{status}")

        # Metrics
        metrics = []
        if result.passed > 0:
            metrics.append(f"{self.colors.GREEN}{result.passed} passed{self.colors.NC}")
        if result.failed > 0:
            metrics.append(f"{self.colors.RED}{result.failed} failed{self.colors.NC}")
        if result.errors > 0:
            metrics.append(f"{self.colors.RED}{result.errors} errors{self.colors.NC}")
        if result.skipped > 0:
            metrics.append(f"{self.colors.YELLOW}{result.skipped} skipped{self.colors.NC}")

        if metrics:
            print(f"  {', '.join(metrics)}")

        if result.total > 0:
            success_rate = result.success_rate()
            rate_color = (
                self.colors.GREEN
                if success_rate >= 80
                else self.colors.YELLOW if success_rate >= 50 else self.colors.RED
            )
            print(f"  {rate_color}Success rate: {success_rate:.1f}%{self.colors.NC}")

        if result.duration > 0:
            duration_str = format_duration(result.duration)
            print(f"  {self.colors.GRAY}Duration: {duration_str}{self.colors.NC}")

    def print_failed_tests(self, result: TestResult, *, test_type: str | None = None) -> None:
        """Print list of failed tests grouped by error.

        Args:
            result: Test result metrics.
        """
        if not result.failed_tests:
            return

        print(f"\n{self.colors.RED}Failed Tests:{self.colors.NC}")

        grouped = self._group_by_error(result)
        for error_msg, tests in grouped.items():
            if len(tests) <= 1:
                single_test = tests[0]
                print(f"  - {single_test}")
                for line in self._render_error_lines(error_msg):
                    print(f"      {line}")
                continue

            print(f"  - Shared error for {len(tests)} tests:")
            if test_type == "jest":
                for test_name in tests:
                    print(f"      - {test_name}")
                for line in self._render_error_lines(error_msg):
                    print(f"      {line}")
            else:
                for line in self._render_error_lines(error_msg):
                    print(f"      {line}")
                print("      Tests:")
                for test_name in tests:
                    print(f"        - {test_name}")
            print("")

    def print_coverage(self, result: TestResult) -> None:
        """Print coverage information.

        Args:
            result: Test result metrics.
        """
        if result.coverage_percent is None:
            return

        coverage = result.coverage_percent
        coverage_color = (
            self.colors.GREEN
            if coverage >= 80
            else self.colors.YELLOW if coverage >= 60 else self.colors.RED
        )

        print(f"\n{self.colors.CYAN}Coverage:{self.colors.NC}")
        print(f"  {coverage_color}{coverage:.1f}%{self.colors.NC}")

        if result.coverage_path:
            print(f"  {self.colors.GRAY}Report: {result.coverage_path}{self.colors.NC}")

    def _group_by_error(self, result: TestResult) -> dict[str, list[str]]:
        """Group failed tests by error message.

        Args:
            result: Test result metrics.

        Returns:
            Dictionary mapping error messages to lists of test names.
        """
        grouped: dict[str, list[str]] = {}

        for test_name in result.failed_tests:
            error_msg = self._resolve_error_message(result, test_name)
            if error_msg not in grouped:
                grouped[error_msg] = []
            grouped[error_msg].append(test_name)

        return grouped

    @staticmethod
    def _resolve_error_message(result: TestResult, test_name: str) -> str:
        direct = result.error_details.get(test_name)
        if isinstance(direct, str) and direct.strip():
            return direct
        if "::" in test_name:
            file_key = test_name.split("::", 1)[0]
            by_file = result.error_details.get(file_key)
            if isinstance(by_file, str) and by_file.strip():
                return by_file
        return "(No extracted error details; see log)"

    @staticmethod
    def _render_error_lines(error_msg: str) -> list[str]:
        if not error_msg:
            return ["(No extracted error details; see log)"]
        lines = [line.rstrip() for line in str(error_msg).splitlines() if line.strip()]
        if not lines:
            return ["(No extracted error details; see log)"]
        return lines[:6]

    def _print_footer(self) -> None:
        """Print footer banner."""
        banner = "═" * 70
        print(f"\n{self.colors.CYAN}{banner}{self.colors.NC}\n")
