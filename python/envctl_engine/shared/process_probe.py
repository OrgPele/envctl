from __future__ import annotations

import re
from typing import Callable, Protocol
import importlib
import importlib.util
import time


class ProbeBackend(Protocol):
    """Protocol for probe backends that check process and port status."""

    def is_pid_running(self, pid: int) -> bool:
        """Check if a process ID is running."""
        ...

    def wait_for_pid_port(self, pid: int, port: int, *, timeout: float) -> bool:
        """Wait for a process to listen on a port."""
        ...

    def pid_owns_port(self, pid: int, port: int) -> bool:
        """Check if a process owns a port."""
        ...

    def wait_for_port(self, port: int, *, timeout: float) -> bool:
        """Wait for a port to become available."""
        ...


class ShellProbeBackend:
    """Shell-based probe backend using process_runner methods."""

    def __init__(self, process_runner: object) -> None:
        self.process_runner: object = process_runner

    def is_pid_running(self, pid: int) -> bool:
        """Check if a process ID is running."""
        return bool(getattr(self.process_runner, "is_pid_running")(pid))

    def wait_for_pid_port(self, pid: int, port: int, *, timeout: float) -> bool:
        """Wait for a process to listen on a port."""
        wait_for_pid = getattr(self.process_runner, "wait_for_pid_port", None)
        if not callable(wait_for_pid):
            return False
        return bool(wait_for_pid(pid, port, timeout=timeout))

    def pid_owns_port(self, pid: int, port: int) -> bool:
        """Check if a process owns a port."""
        owns = getattr(self.process_runner, "pid_owns_port", None)
        if not callable(owns):
            return False
        return bool(owns(pid, port))

    def wait_for_port(self, port: int, *, timeout: float) -> bool:
        """Wait for a port to become available."""
        wait_for_port = getattr(self.process_runner, "wait_for_port", None)
        if not callable(wait_for_port):
            return False
        return bool(wait_for_port(port, timeout=timeout))


def psutil_available() -> bool:
    return importlib.util.find_spec("psutil") is not None


def _load_psutil() -> object | None:
    if not psutil_available():
        return None
    try:
        return importlib.import_module("psutil")
    except Exception:
        return None


