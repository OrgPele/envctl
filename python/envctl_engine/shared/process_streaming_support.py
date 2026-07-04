from __future__ import annotations

import os
import selectors
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from envctl_engine.ui.spinner import spinner, spinner_enabled, use_spinner_policy
from envctl_engine.ui.spinner_service import resolve_spinner_policy

_STREAMING_PROGRESS_SECONDS = 3.0


class ProcessStreamingMixin:
    """Streaming subprocess execution for runtime and action command flows."""

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
        """Run command with real-time streaming output and optional callback."""
        command = list(cmd)
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
                    command,
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
                        args=command,
                        returncode=1,
                        stdout="",
                        stderr="",
                    )

                selector = self._stdout_selector(process.stdout)
                try:
                    while True:
                        wait_seconds = self._streaming_wait_seconds(timeout=timeout, start_time=start_time)
                        if wait_seconds <= 0:
                            return self._finish_streaming_timeout(
                                process,
                                command=command,
                                timeout=timeout,
                                output_lines=output_lines,
                                active_spinner=active_spinner,
                                spinner_enabled=enabled,
                            )
                        if selector is not None:
                            events = selector.select(min(wait_seconds, _STREAMING_PROGRESS_SECONDS))
                            if not events:
                                if process.poll() is not None:
                                    break
                                if echo_output:
                                    print(f"still running: {shlex.join(command)}", file=sys.stderr, flush=True)
                                continue

                        line = process.stdout.readline()
                        if not line:
                            break

                        line_stripped = self._normalize_output_line(line).rstrip("\n")
                        output_lines.append(line_stripped)
                        if callback is not None:
                            try:
                                callback(line_stripped)
                            except Exception:
                                pass
                            if echo_output:
                                print(line_stripped)
                finally:
                    if selector is not None:
                        selector.close()

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
                args=command,
                returncode=returncode,
                stdout="\n".join(output_lines),
                stderr="",
            )

    @staticmethod
    def _stdout_selector(stdout: Any) -> selectors.BaseSelector | None:
        selector = selectors.DefaultSelector()
        try:
            selector.register(stdout, selectors.EVENT_READ)
        except (AttributeError, OSError, ValueError):
            selector.close()
            return None
        return selector

    @staticmethod
    def _streaming_wait_seconds(*, timeout: float | None, start_time: float) -> float:
        if timeout is None:
            return _STREAMING_PROGRESS_SECONDS
        return timeout - (time.time() - start_time)

    def _finish_streaming_timeout(
        self,
        process: subprocess.Popen[str],
        *,
        command: Sequence[str],
        timeout: float | None,
        output_lines: Sequence[str],
        active_spinner: Any,
        spinner_enabled: bool,
    ) -> subprocess.CompletedProcess[str]:
        pid = int(getattr(process, "pid", 0) or 0)
        if pid > 0:
            try:
                os.killpg(pid, signal.SIGTERM)
            except OSError:
                pass
        else:
            try:
                process.terminate()
            except OSError:
                pass
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            if pid > 0:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except OSError:
                    pass
            else:
                try:
                    process.kill()
                except OSError:
                    pass
        close_stdout = getattr(getattr(process, "stdout", None), "close", None)
        if callable(close_stdout):
            close_stdout()
        if spinner_enabled:
            active_spinner.fail("Command timed out")
        return self._timeout_result(
            command,
            timeout=timeout,
            stdout="\n".join(output_lines),
        )
