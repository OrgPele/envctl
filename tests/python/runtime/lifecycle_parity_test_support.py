from __future__ import annotations

import json
import importlib
import os
import threading
import tempfile
import time
import unittest
from contextlib import contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
command_router = importlib.import_module("envctl_engine.runtime.command_router")
config_module = importlib.import_module("envctl_engine.config")
runtime_module = importlib.import_module("envctl_engine.runtime.engine_runtime")
models_module = importlib.import_module("envctl_engine.state.models")
state_module = importlib.import_module("envctl_engine.state")
startup_support = importlib.import_module("envctl_engine.runtime.engine_runtime_startup_support")

parse_route = command_router.parse_route
load_config = config_module.load_config
PythonEngineRuntime = runtime_module.PythonEngineRuntime
ProjectContext = runtime_module.ProjectContext
PortPlan = models_module.PortPlan
RequirementsResult = models_module.RequirementsResult
RunState = models_module.RunState
ServiceRecord = models_module.ServiceRecord
dump_state = state_module.dump_state



class _NoopPlanner:
    def __init__(self) -> None:
        self.released = False
        self.released_ports: list[int] = []

    def release_all(self) -> None:
        self.released = True

    def release(self, port: int, owner: str | None = None) -> None:
        _ = owner
        self.released_ports.append(port)

class _TrackingPlanner:
    def __init__(self) -> None:
        self.released_session = False
        self.released_all = False

    def release_session(self) -> None:
        self.released_session = True

    def release_all(self) -> None:
        self.released_all = True

class _TrackingRunner:
    def __init__(self) -> None:
        self.terminated: list[int] = []
        self.run_calls: list[tuple[str, ...]] = []
        self.docker_ps_stdout = "cid1|postgres:16|envctl-postgres\n"
        self.inspect_volumes_by_cid: dict[str, str] = {}
        self.ps_stdout = ""
        self.ps_tree_stdout = ""

    def terminate(self, pid: int, *, term_timeout: float = 2.0, kill_timeout: float = 1.0) -> bool:
        _ = term_timeout, kill_timeout
        self.terminated.append(pid)
        return True

    def is_pid_running(self, pid: int) -> bool:
        return pid > 0

    def pid_owns_port(self, pid: int, port: int) -> bool:
        _ = pid, port
        return True

    def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
        _ = cwd, env, timeout
        self.run_calls.append(tuple(str(part) for part in cmd))
        joined = " ".join(str(part) for part in cmd)
        if tuple(str(part) for part in cmd) == ("ps", "-axo", "pid=,command="):
            return type("Result", (), {"returncode": 0, "stdout": self.ps_stdout, "stderr": ""})()
        if tuple(str(part) for part in cmd) == ("ps", "-axo", "pid=,ppid="):
            return type("Result", (), {"returncode": 0, "stdout": self.ps_tree_stdout, "stderr": ""})()
        if joined.startswith("docker ps -a --format"):
            return type("Result", (), {"returncode": 0, "stdout": self.docker_ps_stdout, "stderr": ""})()
        if len(cmd) >= 4 and tuple(str(part) for part in cmd[:3]) == ("docker", "inspect", "-f"):
            cid = str(cmd[-1])
            stdout = self.inspect_volumes_by_cid.get(cid, "")
            return type("Result", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

class _OwnershipDenyRunner(_TrackingRunner):
    def pid_owns_port(self, pid: int, port: int) -> bool:
        _ = pid, port
        return False

class _ResumeRestoreRunner:
    def __init__(self) -> None:
        self.run_calls: list[tuple[str, ...]] = []
        self.start_calls: list[tuple[str, ...]] = []
        self.terminated: list[int] = []
        self._next_pid = 42000
        self._running: set[int] = set()
        self.fail_alembic = False

    def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
        _ = cwd, env, timeout
        command = tuple(str(part) for part in cmd)
        self.run_calls.append(command)
        if self.fail_alembic and command[-3:] == ("alembic", "upgrade", "head"):
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="ConnectionResetError: [Errno 54] Connection reset by peer",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def start(self, cmd, *, cwd=None, env=None, stdout_path=None, stderr_path=None):  # noqa: ANN001
        _ = cwd, env, stdout_path, stderr_path
        command = tuple(str(part) for part in cmd)
        self.start_calls.append(command)
        self._next_pid += 1
        self._running.add(self._next_pid)
        return SimpleNamespace(pid=self._next_pid, poll=lambda: None)

    def start_background(self, cmd, *, cwd=None, env=None, stdout_path=None, stderr_path=None):  # noqa: ANN001
        return self.start(
            cmd,
            cwd=cwd,
            env=env,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

    def launch_diagnostics_summary(self) -> dict[str, object]:
        return {
            "tracked_launch_count": len(self.start_calls),
            "active_launch_count": len(self._running),
            "launch_intent_counts": {"background_service": len(self.start_calls)} if self.start_calls else {},
            "controller_input_owners": [],
            "active_controller_input_owners": [],
            "tracked_launches": [],
        }

    def is_pid_running(self, pid: int) -> bool:
        return pid in self._running

    def wait_for_port(self, _port: int, *, host: str = "127.0.0.1", timeout: float = 30.0) -> bool:
        _ = host, timeout
        return False

    def wait_for_pid_port(
        self,
        _pid: int,
        _port: int,
        *,
        host: str = "127.0.0.1",
        timeout: float = 30.0,
        debug_pid_wait_group: str = "",
    ) -> bool:
        _ = host, timeout, debug_pid_wait_group
        return False

    def pid_owns_port(self, pid: int, _port: int) -> bool:
        return pid in self._running

    def terminate(self, pid: int, *, term_timeout: float = 2.0, kill_timeout: float = 1.0) -> bool:
        _ = term_timeout, kill_timeout
        self.terminated.append(pid)
        self._running.discard(pid)
        return True

__all__ = [
    "Path",
    "PYTHON_ROOT",
    "REPO_ROOT",
    "PortPlan",
    "ProjectContext",
    "PythonEngineRuntime",
    "RequirementsResult",
    "RunState",
    "ServiceRecord",
    "SimpleNamespace",
    "StringIO",
    "_NoopPlanner",
    "_OwnershipDenyRunner",
    "_ResumeRestoreRunner",
    "_TrackingPlanner",
    "_TrackingRunner",
    "command_router",
    "config_module",
    "contextmanager",
    "dump_state",
    "json",
    "load_config",
    "models_module",
    "os",
    "parse_route",
    "patch",
    "redirect_stdout",
    "runtime_module",
    "startup_support",
    "state_module",
    "tempfile",
    "threading",
    "time",
    "unittest",
]
