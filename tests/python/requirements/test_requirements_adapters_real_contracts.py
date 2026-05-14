from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
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

        if command[:2] == ["docker", "pull"]:
            image = command[2]
            rc = self.run_returncode.get(f"pull:{image}", 0)
            stderr = self.run_stderr.get(f"pull:{image}", "")
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


class RequirementsAdaptersRealContractsTests(unittest.TestCase):
    def test_supabase_compose_up_default_timeout_is_120_seconds(self) -> None:
        runner = _FakeRunner()
        captured: dict[str, float] = {}

        def _capture_handoff(**kwargs):  # noqa: ANN001
            captured["timeout_seconds"] = kwargs["timeout_seconds"]
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            compose_path = root / "docker-compose.yml"
            compose_path.write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            with mock.patch("envctl_engine.requirements.supabase._compose_up_handoff", side_effect=_capture_handoff):
                result = _compose_run(
                    process_runner=runner,
                    compose_root=root,
                    compose_project_name="envctl-supabase-test",
                    compose_path=compose_path,
                    env={},
                    args=["up", "-d", "supabase-db"],
                )

        self.assertIsNone(result)
        self.assertEqual(captured["timeout_seconds"], 120.0)

    def test_supabase_auth_health_probe_retries_transient_http_failure(self) -> None:
        runner = _FlakyHealthRunner()

        ready, error = _probe_supabase_auth_health(
            process_runner=runner,
            public_port=54321,
            health_url="http://localhost:54321/auth/v1/health",
            env={"ENVCTL_SUPABASE_AUTH_PROBE_TIMEOUT_SECONDS": "1"},
        )

        self.assertTrue(ready)
        self.assertIsNone(error)
        self.assertEqual(runner.run_calls, 2)
        self.assertTrue(runner.sleep_calls)

    def test_supabase_auth_health_probe_does_not_surface_partial_urllib_traceback(self) -> None:
        class _PartialTracebackRunner:
            def wait_for_port(self, port: int, *, host: str = "127.0.0.1", timeout: float = 30.0) -> bool:
                _ = port, host, timeout
                return True

            def run(self, cmd, *, cwd=None, env=None, timeout=None, process_started_callback=None):  # noqa: ANN001
                _ = cwd, env, timeout, process_started_callback
                return subprocess.CompletedProcess(
                    list(cmd),
                    1,
                    "",
                    "Traceback (most recent call last):\n"
                    '  File "/usr/lib/python3.12/urllib/request.py", line 492, in _call_chain\n',
                )

            def sleep(self, seconds: float) -> None:
                _ = seconds

        ready, error = _probe_supabase_auth_health(
            process_runner=_PartialTracebackRunner(),
            public_port=54321,
            health_url="http://127.0.0.1:54321/auth/v1/health",
            env={"ENVCTL_SUPABASE_AUTH_PROBE_TIMEOUT_SECONDS": "0.5"},
        )

        self.assertFalse(ready)
        self.assertEqual(error, "HTTP health probe failed")
        self.assertNotIn("urllib/request.py", error or "")
        self.assertNotIn('File "', error or "")

    def test_supabase_auth_probe_error_condensing_ignores_traceback_frame_line_numbers(self) -> None:
        raw_error = (
            "ConnectionRefusedError: [Errno 111] Connection refused\n"
            '  File "/usr/lib/python3.12/urllib/request.py", line 492, in _call_chain\n'
        )

        self.assertEqual(
            _condense_probe_error(raw_error),
            "ConnectionRefusedError: [Errno 111] Connection refused",
        )

    def test_supabase_auth_recovery_defaults_allow_multiple_probe_windows(self) -> None:
        self.assertEqual(_auth_restart_probe_attempts({}), 2)
        self.assertEqual(_auth_recreate_probe_attempts({}), 3)

    def test_redis_adopts_existing_port_mapping_without_recreate_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_container_name(
                prefix="envctl-redis",
                project_root=root,
                project_name="Main",
            )
            runner.existing.add(container_name)
            runner.status[container_name] = "exited"
            runner.port_mappings[(container_name, "6379")] = "0.0.0.0:6399\n"

            result = start_redis_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=6380,
                env={},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.effective_port, 6399)
            self.assertTrue(result.port_adopted)
            self.assertTrue(result.container_reused)
            self.assertFalse(result.container_recreated)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container_name for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container_name for cmd in runner.commands)
            create_seen = any(
                cmd[:2] == ["docker", "create"] and "--name" in cmd and container_name in cmd for cmd in runner.commands
            )
            start_seen = any(cmd[:2] == ["docker", "start"] and cmd[-1] == container_name for cmd in runner.commands)
            self.assertFalse(stop_seen)
            self.assertFalse(rm_seen)
            self.assertFalse(create_seen)
            self.assertTrue(start_seen)

    def test_redis_recreates_on_port_mismatch_when_policy_is_recreate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_container_name(
                prefix="envctl-redis",
                project_root=root,
                project_name="Main",
            )
            runner.existing.add(container_name)
            runner.status[container_name] = "exited"
            runner.port_mappings[(container_name, "6379")] = "0.0.0.0:6399\n"

            result = start_redis_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=6380,
                env={"ENVCTL_REQUIREMENTS_PORT_MISMATCH_POLICY": "recreate"},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.effective_port, 6380)
            self.assertFalse(result.port_adopted)
            self.assertFalse(result.container_reused)
            self.assertTrue(result.container_recreated)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container_name for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container_name for cmd in runner.commands)
            create_seen = any(
                cmd[:2] == ["docker", "create"] and "--name" in cmd and container_name in cmd for cmd in runner.commands
            )
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)
            self.assertTrue(create_seen)

    def test_redis_adopted_existing_uses_settle_probe_without_restart_or_recreate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_container_name(
                prefix="envctl-redis",
                project_root=root,
                project_name="Main",
            )
            runner.existing.add(container_name)
            runner.status[container_name] = "running"
            runner.port_mappings[(container_name, "6379")] = "0.0.0.0:6399\n"
            runner.exec_returncode_sequence[container_name] = [1, 0]
            runner.exec_stderr_sequence[container_name] = ["loading", ""]

            result = start_redis_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=6380,
                env={"ENVCTL_REDIS_PROBE_ATTEMPTS": "1", "ENVCTL_REDIS_RESTART_PROBE_ATTEMPTS": "2"},
            )

            self.assertTrue(result.success)
            self.assertTrue(result.port_adopted)
            self.assertFalse(
                any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container_name for cmd in runner.commands)
            )
            self.assertFalse(
                any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container_name for cmd in runner.commands)
            )
            self.assertFalse(
                any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container_name for cmd in runner.commands)
            )

    def test_redis_recreates_adopted_container_when_host_listener_never_appears(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_container_name(
                prefix="envctl-redis",
                project_root=root,
                project_name="Main",
            )
            runner.existing.add(container_name)
            runner.status[container_name] = "running"
            runner.port_mappings[(container_name, "6379")] = "0.0.0.0:6399\n"
            runner.wait_for_port_sequences[6399] = [False, False, False]
            runner.wait_for_port_sequences[6380] = [True]

            result = start_redis_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=6380,
                env={
                    "ENVCTL_REDIS_PROBE_ATTEMPTS": "1",
                    "ENVCTL_REDIS_RESTART_PROBE_ATTEMPTS": "1",
                    "ENVCTL_REDIS_RECREATE_PROBE_ATTEMPTS": "1",
                },
            )

            self.assertTrue(result.success)
            self.assertEqual(result.effective_port, 6380)
            self.assertFalse(result.port_adopted)
            self.assertTrue(result.container_recreated)
            self.assertTrue(
                any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container_name for cmd in runner.commands)
            )
            self.assertTrue(
                any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container_name for cmd in runner.commands)
            )
            self.assertTrue(
                any(
                    cmd[:2] == ["docker", "create"] and "--name" in cmd and container_name in cmd
                    for cmd in runner.commands
                )
            )

    def test_redis_recovers_when_create_times_out_but_container_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_container_name(
                prefix="envctl-redis",
                project_root=root,
                project_name="Main",
            )
            runner.create_timeout.add(container_name)
            runner.port_mappings[(container_name, "6379")] = "0.0.0.0:6380\n"

            result = start_redis_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=6380,
                env={},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.effective_port, 6380)
            self.assertFalse(result.container_recreated)

    def test_redis_recovered_create_uses_settle_probe_without_restart_or_recreate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_container_name(
                prefix="envctl-redis",
                project_root=root,
                project_name="Main",
            )
            runner.create_timeout.add(container_name)
            runner.port_mappings[(container_name, "6379")] = "0.0.0.0:6380\n"
            runner.exec_returncode_sequence[container_name] = [1, 0]
            runner.exec_stderr_sequence[container_name] = ["loading", ""]

            result = start_redis_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=6380,
                env={"ENVCTL_REDIS_PROBE_ATTEMPTS": "1", "ENVCTL_REDIS_RESTART_PROBE_ATTEMPTS": "2"},
            )

            self.assertTrue(result.success)
            self.assertFalse(
                any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container_name for cmd in runner.commands)
            )
            self.assertFalse(
                any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container_name for cmd in runner.commands)
            )

    def test_n8n_recovers_when_recreate_times_out_but_container_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_container_name(
                prefix="envctl-n8n",
                project_root=root,
                project_name="Main",
            )
            runner.create_timeout.add(container_name)
            runner.port_mappings[(container_name, "5678")] = "0.0.0.0:5680\n"
            runner.wait_for_port_sequences[5680] = [False, False, True]

            result = start_n8n_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=5680,
                env={},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.effective_port, 5680)

    def test_n8n_uses_configured_image_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()

            result = start_n8n_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=5680,
                env={"ENVCTL_N8N_IMAGE": "n8nio/n8n:1.0.0"},
            )

            self.assertTrue(result.success)
            create_commands = [cmd for cmd in runner.commands if cmd[:2] == ["docker", "create"]]
            self.assertTrue(create_commands)
            self.assertEqual(create_commands[0][-1], "n8nio/n8n:1.0.0")

    def test_n8n_pulls_image_before_create_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()

            result = start_n8n_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=5680,
                env={},
            )

            self.assertTrue(result.success)
            pull_index = next(i for i, cmd in enumerate(runner.commands) if cmd[:2] == ["docker", "pull"])
            create_index = next(i for i, cmd in enumerate(runner.commands) if cmd[:2] == ["docker", "create"])
            self.assertLess(pull_index, create_index)

    def test_n8n_can_skip_image_pull(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()

            result = start_n8n_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=5680,
                env={"ENVCTL_N8N_PULL_IMAGE": "false"},
            )

            self.assertTrue(result.success)
            self.assertFalse(any(cmd[:2] == ["docker", "pull"] for cmd in runner.commands))

    def test_n8n_adopted_existing_uses_settle_listener_without_restart_or_recreate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_container_name(
                prefix="envctl-n8n",
                project_root=root,
                project_name="Main",
            )
            runner.existing.add(container_name)
            runner.status[container_name] = "running"
            runner.port_mappings[(container_name, "5678")] = "0.0.0.0:5681\n"
            runner.wait_for_port_sequences[5681] = [False, True]

            result = start_n8n_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=5680,
                env={},
            )

            self.assertTrue(result.success)
            self.assertTrue(result.port_adopted)
            self.assertEqual(result.effective_port, 5681)
            self.assertFalse(
                any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container_name for cmd in runner.commands)
            )
            self.assertFalse(
                any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container_name for cmd in runner.commands)
            )
            self.assertFalse(
                any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container_name for cmd in runner.commands)
            )

    def test_n8n_recovered_create_uses_settle_listener_without_restart_or_recreate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_container_name(
                prefix="envctl-n8n",
                project_root=root,
                project_name="Main",
            )
            runner.create_timeout.add(container_name)
            runner.port_mappings[(container_name, "5678")] = "0.0.0.0:5680\n"
            runner.wait_for_port_sequences[5680] = [False, True]

            result = start_n8n_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=5680,
                env={},
            )

            self.assertTrue(result.success)
            self.assertFalse(
                any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container_name for cmd in runner.commands)
            )
            self.assertFalse(
                any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container_name for cmd in runner.commands)
            )
            self.assertFalse(
                any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container_name for cmd in runner.commands)
            )

    def test_supabase_stack_starts_compose_services_and_waits_for_db_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")

            runner = _FakeRunner()
            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_TWO_PHASE_STARTUP": "false"},
            )
            self.assertTrue(result.success)
            compose_project = build_supabase_project_name(project_root=root, project_name="feature-a-1")
            self.assertEqual(result.container_name, compose_project)
            self.assertTrue(
                any(
                    cmd[:5] == ["docker", "compose", "-p", compose_project, "-f"] and "config" in cmd
                    for cmd in runner.commands
                )
            )
            self.assertTrue(
                any(
                    cmd[:5] == ["docker", "compose", "-p", compose_project, "-f"]
                    and cmd[-5:] == ["up", "-d", "supabase-db", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )

    def test_supabase_stack_recovers_address_pool_exhaustion_by_removing_empty_envctl_supabase_networks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_returncode_sequence["up -d supabase-db supabase-auth supabase-kong"] = [1, 0]
            runner.compose_stderr_sequence["up -d supabase-db supabase-auth supabase-kong"] = [
                "Error response from daemon: all predefined address pools have been fully subnetted",
                "",
            ]
            runner.network_names = [
                "envctl-supabase-main-deadbeef_default",
                "envctl-supabase-main-deadbeef_supabase-net",
                "envctl-redis-main-deadbeef_default",
                "bridge",
                "envctl-supabase-active_supabase-net",
            ]
            runner.network_container_counts = {
                "envctl-supabase-active_supabase-net": 1,
            }

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_TWO_PHASE_STARTUP": "false"},
            )

            self.assertTrue(result.success)
            graph_ups = [
                cmd
                for cmd in runner.commands
                if cmd[:2] == ["docker", "compose"]
                and cmd[-5:] == ["up", "-d", "supabase-db", "supabase-auth", "supabase-kong"]
            ]
            self.assertEqual(len(graph_ups), 2)
            removed_networks = [cmd[-1] for cmd in runner.commands if cmd[:3] == ["docker", "network", "rm"]]
            self.assertEqual(
                removed_networks,
                [
                    "envctl-supabase-main-deadbeef_default",
                    "envctl-supabase-main-deadbeef_supabase-net",
                ],
            )
            self.assertNotIn("envctl-redis-main-deadbeef_default", removed_networks)
            self.assertNotIn("envctl-supabase-active_supabase-net", removed_networks)

    def test_supabase_stack_recovers_missing_network_during_db_up_with_scoped_compose_down(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_returncode_sequence["up -d supabase-db supabase-auth supabase-kong"] = [1, 0]
            runner.compose_stderr_sequence["up -d supabase-db supabase-auth supabase-kong"] = [
                "failed to set up container networking: network 3b2e1a0f9d8c not found",
                "",
            ]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
            )

            self.assertTrue(result.success)
            compose_project = build_supabase_project_name(project_root=root, project_name="feature-a-1")
            graph_ups = [
                cmd
                for cmd in runner.commands
                if cmd[:2] == ["docker", "compose"]
                and cmd[-5:] == ["up", "-d", "supabase-db", "supabase-auth", "supabase-kong"]
            ]
            self.assertEqual(len(graph_ups), 2)
            self.assertTrue(
                any(
                    cmd[:5] == ["docker", "compose", "-p", compose_project, "-f"]
                    and cmd[-2:] == ["down", "--remove-orphans"]
                    for cmd in runner.commands
                )
            )
            network_events = [
                item for item in result.stage_events or [] if item.get("stage") == "supabase.compose.network_recovery"
            ]
            self.assertTrue(network_events)
            self.assertIn("compose_down_remove_orphans", str(network_events[-1].get("detail", "")))
            self.assertFalse(any(cmd[:3] == ["docker", "network", "rm"] for cmd in runner.commands))

    def test_supabase_stack_recovers_missing_network_during_secondary_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_returncode_sequence["up -d supabase-db supabase-auth supabase-kong"] = [1, 0]
            runner.compose_stderr_sequence["up -d supabase-db supabase-auth supabase-kong"] = [
                "failed to set up container networking: network 0123456789abcdef not found",
                "",
            ]
            runner.wait_for_port_overrides[5432] = True
            runner.wait_for_port_overrides[54321] = True

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
            )

            self.assertTrue(result.success)
            graph_ups = [
                cmd
                for cmd in runner.commands
                if cmd[:2] == ["docker", "compose"]
                and cmd[-5:] == ["up", "-d", "supabase-db", "supabase-auth", "supabase-kong"]
            ]
            self.assertEqual(len(graph_ups), 2)
            self.assertTrue(any(cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["down", "--remove-orphans"] for cmd in runner.commands))

    def test_supabase_missing_network_recovery_does_not_remove_other_worktree_or_non_empty_networks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            compose_project = build_supabase_project_name(project_root=root, project_name="feature-a-1")
            runner = _FakeRunner()
            runner.compose_returncode_sequence["up -d supabase-db supabase-auth supabase-kong"] = [1, 0]
            runner.compose_stderr_sequence["up -d supabase-db supabase-auth supabase-kong"] = [
                "Error response from daemon: failed to set up container networking: network 0123456789ab not found",
                "",
            ]
            runner.compose_returncode["down --remove-orphans"] = 1
            runner.compose_stderr["down --remove-orphans"] = "compose down failed"
            runner.network_names = [
                f"{compose_project}_default",
                f"{compose_project}_supabase-net",
                f"{compose_project}_other",
                f"{compose_project}_supabase-net_nonempty",
                "envctl-supabase-otherworktree_default",
                "envctl-redis-main-deadbeef_default",
                "bridge",
            ]
            runner.network_container_counts = {
                f"{compose_project}_supabase-net_nonempty": 2,
                "envctl-supabase-otherworktree_default": 0,
            }

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
            )

            self.assertTrue(result.success)
            removed_networks = [cmd[-1] for cmd in runner.commands if cmd[:3] == ["docker", "network", "rm"]]
            self.assertEqual(removed_networks, [f"{compose_project}_default", f"{compose_project}_supabase-net"])
            self.assertNotIn(f"{compose_project}_supabase-net_nonempty", removed_networks)
            self.assertNotIn("envctl-supabase-otherworktree_default", removed_networks)
            self.assertNotIn("envctl-redis-main-deadbeef_default", removed_networks)

    def test_supabase_missing_network_recovery_reports_exhausted_scoped_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_returncode_sequence["up -d supabase-db supabase-auth supabase-kong"] = [1, 1]
            runner.compose_stderr_sequence["up -d supabase-db supabase-auth supabase-kong"] = [
                "failed to set up container networking: network 0123456789ab not found",
                "still missing network",
            ]
            runner.compose_returncode["down --remove-orphans"] = 1
            runner.compose_stderr["down --remove-orphans"] = "compose down failed"

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
            )

            self.assertFalse(result.success)
            self.assertIn("scoped Supabase network recovery", result.error or "")
            self.assertIn("compose_down_error=compose down failed", result.error or "")
            self.assertIn("still missing network", result.error or "")
            self.assertIn(build_supabase_project_name(project_root=root, project_name="feature-a-1"), result.error or "")

    def test_supabase_stack_records_db_probe_stage_when_db_becomes_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_overrides[5432] = True
            runner.wait_for_port_overrides[54321] = True

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
            )

            self.assertTrue(result.success)
            db_probe_events = [
                item for item in result.stage_events or [] if item.get("stage") == "supabase.db.probe"
            ]
            self.assertTrue(db_probe_events)
            self.assertEqual(db_probe_events[-1].get("reason"), "ready")
            self.assertIn("port=5432", str(db_probe_events[-1].get("detail", "")))

    def test_supabase_stack_records_db_probe_stage_when_db_probe_exhausts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [False, False]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_DB_RESTART_ON_PROBE_FAILURE": "false"},
            )

            self.assertFalse(result.success)
            db_probe_events = [
                item for item in result.stage_events or [] if item.get("stage") == "supabase.db.probe"
            ]
            self.assertTrue(db_probe_events)
            self.assertEqual(db_probe_events[-1].get("reason"), "failed")
            self.assertIn("attempts=2", str(db_probe_events[-1].get("detail", "")))

    def test_supabase_stack_fails_when_auth_kong_health_unreachable_after_db_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_overrides[5432] = True
            runner.wait_for_port_overrides[54321] = False
            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_TWO_PHASE_STARTUP": "false"},
            )

            self.assertFalse(result.success)
            self.assertIn("Supabase DB is healthy but Supabase Auth/Kong is not reachable", result.error or "")
            self.assertIn("http://127.0.0.1:54321/auth/v1/health", result.error or "")
            self.assertIn("probe_url=http://127.0.0.1:54321/auth/v1/health", result.error or "")
            self.assertIn("actions=initial_probe,restart,recreate", result.error or "")
            self.assertNotIn("Traceback", result.error or "")
            self.assertNotIn('File "', result.error or "")
            self.assertTrue(
                any(
                    cmd[:2] == ["docker", "compose"]
                    and cmd[-3:] == ["restart", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )
            self.assertTrue(
                any(
                    cmd[:2] == ["docker", "compose"]
                    and cmd[-4:] == ["rm", "-f", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )

    def test_supabase_auth_kong_failure_records_service_inspection_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_overrides[5432] = True
            runner.wait_for_port_overrides[54321] = False
            runner.compose_ps_q_stdout["supabase-auth"] = "auth-container-id\n"
            runner.compose_ps_q_stdout["supabase-kong"] = "kong-container-id\n"
            runner.status["auth-container-id"] = "exited"
            runner.status["kong-container-id"] = "running"
            runner.health_status["kong-container-id"] = "starting"
            runner.state_error["auth-container-id"] = (
                "Traceback (most recent call last):\n"
                '  File "/app/auth.py", line 12, in boot\n'
                "SERVICE_ROLE_KEY=should-not-leak crashed"
            )

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_AUTH_RECREATE_PROBE_ATTEMPTS": "1"},
            )

            self.assertFalse(result.success)
            inspect_events = [
                item for item in result.stage_events or [] if item.get("stage") == "supabase.auth.inspect"
            ]
            self.assertGreaterEqual(len(inspect_events), 2)
            inspect_detail = " ".join(str(item.get("detail", "")) for item in inspect_events)
            self.assertIn("supabase-auth", inspect_detail)
            self.assertIn("status=exited", inspect_detail)
            self.assertIn("supabase-kong", inspect_detail)
            self.assertIn("status=running", inspect_detail)
            self.assertIn("health=starting", inspect_detail)
            self.assertIn("service_state=", result.error or "")
            self.assertIn("supabase-auth", result.error or "")
            self.assertIn("status=exited", result.error or "")
            self.assertIn("health=starting", result.error or "")
            self.assertNotIn("SERVICE_ROLE_KEY", result.error or "")
            self.assertNotIn("should-not-leak", result.error or "")
            self.assertNotIn("Traceback", result.error or "")
            self.assertNotIn('File "', result.error or "")

    def test_supabase_auth_kong_inspect_failure_is_summarized_without_blocking_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [True]
            runner.wait_for_port_sequences[54321] = [False, True]
            runner.compose_ps_q_returncode["supabase-auth"] = 1
            runner.compose_ps_q_stderr["supabase-auth"] = "compose ps failed"

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_AUTH_RESTART_PROBE_ATTEMPTS": "1"},
            )

            self.assertTrue(result.success)
            inspect_events = [
                item for item in result.stage_events or [] if item.get("stage") == "supabase.auth.inspect"
            ]
            self.assertTrue(inspect_events)
            inspect_detail = " ".join(str(item.get("detail", "")) for item in inspect_events)
            self.assertIn("inspect_error", inspect_detail)
            self.assertTrue(
                any(
                    cmd[:2] == ["docker", "compose"]
                    and cmd[-3:] == ["restart", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )

    def test_supabase_auth_kong_restart_recovers_when_service_state_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [True]
            runner.wait_for_port_sequences[54321] = [False, True]
            runner.compose_ps_q_stdout["supabase-auth"] = "auth-container-id\n"
            runner.compose_ps_q_stdout["supabase-kong"] = "kong-container-id\n"
            runner.status["auth-container-id"] = "exited"
            runner.status["kong-container-id"] = "running"

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_AUTH_RESTART_PROBE_ATTEMPTS": "1"},
            )

            self.assertTrue(result.success)
            self.assertFalse(result.container_recreated)
            self.assertTrue(
                any(
                    cmd[:2] == ["docker", "compose"]
                    and cmd[-3:] == ["restart", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )
            self.assertFalse(
                any(
                    cmd[:2] == ["docker", "compose"]
                    and cmd[-4:] == ["rm", "-f", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )

    def test_supabase_auth_kong_recreate_recovers_when_http_health_appears_late(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_overrides[5432] = True
            runner.wait_for_port_overrides[54321] = True
            runner.health_returncode_by_phase = {"initial": [1], "restart": [1], "recreate": [0]}
            runner.health_stderr_by_phase = {
                "initial": [
                    "Traceback (most recent call last):\n"
                    "ConnectionRefusedError: [Errno 111] Connection refused"
                ],
                "restart": ["temporary 503"],
                "recreate": [""],
            }

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={
                    "ENVCTL_SUPABASE_AUTH_PROBE_TIMEOUT_SECONDS": "0.5",
                    "ENVCTL_SUPABASE_AUTH_RESTART_PROBE_ATTEMPTS": "1",
                    "ENVCTL_SUPABASE_AUTH_RECREATE_PROBE_ATTEMPTS": "1",
                },
            )

            self.assertTrue(result.success)
            self.assertTrue(result.container_recreated)
            self.assertTrue(
                any(
                    cmd[:2] == ["docker", "compose"]
                    and cmd[-4:] == ["rm", "-f", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )

    def test_supabase_auth_kong_recovery_does_not_recreate_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_overrides[5432] = True
            runner.wait_for_port_overrides[54321] = False

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_AUTH_RECREATE_PROBE_ATTEMPTS": "1"},
            )

            self.assertFalse(result.success)
            self.assertFalse(
                any(cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["stop", "supabase-db"] for cmd in runner.commands)
            )
            self.assertFalse(
                any(
                    cmd[:2] == ["docker", "compose"] and cmd[-3:] == ["rm", "-f", "supabase-db"]
                    for cmd in runner.commands
                )
            )

    def test_supabase_auth_probe_uses_local_loopback_when_public_url_is_remote(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_overrides[5432] = True
            runner.wait_for_port_overrides[54398] = True

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54398,
                env={"SUPABASE_PUBLIC_URL": "http://72.61.80.25:54398"},
            )

            self.assertTrue(result.success)
            self.assertEqual(runner.health_urls, ["http://127.0.0.1:54398/auth/v1/health"])

    def test_supabase_auth_recovery_respects_restart_and_recreate_env_toggles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_overrides[5432] = True
            runner.wait_for_port_overrides[54321] = False

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={
                    "ENVCTL_SUPABASE_AUTH_RESTART_ON_PROBE_FAILURE": "false",
                    "ENVCTL_SUPABASE_AUTH_RECREATE_ON_PROBE_FAILURE": "false",
                    "ENVCTL_SUPABASE_AUTH_RESTART_PROBE_ATTEMPTS": "0",
                    "ENVCTL_SUPABASE_AUTH_RECREATE_PROBE_ATTEMPTS": "0",
                },
            )

            self.assertFalse(result.success)
            self.assertNotIn("restart", result.error or "")
            self.assertNotIn("recreate", result.error or "")
            self.assertFalse(any(cmd[:2] == ["docker", "compose"] and "restart" in cmd for cmd in runner.commands))
            self.assertFalse(any(cmd[:2] == ["docker", "compose"] and "rm" in cmd for cmd in runner.commands))

    def test_supabase_stack_starts_full_graph_before_auth_health_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")

            runner = _FakeRunner()
            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
            )

            self.assertTrue(result.success)
            graph_ups = [
                cmd
                for cmd in runner.commands
                if cmd[:2] == ["docker", "compose"]
                and cmd[-5:] == ["up", "-d", "supabase-db", "supabase-auth", "supabase-kong"]
            ]
            self.assertEqual(len(graph_ups), 1)
            self.assertFalse(
                any(
                    cmd[:2] == ["docker", "compose"] and cmd[-4:] == ["up", "-d", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )
            stage_names = [str(item.get("stage", "")) for item in result.stage_events or []]
            self.assertIn("supabase.graph.up", stage_names)
            self.assertIn("supabase.db.probe", stage_names)
            self.assertIn("supabase.auth.probe", stage_names)

    def test_supabase_graph_startup_does_not_fail_when_auth_kong_progress_past_old_compose_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_ps_q_stdout["supabase-db"] = "db-container-id\n"
            runner.compose_ps_q_stdout["supabase-auth"] = "auth-container-id\n"
            runner.compose_ps_q_stdout["supabase-kong"] = "kong-container-id\n"
            runner.status["db-container-id"] = "running"
            runner.status["auth-container-id"] = "running"
            runner.status["kong-container-id"] = "created"
            runner.wait_for_port_overrides[5432] = True
            runner.wait_for_port_overrides[54321] = True
            runner.health_returncode_sequence = [0]

            def _hung_graph(cmd, *, cwd=None, env=None):  # noqa: ANN001
                _ = cwd, env
                runner.commands.append(list(cmd))
                return _FakeComposeProcess(returncode=None)

            runner.compose_up_process = _hung_graph  # type: ignore[method-assign]

            with mock.patch("envctl_engine.requirements.supabase.os.killpg", side_effect=OSError()):
                result = start_supabase_stack(
                    process_runner=runner,
                    project_root=root,
                    project_name="feature-a-1",
                    db_port=5432,
                    public_port=54321,
                )

            self.assertTrue(result.success)
            self.assertTrue(
                any(
                    cmd[:2] == ["docker", "compose"]
                    and cmd[-5:] == ["up", "-d", "supabase-db", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )
            self.assertEqual(runner.health_urls, ["http://127.0.0.1:54321/auth/v1/health"])

    def test_supabase_compose_handoff_does_not_treat_created_service_as_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            compose_path = supabase_dir / "docker-compose.yml"
            compose_path.write_text("services:\n  supabase-auth: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_ps_q_stdout["supabase-auth"] = "auth-container-id\n"
            runner.status["auth-container-id"] = "created"

            ready = _compose_services_started(
                process_runner=runner,
                compose_root=supabase_dir,
                compose_project_name="envctl-supabase-test",
                compose_path=compose_path,
                env={},
                service_names=["supabase-auth"],
            )

            self.assertFalse(ready)

    def test_supabase_timeout_recovery_for_auth_kong_requires_running_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            compose_path = supabase_dir / "docker-compose.yml"
            compose_path.write_text("services:\n  supabase-auth: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_ps_q_stdout["supabase-auth"] = "auth-container-id\n"
            runner.status["auth-container-id"] = "created"

            created_recovered = _compose_timeout_recovered(
                process_runner=runner,
                compose_root=supabase_dir,
                compose_project_name="envctl-supabase-test",
                compose_path=compose_path,
                env={},
                service_name="supabase-auth",
                probe_port=None,
                error="Command timed out after 45.0s: docker compose up -d supabase-auth supabase-kong",
            )
            runner.status["auth-container-id"] = "running"
            running_recovered = _compose_timeout_recovered(
                process_runner=runner,
                compose_root=supabase_dir,
                compose_project_name="envctl-supabase-test",
                compose_path=compose_path,
                env={},
                service_name="supabase-auth",
                probe_port=None,
                error="Command timed out after 45.0s: docker compose up -d supabase-auth supabase-kong",
            )

            self.assertFalse(created_recovered)
            self.assertTrue(running_recovered)

    def test_supabase_graph_startup_failure_reports_phase_timeout_port_and_service_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_returncode["up -d supabase-db supabase-auth supabase-kong"] = 1
            runner.compose_stderr["up -d supabase-db supabase-auth supabase-kong"] = "Container supabase-kong-1 Starting"
            runner.compose_ps_q_stdout["supabase-db"] = "db-container-id\n"
            runner.compose_ps_q_stdout["supabase-auth"] = "auth-container-id\n"
            runner.compose_ps_q_stdout["supabase-kong"] = "kong-container-id\n"
            runner.status["db-container-id"] = "running"
            runner.status["auth-container-id"] = "running"
            runner.status["kong-container-id"] = "created"

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_COMPOSE_UP_TIMEOUT_SECONDS": "45"},
            )

            self.assertFalse(result.success)
            self.assertIn("phase=compose_graph", result.error or "")
            self.assertIn("compose_timeout_s=45", result.error or "")
            self.assertIn("public_port=54321", result.error or "")
            self.assertIn("probe_url=http://127.0.0.1:54321/auth/v1/health", result.error or "")
            self.assertIn("supabase-kong", result.error or "")
            self.assertIn("status=created", result.error or "")
            self.assertIn("last_error=Container supabase-kong-1 Starting", result.error or "")
            self.assertIn("startup_budget_s=120", result.error or "")
            self.assertIn("elapsed_ms=", result.error or "")

    def test_supabase_compose_timeout_override_does_not_exceed_overall_startup_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [True]
            runner.wait_for_port_sequences[54321] = [True]
            runner.health_returncode_sequence = [0]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={
                    "ENVCTL_SUPABASE_STARTUP_TIMEOUT_SECONDS": "1",
                    "ENVCTL_SUPABASE_COMPOSE_UP_TIMEOUT_SECONDS": "45",
                },
            )

            self.assertTrue(result.success)
            graph_event = next(
                item for item in result.stage_events or [] if item.get("stage") == "supabase.graph.up"
            )
            self.assertEqual(graph_event.get("timeout_s"), 1.0)
            self.assertEqual(graph_event.get("startup_budget_s"), 1.0)

    def test_supabase_auth_progress_waits_without_restart_when_public_health_appears_late(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [True]
            runner.wait_for_port_sequences[54321] = [False, True]
            runner.compose_ps_q_stdout["supabase-auth"] = "auth-container-id\n"
            runner.compose_ps_q_stdout["supabase-kong"] = "kong-container-id\n"
            runner.status["auth-container-id"] = "running"
            runner.status["kong-container-id"] = "running"
            runner.health_status["auth-container-id"] = "starting"
            runner.health_status["kong-container-id"] = "starting"
            runner.health_returncode_sequence = [0]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={
                    "ENVCTL_SUPABASE_STARTUP_TIMEOUT_SECONDS": "5",
                    "ENVCTL_SUPABASE_AUTH_PROBE_TIMEOUT_SECONDS": "0.5",
                },
            )

            self.assertTrue(result.success)
            self.assertFalse(
                any(
                    cmd[:2] == ["docker", "compose"]
                    and cmd[-3:] == ["restart", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )
            self.assertFalse(
                any(
                    cmd[:2] == ["docker", "compose"]
                    and cmd[-4:] == ["rm", "-f", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )
            self.assertTrue(
                any(item.get("stage") == "supabase.auth.wait_progress" for item in result.stage_events or [])
            )

    def test_supabase_db_probe_failure_reports_phase_budget_elapsed_and_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [False, False]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={
                    "ENVCTL_SUPABASE_DB_RESTART_ON_PROBE_FAILURE": "false",
                    "ENVCTL_SUPABASE_DB_PROBE_TIMEOUT_SECONDS": "0.5",
                    "ENVCTL_SUPABASE_STARTUP_TIMEOUT_SECONDS": "5",
                },
            )

            self.assertFalse(result.success)
            self.assertIn("phase=db_probe", result.error or "")
            self.assertIn("db_port=5432", result.error or "")
            self.assertIn("db_probe_timeout_s=0.5", result.error or "")
            self.assertIn("attempts=2", result.error or "")
            self.assertIn("startup_budget_s=5", result.error or "")
            self.assertIn("elapsed_ms=", result.error or "")
            self.assertIn("last_error=probe timeout waiting for readiness on port 5432 after retry", result.error or "")

    def test_supabase_auth_health_failure_reports_auth_phase_budget_elapsed_and_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [True]
            runner.wait_for_port_overrides[54321] = False
            runner.compose_ps_q_stdout["supabase-auth"] = "auth-container-id\n"
            runner.compose_ps_q_stdout["supabase-kong"] = "kong-container-id\n"
            runner.status["auth-container-id"] = "running"
            runner.status["kong-container-id"] = "running"
            runner.health_status["auth-container-id"] = "starting"
            runner.health_status["kong-container-id"] = "starting"

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={
                    "ENVCTL_SUPABASE_STARTUP_TIMEOUT_SECONDS": "1",
                    "ENVCTL_SUPABASE_AUTH_PROBE_TIMEOUT_SECONDS": "0.5",
                    "ENVCTL_SUPABASE_AUTH_RESTART_ON_PROBE_FAILURE": "false",
                    "ENVCTL_SUPABASE_AUTH_RECREATE_ON_PROBE_FAILURE": "false",
                },
            )

            self.assertFalse(result.success)
            self.assertIn("phase=auth_health", result.error or "")
            self.assertIn("public_port=54321", result.error or "")
            self.assertIn("probe_url=http://127.0.0.1:54321/auth/v1/health", result.error or "")
            self.assertIn("auth_probe_timeout_s=0.5", result.error or "")
            self.assertIn("startup_budget_s=1", result.error or "")
            self.assertIn("elapsed_ms=", result.error or "")
            self.assertIn("service_state=", result.error or "")
            self.assertIn("health=starting", result.error or "")
            self.assertIn("last_error=listener probe failed on port 54321", result.error or "")

    def test_supabase_recovers_when_initial_up_times_out_but_service_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_services_stdout = "supabase-db\n"
            runner.compose_ps_q_stdout["supabase-db"] = ["abc123\n", "abc123\n"]
            runner.wait_for_port_result = True

            def _hung_compose(cmd, *, cwd=None, env=None):  # noqa: ANN001
                _ = cwd, env
                runner.commands.append(list(cmd))
                return _FakeComposeProcess(returncode=None)

            runner.compose_up_process = _hung_compose  # type: ignore[method-assign]

            with mock.patch("envctl_engine.requirements.supabase.os.killpg", side_effect=OSError()):
                result = start_supabase_stack(
                    process_runner=runner,
                    project_root=root,
                    project_name="feature-a-1",
                    db_port=5432,
                )

            self.assertTrue(result.success)

    def test_supabase_timeout_recovery_skips_repeated_db_up_when_service_already_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_services_stdout = "supabase-db\n"
            runner.compose_ps_q_stdout["supabase-db"] = ["", "abc123\n", "abc123\n"]
            runner.wait_for_port_sequences[5432] = [False, True]

            def _hung_compose(cmd, *, cwd=None, env=None):  # noqa: ANN001
                _ = cwd, env
                runner.commands.append(list(cmd))
                return _FakeComposeProcess(returncode=None)

            runner.compose_up_process = _hung_compose  # type: ignore[method-assign]

            with mock.patch("envctl_engine.requirements.supabase.os.killpg", side_effect=OSError()):
                result = start_supabase_stack(
                    process_runner=runner,
                    project_root=root,
                    project_name="feature-a-1",
                    db_port=5432,
                )

            self.assertTrue(result.success)
            db_ups = [
                cmd for cmd in runner.commands if cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["-d", "supabase-db"]
            ]
            self.assertEqual(len(db_ups), 1)

    def test_supabase_handoffs_when_compose_cli_hangs_after_db_is_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_services_stdout = "supabase-db\n"
            runner.compose_ps_q_stdout["supabase-db"] = ["", "abc123\n", "abc123\n"]
            runner.wait_for_port_sequences[5432] = [False, True]

            def _hung_compose(cmd, *, cwd=None, env=None):  # noqa: ANN001
                _ = cwd, env
                runner.commands.append(list(cmd))
                return _FakeComposeProcess(returncode=None)

            runner.compose_up_process = _hung_compose  # type: ignore[method-assign]

            with mock.patch("envctl_engine.requirements.supabase.os.killpg", side_effect=OSError()):
                result = start_supabase_stack(
                    process_runner=runner,
                    project_root=root,
                    project_name="feature-a-1",
                    db_port=5432,
                )

            self.assertTrue(result.success)
            db_ups = [
                cmd for cmd in runner.commands if cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["-d", "supabase-db"]
            ]
            self.assertEqual(len(db_ups), 1)
            self.assertTrue(any(cmd[-4:] == ["ps", "--format", "json", "supabase-db"] for cmd in runner.commands))

    def test_supabase_stack_uses_discovered_alternative_service_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text(
                "services:\n  db: {}\n  auth: {}\n  kong: {}\n", encoding="utf-8"
            )

            runner = _FakeRunner()
            runner.compose_services_stdout = "db\nauth\nkong\n"

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
            )
            self.assertTrue(result.success)
            compose_project = build_supabase_project_name(project_root=root, project_name="feature-a-1")
            self.assertTrue(
                any(
                    cmd[:5] == ["docker", "compose", "-p", compose_project, "-f"]
                    and cmd[-5:] == ["up", "-d", "db", "auth", "kong"]
                    for cmd in runner.commands
                )
            )

    def test_supabase_stack_fails_when_compose_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result = start_supabase_stack(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                db_port=5432,
            )
            self.assertFalse(result.success)
            self.assertIn("missing supabase compose file", result.error or "")

    def test_supabase_stack_retries_db_bringup_when_initial_probe_times_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [False, True]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
            )
            self.assertTrue(result.success)
            graph_ups = [
                cmd
                for cmd in runner.commands
                if cmd[:2] == ["docker", "compose"]
                and cmd[-5:] == ["up", "-d", "supabase-db", "supabase-auth", "supabase-kong"]
            ]
            db_retry_ups = [
                cmd for cmd in runner.commands if cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["-d", "supabase-db"]
            ]
            self.assertEqual(len(graph_ups), 1)
            self.assertGreaterEqual(len(db_retry_ups), 1)

    def test_supabase_stack_fails_after_db_probe_retry_exhausted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [False, False]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                env={"ENVCTL_SUPABASE_DB_RESTART_ON_PROBE_FAILURE": "false"},
            )
            self.assertFalse(result.success)
            self.assertIn("after retry", result.error or "")

    def test_supabase_stack_restarts_db_after_probe_exhaustion_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [False, False, True]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
            )
            self.assertTrue(result.success)
            restart_seen = any(
                cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["restart", "supabase-db"] for cmd in runner.commands
            )
            self.assertTrue(restart_seen)

    def test_supabase_stack_reports_restart_failure_when_restart_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [False, False]
            runner.compose_returncode["restart supabase-db"] = 1
            runner.compose_stderr["restart supabase-db"] = "restart failed"

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
            )
            self.assertFalse(result.success)
            self.assertIn("failed restarting supabase db service", result.error or "")

    def test_supabase_stack_recreates_db_after_restart_probe_exhaustion_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [False, False, False, False, True]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
            )
            self.assertTrue(result.success)
            restart_seen = any(
                cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["restart", "supabase-db"] for cmd in runner.commands
            )
            stop_seen = any(
                cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["stop", "supabase-db"] for cmd in runner.commands
            )
            rm_seen = any(
                cmd[:2] == ["docker", "compose"] and cmd[-3:] == ["rm", "-f", "supabase-db"] for cmd in runner.commands
            )
            self.assertTrue(restart_seen)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)

    def test_supabase_stack_reports_recreate_failure_when_recreate_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [False, False, False, False]
            runner.compose_returncode["rm -f supabase-db"] = 1
            runner.compose_stderr["rm -f supabase-db"] = "remove failed"

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
            )
            self.assertFalse(result.success)
            self.assertIn("failed recreating supabase db service", result.error or "")

    def test_supabase_native_db_recovers_from_timed_out_start_when_container_becomes_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_supabase_project_name(project_root=root, project_name="Main") + "-supabase-db-1"
            runner.existing.add(container_name)
            runner.status[container_name] = "exited"
            runner.port_mappings[(container_name, "5432")] = "0.0.0.0:5435\n"
            runner.start_timeout.add(container_name)

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                db_port=5435,
                env={"ENVCTL_SUPABASE_DB_START_NATIVE": "true"},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.container_name, container_name)
            self.assertEqual(result.effective_port, 5435)
            self.assertTrue(
                any(cmd[:2] == ["docker", "start"] and cmd[-1] == container_name for cmd in runner.commands)
            )

    def test_supabase_native_db_start_timeout_surfaces_bind_conflict_state_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_supabase_project_name(project_root=root, project_name="Main") + "-supabase-db-1"
            runner.existing.add(container_name)
            runner.status[container_name] = "created"
            runner.port_mappings[(container_name, "5432")] = "0.0.0.0:5435\n"
            runner.start_timeout.add(container_name)
            runner.state_error[container_name] = "Bind for 0.0.0.0:5435 failed: port is already allocated"

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                db_port=5435,
                env={"ENVCTL_SUPABASE_DB_START_NATIVE": "true"},
            )

            self.assertFalse(result.success)
            self.assertIn("port is already allocated", result.error or "")

    def test_supabase_native_db_start_timeout_surfaces_missing_published_port_as_bind_retryable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_supabase_project_name(project_root=root, project_name="Main") + "-supabase-db-1"
            runner.existing.add(container_name)
            runner.status[container_name] = "created"
            runner.port_mappings[(container_name, "5432")] = "0.0.0.0:5435\n"
            runner.network_port_mappings[(container_name, "5432")] = None
            runner.start_timeout.add(container_name)

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                db_port=5435,
                env={"ENVCTL_SUPABASE_DB_START_NATIVE": "true"},
            )

            self.assertFalse(result.success)
            self.assertIn("published host port missing", result.error or "")

    def test_redis_created_bind_conflict_container_is_cleaned_in_discover(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_container_name(
                prefix="envctl-redis",
                project_root=root,
                project_name="feature-a-1",
            )
            runner.existing.add(container_name)
            runner.status[container_name] = "created"
            runner.port_mappings[(container_name, "6379")] = "0.0.0.0:6384\n"
            runner.state_error[container_name] = "Bind for 0.0.0.0:6384 failed: port is already allocated"

            result = start_redis_container(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                port=6384,
            )

            self.assertTrue(result.success)
            self.assertIn(["docker", "stop", container_name], runner.commands)
            self.assertIn(["docker", "rm", "-f", container_name], runner.commands)
            self.assertIn(
                ["docker", "create", "--name", container_name, "-p", "6384:6379", "redis:7-alpine"], runner.commands
            )

    def test_n8n_created_bind_conflict_container_is_cleaned_in_discover(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_container_name(
                prefix="envctl-n8n",
                project_root=root,
                project_name="feature-a-1",
            )
            runner.existing.add(container_name)
            runner.status[container_name] = "created"
            runner.port_mappings[(container_name, "5678")] = "0.0.0.0:5683\n"
            runner.state_error[container_name] = "Bind for 0.0.0.0:5683 failed: port is already allocated"
            runner.wait_for_port_overrides[5683] = True

            result = start_n8n_container(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                port=5683,
            )

            self.assertTrue(result.success)
            self.assertIn(["docker", "stop", container_name], runner.commands)
            self.assertIn(["docker", "rm", "-f", container_name], runner.commands)

    def test_supabase_native_db_start_timeout_recovers_when_published_port_appears_late(self) -> None:
        class _RecoveringRunner(_FakeRunner):
            def sleep(self, seconds: float) -> None:
                super().sleep(seconds)
                if len(self.sleep_calls) >= 2:
                    self.network_port_mappings[(container_name, "5432")] = "0.0.0.0:5435\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _RecoveringRunner()
            container_name = build_supabase_project_name(project_root=root, project_name="Main") + "-supabase-db-1"
            runner.existing.add(container_name)
            runner.status[container_name] = "created"
            runner.port_mappings[(container_name, "5432")] = "0.0.0.0:5435\n"
            runner.network_port_mappings[(container_name, "5432")] = None
            runner.start_timeout.add(container_name)

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                db_port=5435,
                env={"ENVCTL_SUPABASE_DB_START_NATIVE": "true"},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.effective_port, 5435)
            self.assertGreaterEqual(len(runner.sleep_calls), 2)

    def test_supabase_project_env_exports_database_url_and_password(self) -> None:
        class _Runtime:
            @staticmethod
            def _command_override_value(key: str) -> str | None:
                return {
                    "SUPABASE_ANON_KEY": "anon-secret",
                    "SUPABASE_SERVICE_ROLE_KEY": "service-secret",
                    "SUPABASE_JWT_SECRET": "jwt-secret",
                }.get(key)

        class _Context:
            ports = {"db": type("Plan", (), {"final": 5432})()}

        class _Requirements:
            @staticmethod
            def component(name: str) -> dict[str, object]:
                assert name == "supabase"
                return {"final": 5432, "requested": 5432}

        env_projector = dependency_definition("supabase").env_projector
        assert env_projector is not None
        env = env_projector(runtime=_Runtime(), context=_Context(), requirements=_Requirements(), route=None)

        self.assertEqual(env["DB_HOST"], "localhost")
        self.assertEqual(env["DB_PORT"], "5432")
        self.assertEqual(env["DB_USER"], "postgres")
        self.assertEqual(env["DB_PASSWORD"], "supabase-db-password")
        self.assertIn("supabase-db-password", env["DATABASE_URL"])
        self.assertEqual(env["DATABASE_URL"], env["SQLALCHEMY_DATABASE_URL"])
        self.assertEqual(env["DATABASE_URL"], env["ASYNC_DATABASE_URL"])
        self.assertEqual(env["SUPABASE_URL"], "http://localhost:5432")
        self.assertEqual(env["SUPABASE_ANON_KEY"], "anon-secret")
        self.assertEqual(env["SUPABASE_SERVICE_ROLE_KEY"], "service-secret")
        self.assertEqual(env["SUPABASE_JWT_SECRET"], "jwt-secret")
        self.assertEqual(env["SUPABASE_JWKS_URL"], "http://localhost:5432/auth/v1/.well-known/jwks.json")

    def test_supabase_native_db_recreates_existing_container_without_host_port_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_supabase_project_name(project_root=root, project_name="Main") + "-supabase-db-1"
            runner.existing.add(container_name)
            runner.status[container_name] = "running"

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                db_port=5435,
                env={"ENVCTL_SUPABASE_DB_START_NATIVE": "true"},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.container_name, container_name)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container_name for cmd in runner.commands)
            create_seen = any(
                cmd[:2] == ["docker", "create"] and "--name" in cmd and container_name in cmd for cmd in runner.commands
            )
            self.assertTrue(rm_seen)
            self.assertTrue(create_seen)

    def test_supabase_native_db_recreates_existing_container_when_host_probe_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_supabase_project_name(project_root=root, project_name="Main") + "-supabase-db-1"
            runner.existing.add(container_name)
            runner.status[container_name] = "running"
            runner.port_mappings[(container_name, "5432")] = "0.0.0.0:5435\n"
            runner.wait_for_port_sequences[5435] = [False, True]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                db_port=5435,
                env={"ENVCTL_SUPABASE_DB_START_NATIVE": "true"},
            )

            self.assertTrue(result.success)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container_name for cmd in runner.commands)
            create_seen = any(
                cmd[:2] == ["docker", "create"] and "--name" in cmd and container_name in cmd for cmd in runner.commands
            )
            self.assertTrue(rm_seen)
            self.assertTrue(create_seen)

    def test_supabase_native_db_recovers_from_timed_out_create_when_container_becomes_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_supabase_project_name(project_root=root, project_name="Main") + "-supabase-db-1"
            runner.create_timeout.add(container_name)

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                db_port=5435,
                env={"ENVCTL_SUPABASE_DB_START_NATIVE": "true"},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.container_name, container_name)
            self.assertEqual(result.effective_port, 5435)
            self.assertTrue(
                any(
                    cmd[:2] == ["docker", "create"] and "--name" in cmd and container_name in cmd
                    for cmd in runner.commands
                )
            )
            self.assertTrue(
                any(cmd[:2] == ["docker", "start"] and cmd[-1] == container_name for cmd in runner.commands)
            )

    def test_supabase_stack_uses_unique_compose_project_name_per_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = root / "trees" / "feature-a" / "1"
            second = root / "trees" / "feature-b" / "1"
            for path in (first, second):
                supabase_dir = path / "supabase"
                supabase_dir.mkdir(parents=True, exist_ok=True)
                (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            first_runner = _FakeRunner()
            second_runner = _FakeRunner()

            first_result = start_supabase_stack(
                process_runner=first_runner,
                project_root=first,
                project_name="feature-a-1",
                db_port=5432,
            )
            second_result = start_supabase_stack(
                process_runner=second_runner,
                project_root=second,
                project_name="feature-b-1",
                db_port=5433,
            )

            self.assertTrue(first_result.success)
            self.assertTrue(second_result.success)
            self.assertNotEqual(first_result.container_name, second_result.container_name)

    def test_supabase_stack_condenses_container_name_conflict_into_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_returncode["up -d supabase-db supabase-auth supabase-kong"] = 1
            runner.compose_stderr["up -d supabase-db supabase-auth supabase-kong"] = (
                "Container supabase-supabase-db-1 Error response from daemon: Conflict. "
                'The container name "/supabase-supabase-db-1" is already in use by container "abc".\n'
                'Error response from daemon: Conflict. The container name "/supabase-supabase-db-1" is already in use by container "abc".'
            )

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
            )

            self.assertFalse(result.success)
            self.assertIn("supabase compose namespace conflict", result.error or "")
            self.assertIn("supabase-supabase-db-1", result.error or "")

    def test_postgres_creates_container_and_probes_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(result.success)
            self.assertIn("envctl-postgres", result.container_name)
            self.assertTrue(any(cmd[:2] == ["docker", "run"] for cmd in runner.commands))
            self.assertTrue(any("5434:5432" in cmd for cmd in runner.commands))
            self.assertTrue(any(cmd[:2] == ["docker", "exec"] for cmd in runner.commands))

    def test_postgres_retries_readiness_probe_before_declaring_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            preview = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(preview.success)
            container = preview.container_name

            runner.exec_returncode_sequence[container] = [2, 0]
            runner.exec_stderr_sequence[container] = ["/var/run/postgresql:5432 - no response", ""]

            result = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )

            self.assertTrue(result.success)
            exec_calls = [cmd for cmd in runner.commands if cmd[:2] == ["docker", "exec"] and cmd[2] == container]
            self.assertGreaterEqual(len(exec_calls), 3)
            self.assertGreaterEqual(len(runner.sleep_calls), 1)

    def test_postgres_readiness_probe_uses_backoff_before_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            preview = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(preview.success)
            container = preview.container_name

            runner.exec_returncode[container] = 2
            runner.exec_stderr[container] = "/var/run/postgresql:5432 - no response"

            result = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )

            self.assertFalse(result.success)
            self.assertIn("no response", result.error or "")
            self.assertGreaterEqual(len(runner.sleep_calls), 3)

    def test_postgres_slow_probe_eventually_succeeds_after_many_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            preview = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(preview.success)
            container = preview.container_name

            runner.exec_returncode_sequence[container] = [2] * 25 + [0]
            runner.exec_stderr_sequence[container] = ["/var/run/postgresql:5432 - no response"] * 25 + [""]

            result = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )

            self.assertTrue(result.success)

    def test_postgres_restarts_once_after_probe_exhaustion_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            preview = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(preview.success)
            container = preview.container_name

            runner.exec_returncode_sequence[container] = [2] * 60 + [0]
            runner.exec_stderr_sequence[container] = ["/var/run/postgresql:5432 - no response"] * 60 + [""]

            result = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )

            self.assertTrue(result.success)
            restart_seen = any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(restart_seen)

    def test_postgres_restarts_when_listener_timeout_occurs_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mappings[(container, "5432")] = "0.0.0.0:5434"
            runner.wait_for_port_sequences[5434] = [False, True]

            second = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(second.success)
            restart_seen = any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(restart_seen)

    def test_postgres_listener_wait_timeout_honors_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
                env={"ENVCTL_POSTGRES_LISTENER_WAIT_TIMEOUT_SECONDS": "41.5"},
            )
            self.assertTrue(result.success)
            self.assertTrue(any(port == 5434 and timeout == 41.5 for port, timeout in runner.wait_for_port_calls))

    def test_postgres_recreates_after_restart_listener_timeout_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mappings[(container, "5432")] = "0.0.0.0:5434"
            runner.wait_for_port_sequences[5434] = [False, False, True]

            second = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(second.success)
            restart_seen = any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container for cmd in runner.commands)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(restart_seen)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)

    def test_postgres_reports_restart_failure_when_recovery_restart_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            preview = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(preview.success)
            container = preview.container_name

            runner.exec_returncode[container] = 2
            runner.exec_stderr[container] = "/var/run/postgresql:5432 - no response"
            runner.restart_returncode[container] = 1
            runner.restart_stderr[container] = "restart failed"

            result = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )

            self.assertFalse(result.success)
            self.assertIn("failed restarting postgres container", result.error or "")

    def test_postgres_recreates_after_restart_probe_exhaustion_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            preview = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(preview.success)
            container = preview.container_name
            runner.port_mappings[(container, "5432")] = "0.0.0.0:5434"

            runner.exec_returncode_sequence[container] = [2] * 90 + [0]
            runner.exec_stderr_sequence[container] = ["/var/run/postgresql:5432 - no response"] * 90 + [""]

            result = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )

            self.assertTrue(result.success)
            restart_seen = any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(restart_seen)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)

    def test_postgres_reports_recreate_failure_when_recreate_run_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            preview = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(preview.success)
            container = preview.container_name
            runner.port_mappings[(container, "5432")] = "0.0.0.0:5434"

            runner.exec_returncode[container] = 2
            runner.exec_stderr[container] = "/var/run/postgresql:5432 - no response"
            runner.run_returncode_sequence[container] = [1]
            runner.run_stderr[container] = "create failed"

            result = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )

            self.assertFalse(result.success)
            self.assertIn("failed recreating postgres container", result.error or "")

    def test_postgres_recreates_existing_container_when_mapping_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mappings[(container, "5432")] = ""

            second = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(second.success)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)

    def test_postgres_recreates_existing_container_when_port_command_reports_no_public_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mapping_errors[(container, "5432")] = (
                "Error: No public port '5432' published for envctl-postgres"
            )

            second = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(second.success)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)

    def test_redis_fails_when_ping_probe_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result_first = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(result_first.success)

            container = result_first.container_name
            runner.exec_returncode[container] = 1
            runner.exec_stderr[container] = "NOAUTH"

            result_second = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertFalse(result_second.success)
            self.assertIn("redis-cli ping", result_second.error or "")

    def test_redis_retries_ping_probe_before_declaring_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result_first = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(result_first.success)

            container = result_first.container_name
            runner.exec_returncode_sequence[container] = [1, 0]
            runner.exec_stderr_sequence[container] = ["LOADING", ""]

            result_second = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(result_second.success)
            exec_calls = [cmd for cmd in runner.commands if cmd[:2] == ["docker", "exec"] and cmd[2] == container]
            self.assertGreaterEqual(len(exec_calls), 3)
            self.assertGreaterEqual(len(runner.sleep_calls), 1)

    def test_redis_ping_probe_uses_backoff_before_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result_first = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(result_first.success)

            container = result_first.container_name
            runner.exec_returncode[container] = 1
            runner.exec_stderr[container] = "NOAUTH"

            result_second = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertFalse(result_second.success)
            self.assertIn("redis-cli ping", result_second.error or "")
            self.assertGreaterEqual(len(runner.sleep_calls), 3)

    def test_redis_restarts_once_after_probe_exhaustion_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result_first = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(result_first.success)

            container = result_first.container_name
            runner.port_mappings[(container, "6379")] = "0.0.0.0:6380"
            runner.exec_returncode_sequence[container] = [1] * 20 + [0]
            runner.exec_stderr_sequence[container] = ["LOADING"] * 20 + [""]

            result_second = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(result_second.success)
            restart_seen = any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(restart_seen)

    def test_redis_restarts_when_listener_timeout_occurs_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mappings[(container, "6379")] = "0.0.0.0:6380"
            runner.wait_for_port_sequences[6380] = [False, True]

            second = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(second.success)
            restart_seen = any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(restart_seen)

    def test_redis_listener_wait_timeout_honors_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
                env={"ENVCTL_REDIS_LISTENER_WAIT_TIMEOUT_SECONDS": "33"},
            )
            self.assertTrue(result.success)
            self.assertTrue(any(port == 6380 and timeout == 33.0 for port, timeout in runner.wait_for_port_calls))

    def test_redis_recreates_after_restart_listener_timeout_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mappings[(container, "6379")] = "0.0.0.0:6380"
            runner.wait_for_port_sequences[6380] = [False, False, True]

            second = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(second.success)
            restart_seen = any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container for cmd in runner.commands)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(restart_seen)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)

    def test_redis_recreates_after_restart_probe_exhaustion_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result_first = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(result_first.success)

            container = result_first.container_name
            runner.port_mappings[(container, "6379")] = "0.0.0.0:6380"
            runner.exec_returncode_sequence[container] = [1] * 50 + [0]
            runner.exec_stderr_sequence[container] = ["LOADING"] * 50 + [""]

            result_second = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(result_second.success)
            restart_seen = any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(restart_seen)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)

    def test_redis_reports_recreate_failure_when_recreate_run_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result_first = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(result_first.success)

            container = result_first.container_name
            runner.port_mappings[(container, "6379")] = "0.0.0.0:6380"
            runner.exec_returncode[container] = 1
            runner.exec_stderr[container] = "LOADING"
            runner.create_returncode[container] = 1
            runner.create_stderr[container] = "create failed"

            result_second = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertFalse(result_second.success)
            self.assertIn("failed recreating redis container", result_second.error or "")

    def test_redis_recreates_existing_container_when_mapping_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mappings[(container, "6379")] = ""

            second = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(second.success)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)

    def test_redis_recreates_existing_container_when_port_command_reports_no_public_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mapping_errors[(container, "6379")] = "Error: No public port '6379' published for envctl-redis"

            second = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(second.success)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)

    def test_n8n_adopts_existing_container_port_mapping_on_mismatch_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result_first = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertTrue(result_first.success)
            container = result_first.container_name
            runner.port_mappings[(container, "5678")] = "0.0.0.0:5688\n"
            runner.status[container] = "exited"

            result_second = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5679,
            )
            self.assertTrue(result_second.success)
            self.assertEqual(result_second.effective_port, 5688)
            self.assertTrue(result_second.port_adopted)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            recreate_seen = any(cmd[:2] == ["docker", "create"] and "5679:5678" in cmd for cmd in runner.commands)
            start_seen = any(cmd[:2] == ["docker", "start"] and cmd[-1] == container for cmd in runner.commands)
            self.assertFalse(stop_seen)
            self.assertFalse(rm_seen)
            self.assertFalse(recreate_seen)
            self.assertTrue(start_seen)

    def test_n8n_recreates_existing_container_when_mapping_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mappings[(container, "5678")] = ""

            second = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertTrue(second.success)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)

    def test_n8n_recreates_existing_container_when_port_command_reports_no_public_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mapping_errors[(container, "5678")] = "Error: No public port '5678' published for envctl-n8n"

            second = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertTrue(second.success)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)

    def test_n8n_restarts_when_port_probe_times_out_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mappings[(container, "5678")] = "0.0.0.0:5678"
            runner.wait_for_port_sequences[5678] = [False, True]

            second = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertTrue(second.success)
            restart_seen = any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(restart_seen)

    def test_n8n_recreates_after_restart_probe_timeout_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mappings[(container, "5678")] = "0.0.0.0:5678"
            runner.wait_for_port_sequences[5678] = [False, False, True]

            second = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertTrue(second.success)
            restart_seen = any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container for cmd in runner.commands)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(restart_seen)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)

    def test_n8n_uses_reduced_default_probe_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertTrue(result.success)
            self.assertTrue(any(port == 5678 and timeout == 6.0 for port, timeout in runner.wait_for_port_calls))

    def test_n8n_reports_recreate_failure_when_recreate_run_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mappings[(container, "5678")] = "0.0.0.0:5678"
            runner.wait_for_port_sequences[5678] = [False, False]
            runner.create_returncode[container] = 1
            runner.create_stderr[container] = "create failed"

            second = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertFalse(second.success)
            self.assertIn("failed recreating n8n container", second.error or "")


if __name__ == "__main__":
    unittest.main()
