from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Callable, Mapping, Sequence, TextIO


@dataclass
class LaunchRecord:
    launch_intent: str
    pid: int | None
    command_hash: str
    command_length: int
    cwd: str | None
    stdin_policy: str
    stdout_policy: str
    stderr_policy: str
    controller_input_owner_allowed: bool
    active: bool
    launched_at_monotonic: float


class ProcessHandoffCleanupError(RuntimeError):
    """A spawned process whose exit could not be confirmed after handoff failed."""

    def __init__(self, *, process: object, launch_intent: str) -> None:
        raw_pid = getattr(process, "pid", None)
        self.pid = raw_pid if isinstance(raw_pid, int) and not isinstance(raw_pid, bool) and raw_pid > 0 else None
        self.process = process
        self.launch_intent = launch_intent
        identity = f"PID {self.pid}" if self.pid is not None else "an unknown PID"
        super().__init__(
            f"{launch_intent} failed and cleanup could not confirm exit of {identity}"
        )


def _hash_command(command: Sequence[str]) -> tuple[str, int]:
    rendered = "\0".join(str(part) for part in command)
    return hashlib.sha256(rendered.encode("utf-8", errors="ignore")).hexdigest(), len(rendered)


def _stdio_policy_name(target: object, *, inherited_label: str) -> str:
    if target is None:
        return inherited_label
    if target is subprocess.DEVNULL:
        return "devnull"
    if target is subprocess.PIPE:
        return "pipe"
    if target is subprocess.STDOUT:
        return "stdout"
    return "file"


def _process_exited(process: object, *, timeout: float) -> bool:
    wait = getattr(process, "wait", None)
    if callable(wait):
        try:
            wait(timeout=max(timeout, 0.0))
            return True
        except subprocess.TimeoutExpired:
            return False
        except (ChildProcessError, ProcessLookupError):
            return True
        except BaseException:  # noqa: BLE001 - cleanup must preserve the original failure
            pass
    poll = getattr(process, "poll", None)
    if not callable(poll):
        return False
    try:
        return poll() is not None
    except BaseException:  # noqa: BLE001 - cleanup must preserve the original failure
        return False


def _process_pid(process: object) -> int | None:
    pid = getattr(process, "pid", None)
    return (
        pid
        if (
            isinstance(pid, int)
            and not isinstance(pid, bool)
            and pid > 0
            and pid not in {os.getpid(), os.getppid()}
        )
        else None
    )


def _process_group_exists(pid: int) -> bool | None:
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except BaseException:  # noqa: BLE001 - cleanup must preserve the original failure
        return None


def _wait_for_process_group_exit(pid: int, *, timeout: float) -> bool:
    deadline = time.monotonic() + max(timeout, 0.0)
    while True:
        exists = _process_group_exists(pid)
        if exists is False:
            return True
        if exists is None or time.monotonic() >= deadline:
            return False
        try:
            time.sleep(min(0.01, max(deadline - time.monotonic(), 0.0)))
        except BaseException:  # noqa: BLE001 - cancellation cannot abandon authority
            return False


def _signal_spawned_process(
    process: object,
    sig: signal.Signals,
    *,
    process_group: bool,
) -> None:
    pid = _process_pid(process)
    if process_group and pid is not None:
        try:
            os.killpg(pid, sig)
            return
        except BaseException:  # noqa: BLE001 - fall back to the Popen handle
            pass
    method_name = "terminate" if sig == signal.SIGTERM else "kill"
    method = getattr(process, method_name, None)
    if callable(method):
        try:
            method()
        except BaseException:  # noqa: BLE001 - cleanup must preserve the original failure
            pass


