"""TestRunner orchestrates test execution with rich output and real-time parsing."""

from __future__ import annotations

import json
import inspect
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .colors import TerminalColors
from .parser_base import TestOutputParser, TestResult
from .parser_jest import JestOutputParser
from .parser_pytest import PytestOutputParser
from .progress_markers import parse_progress_marker, strip_progress_markers
from .parser_unittest import UnittestOutputParser
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
        progress_callback: Callable[[int, int], None] | None = None,
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
        self.last_result = parser.result
        self.last_test_type = test_type

        # Run with streaming output
        instrumented_command, instrumented_env = self._instrument_command(
            command,
            test_type=test_type,
            cwd=cwd,
            env=env,
        )
        completed = self._run_with_streaming(
            instrumented_command,
            cwd=cwd,
            env=instrumented_env,
            timeout=timeout,
            parser=parser,
            progress_callback=progress_callback,
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
            return UnittestOutputParser()
        return PytestOutputParser()

    def _run_with_streaming(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        parser: TestOutputParser,
        progress_callback: Callable[[int, int], None] | None = None,
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

        streamed_parse = False

        def parse_callback(line: str) -> None:
            """Parse line and emit events."""
            nonlocal streamed_parse
            progress = parse_progress_marker(line)
            if progress is not None:
                if progress_callback is not None:
                    progress_callback(progress.current, progress.total)
                return
            streamed_parse = True
            parser.parse_line(line)
            if self.emit_callback:
                self.emit_callback("test.output.line", {"line": line})

        run_streaming = getattr(self.runtime.process_runner, "run_streaming", None)
        if callable(run_streaming):
            parameters = inspect.signature(run_streaming).parameters
            supports_show_spinner = "show_spinner" in parameters
            supports_echo_output = "echo_output" in parameters
            kwargs: dict[str, Any] = {
                "cwd": cwd,
                "env": env,
                "timeout": timeout,
                "callback": parse_callback,
            }
            if supports_show_spinner:
                kwargs["show_spinner"] = False
            if supports_echo_output:
                kwargs["echo_output"] = self.verbose
            if "stdin" in parameters:
                kwargs["stdin"] = subprocess.DEVNULL
            completed = run_streaming(command, **kwargs)
        else:
            run_parameters = inspect.signature(self.runtime.process_runner.run).parameters
            run_kwargs: dict[str, Any] = {
                "cwd": cwd,
                "env": env,
                "timeout": timeout,
            }
            if "stdin" in run_parameters:
                run_kwargs["stdin"] = subprocess.DEVNULL
            completed = self.runtime.process_runner.run(command, **run_kwargs)
            stdout_text = str(getattr(completed, "stdout", "") or "")
            stderr_text = str(getattr(completed, "stderr", "") or "")
            for line in stdout_text.splitlines():
                parse_callback(line)
            for line in stderr_text.splitlines():
                parse_callback(line)

        clean_stdout = self._strip_progress_markers(str(getattr(completed, "stdout", "") or ""))
        clean_stderr = self._strip_progress_markers(str(getattr(completed, "stderr", "") or ""))

        if streamed_parse:
            parser.finalize()
        else:
            parser.parse_output(self._combined_fallback_output(clean_stdout, clean_stderr))

        return subprocess.CompletedProcess(
            args=list(command),
            returncode=int(getattr(completed, "returncode", 1)),
            stdout=clean_stdout,
            stderr=clean_stderr,
        )

    def _instrument_command(
        self,
        command: Sequence[str],
        *,
        test_type: str,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None,
    ) -> tuple[list[str], dict[str, str] | None]:
        instrumented_env = self._ensure_helper_pythonpath(env)
        command_list = [str(part) for part in command]
        if test_type == "pytest":
            return self._instrument_pytest_command(command_list), instrumented_env
        if test_type == "unittest":
            instrumented = self._instrument_unittest_command(command_list)
            return instrumented, instrumented_env
        if test_type == "jest":
            return self._instrument_vitest_command(command_list, cwd=cwd), instrumented_env
        return command_list, instrumented_env

    @staticmethod
    def _strip_progress_markers(output: str) -> str:
        if not output:
            return ""
        lines: list[str] = []
        for raw_line in output.splitlines():
            cleaned = strip_progress_markers(raw_line).strip()
            if cleaned:
                lines.append(cleaned)
        return "\n".join(lines)

    @staticmethod
    def _combined_fallback_output(stdout: str, stderr: str) -> str:
        chunks = [chunk for chunk in (stdout, stderr) if chunk]
        return "\n".join(chunks)

    @staticmethod
    def _instrument_pytest_command(command: list[str]) -> list[str]:
        if not command:
            return command
        if "-p" in command and "envctl_engine.test_output.pytest_progress_plugin" in command:
            return command
        if len(command) >= 3 and command[1] == "-m" and command[2] == "pytest":
            return [
                *command[:3],
                "-p",
                "envctl_engine.test_output.pytest_progress_plugin",
                *command[3:],
            ]
        if Path(command[0]).name.startswith("pytest") or command[0] == "pytest":
            return [
                command[0],
                "-p",
                "envctl_engine.test_output.pytest_progress_plugin",
                *command[1:],
            ]
        return command

    @staticmethod
    def _instrument_unittest_command(command: list[str]) -> list[str]:
        if len(command) >= 5 and command[1] == "-m" and command[2] == "unittest" and command[3] == "discover":
            return [
                command[0],
                "-m",
                "envctl_engine.test_output.unittest_runner",
                *command[3:],
            ]
        return command

    @classmethod
    def _instrument_vitest_command(cls, command: list[str], *, cwd: str | Path | None) -> list[str]:
        if not cls._is_vitest_command(command, cwd=cwd):
            return command
        reporter_path = cls._vitest_progress_reporter_path()
        if any(str(part) == f"--reporter={reporter_path}" for part in command):
            return command
        rendered = " ".join(command).lower()
        if "vitest" in rendered:
            return [*command, "--reporter=default", f"--reporter={reporter_path}"]
        if "--" in command:
            return [*command, "--reporter=default", f"--reporter={reporter_path}"]
        return [*command, "--", "--reporter=default", f"--reporter={reporter_path}"]

    @staticmethod
    def _vitest_progress_reporter_path() -> str:
        return str(Path(__file__).resolve().with_name("vitest_progress_reporter.mjs"))

    @staticmethod
    def _is_vitest_command(command: Sequence[str], *, cwd: str | Path | None) -> bool:
        rendered = " ".join(str(part) for part in command).lower()
        if "vitest" in rendered:
            return True
        if cwd is None:
            return False
        package_json = Path(cwd) / "package.json"
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(payload, dict):
            return False
        scripts = payload.get("scripts")
        if not isinstance(scripts, dict):
            return False
        test_script = scripts.get("test")
        return isinstance(test_script, str) and "vitest" in test_script.lower()

    @staticmethod
    def _ensure_helper_pythonpath(env: Mapping[str, str] | None) -> dict[str, str] | None:
        python_root = str(Path(__file__).resolve().parents[2])
        env_map = dict(os.environ)
        if env is not None:
            env_map.update(dict(env))
        existing = env_map.get("PYTHONPATH", "")
        if existing:
            parts = [part for part in existing.split(os.pathsep) if part]
            if python_root not in parts:
                env_map["PYTHONPATH"] = os.pathsep.join([python_root, *parts])
        else:
            env_map["PYTHONPATH"] = python_root
        return env_map

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
