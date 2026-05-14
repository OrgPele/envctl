from __future__ import annotations

import subprocess
import sys


class SupabaseFakeComposeProcess:
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


class SupabaseFakeRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.wait_for_port_calls: list[tuple[int, float]] = []
        self.wait_for_port_result = True
        self.wait_for_port_sequences: dict[int, list[bool]] = {}
        self.sleep_calls: list[float] = []
        self.compose_services_stdout = "supabase-db\nsupabase-auth\nsupabase-kong\n"
        self.compose_returncode: dict[str, int] = {}
        self.compose_stderr: dict[str, str] = {}
        self.compose_returncode_sequence: dict[str, list[int]] = {}
        self.compose_stderr_sequence: dict[str, list[str]] = {}
        self.compose_ps_q_stdout: dict[str, str | list[str]] = {}
        self.compose_json_stdout: dict[str, str] = {}
        self.compose_json_returncode: dict[str, int] = {}
        self.inspect_state_stdout: dict[str, str] = {}
        self.inspect_returncode: dict[str, int] = {}
        self.inspect_stderr: dict[str, str] = {}
        self.network_names: list[str] = []
        self.network_container_counts: dict[str, int] = {}
        self.network_rm_returncode: dict[str, int] = {}
        self.network_rm_stderr: dict[str, str] = {}
        self.health_returncode_sequence: list[int] = []
        self.health_stderr_sequence: list[str] = []
        self.health_urls: list[str] = []

    def run(self, cmd, *, cwd=None, env=None, timeout=None, process_started_callback=None):  # noqa: ANN001
        _ = cwd, env, timeout, process_started_callback
        command = list(cmd)
        self.commands.append(command)
        if command[:2] == ["docker", "compose"] and "-f" in command:
            compose_args = command[command.index("-f") + 2 :]
            compose_key = " ".join(compose_args)
            if compose_args == ["config", "--services"]:
                return subprocess.CompletedProcess(command, 0, self.compose_services_stdout, "")
            if compose_args[:3] == ["ps", "--format", "json"]:
                service = compose_args[3] if len(compose_args) > 3 else ""
                rc = self.compose_json_returncode.get(service, 0)
                return subprocess.CompletedProcess(command, rc, self.compose_json_stdout.get(service, ""), "")
            if compose_args[:2] == ["ps", "-q"]:
                service = compose_args[2] if len(compose_args) > 2 else ""
                configured = self.compose_ps_q_stdout.get(service, "")
                stdout = configured.pop(0) if isinstance(configured, list) and configured else configured
                return subprocess.CompletedProcess(command, 0, str(stdout), "")
            sequence = self.compose_returncode_sequence.get(compose_key)
            rc = sequence.pop(0) if sequence else self.compose_returncode.get(compose_key, 0)
            stderr_sequence = self.compose_stderr_sequence.get(compose_key)
            stderr = stderr_sequence.pop(0) if stderr_sequence else self.compose_stderr.get(compose_key, "")
            return subprocess.CompletedProcess(command, rc, "" if rc else "ok\n", stderr)
        if command[:3] == ["docker", "inspect", "-f"]:
            container = command[-1]
            rc = self.inspect_returncode.get(container, 0)
            stderr = self.inspect_stderr.get(container, "")
            stdout = self.inspect_state_stdout.get(container, '{"Status":"running","ExitCode":0}')
            return subprocess.CompletedProcess(command, rc, stdout if rc == 0 else "", stderr)
        if command[:3] == ["docker", "network", "ls"]:
            stdout = "\n".join(self.network_names) + ("\n" if self.network_names else "")
            return subprocess.CompletedProcess(command, 0, stdout, "")
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
        if command and command[0] == sys.executable and any("/auth/v1/health" in part for part in command):
            self.health_urls.append(command[-2])
            rc = self.health_returncode_sequence.pop(0) if self.health_returncode_sequence else 0
            stderr = self.health_stderr_sequence.pop(0) if self.health_stderr_sequence else ""
            return subprocess.CompletedProcess(command, rc, "", stderr)
        return subprocess.CompletedProcess(command, 0, "", "")

    def wait_for_port(self, port: int, *, host: str = "127.0.0.1", timeout: float = 30.0) -> bool:
        _ = host
        self.wait_for_port_calls.append((port, float(timeout)))
        sequence = self.wait_for_port_sequences.get(port)
        if sequence:
            return sequence.pop(0)
        return self.wait_for_port_result

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(float(seconds))

    def compose_up_process(self, cmd, *, cwd=None, env=None):  # noqa: ANN001
        _ = cwd, env
        self.commands.append(list(cmd))
        compose_args = cmd[cmd.index("-f") + 2 :] if "-f" in cmd else cmd
        compose_key = " ".join(compose_args)
        sequence = self.compose_returncode_sequence.get(compose_key)
        rc = sequence.pop(0) if sequence else self.compose_returncode.get(compose_key, 0)
        stderr_sequence = self.compose_stderr_sequence.get(compose_key)
        stderr = stderr_sequence.pop(0) if stderr_sequence else self.compose_stderr.get(compose_key, "")
        return SupabaseFakeComposeProcess(returncode=rc, stderr=stderr)
