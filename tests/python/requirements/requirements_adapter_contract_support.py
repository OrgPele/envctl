from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.requirements.n8n import start_n8n_container
from envctl_engine.requirements.postgres import start_postgres_container
from envctl_engine.requirements.redis import start_redis_container
from envctl_engine.requirements.supabase import (
    _auth_recreate_probe_attempts,
    _auth_restart_probe_attempts,
    _compose_services_started,
    _compose_timeout_recovered,
    _compose_run,
    _condense_probe_error,
    _probe_supabase_auth_health,
    build_supabase_project_name,
    start_supabase_stack,
)
from envctl_engine.requirements.core.registry import dependency_definition
from envctl_engine.requirements.common import build_container_name


class _FakeRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.wait_for_port_calls: list[tuple[int, float]] = []
        self.wait_for_port_result = True
        self.wait_for_port_overrides: dict[int, bool] = {}
        self.wait_for_port_sequences: dict[int, list[bool]] = {}
        self.sleep_calls: list[float] = []
        self.port_mappings: dict[tuple[str, str], str] = {}
        self.network_port_mappings: dict[tuple[str, str], str | None] = {}
        self.port_mapping_errors: dict[tuple[str, str], str] = {}
        self.existing: set[str] = set()
        self.status: dict[str, str] = {}
        self.health_status: dict[str, str] = {}
        self.exit_code: dict[str, int] = {}
        self.start_returncode: dict[str, int] = {}
        self.start_stderr: dict[str, str] = {}
        self.start_timeout: set[str] = set()
        self.state_error: dict[str, str] = {}
        self.exec_returncode: dict[str, int] = {}
        self.exec_stderr: dict[str, str] = {}
        self.exec_returncode_sequence: dict[str, list[int]] = {}
        self.exec_stderr_sequence: dict[str, list[str]] = {}
        self.run_returncode: dict[str, int] = {}
        self.run_stderr: dict[str, str] = {}
        self.run_returncode_sequence: dict[str, list[int]] = {}
        self.run_stderr_sequence: dict[str, list[str]] = {}
        self.images: set[str] = set()
        self.run_timeout: set[str] = set()
        self.create_returncode: dict[str, int] = {}
        self.create_stderr: dict[str, str] = {}
        self.create_timeout: set[str] = set()
        self.compose_returncode: dict[str, int] = {}
        self.compose_stderr: dict[str, str] = {}
        self.compose_returncode_sequence: dict[str, list[int]] = {}
        self.compose_stderr_sequence: dict[str, list[str]] = {}
        self.compose_ps_json_stdout: dict[str, str] = {}
        self.compose_ps_json_returncode: dict[str, int] = {}
        self.compose_ps_json_stderr: dict[str, str] = {}
        self.compose_ps_q_stdout: dict[str, list[str] | str] = {}
        self.compose_ps_q_returncode: dict[str, int] = {}
        self.compose_ps_q_stderr: dict[str, str] = {}
        self.restart_returncode: dict[str, int] = {}
        self.restart_stderr: dict[str, str] = {}
        self.compose_services_stdout: str = "supabase-db\nsupabase-auth\nsupabase-kong\n"
        self.network_names: list[str] = []
        self.network_container_counts: dict[str, int] = {}
        self.network_rm_returncode: dict[str, int] = {}
        self.network_rm_stderr: dict[str, str] = {}
        self.health_returncode_sequence: list[int] = []
        self.health_stderr_sequence: list[str] = []
        self.health_returncode_by_phase: dict[str, list[int]] = {}
        self.health_stderr_by_phase: dict[str, list[str]] = {}
        self.health_phase = "initial"
        self.health_urls: list[str] = []
        self._time = 0.0

    def run(self, cmd, *, cwd=None, env=None, timeout=None, process_started_callback=None):  # noqa: ANN001
        _ = cwd, env, timeout, process_started_callback
        command = list(cmd)
        self.commands.append(command)

        if command[:3] == ["docker", "ps", "-a"]:
            name_filter = next((item for item in command if item.startswith("name=")), "")
            container = name_filter.replace("name=^/", "").replace("$", "")
            stdout = f"{container}\n" if container in self.existing else ""
            return subprocess.CompletedProcess(command, 0, stdout, "")

        if command[:3] == ["docker", "inspect", "-f"]:
            inspect_format = command[3] if len(command) > 3 else ""
            container = command[-1]
            if "HostConfig.PortBindings" in inspect_format:
                bindings: dict[str, list[dict[str, str]]] = {}
                for (name, port), raw in self.port_mappings.items():
                    if name != container:
                        continue
                    text = str(raw).strip()
                    if not text:
                        continue
                    host_port = text.splitlines()[0].rsplit(":", 1)[-1].strip()
                    bindings[f"{port}/tcp"] = [{"HostIp": "", "HostPort": host_port}]
                return subprocess.CompletedProcess(command, 0, json.dumps(bindings), "")
            if "NetworkSettings.Ports" in inspect_format:
                bindings: dict[str, list[dict[str, str]]] = {}
                keys = set(self.port_mappings) | set(self.network_port_mappings)
                for name, port in keys:
                    if name != container:
                        continue
                    raw = self.network_port_mappings.get((name, port), self.port_mappings.get((name, port)))
                    if raw is None:
                        bindings[f"{port}/tcp"] = []
                        continue
                    text = str(raw).strip()
                    if not text:
                        bindings[f"{port}/tcp"] = []
                        continue
                    host_port = text.splitlines()[0].rsplit(":", 1)[-1].strip()
                    bindings[f"{port}/tcp"] = [{"HostIp": "", "HostPort": host_port}]
                return subprocess.CompletedProcess(command, 0, json.dumps(bindings), "")
            if "json .State" in inspect_format:
                state: dict[str, object] = {
                    "Status": self.status.get(container, "running"),
                    "ExitCode": self.exit_code.get(container, 0),
                    "Error": self.state_error.get(container, ""),
                }
                if container in self.health_status:
                    state["Health"] = {"Status": self.health_status[container]}
                return subprocess.CompletedProcess(command, 0, json.dumps(state), "")
            if ".State.Error" in inspect_format:
                return subprocess.CompletedProcess(command, 0, self.state_error.get(container, "") + "\n", "")
            return subprocess.CompletedProcess(command, 0, self.status.get(container, "running") + "\n", "")

        if command[:2] == ["docker", "port"]:
            container = command[2]
            port = command[3]
            error = self.port_mapping_errors.get((container, port))
            if error is not None:
                return subprocess.CompletedProcess(command, 1, "", error)
            stdout = self.port_mappings.get((container, port), "")
            return subprocess.CompletedProcess(command, 0, stdout, "")

        if command[:3] == ["docker", "network", "ls"]:
            return subprocess.CompletedProcess(
                command, 0, "\n".join(self.network_names) + ("\n" if self.network_names else ""), ""
            )

        if command[:4] == ["docker", "network", "inspect", "-f"]:
            network_name = command[-1]
            count = self.network_container_counts.get(network_name, 0)
            return subprocess.CompletedProcess(command, 0, f"{count}\n", "")

        if command[:3] == ["docker", "network", "rm"]:
            network_name = command[-1]
            rc = self.network_rm_returncode.get(network_name, 0)
            stderr = self.network_rm_stderr.get(network_name, "")
            if rc == 0:
                self.network_names = [name for name in self.network_names if name != network_name]
                self.network_container_counts.pop(network_name, None)
            return subprocess.CompletedProcess(command, rc, network_name + "\n" if rc == 0 else "", stderr)

        if command[:2] == ["docker", "start"]:
            container = command[2]
            if container in self.start_timeout:
                self.existing.add(container)
                if self.state_error.get(container):
                    self.status[container] = "created"
                else:
                    self.status[container] = "running"
                raise subprocess.TimeoutExpired(command, timeout if timeout is not None else 30.0)
            rc = self.start_returncode.get(container, 0)
            stderr = self.start_stderr.get(container, "")
            if rc != 0:
                return subprocess.CompletedProcess(command, rc, "", stderr)
            self.existing.add(container)
            self.status[container] = "running"
            return subprocess.CompletedProcess(command, 0, "", "")

        if command[:2] == ["docker", "restart"]:
            container = command[2]
            rc = self.restart_returncode.get(container, 0)
            stderr = self.restart_stderr.get(container, "")
            if rc == 0:
                self.existing.add(container)
                self.status[container] = "running"
            return subprocess.CompletedProcess(command, rc, "", stderr)

        if command[:2] == ["docker", "stop"]:
            container = command[2]
            self.status[container] = "exited"
            return subprocess.CompletedProcess(command, 0, "", "")

        if command[:3] == ["docker", "rm", "-f"]:
            container = command[3]
            self.existing.discard(container)
            self.status.pop(container, None)
            return subprocess.CompletedProcess(command, 0, "", "")

        if command[:2] == ["docker", "run"]:
            container = command[command.index("--name") + 1]
            if container in self.run_timeout:
                self.existing.add(container)
                self.status[container] = "running"
                raise subprocess.TimeoutExpired(command, timeout if timeout is not None else 60.0)
            sequence = self.run_returncode_sequence.get(container)
            if sequence:
                rc = sequence.pop(0)
            else:
                rc = self.run_returncode.get(container, 0)
            stderr_sequence = self.run_stderr_sequence.get(container)
            if stderr_sequence:
                stderr = stderr_sequence.pop(0)
            else:
                stderr = self.run_stderr.get(container, "")
            if rc == 0:
                self.existing.add(container)
                self.status[container] = "running"
            return subprocess.CompletedProcess(command, rc, "", stderr)

        if command[:2] == ["docker", "create"]:
            container = command[command.index("--name") + 1]
            if container in self.create_timeout:
                self.existing.add(container)
                self.status[container] = "created"
                raise subprocess.TimeoutExpired(command, timeout if timeout is not None else 60.0)
            rc = self.create_returncode.get(container, 0)
            stderr = self.create_stderr.get(container, "")
            if rc == 0:
                self.existing.add(container)
                self.status[container] = "created"
            return subprocess.CompletedProcess(command, rc, "container-id\n" if rc == 0 else "", stderr)

        if command[:3] == ["docker", "image", "inspect"]:
            image = command[3]
            return subprocess.CompletedProcess(
                command,
                0 if image in self.images else 1,
                "image-id\n" if image in self.images else "",
                "" if image in self.images else "No such image\n",
            )

        if command[:2] == ["docker", "pull"]:
            image = command[2]
            rc = self.run_returncode.get(f"pull:{image}", 0)
            stderr = self.run_stderr.get(f"pull:{image}", "")
            if rc == 0:
                self.images.add(image)
            return subprocess.CompletedProcess(command, rc, "pulled\n" if rc == 0 else "", stderr)

        if command[:2] == ["docker", "exec"]:
            container = command[2]
            sequence = self.exec_returncode_sequence.get(container)
            if sequence:
                rc = sequence.pop(0)
            else:
                rc = self.exec_returncode.get(container, 0)
            stderr_sequence = self.exec_stderr_sequence.get(container)
            if stderr_sequence:
                stderr = stderr_sequence.pop(0)
            else:
                stderr = self.exec_stderr.get(container, "")
            return subprocess.CompletedProcess(command, rc, "PONG\n" if rc == 0 else "", stderr)

        if len(command) >= 4 and command[:2] == ["docker", "compose"] and "-f" in command:
            compose_args = command[command.index("-f") + 2 :]
            compose_key = " ".join(compose_args)
            if len(compose_args) >= 4 and compose_args[:3] == ["ps", "--format", "json"]:
                service_name = compose_args[3]
                rc = self.compose_ps_json_returncode.get(
                    service_name,
                    self.compose_ps_q_returncode.get(service_name, 0),
                )
                stderr = self.compose_ps_json_stderr.get(
                    service_name,
                    self.compose_ps_q_stderr.get(service_name, ""),
                )
                if service_name in self.compose_ps_json_stdout:
                    stdout = self.compose_ps_json_stdout[service_name]
                else:
                    container_id = self.compose_ps_q_stdout.get(service_name, f"{service_name}-container-id\n")
                    if isinstance(container_id, list):
                        container_id = container_id[0] if container_id else ""
                    container_id = str(container_id).strip()
                    status = self.status.get(container_id, "running") if container_id else "missing"
                    health = self.health_status.get(container_id)
                    item: dict[str, object] = {
                        "ID": container_id,
                        "Name": container_id,
                        "Service": service_name,
                        "State": status,
                        "Status": status,
                    }
                    if health:
                        item["Health"] = health
                    stdout = json.dumps([item]) if container_id else "[]"
                return subprocess.CompletedProcess(command, rc, stdout if rc == 0 else "", stderr)
            if compose_args[:2] == ["ps", "-q"] and len(compose_args) >= 3:
                service_name = compose_args[2]
                rc = self.compose_ps_q_returncode.get(service_name, 0)
                stderr = self.compose_ps_q_stderr.get(service_name, "")
                configured = self.compose_ps_q_stdout.get(service_name, "")
                if isinstance(configured, list):
                    stdout = configured.pop(0) if configured else ""
                else:
                    stdout = configured
                return subprocess.CompletedProcess(command, rc, stdout if rc == 0 else "", stderr)
            sequence = self.compose_returncode_sequence.get(compose_key)
            if sequence:
                rc = sequence.pop(0)
            else:
                rc = self.compose_returncode.get(compose_key, 0)
            stderr_sequence = self.compose_stderr_sequence.get(compose_key)
            if stderr_sequence:
                stderr = stderr_sequence.pop(0)
            else:
                stderr = self.compose_stderr.get(compose_key, "")
            if rc != 0:
                return subprocess.CompletedProcess(command, rc, "", stderr)
            if compose_args[:1] == ["restart"]:
                self.health_phase = "restart"
            elif compose_args[:2] == ["rm", "-f"] and any(
                "supabase-auth" == item or "auth" == item for item in compose_args
            ):
                self.health_phase = "recreate"
            if "config" in compose_args and "--services" in compose_args:
                return subprocess.CompletedProcess(command, rc, self.compose_services_stdout, stderr)
            return subprocess.CompletedProcess(command, rc, "", stderr)

        if command and command[0] == sys.executable and any("/auth/v1/health" in part for part in command):
            self.health_urls.append(command[-2])
            phase_returncodes = self.health_returncode_by_phase.get(self.health_phase)
            if phase_returncodes:
                rc = phase_returncodes.pop(0)
            elif self.health_phase in self.health_returncode_by_phase:
                rc = 1
            else:
                rc = self.health_returncode_sequence.pop(0) if self.health_returncode_sequence else 0
            phase_stderr = self.health_stderr_by_phase.get(self.health_phase)
            if phase_stderr:
                stderr = phase_stderr.pop(0)
            elif self.health_phase in self.health_stderr_by_phase:
                stderr = "still failing"
            else:
                stderr = self.health_stderr_sequence.pop(0) if self.health_stderr_sequence else ""
            return subprocess.CompletedProcess(command, rc, "", stderr)

        return subprocess.CompletedProcess(command, 0, "", "")

    def wait_for_port(self, port: int, *, host: str = "127.0.0.1", timeout: float = 30.0) -> bool:
        _ = host
        self.wait_for_port_calls.append((port, float(timeout)))
        sequence = self.wait_for_port_sequences.get(port)
        if sequence:
            return sequence.pop(0)
        return self.wait_for_port_overrides.get(port, self.wait_for_port_result)

    def start(self, cmd, *, cwd=None, env=None, stdout_path=None, stderr_path=None):  # noqa: ANN001
        _ = cwd, env, stdout_path, stderr_path
        self.commands.append(list(cmd))
        return _FakeComposeProcess()

    def start_background(self, cmd, *, cwd=None, env=None, stdout_path=None, stderr_path=None):  # noqa: ANN001
        return self.start(cmd, cwd=cwd, env=env, stdout_path=stdout_path, stderr_path=stderr_path)

    def terminate(self, pid: int, *, term_timeout: float, kill_timeout: float) -> bool:
        _ = pid, term_timeout, kill_timeout
        return True

    def terminate_process_group(self, pid: int, *, term_timeout: float, kill_timeout: float) -> bool:
        _ = pid, term_timeout, kill_timeout
        return True

    def is_pid_running(self, pid: int) -> bool:
        _ = pid
        return True

    def wait_for_pid_port(self, pid: int, port: int, *, host: str = "127.0.0.1", timeout: float = 30.0) -> bool:
        _ = pid
        return self.wait_for_port(port, host=host, timeout=timeout)

    def pid_owns_port(self, pid: int, port: int) -> bool:
        _ = pid, port
        return True

    def listener_pids_for_port(self, port: int) -> list[int]:
        _ = port
        return []

    def process_tree_listener_pids(self, root_pid: int, port: int) -> list[int]:
        _ = root_pid, port
        return []

    def find_pid_listener_port(self, pid: int, preferred_port: int, *, max_delta: int = 200) -> int | None:
        _ = pid, max_delta
        return preferred_port

    def supports_process_tree_probe(self) -> bool:
        return False

    def sleep(self, seconds: float) -> None:
        elapsed = float(seconds)
        self.sleep_calls.append(elapsed)
        self._time += max(0.0, elapsed)

    def monotonic(self) -> float:
        return self._time

    def compose_up_process(self, cmd, *, cwd=None, env=None):  # noqa: ANN001
        _ = cwd, env
        self.commands.append(list(cmd))
        compose_args = cmd[cmd.index("-f") + 2 :] if "-f" in cmd else cmd
        compose_key = " ".join(compose_args)
        sequence = self.compose_returncode_sequence.get(compose_key)
        if sequence:
            rc = sequence.pop(0)
        else:
            rc = self.compose_returncode.get(compose_key, 0)
        stderr_sequence = self.compose_stderr_sequence.get(compose_key)
        if stderr_sequence:
            stderr = stderr_sequence.pop(0)
        else:
            stderr = self.compose_stderr.get(compose_key, "")
        return _FakeComposeProcess(returncode=rc, stderr=stderr)


