"""TestRunner orchestrates test execution with rich output and real-time parsing."""

from __future__ import annotations

import re
import inspect
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .colors import TerminalColors
from .parser_base import TestOutputParser, TestResult
from .parser_jest import JestOutputParser
from .parser_pytest import PytestOutputParser
from .summary import TestSummaryFormatter
class TestRunner:
    """Orchestrates test execution with rich output, spinner, and real-time parsing."""

    def __init__(
        self,
        runtime: Any,
        verbose: bool = False,
        detailed: bool = False,
        run_coverage: bool = False,
        emit_callback: Callable[[str, dict[str, Any]], None] | None = None,
        render_output: bool = True,
    ) -> None:
        """Initialize TestRunner.

        Args:
            runtime: Runtime context with process_runner and config.
            verbose: Stream all output vs summary only.
            detailed: Show detailed test results.
            run_coverage: Include coverage in output.
            emit_callback: Optional callback for emitting events.
        """
        self.runtime = runtime
        self.verbose = verbose
        self.detailed = detailed
        self.run_coverage = run_coverage
        self.emit_callback = emit_callback
        self.render_output = render_output
        self.colors = TerminalColors.get_colors()
        self.last_result: TestResult | None = None
        self.last_test_type: str | None = None

    def run_tests(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run tests with streaming output and real-time parsing.

        Args:
            command: Test command to execute.
            cwd: Working directory.
            env: Environment variables.
            timeout: Timeout in seconds.

        Returns:
            CompletedProcess with stdout, stderr, and returncode.
        """
        if self.render_output:
            self._print_header(command)
            self._print_progress(command)

        test_type = self._detect_test_type(command)
        parser = self._get_parser(test_type)

        # Run with streaming output
        completed = self._run_with_streaming(
            command,
            cwd=cwd,
            env=env,
            timeout=timeout,
            parser=parser,
        )

        # Print summary
        if self.render_output:
            self._print_summary(parser.result, test_type)
        self.last_result = parser.result
        self.last_test_type = test_type

        return completed

    def _detect_test_type(self, command: Sequence[str]) -> str:
        """Detect test framework type from command.

        Args:
            command: Test command.

        Returns:
            "pytest", "jest", or "unittest".
        """
        cmd_str = " ".join(str(c) for c in command).lower()

        if "pytest" in cmd_str or "-m pytest" in cmd_str:
            return "pytest"
        if (
            "jest" in cmd_str
            or "vitest" in cmd_str
            or "npm test" in cmd_str
            or "npm run test" in cmd_str
            or "pnpm test" in cmd_str
            or "pnpm run test" in cmd_str
            or "bun test" in cmd_str
            or "bun run test" in cmd_str
            or "yarn test" in cmd_str
        ):
            return "jest"
        if "unittest" in cmd_str or "discover" in cmd_str:
            return "unittest"

        return "pytest"  # Default

    def _get_parser(self, test_type: str) -> TestOutputParser:
        """Get appropriate parser for test type.

        Args:
            test_type: Test framework type.

        Returns:
            Parser instance.
        """
        if test_type == "jest":
            return JestOutputParser()
        if test_type == "unittest":
            return PytestOutputParser()  # Reuse pytest parser for unittest
        return PytestOutputParser()

    def _run_with_streaming(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        parser: TestOutputParser,
    ) -> subprocess.CompletedProcess[str]:
        """Run command with streaming output and real-time parsing.

        Args:
            command: Command to run.
            cwd: Working directory.
            env: Environment variables.
            timeout: Timeout in seconds.
            parser: Parser for test output.

        Returns:
            CompletedProcess with aggregated output.
        """

        def parse_callback(line: str) -> None:
            """Parse line and emit events."""
            parser.parse_line(line)
            if self.emit_callback:
                self.emit_callback("test.output.line", {"line": line})

        run_streaming = getattr(self.runtime.process_runner, "run_streaming", None)
        if callable(run_streaming):
            parameters = inspect.signature(run_streaming).parameters
            supports_show_spinner = "show_spinner" in parameters
            if supports_show_spinner:
                completed = run_streaming(
                    command,
                    cwd=cwd,
                    env=env,
                    timeout=timeout,
                    callback=parse_callback if self.verbose else None,
                    show_spinner=False,
                )
            else:
                completed = run_streaming(
                    command,
                    cwd=cwd,
                    env=env,
                    timeout=timeout,
                    callback=parse_callback if self.verbose else None,
                )
        else:
            completed = self.runtime.process_runner.run(
                command,
                cwd=cwd,
                env=env,
                timeout=timeout,
            )
            if self.verbose:
                stdout_text = str(getattr(completed, "stdout", "") or "")
                for line in stdout_text.splitlines():
                    parse_callback(line)

        # Finalize parser with full output if not verbose
        if not self.verbose:
            parser.parse_output(completed.stdout)

        return completed

    def _print_header(self, command: Sequence[str]) -> None:
        """Print colored banner header.

        Args:
            command: Test command.
        """
        banner = "=" * 70
        print(f"\n{self.colors.CYAN}{banner}{self.colors.NC}")
        print(f"{self.colors.BOLD}{self.colors.CYAN}Running Tests{self.colors.NC}")
        print(f"{self.colors.CYAN}{banner}{self.colors.NC}\n")

    def _print_progress(self, command: Sequence[str]) -> None:
        """Print progress message.

        Args:
            command: Test command.
        """
        cmd_snippet = " ".join(str(c) for c in command[:3])
        print(f"{self.colors.BLUE}→{self.colors.NC} {cmd_snippet}...\n")

    def _print_summary(self, result: TestResult, test_type: str) -> None:
        """Print test summary with colors.

        Args:
            result: Test result metrics.
            test_type: Test framework type.
        """
        formatter = TestSummaryFormatter(colors=self.colors, detailed=self.detailed or bool(result.failed_tests))
        formatter.print_counts(result)
        if formatter.detailed and result.failed_tests:
            formatter.print_failed_tests(result, test_type=test_type)
        if result.coverage_percent is not None and self.run_coverage:
            formatter.print_coverage(result)
        formatter._print_footer()
