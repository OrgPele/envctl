from __future__ import annotations

import hashlib
import os
import re
import shutil
import signal
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from envctl_engine.ui.spinner import spinner, spinner_enabled, use_spinner_policy
from envctl_engine.ui.spinner_service import resolve_spinner_policy


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


class ProcessRunner:
    """Thin subprocess/process utility wrapper for orchestration flows."""

    def __init__(self, *, emit: Callable[..., Any] | None = None) -> None:
        self._emit = emit
        self._launch_records: list[LaunchRecord] = []

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

                    line_stripped = line.rstrip("\n")
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
    ) -> tuple[object, object, list[object]]:
        stdout_target: object
        stderr_target: object
        opened_handles: list[object] = []

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
        stdin: object | None = None,
        stdout: object | None = None,
        stderr: object | None = None,
    ) -> subprocess.Popen[str]:
        process = subprocess.Popen(
            list(cmd),
            cwd=str(cwd) if cwd is not None else None,
            env=dict(env) if env is not None else None,
            text=True,
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

    def run_probe(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        stdout_target: object = subprocess.PIPE,
        stderr_target: object = subprocess.PIPE,
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

    def is_pid_running(self, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        identity = self._pid_identity(pid)
        if identity is not None:
            try:
                completed = self.run_probe(["ps", "-p", str(pid), "-o", "stat="])
            except OSError:
                completed = None
            if completed is not None and completed.returncode == 0:
                stat = completed.stdout.strip().upper()
                if stat.startswith("Z"):
                    return False
        return True

    def wait_for_port(self, port: int, *, host: str = "127.0.0.1", timeout: float = 30.0) -> bool:
        if port <= 0:
            return False
        probe_hosts = self._probe_hosts(host)
        if not probe_hosts:
            return False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for probe_host in probe_hosts:
                if self._host_port_reachable(probe_host, port, timeout=0.25):
                    return True
            time.sleep(0.1)
        return False

    def supports_process_tree_probe(self) -> bool:
        try:
            completed = self.run_probe(["ps", "-axo", "pid=,ppid="])
        except OSError:
            return False
        return completed.returncode == 0

    @staticmethod
    def _probe_hosts(host: str) -> list[str]:
        raw = host.strip()
        normalized = raw.lower()
        if normalized not in {"", "127.0.0.1", "::1", "localhost"}:
            return [raw]

        candidates = [raw or "127.0.0.1", "127.0.0.1", "::1", "localhost"]
        resolved: list[str] = []
        for candidate in candidates:
            text = candidate.strip()
            if not text or text in resolved:
                continue
            resolved.append(text)
        return resolved

    @staticmethod
    def _host_port_reachable(host: str, port: int, *, timeout: float) -> bool:
        try:
            addresses = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except OSError:
            return False

        attempted: set[tuple[int, int, int, object]] = set()
        for family, socktype, proto, _canonname, sockaddr in addresses:
            key = (family, socktype, proto, sockaddr)
            if key in attempted:
                continue
            attempted.add(key)
            try:
                with socket.socket(family, socktype, proto) as sock:
                    sock.settimeout(timeout)
                    if sock.connect_ex(sockaddr) == 0:
                        return True
            except OSError:
                continue
        return False

    def pid_owns_port(self, pid: int, port: int) -> bool:
        if pid <= 0 or port <= 0:
            return False

        lsof_bin = shutil.which("lsof")
        if lsof_bin is None:
            return False

        try:
            completed = self.run_probe(
                [
                    lsof_bin,
                    "-nP",
                    "-a",
                    "-p",
                    str(pid),
                    f"-iTCP:{port}",
                    "-sTCP:LISTEN",
                    "-t",
                ]
            )
        except OSError:
            return False
        if completed.returncode != 0:
            return False
        return bool(completed.stdout.strip())

    def wait_for_pid_port(
        self,
        pid: int,
        port: int,
        *,
        host: str = "127.0.0.1",
        timeout: float = 30.0,
        debug_pid_wait_group: str = "",
    ) -> bool:
        if pid <= 0 or port <= 0:
            return False
        if debug_pid_wait_group not in {"", "signal_gate", "pid_port_lsof", "tree_port_scan"}:
            debug_pid_wait_group = ""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if debug_pid_wait_group in {"", "signal_gate"} and not self.is_pid_running(pid):
                return False
            if debug_pid_wait_group in {"", "pid_port_lsof"} and self.pid_owns_port(pid, port):
                return True
            if debug_pid_wait_group in {"", "tree_port_scan"}:
                discovered = self.find_pid_listener_port(pid, port, max_delta=0)
                if discovered == port:
                    return True
            time.sleep(0.05)
        return False

    def find_pid_listener_port(
        self,
        pid: int,
        preferred_port: int,
        *,
        max_delta: int = 200,
    ) -> int | None:
        if pid <= 0:
            return None

        ports = self._list_process_tree_listener_ports(pid)
        if not ports:
            return None

        if preferred_port > 0 and preferred_port in ports:
            return preferred_port

        if preferred_port > 0:
            upper_bound = preferred_port + max(max_delta, 0)
            higher_or_equal = sorted(port for port in ports if preferred_port <= port <= upper_bound)
            if higher_or_equal:
                return higher_or_equal[0]

            closest = min(ports, key=lambda value: abs(value - preferred_port))
            if abs(closest - preferred_port) <= max(max_delta, 0):
                return closest
            return None

        return min(ports)

    def _list_process_tree_listener_ports(self, root_pid: int) -> set[int]:
        lsof_bin = shutil.which("lsof")
        if lsof_bin is None:
            return set()

        ports: set[int] = set()
        for pid in sorted(self._process_tree_pids(root_pid)):
            try:
                completed = self.run_probe(
                    [
                        lsof_bin,
                        "-nP",
                        "-a",
                        "-p",
                        str(pid),
                        "-iTCP",
                        "-sTCP:LISTEN",
                    ]
                )
            except OSError:
                continue
            if completed.returncode not in {0, 1}:
                continue
            ports.update(self._parse_listener_ports(completed.stdout))
        return ports

    def process_tree_listener_pids(self, root_pid: int, *, port: int | None = None) -> list[int]:
        if root_pid <= 0:
            return []
        lsof_bin = shutil.which("lsof")
        if lsof_bin is None:
            return []

        listeners: set[int] = set()
        for pid in sorted(self._process_tree_pids(root_pid)):
            cmd = [lsof_bin, "-nP", "-a", "-p", str(pid)]
            if isinstance(port, int) and port > 0:
                cmd.append(f"-iTCP:{port}")
            else:
                cmd.append("-iTCP")
            cmd.extend(["-sTCP:LISTEN", "-t"])
            try:
                completed = self.run_probe(
                    cmd,
                )
            except OSError:
                continue
            if completed.returncode not in {0, 1}:
                continue
            listeners.update(self._parse_pid_list(completed.stdout))
        return sorted(listeners)

    def listener_pids_for_port(self, port: int) -> list[int]:
        if port <= 0:
            return []
        lsof_bin = shutil.which("lsof")
        if lsof_bin is None:
            return []
        try:
            completed = self.run_probe(
                [
                    lsof_bin,
                    "-nP",
                    "-iTCP:" + str(port),
                    "-sTCP:LISTEN",
                    "-t",
                ]
            )
        except OSError:
            return []
        if completed.returncode not in {0, 1}:
            return []
        return sorted(self._parse_pid_list(completed.stdout))

    @staticmethod
    def _parse_listener_ports(output: str) -> set[int]:
        ports: set[int] = set()
        for line in output.splitlines():
            match = re.search(r":(\d+)(?:->\S+)?\s+\(LISTEN\)\s*$", line)
            if match is None:
                continue
            ports.add(int(match.group(1)))
        return ports

    @staticmethod
    def _parse_pid_list(output: str) -> set[int]:
        pids: set[int] = set()
        for line in output.splitlines():
            text = line.strip()
            if not text:
                continue
            if text.isdigit():
                value = int(text)
                if value > 0:
                    pids.add(value)
        return pids

    def _process_tree_pids(self, root_pid: int) -> set[int]:
        try:
            completed = self.run_probe(["ps", "-axo", "pid=,ppid="])
        except OSError:
            return {root_pid}
        if completed.returncode != 0:
            return {root_pid}

        children_by_parent: dict[int, set[int]] = {}
        for line in completed.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) != 2:
                continue
            if not (parts[0].isdigit() and parts[1].isdigit()):
                continue
            pid = int(parts[0])
            ppid = int(parts[1])
            children_by_parent.setdefault(ppid, set()).add(pid)

        discovered: set[int] = set()
        stack = [root_pid]
        while stack:
            current = stack.pop()
            if current in discovered:
                continue
            discovered.add(current)
            stack.extend(sorted(children_by_parent.get(current, ())))
        return discovered

    def _terminate_with_signal_sender(
        self,
        pid: int,
        *,
        term_timeout: float,
        kill_timeout: float,
        signal_sender: Callable[[int, signal.Signals], None],
    ) -> bool:
        if pid <= 0:
            return True
        initial_identity = self._pid_identity(pid)
        try:
            signal_sender(pid, signal.SIGTERM)
        except OSError:
            return True

        deadline = time.monotonic() + max(term_timeout, 0.0)
        while time.monotonic() < deadline:
            if not self.is_pid_running(pid):
                return True
            if initial_identity is not None:
                current_identity = self._pid_identity(pid)
                if current_identity is None or current_identity != initial_identity:
                    return True
            time.sleep(0.05)

        try:
            if initial_identity is not None:
                current_identity = self._pid_identity(pid)
                if current_identity is None or current_identity != initial_identity:
                    return True
            signal_sender(pid, signal.SIGKILL)
        except OSError:
            return True

        kill_deadline = time.monotonic() + max(kill_timeout, 0.0)
        while time.monotonic() < kill_deadline:
            if not self.is_pid_running(pid):
                return True
            if initial_identity is not None:
                current_identity = self._pid_identity(pid)
                if current_identity is None or current_identity != initial_identity:
                    return True
            time.sleep(0.05)
        if initial_identity is not None:
            current_identity = self._pid_identity(pid)
            if current_identity is None or current_identity != initial_identity:
                return True
        return not self.is_pid_running(pid)

    def terminate(self, pid: int, *, term_timeout: float = 2.0, kill_timeout: float = 1.0) -> bool:
        return self._terminate_with_signal_sender(
            pid,
            term_timeout=term_timeout,
            kill_timeout=kill_timeout,
            signal_sender=os.kill,
        )

    def terminate_process_group(self, pid: int, *, term_timeout: float = 2.0, kill_timeout: float = 1.0) -> bool:
        return self._terminate_with_signal_sender(
            pid,
            term_timeout=term_timeout,
            kill_timeout=kill_timeout,
            signal_sender=os.killpg,
        )

    def _pid_identity(self, pid: int) -> str | None:
        if pid <= 0:
            return None
        try:
            completed = self.run_probe(["ps", "-p", str(pid), "-o", "lstart="])
        except OSError:
            return None
        if completed.returncode != 0:
            return None
        identity = completed.stdout.strip()
        return identity or None
