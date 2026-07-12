from __future__ import annotations

import os
import shutil as shutil
import signal
import socket as socket
import subprocess
import time as time
from pathlib import Path
from typing import Any, Callable, Mapping, NoReturn, Sequence, TextIO
from envctl_engine.shared.process_launch_support import (
    LaunchRecord as LaunchRecord,
    ProcessHandoffCleanupError as ProcessHandoffCleanupError,
    ProcessLaunchMixin,
    _hash_command as _hash_command,
    _stdio_policy_name as _stdio_policy_name,
    _terminate_unhanded_process,
)
from envctl_engine.shared.process_lifecycle_probe import ProcessLifecycleProbeMixin
from envctl_engine.shared.process_streaming_support import ProcessStreamingMixin


class ProcessRunner(ProcessLaunchMixin, ProcessLifecycleProbeMixin, ProcessStreamingMixin):
    """Thin subprocess/process utility wrapper for orchestration flows."""

    def __init__(self, *, emit: Callable[..., Any] | None = None) -> None:
        self._emit = emit
        self._launch_records: list[LaunchRecord] = []

    def _raise_unconfirmed_process_cleanup(
        self,
        *,
        process: object,
        command: Sequence[str],
        cwd: str | Path | None,
        stdin: object,
        cause: BaseException,
    ) -> NoReturn:
        try:
            self._record_launch(
                launch_intent="foreground_cleanup_unconfirmed",
                command=command,
                pid=getattr(process, "pid", None),
                cwd=cwd,
                stdin_policy=_stdio_policy_name(stdin, inherited_label="inherit"),
                stdout_policy="pipe",
                stderr_policy="pipe",
                controller_input_owner_allowed=False,
                active=True,
                emit_event=False,
            )
        except BaseException:  # noqa: BLE001 - the durable error still carries the process
            pass
        raise ProcessHandoffCleanupError(
            process=process,
            launch_intent="foreground_completion",
        ) from cause

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
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                stdout = exc.stdout if isinstance(exc.stdout, str) else ""
                stderr_prefix = exc.stderr if isinstance(exc.stderr, str) else ""
                if process.pid > 0:
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
                cleanup_confirmed = _terminate_unhanded_process(process)
                if not cleanup_confirmed:
                    self._raise_unconfirmed_process_cleanup(
                        process=process,
                        command=command,
                        cwd=cwd,
                        stdin=stdin,
                        cause=exc,
                    )
                return self._timeout_result(
                    command,
                    timeout=timeout,
                    stdout=stdout,
                    stderr_prefix=stderr_prefix,
                )
            return subprocess.CompletedProcess(
                args=command,
                returncode=process.returncode,
                stdout=stdout,
                stderr=stderr,
            )
        except BaseException as exc:  # noqa: BLE001 - a failed completion must not orphan the child
            if isinstance(exc, ProcessHandoffCleanupError):
                raise
            if process is not None:
                if _terminate_unhanded_process(process):
                    raise
                self._raise_unconfirmed_process_cleanup(
                    process=process,
                    command=command,
                    cwd=cwd,
                    stdin=stdin,
                    cause=exc,
                )
            raise

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
