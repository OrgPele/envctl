"""Progress tracking for test execution across multiple projects."""

from __future__ import annotations

import time

from .colors import TerminalColors
from .symbols import CHECK_MARK, CROSS_MARK, format_duration


class ProgressTracker:
    """Tracks test execution progress across multiple projects with colored output."""

    total_projects: int
    colors: TerminalColors
    current_project: int
    total_passed: int
    total_failed: int
    start_time: float
    project_times: dict[str, float]
    project_start_time: float | None

    def __init__(self, total_projects: int, colors: TerminalColors | None = None) -> None:
        """Initialize progress tracker.

        Args:
            total_projects: Total number of projects to test.
            colors: TerminalColors instance for styling. If None, uses default.
        """
        self.total_projects = total_projects
        self.colors = colors or TerminalColors.get_colors()
        self.current_project = 0
        self.total_passed = 0
        self.total_failed = 0
        self.start_time = time.monotonic()
        self.project_times = {}
        self.project_start_time = None

    def start_project(self, name: str) -> None:
        """Start tracking a project's test execution.

        Args:
            name: Project name.
        """
        self.current_project += 1
        self.project_start_time = time.monotonic()
        progress_str = f"[{self.current_project}/{self.total_projects}]"
        msg = (
            f"{self.colors.BLUE}→{self.colors.NC} Running tests for "
            f"{self.colors.BOLD}{name}{self.colors.NC}... {progress_str}"
        )
        print(msg)

    def finish_project(self, name: str, passed: int, failed: int) -> None:
        """Mark project test execution as complete.

        Args:
            name: Project name.
            passed: Number of passed tests.
            failed: Number of failed tests.
        """
        if self.project_start_time is None:
            elapsed = 0.0
        else:
            elapsed = time.monotonic() - self.project_start_time
            self.project_times[name] = elapsed

        self.total_passed += passed
        self.total_failed += failed

        # Format status
        if failed == 0:
            status = f"{self.colors.GREEN}{CHECK_MARK} {name}{self.colors.NC}"
            details = f"{self.colors.GREEN}{passed} passed{self.colors.NC}"
        else:
            status = f"{self.colors.RED}{CROSS_MARK} {name}{self.colors.NC}"
            details = (
                f"{self.colors.GREEN}{passed} passed{self.colors.NC}, {self.colors.RED}{failed} failed{self.colors.NC}"
            )

        duration_str = format_duration(elapsed)
        print(f"  {status}: {details} ({self.colors.GRAY}{duration_str}{self.colors.NC})")

    def update_counts(self, passed: int, failed: int) -> None:
        """Update running totals of passed and failed tests.

        Args:
            passed: Number of passed tests to add.
            failed: Number of failed tests to add.
        """
        self.total_passed += passed
        self.total_failed += failed

    def get_elapsed_time(self) -> float:
        """Get total elapsed time since tracker initialization.

        Returns:
            Elapsed time in seconds.
        """
        return time.monotonic() - self.start_time

    def print_summary(self) -> None:
        """Print overall progress summary."""
        elapsed = self.get_elapsed_time()
        duration_str = format_duration(elapsed)

        print(f"\n{self.colors.CYAN}{'=' * 70}{self.colors.NC}")
        print(f"{self.colors.BOLD}Overall Results{self.colors.NC}")

        if self.total_failed == 0:
            status = f"{self.colors.GREEN}{CHECK_MARK} All tests passed{self.colors.NC}"
        else:
            status = f"{self.colors.RED}{CROSS_MARK} Some tests failed{self.colors.NC}"

        print(f"  {status}")
        msg = (
            f"  {self.colors.GREEN}{self.total_passed} passed{self.colors.NC}, "
            f"{self.colors.RED}{self.total_failed} failed{self.colors.NC} "
            f"({self.colors.GRAY}{duration_str}{self.colors.NC})"
        )
        print(msg)
        print(f"{self.colors.CYAN}{'=' * 70}{self.colors.NC}\n")
