from __future__ import annotations

import os
import shutil as shutil
import signal
import socket as socket
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TextIO
from envctl_engine.shared.process_launch_support import (
    LaunchRecord as LaunchRecord,
    ProcessLaunchMixin,
    _hash_command as _hash_command,
    _stdio_policy_name as _stdio_policy_name,
)
from envctl_engine.shared.process_lifecycle_probe import ProcessLifecycleProbeMixin
from envctl_engine.ui.spinner import spinner, spinner_enabled, use_spinner_policy
from envctl_engine.ui.spinner_service import resolve_spinner_policy


class ProcessRunner(ProcessLaunchMixin, ProcessLifecycleProbeMixin):
    """Thin subprocess/process utility wrapper for orchestration flows."""

    def __init__(self, *, emit: Callable[..., Any] | None = None) -> None:
        self._emit = emit
        self._launch_records: list[LaunchRecord] = []

    @staticmethod
    def _normalize_output_line(line: str | bytes) -> str:
        if isinstance(line, bytes):
            return line.decode("utf-8", errors="replace")
        return line

    @staticmethod
    def _timeout_result(
        command: Sequence[str],
        *,
        timeout: float | None,
        stdout: str = "",
        stderr_prefix: str = "",
    ) -> subprocess.CompletedProcess[str]:
        timeout_hint = (
            f"Command timed out after {timeout:.1f}s: {' '.join(command)}"
            if isinstance(timeout, (int, float))
            else f"Command timed out: {' '.join(command)}"
        )
        stderr = f"{stderr_prefix}\n{timeout_hint}".strip()
        return subprocess.CompletedProcess(
            args=list(command),
            returncode=124,
            stdout=stdout,
            stderr=stderr,
        )

    def run(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        stdin: int | None = None,
        process_started_callback: Callable[[int], None] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = list(cmd)
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                command,
                cwd=str(cwd) if cwd is not None else None,
                env=dict(env) if env is not None else None,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=stdin,
                start_new_session=True,
            )
            if callable(process_started_callback) and int(getattr(process, "pid", 0) or 0) > 0:
                try:
                    process_started_callback(int(process.pid))
                except Exception:
                    pass
            stdout, stderr = process.communicate(timeout=timeout)
            return subprocess.CompletedProcess(
                args=command,
                returncode=process.returncode,
                stdout=stdout,
                stderr=stderr,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr_prefix = exc.stderr if isinstance(exc.stderr, str) else ""
            if process is not None and process.pid > 0:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except OSError:
                    pass
                try:
                    extra_stdout, extra_stderr = process.communicate(timeout=2.0)
                    if isinstance(extra_stdout, str):
                        stdout = f"{stdout}{extra_stdout}"
                    if isinstance(extra_stderr, str):
                        stderr_prefix = f"{stderr_prefix}{extra_stderr}"
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except OSError:
                        pass
                    try:
                        extra_stdout, extra_stderr = process.communicate(timeout=2.0)
                        if isinstance(extra_stdout, str):
                            stdout = f"{stdout}{extra_stdout}"
                        if isinstance(extra_stderr, str):
                            stderr_prefix = f"{stderr_prefix}{extra_stderr}"
                    except subprocess.TimeoutExpired:
                        pass
            return self._timeout_result(
                command,
                timeout=timeout,
                stdout=stdout,
                stderr_prefix=stderr_prefix,
            )
        except OSError:
            raise

    def run_streaming(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        callback: Callable[[str], None] | None = None,
        process_started_callback: Callable[[int], None] | None = None,
        show_spinner: bool = True,
        echo_output: bool = True,
        stdin: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run command with real-time streaming output and optional callback.

        Args:
            cmd: Command to run
            cwd: Working directory
            env: Environment variables
            timeout: Timeout in seconds
            callback: Optional callback for each output line

        Returns:
            CompletedProcess with stdout, stderr, and returncode
        """
        output_lines: list[str] = []
        start_time = time.time()
        env_map = dict(env) if env is not None else None
        spinner_policy = resolve_spinner_policy(env_map)
        enabled = bool(show_spinner) and spinner_enabled(env_map)
        with (
            use_spinner_policy(spinner_policy),
            spinner(
                "Running command...",
                enabled=enabled,
                start_immediately=True,
            ) as active_spinner,
        ):
            try:
                process = subprocess.Popen(
                    list(cmd),
                    cwd=str(cwd) if cwd is not None else None,
                    env=env_map,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=stdin,
                    start_new_session=True,
                )
                if callable(process_started_callback) and int(getattr(process, "pid", 0) or 0) > 0:
                    try:
                        process_started_callback(int(process.pid))
                    except Exception:
                        pass

                if process.stdout is None:
                    if enabled:
                        active_spinner.fail("Unable to read command output")
                    return subprocess.CompletedProcess(
                        args=list(cmd),
                        returncode=1,
                        stdout="",
                        stderr="",
                    )

                # Read output line-by-line
                for line in iter(process.stdout.readline, ""):
                    if not line:
                        break

                    # Check timeout
                    if timeout is not None:
                        elapsed = time.time() - start_time
                        if elapsed > timeout:
                            process.terminate()
                            try:
                                process.wait(timeout=2.0)
                            except subprocess.TimeoutExpired:
                                process.kill()
                            if enabled:
                                active_spinner.fail("Command timed out")
                            return subprocess.CompletedProcess(
                                args=list(cmd),
                                returncode=-1,
                                stdout="\n".join(output_lines),
                                stderr="",
                            )

                    line_stripped = self._normalize_output_line(line).rstrip("\n")
                    output_lines.append(line_stripped)
                    if callback is not None:
                        try:
                            callback(line_stripped)
                        except Exception:
                            pass
                        if echo_output:
                            print(line_stripped)

                process.stdout.close()
                returncode = process.wait()
                if enabled:
                    if returncode == 0:
                        active_spinner.succeed("Command completed")
                    else:
                        active_spinner.fail(f"Command failed (exit {returncode})")

            except Exception:
                if enabled:
                    active_spinner.fail("Command execution failed")
                raise

            return subprocess.CompletedProcess(
                args=list(cmd),
                returncode=returncode,
                stdout="\n".join(output_lines),
                stderr="",
            )

    def run_probe(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        stdout_target: int | TextIO | None = subprocess.PIPE,
        stderr_target: int | TextIO | None = subprocess.PIPE,
    ) -> subprocess.CompletedProcess[str]:
        command = list(cmd)
        self._record_launch(
            launch_intent="probe",
            command=command,
            pid=None,
            cwd=cwd,
            stdin_policy="devnull",
            stdout_policy=_stdio_policy_name(stdout_target, inherited_label="inherit"),
            stderr_policy=_stdio_policy_name(stderr_target, inherited_label="inherit"),
            controller_input_owner_allowed=False,
            active=False,
        )
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd) if cwd is not None else None,
                env=dict(env) if env is not None else None,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                stdout=stdout_target,
                stderr=stderr_target,
                check=False,
                timeout=timeout,
            )
            return subprocess.CompletedProcess(
                args=command,
                returncode=completed.returncode,
                stdout=completed.stdout if isinstance(completed.stdout, str) else "",
                stderr=completed.stderr if isinstance(completed.stderr, str) else "",
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr_prefix = exc.stderr if isinstance(exc.stderr, str) else ""
            return self._timeout_result(command, timeout=timeout, stdout=stdout, stderr_prefix=stderr_prefix)
        except OSError:
            raise
