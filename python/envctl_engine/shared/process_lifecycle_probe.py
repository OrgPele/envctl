from __future__ import annotations

from collections.abc import Callable
import errno
import os
import re
import shutil
import signal
import socket
import time

from envctl_engine.shared.process_cwd import process_cwd as read_process_cwd


class ProcessLifecycleProbeMixin:
    def is_pid_running(self, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError as exc:
            return exc.errno != errno.ESRCH
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

    def process_cwd(self, pid: int) -> str | None:
        return read_process_cwd(pid, run_probe=self.run_probe)

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
            return not self.is_pid_running(pid)

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
            return not self.is_pid_running(pid)

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
        if pid <= 0:
            return True
        try:
            process_group_id = os.getpgid(pid)
        except ProcessLookupError:
            return not self.is_pid_running(pid)
        except (PermissionError, OSError):
            return False
        if process_group_id <= 0:
            return False
        if process_group_id == os.getpgrp():
            return False

        initial_members = self._process_group_member_pids(process_group_id)
        initial_identities = {member_pid: self._pid_identity(member_pid) for member_pid in initial_members or ()}
        try:
            os.killpg(process_group_id, signal.SIGTERM)
        except OSError:
            return not self._process_group_is_running(process_group_id) and not self.is_pid_running(pid)

        if self._wait_for_process_group_exit(process_group_id, timeout=term_timeout):
            return True
        if not self._process_group_escalation_is_safe(
            process_group_id,
            initial_members=initial_members,
            initial_identities=initial_identities,
        ):
            return False
        try:
            os.killpg(process_group_id, signal.SIGKILL)
        except OSError:
            return not self._process_group_is_running(process_group_id) and not self.is_pid_running(pid)
        return self._wait_for_process_group_exit(process_group_id, timeout=kill_timeout)

    def _process_group_member_pids(self, process_group_id: int) -> set[int] | None:
        try:
            completed = self.run_probe(["ps", "-axo", "pid=,pgid=,stat="])
        except OSError:
            return None
        if completed.returncode != 0:
            return None

        members: set[int] = set()
        for line in completed.stdout.splitlines():
            parts = line.strip().split(maxsplit=2)
            if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
                continue
            if int(parts[1]) != process_group_id or parts[2].upper().startswith("Z"):
                continue
            members.add(int(parts[0]))
        return members

    def _process_group_is_running(self, process_group_id: int) -> bool:
        members = self._process_group_member_pids(process_group_id)
        if members is not None:
            return bool(members)
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError as exc:
            return exc.errno != errno.ESRCH
        return True

    def _wait_for_process_group_exit(self, process_group_id: int, *, timeout: float) -> bool:
        deadline = time.monotonic() + max(timeout, 0.0)
        while True:
            if not self._process_group_is_running(process_group_id):
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.05, remaining))

    def _process_group_escalation_is_safe(
        self,
        process_group_id: int,
        *,
        initial_members: set[int] | None,
        initial_identities: dict[int, str | None],
    ) -> bool:
        if process_group_id == os.getpgrp():
            return False
        current_members = self._process_group_member_pids(process_group_id)
        if current_members is None or initial_members is None:
            return self._process_group_is_running(process_group_id)
        for member_pid in initial_members.intersection(current_members):
            initial_identity = initial_identities.get(member_pid)
            current_identity = self._pid_identity(member_pid)
            if initial_identity is None or current_identity is None or current_identity == initial_identity:
                return True
        return False

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
