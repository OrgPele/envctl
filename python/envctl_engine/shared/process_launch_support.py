from __future__ import annotations

import hashlib
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
        if callable(self._emit):
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
        finally:
            for handle in opened_handles:
                try:
                    handle.close()
                except OSError:
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