class PsutilProbeBackend:
    """psutil-based probe backend for process and port status."""

    def __init__(
        self,
        psutil_module: object | None = None,
        *,
        time_source: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._psutil: object | None = psutil_module or _load_psutil()
        self._time = time_source
        self._sleep = sleep

    def is_pid_running(self, pid: int) -> bool:
        psutil_mod = self._psutil
        if psutil_mod is None:
            return False
        try:
            pid_exists = getattr(psutil_mod, "pid_exists")
            if not bool(pid_exists(pid)):
                return False
            process = getattr(psutil_mod, "Process")(pid)
            return bool(process.is_running())
        except Exception:
            return False

    def wait_for_pid_port(self, pid: int, port: int, *, timeout: float) -> bool:
        deadline = self._time() + max(0.0, float(timeout))
        while True:
            if self.pid_owns_port(pid, port):
                return True
            if self._time() >= deadline:
                return False
            self._sleep(0.05)

    def pid_owns_port(self, pid: int, port: int) -> bool:
        for conn in self._iter_connections():
            if getattr(conn, "pid", None) != pid:
                continue
            laddr = getattr(conn, "laddr", None)
            if laddr is None or getattr(laddr, "port", None) != port:
                continue
            status = getattr(conn, "status", None)
            if status and status != "LISTEN":
                continue
            return True
        return False

    def wait_for_port(self, port: int, *, timeout: float) -> bool:
        deadline = self._time() + max(0.0, float(timeout))
        while True:
            if self._port_listening(port):
                return True
            if self._time() >= deadline:
                return False
            self._sleep(0.05)

    def _iter_connections(self) -> list[object]:
        psutil_mod = self._psutil
        if psutil_mod is None:
            return []
        try:
            net_connections = getattr(psutil_mod, "net_connections")
            return list(net_connections(kind="inet"))
        except Exception:
            return []

    def _port_listening(self, port: int) -> bool:
        for conn in self._iter_connections():
            laddr = getattr(conn, "laddr", None)
            if laddr is None or getattr(laddr, "port", None) != port:
                continue
            status = getattr(conn, "status", None)
            if status and status != "LISTEN":
                continue
            return True
        return False


from dataclasses import dataclass


@dataclass
class ProbeRecord:
    """Normalized probe record with backend, pid, listener_ports, and ownership info."""
    backend: str
    pid: int
    listener_ports: set[int]
    ownership: dict[int, bool]  # port -> is_owned_by_pid


class ProcessProbe:
    def __init__(self, backend: ProbeBackend) -> None:
        self.backend: ProbeBackend = backend

    def service_truth_status(
        self,
        *,
        service: object,
        listener_truth_enforced: bool,
        service_truth_timeout: float,
        within_startup_grace: Callable[[object], bool],
        truth_discovery: Callable[[object, int], int | None],
        clear_listener_pids: Callable[[object], None],
        refresh_listener_pids: Callable[[object, int], None],
        emit: Callable[..., None],
        fallback_enabled: bool = False,
        rebind_stale: Callable[[object, int | None], bool],
    ) -> str:
        debug_poststart_truth_group = str(getattr(self, "_debug_poststart_truth_group", "") or "").strip().lower()
        if debug_poststart_truth_group not in {"", "pid_wait", "port_fallback", "truth_discovery"}:
            debug_poststart_truth_group = ""
        pid = getattr(service, "pid", None)
        if not isinstance(pid, int) or pid <= 0:
            if self._call_rebind(rebind_stale, service, pid if isinstance(pid, int) else None):
                return "running"
            return "stale"

        if not self.backend.is_pid_running(pid):
            if self._call_rebind(rebind_stale, service, pid):
                return "running"
            return "stale"

        if not listener_truth_enforced:
            clear_listener_pids(service)
            return "running"

        port = getattr(service, "actual_port", None)
        if port is None:
            port = getattr(service, "requested_port", None)
        if not isinstance(port, int) or port <= 0:
            clear_listener_pids(service)
            return "starting" if within_startup_grace(service) else "unreachable"

        wait_for_pid = self.backend.wait_for_pid_port
        if callable(wait_for_pid):
            if debug_poststart_truth_group in {"", "pid_wait"} and wait_for_pid(pid, port, timeout=service_truth_timeout):
                self._call_refresh(refresh_listener_pids, service, port)
                return "running"
            if debug_poststart_truth_group in {"", "port_fallback"} and self._port_fallback_running(
                fallback_enabled=fallback_enabled,
                emit=emit,
                service=service,
                port=port,
                timeout=service_truth_timeout,
            ):
                self._call_refresh(refresh_listener_pids, service, port)
                return "running"
            if debug_poststart_truth_group in {"", "truth_discovery"} and truth_discovery(service, port) is not None:
                self._call_refresh(refresh_listener_pids, service, port)
                return "running"
            if within_startup_grace(service):
                clear_listener_pids(service)
                return "starting"
            clear_listener_pids(service)
            return "unreachable"

        owns = self.backend.pid_owns_port
        if callable(owns):
            if debug_poststart_truth_group in {"", "pid_wait"} and owns(pid, port):
                self._call_refresh(refresh_listener_pids, service, port)
                return "running"
            if debug_poststart_truth_group in {"", "port_fallback"} and self._port_fallback_running(
                fallback_enabled=fallback_enabled,
                emit=emit,
                service=service,
                port=port,
                timeout=service_truth_timeout,
            ):
                self._call_refresh(refresh_listener_pids, service, port)
                return "running"
            if debug_poststart_truth_group in {"", "truth_discovery"} and truth_discovery(service, port) is not None:
                self._call_refresh(refresh_listener_pids, service, port)
                return "running"
            if within_startup_grace(service):
                clear_listener_pids(service)
                return "starting"
            clear_listener_pids(service)
            return "unreachable"

        if not fallback_enabled:
            if within_startup_grace(service):
                clear_listener_pids(service)
                return "starting"
            clear_listener_pids(service)
            return "unreachable"

        if debug_poststart_truth_group not in {"", "port_fallback"} or not self._port_fallback_running(
            fallback_enabled=fallback_enabled,
            emit=emit,
            service=service,
            port=port,
            timeout=service_truth_timeout,
        ):
            if debug_poststart_truth_group in {"", "truth_discovery"} and truth_discovery(service, port) is not None:
                self._call_refresh(refresh_listener_pids, service, port)
                return "running"
            if within_startup_grace(service):
                clear_listener_pids(service)
                return "starting"
            clear_listener_pids(service)
            return "unreachable"

        self._call_refresh(refresh_listener_pids, service, port)
        return "running"

    def _port_fallback_running(
        self,
        *,
        fallback_enabled: bool,
        emit: Callable[..., None],
        service: object,
        port: int,
        timeout: float,
    ) -> bool:
        if not fallback_enabled:
            return False
        wait_for_port = self.backend.wait_for_port
        if not callable(wait_for_port):
            return False
        if not callable(wait_for_port):
            return False
        emit(
            "service.truth.degraded",
            service=str(getattr(service, "name", getattr(service, "type", "service"))),
            port=port,
            reason_code="pid_probe_unavailable_port_fallback",
        )
        return bool(wait_for_port(port, timeout=timeout))

    @staticmethod
    def parse_lsof_listener_pid_map(*, stdout: str, target_ports: set[int]) -> dict[int, set[int]] | None:
        if not stdout:
            return {}
        pid_port_map: dict[int, set[int]] = {}
        saw_non_header_line = False
        for line in stdout.splitlines():
            text = line.rstrip()
            if not text:
                continue
            lowered = text.lower()
            if lowered.startswith("command ") and " pid " in lowered:
                continue
            saw_non_header_line = True
            port_match = re.search(r":(\d+)(?:->\S+)?\s+\(listen\)\s*$", text, flags=re.IGNORECASE)
            if port_match is None:
                continue
            port = int(port_match.group(1))
            if port not in target_ports:
                continue
            parts = text.split()
            if len(parts) < 2 or not parts[1].isdigit():
                continue
            pid = int(parts[1])
            pid_port_map.setdefault(pid, set()).add(port)
        if not saw_non_header_line:
            return {}
        return pid_port_map

    @staticmethod
    def split_listener_pid_maps(
        *,
        pid_port_map: dict[int, set[int]],
        command_for_pid: Callable[[int], str],
        is_docker_process: Callable[[str], bool],
    ) -> tuple[dict[int, set[int]], dict[int, set[int]]]:
        kill_pid_ports: dict[int, set[int]] = {}
        docker_pid_ports: dict[int, set[int]] = {}
        for pid in sorted(pid_port_map):
            command_text = command_for_pid(pid)
            if is_docker_process(command_text):
                docker_pid_ports[pid] = set(pid_port_map[pid])
            else:
                kill_pid_ports[pid] = set(pid_port_map[pid])
        return kill_pid_ports, docker_pid_ports

    @staticmethod
    def _call_rebind(callback: Callable[..., bool], service: object, previous_pid: int | None) -> bool:
        try:
            return bool(callback(service, previous_pid=previous_pid))
        except TypeError:
            return bool(callback(service, previous_pid))

    @staticmethod
    def _call_refresh(callback: Callable[..., None], service: object, port: int) -> None:
        try:
            callback(service, port=port)
        except TypeError:
            callback(service, port)
