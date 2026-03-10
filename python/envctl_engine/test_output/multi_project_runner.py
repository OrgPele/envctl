"""Multi-project test runner orchestration."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from .colors import TerminalColors
from .progress import ProgressTracker
from .test_runner import TestRunner


@dataclass(slots=True)
class ProjectTestResult:
    """Test results for a single project."""

    project_name: str
    backend_passed: int = 0
    backend_failed: int = 0
    frontend_passed: int = 0
    frontend_failed: int = 0
    backend_duration: float = 0.0
    frontend_duration: float = 0.0
    backend_success: bool = True
    frontend_success: bool = True
    errors: list[str] = field(default_factory=list)

    def total_passed(self) -> int:
        """Get total passed tests.

        Returns:
            Sum of backend and frontend passed tests.
        """
        return self.backend_passed + self.frontend_passed

    def total_failed(self) -> int:
        """Get total failed tests.

        Returns:
            Sum of backend and frontend failed tests.
        """
        return self.backend_failed + self.frontend_failed

    def is_success(self) -> bool:
        """Check if all tests passed.

        Returns:
            True if no tests failed.
        """
        return self.backend_success and self.frontend_success


class MultiProjectTestRunner:
    """Orchestrates test execution across multiple projects."""

    runtime: Any
    verbose: bool
    detailed: bool
    run_coverage: bool
    parallel: bool
    emit_callback: Callable[[str, dict[str, Any]], None] | None
    colors: TerminalColors
    test_runner: TestRunner
    project_results: list[ProjectTestResult]

    def __init__(
        self,
        runtime: Any,
        verbose: bool = False,
        detailed: bool = False,
        run_coverage: bool = False,
        parallel: bool = False,
        emit_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        """Initialize multi-project test runner.

        Args:
            runtime: Runtime context with process_runner and config.
            verbose: Stream all output vs summary only.
            detailed: Show detailed test results.
            run_coverage: Include coverage in output.
            parallel: Run tests in parallel (not yet implemented).
            emit_callback: Optional callback for emitting events.
        """
        self.runtime = runtime
        self.verbose = verbose
        self.detailed = detailed
        self.run_coverage = run_coverage
        self.parallel = parallel
        self.emit_callback = emit_callback
        self.colors = TerminalColors.get_colors()
        self.test_runner = TestRunner(
            runtime,
            verbose=verbose,
            detailed=detailed,
            run_coverage=run_coverage,
            emit_callback=emit_callback,
        )
        self.project_results = []

    def run_all_projects(self, projects: Sequence[str | Path]) -> list[ProjectTestResult]:
        """Run tests across all projects.

        Args:
            projects: List of project paths to test.

        Returns:
            List of ProjectTestResult for each project.
        """
        self.project_results = []
        progress = ProgressTracker(len(projects), self.colors)

        for project_path in projects:
            project_path = Path(project_path)
            project_name = project_path.name

            progress.start_project(project_name)

            result = self._run_project_tests(project_path, progress)
            self.project_results.append(result)

            progress.finish_project(
                project_name,
                result.total_passed(),
                result.total_failed(),
            )

        self._print_aggregate_summary()
        return self.project_results

    def _run_project_tests(
        self,
        project_path: Path,
        progress: ProgressTracker,
    ) -> ProjectTestResult:
        """Run tests for a single project.

        Args:
            project_path: Path to project directory.
            progress: ProgressTracker instance.

        Returns:
            ProjectTestResult with test metrics.
        """
        result = ProjectTestResult(project_name=project_path.name)

        # Run backend tests if backend directory exists
        backend_dir = project_path / "backend"
        if backend_dir.exists():
            backend_result = self._run_backend_tests(backend_dir)
            result.backend_passed = backend_result.get("passed", 0)
            result.backend_failed = backend_result.get("failed", 0)
            result.backend_duration = backend_result.get("duration", 0.0)
            result.backend_success = backend_result.get("success", True)
            if backend_result.get("error"):
                result.errors.append(f"Backend: {backend_result['error']}")

        # Run frontend tests if frontend directory exists
        frontend_dir = project_path / "frontend"
        if frontend_dir.exists():
            frontend_result = self._run_frontend_tests(frontend_dir)
            result.frontend_passed = frontend_result.get("passed", 0)
            result.frontend_failed = frontend_result.get("failed", 0)
            result.frontend_duration = frontend_result.get("duration", 0.0)
            result.frontend_success = frontend_result.get("success", True)
            if frontend_result.get("error"):
                result.errors.append(f"Frontend: {frontend_result['error']}")

        return result

    def _run_backend_tests(self, backend_dir: Path) -> dict[str, Any]:
        """Run backend tests (pytest).

        Args:
            backend_dir: Path to backend directory.

        Returns:
            Dictionary with test results.
        """
        try:
            # Detect if pytest is available
            command = ["python", "-m", "pytest", str(backend_dir), "-v", "--tb=short"]

            completed = self.test_runner.run_tests(command, cwd=backend_dir)

            # Parse results from output
            passed = completed.stdout.count(" PASSED")
            failed = completed.stdout.count(" FAILED")
            duration = self._extract_duration(completed.stdout)

            return {
                "passed": passed,
                "failed": failed,
                "duration": duration,
                "success": completed.returncode == 0,
            }
        except Exception as e:
            return {
                "passed": 0,
                "failed": 0,
                "duration": 0.0,
                "success": False,
                "error": str(e),
            }

    def _run_frontend_tests(self, frontend_dir: Path) -> dict[str, Any]:
        """Run frontend tests (Jest/Vitest).

        Args:
            frontend_dir: Path to frontend directory.

        Returns:
            Dictionary with test results.
        """
        try:
            # Detect test command (npm test, yarn test, or vitest)
            command = ["npm", "test", "--", "--run"]

            completed = self.test_runner.run_tests(command, cwd=frontend_dir)

            # Parse results from output
            passed = completed.stdout.count(" passed")
            failed = completed.stdout.count(" failed")
            duration = self._extract_duration(completed.stdout)

            return {
                "passed": passed,
                "failed": failed,
                "duration": duration,
                "success": completed.returncode == 0,
            }
        except Exception as e:
            return {
                "passed": 0,
                "failed": 0,
                "duration": 0.0,
                "success": False,
                "error": str(e),
            }

    def _print_aggregate_summary(self) -> None:
        """Print aggregate summary table for all projects."""
        if not self.project_results:
            return

        print(f"\n{self.colors.CYAN}{'=' * 80}{self.colors.NC}")
        print(f"{self.colors.BOLD}Multi-Project Test Summary{self.colors.NC}")
        print(f"{self.colors.CYAN}{'=' * 80}{self.colors.NC}\n")

        # Print table header
        header = f"{'Project':<20} | {'Backend':<20} | {'Frontend':<20}"
        print(header)
        print("-" * 80)

        # Print each project row
        total_passed = 0
        total_failed = 0

        for result in self.project_results:
            backend_str = self._format_result_cell(
                result.backend_passed,
                result.backend_failed,
                result.backend_success,
            )
            frontend_str = self._format_result_cell(
                result.frontend_passed,
                result.frontend_failed,
                result.frontend_success,
            )

            project_name = result.project_name[:19]
            row = f"{project_name:<20} | {backend_str:<20} | {frontend_str:<20}"
            print(row)

            total_passed += result.total_passed()
            total_failed += result.total_failed()

        # Print totals
        print("-" * 80)
        total_str = self._format_result_cell(total_passed, total_failed, total_failed == 0)
        print(f"{'TOTAL':<20} | {total_str:<20}")

        print(f"{self.colors.CYAN}{'=' * 80}{self.colors.NC}\n")

    def _format_result_cell(self, passed: int, failed: int, success: bool) -> str:
        """Format a result cell for the summary table.

        Args:
            passed: Number of passed tests.
            failed: Number of failed tests.
            success: Whether all tests passed.

        Returns:
            Formatted cell string.
        """
        if passed == 0 and failed == 0:
            return f"{self.colors.GRAY}—{self.colors.NC}"

        if success:
            return f"{self.colors.GREEN}✓ {passed} passed{self.colors.NC}"

        return f"{self.colors.GREEN}{passed} passed{self.colors.NC}, {self.colors.RED}{failed} failed{self.colors.NC}"

    @staticmethod
    def _extract_duration(output: str) -> float:
        """Extract duration from test output.

        Args:
            output: Test output string.

        Returns:
            Duration in seconds.
        """
        # Try pytest format: "=== 1.23s ==="
        match = re.search(r"(\d+\.\d+)s", output)
        if match:
            return float(match.group(1))

        return 0.0