def _terminate_unhanded_process(
    process: object,
    *,
    term_timeout: float = 0.5,
    kill_timeout: float = 1.0,
    process_group: bool = True,
) -> bool:
    """Best-effort terminate and reap a spawned process whose handoff failed."""

    pid = _process_pid(process)
    process_exited = _process_exited(process, timeout=0.0)
    group_exited = (
        _process_group_exists(pid) is False
        if process_group and pid is not None
        else True
    )
    if process_exited and group_exited:
        return True
    _signal_spawned_process(process, signal.SIGTERM, process_group=process_group)
    process_exited = _process_exited(process, timeout=term_timeout)
    group_exited = (
        _process_group_exists(pid) is False
        if process_group and pid is not None
        else True
    )
    if process_exited and group_exited:
        return True
    _signal_spawned_process(process, signal.SIGKILL, process_group=process_group)
    process_exited = _process_exited(process, timeout=kill_timeout)
    group_exited = (
        _wait_for_process_group_exit(pid, timeout=kill_timeout)
        if process_group and pid is not None
        else True
    )
    return process_exited and group_exited


class ProcessLaunchMixin:
    _emit: Callable[..., Any] | None
    _launch_records: list[LaunchRecord]

    def _record_launch(
        self,
        *,
        launch_intent: str,
        command: Sequence[str],
        pid: int | None,
        cwd: str | Path | None,
        stdin_policy: str,
        stdout_policy: str,
        stderr_policy: str,
        controller_input_owner_allowed: bool,
        active: bool,
        emit_event: bool = True,
    ) -> None:
        command_hash, command_length = _hash_command(command)
        record = LaunchRecord(
            launch_intent=launch_intent,
            pid=pid if isinstance(pid, int) and pid > 0 else None,
            command_hash=command_hash,
            command_length=command_length,
            cwd=str(cwd) if cwd is not None else None,
            stdin_policy=stdin_policy,
            stdout_policy=stdout_policy,
            stderr_policy=stderr_policy,
            controller_input_owner_allowed=bool(controller_input_owner_allowed),
            active=bool(active),
            launched_at_monotonic=time.monotonic(),
        )
        self._launch_records.append(record)
        if emit_event and callable(self._emit):
            self._emit(
                "process.launch",
                component="shared.process_runner",
                launch_intent=launch_intent,
                pid=record.pid,
                command_hash=record.command_hash,
                command_length=record.command_length,
                cwd=record.cwd,
                stdin_policy=stdin_policy,
                stdout_policy=stdout_policy,
                stderr_policy=stderr_policy,
                controller_input_owner_allowed=bool(controller_input_owner_allowed),
                active=bool(active),
            )

    def _mark_launch_inactive(self, process: object) -> None:
        pid = getattr(process, "pid", None)
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            return
        for record in reversed(self._launch_records):
            if record.pid == pid and record.active:
                record.active = False
                return

    @staticmethod
    def _prepare_log_targets(
        *,
        stdout_path: str | Path | None,
        stderr_path: str | Path | None,
    ) -> tuple[int | IO[str], int | IO[str], list[IO[str]]]:
        stdout_target: int | IO[str]
        stderr_target: int | IO[str]
        opened_handles: list[IO[str]] = []

        if stdout_path is not None:
            stdout_file = Path(stdout_path)
            stdout_file.parent.mkdir(parents=True, exist_ok=True)
            handle = stdout_file.open("a", encoding="utf-8")
            stdout_target = handle
            opened_handles.append(handle)
        else:
            stdout_target = subprocess.DEVNULL

        if stderr_path is not None:
            stderr_file = Path(stderr_path)
            stderr_file.parent.mkdir(parents=True, exist_ok=True)
            if stdout_path is not None and Path(stdout_path) == stderr_file:
                stderr_target = stdout_target
            else:
                handle = stderr_file.open("a", encoding="utf-8")
                stderr_target = handle
                opened_handles.append(handle)
        elif stdout_path is not None:
            stderr_target = stdout_target
        else:
            stderr_target = subprocess.DEVNULL
        return stdout_target, stderr_target, opened_handles

    def start_background(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        stdout_path: str | Path | None = None,
        stderr_path: str | Path | None = None,
    ) -> subprocess.Popen[str]:
        stdout_target, stderr_target, opened_handles = self._prepare_log_targets(
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                list(cmd),
                cwd=str(cwd) if cwd is not None else None,
                env=dict(env) if env is not None else None,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=stdout_target,
                stderr=stderr_target,
            )
            self._record_launch(
                launch_intent="background_service",
                command=cmd,
                pid=getattr(process, "pid", None),
                cwd=cwd,
                stdin_policy="devnull",
                stdout_policy=_stdio_policy_name(stdout_target, inherited_label="inherit"),
                stderr_policy=_stdio_policy_name(stderr_target, inherited_label="inherit"),
                controller_input_owner_allowed=False,
                active=True,
            )
            return process
        except BaseException as exc:  # noqa: BLE001 - a failed handoff must not orphan the child
            if process is not None:
                if _terminate_unhanded_process(process):
                    self._mark_launch_inactive(process)
                else:
                    raise ProcessHandoffCleanupError(
                        process=process,
                        launch_intent="background_service",
                    ) from exc
            raise
        finally:
            for handle in opened_handles:
                try:
                    handle.close()
                except BaseException:  # noqa: BLE001 - diagnostics cleanup cannot orphan the child
                    continue

    def start(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        stdout_path: str | Path | None = None,
        stderr_path: str | Path | None = None,
    ) -> subprocess.Popen[str]:
        return self.start_background(
            cmd,
            cwd=cwd,
            env=env,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

    def start_interactive_child(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin: int | TextIO | None = None,
        stdout: int | TextIO | None = None,
        stderr: int | TextIO | None = None,
    ) -> subprocess.Popen[str]:
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                list(cmd),
                cwd=str(cwd) if cwd is not None else None,
                env=dict(env) if env is not None else None,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
            )
            self._record_launch(
                launch_intent="interactive_child",
                command=cmd,
                pid=getattr(process, "pid", None),
                cwd=cwd,
                stdin_policy=_stdio_policy_name(stdin, inherited_label="inherit"),
                stdout_policy=_stdio_policy_name(stdout, inherited_label="inherit"),
                stderr_policy=_stdio_policy_name(stderr, inherited_label="inherit"),
                controller_input_owner_allowed=True,
                active=True,
            )
            return process
        except BaseException as exc:  # noqa: BLE001 - a failed handoff must not orphan the child
            if process is not None:
                if _terminate_unhanded_process(process, process_group=False):
                    self._mark_launch_inactive(process)
                else:
                    raise ProcessHandoffCleanupError(
                        process=process,
                        launch_intent="interactive_child",
                    ) from exc
            raise

    def tracked_launches(self, *, active_only: bool = False) -> list[dict[str, object]]:
        launches: list[dict[str, object]] = []
        for record in self._launch_records:
            active = bool(record.active and isinstance(record.pid, int) and self.is_pid_running(record.pid))
            if active_only and not active:
                continue
            launches.append(
                {
                    "launch_intent": record.launch_intent,
                    "pid": record.pid,
                    "command_hash": record.command_hash,
                    "command_length": record.command_length,
                    "cwd": record.cwd,
                    "stdin_policy": record.stdin_policy,
                    "stdout_policy": record.stdout_policy,
                    "stderr_policy": record.stderr_policy,
                    "controller_input_owner_allowed": record.controller_input_owner_allowed,
                    "active": active,
                }
            )
        return launches

    def launch_diagnostics_summary(self) -> dict[str, object]:
        tracked = self.tracked_launches(active_only=False)
        active = [item for item in tracked if bool(item.get("active", False))]
        counts: dict[str, int] = {}
        controller_input_owners: list[dict[str, object]] = []
        for item in tracked:
            intent = str(item.get("launch_intent", "")).strip() or "unknown"
            counts[intent] = counts.get(intent, 0) + 1
            if bool(item.get("controller_input_owner_allowed", False)):
                controller_input_owners.append(item)
        return {
            "tracked_launch_count": len(tracked),
            "active_launch_count": len(active),
            "launch_intent_counts": dict(sorted(counts.items(), key=lambda item: item[0])),
            "controller_input_owners": controller_input_owners,
            "active_controller_input_owners": [
                item for item in controller_input_owners if bool(item.get("active", False))
            ],
            "tracked_launches": tracked,
        }