class _FakeComposeProcess:
    def __init__(self, *, returncode: int | None = 0, stdout: str = "", stderr: str = "") -> None:
        self.pid: int | None = 424242
        self._returncode = returncode
        self._terminated = False
        self._stdout = stdout
        self._stderr = stderr

    def poll(self):  # noqa: ANN001
        if self._terminated:
            return self._returncode if self._returncode is not None else -15
        return self._returncode

    def communicate(self, timeout=None):  # noqa: ANN001
        _ = timeout
        self._terminated = True
        return self._stdout, self._stderr


class _FlakyHealthRunner:
    def __init__(self) -> None:
        self.health_returncodes = [1, 0]
        self.run_calls = 0
        self.sleep_calls: list[float] = []

    def wait_for_port(self, port: int, *, host: str = "127.0.0.1", timeout: float = 30.0) -> bool:
        _ = port, host, timeout
        return True

    def run(self, cmd, *, cwd=None, env=None, timeout=None, process_started_callback=None):  # noqa: ANN001
        _ = cwd, env, timeout, process_started_callback
        self.run_calls += 1
        rc = self.health_returncodes.pop(0) if self.health_returncodes else 1
        stderr = "temporary 503" if rc else ""
        return subprocess.CompletedProcess(list(cmd), rc, "", stderr)

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(float(seconds))


__all__ = [
    "json",
    "subprocess",
    "sys",
    "tempfile",
    "Path",
    "mock",
    "start_n8n_container",
    "start_postgres_container",
    "start_redis_container",
    "_auth_recreate_probe_attempts",
    "_auth_restart_probe_attempts",
    "_compose_services_started",
    "_compose_timeout_recovered",
    "_compose_run",
    "_condense_probe_error",
    "_probe_supabase_auth_health",
    "build_supabase_project_name",
    "start_supabase_stack",
    "dependency_definition",
    "build_container_name",
    "_FakeRunner",
    "_FakeComposeProcess",
    "_FlakyHealthRunner",
]
