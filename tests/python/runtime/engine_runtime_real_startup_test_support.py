from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import threading
import unittest
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.state.models import PortPlan

FAKE_WORKTREE_GITDIR_CONTENT = "gitdir: /tmp/fake-worktree\n"


class _HealthyHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/auth/v1/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        return


@contextmanager
def _healthy_http_server():
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthyHandler)
    except PermissionError as exc:
        raise unittest.SkipTest(f"local TCP listener unavailable: {exc}") from exc
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


@contextmanager
def _tcp_listener():
    stop = threading.Event()
    ready = threading.Event()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
    except PermissionError as exc:
        sock.close()
        raise unittest.SkipTest(f"local TCP listener unavailable: {exc}") from exc
    sock.listen()
    sock.settimeout(0.1)
    port = int(sock.getsockname()[1])

    def serve() -> None:
        ready.set()
        while not stop.is_set():
            try:
                conn, _addr = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    ready.wait(timeout=1)
    try:
        yield port
    finally:
        stop.set()
        sock.close()
        thread.join(timeout=1)


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


class _FakeProcessRunner:
    def __init__(self) -> None:
        self.run_calls: list[tuple[tuple[str, ...], str]] = []
        self.run_envs: list[dict[str, str] | None] = []
        self.start_calls: list[tuple[tuple[str, ...], str]] = []
        self.start_envs: list[dict[str, str] | None] = []
        self.start_background_calls: list[tuple[tuple[str, ...], str]] = []
        self.start_background_envs: list[dict[str, str] | None] = []
        self._next_pid = 4000
        self.auto_track_listener_ports = False
        self._pid_listener_ports: dict[int, int] = {}
        self.wait_for_port_result = False
        self.wait_for_port_calls: list[tuple[int, float]] = []
        self.wait_for_pid_port_result = False
        self.wait_for_port_overrides: dict[int, bool] = {}
        self.wait_for_pid_port_overrides: dict[int, bool] = {}
        self.wait_for_pid_port_sequences: dict[int, list[bool]] = {}
        self.find_pid_listener_port_result: int | None = None
        self.find_pid_listener_port_overrides: dict[int, int | None] = {}
        self.find_pid_listener_port_calls: list[tuple[int, int, int]] = []
        self.process_tree_probe_supported = True
        self.fail_start_ports: set[int] = set()
        self.fail_alembic = False
        self.alembic_error_text: str | None = None
        self.fail_alembic_async_mismatch_once = False
        self._alembic_async_mismatch_consumed = False
        self.start_log_line: str | None = None
        self.pid_running_result = True
        self.docker_connect_error: str | None = None

    def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
        self.run_calls.append((tuple(cmd), str(cwd)))
        self.run_envs.append(dict(env) if env is not None else None)
        _ = env, timeout
        command = tuple(str(part) for part in cmd)
        if self.docker_connect_error and command and command[0] == "docker":
            return SimpleNamespace(returncode=1, stdout="", stderr=self.docker_connect_error)
        if len(command) >= 5 and command[0] == "git" and "worktree" in command:
            worktree_index = command.index("worktree")
            if worktree_index + 1 >= len(command) or command[worktree_index + 1] != "add":
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            target = Path(str(command[-1]))
            target.mkdir(parents=True, exist_ok=True)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if self.fail_alembic and tuple(cmd[-3:]) == ("alembic", "upgrade", "head"):
            alembic_error = self.alembic_error_text
            if not isinstance(alembic_error, str) or not alembic_error.strip():
                alembic_error = (
                    "sqlalchemy.exc.InvalidRequestError: The asyncio extension requires an async driver to be used."
                )
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr=alembic_error,
            )
        if (
            self.fail_alembic_async_mismatch_once
            and tuple(cmd[-3:]) == ("alembic", "upgrade", "head")
            and not self._alembic_async_mismatch_consumed
        ):
            db_url = ""
            if isinstance(env, dict):
                db_url = str(env.get("DATABASE_URL", ""))
            if "psycopg2" in db_url:
                self._alembic_async_mismatch_consumed = True
                return SimpleNamespace(
                    returncode=1,
                    stdout="",
                    stderr=(
                        "sqlalchemy.exc.InvalidRequestError: "
                        "The asyncio extension requires an async driver to be used. "
                        "The loaded 'psycopg2' is not async."
                    ),
                )
        if tuple(cmd) == ("sh", "-lc", "exit 1"):
            return SimpleNamespace(returncode=1, stdout="", stderr="exit:1")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def start(self, cmd, *, cwd=None, env=None, stdout_path=None, stderr_path=None):  # noqa: ANN001
        self.start_calls.append((tuple(cmd), str(cwd)))
        self.start_envs.append(dict(env) if env is not None else None)
        return self.start_background(
            cmd,
            cwd=cwd,
            env=env,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

    def start_background(self, cmd, *, cwd=None, env=None, stdout_path=None, stderr_path=None):  # noqa: ANN001
        self.start_background_calls.append((tuple(cmd), str(cwd)))
        self.start_background_envs.append(dict(env) if env is not None else None)
        port_raw = None
        if isinstance(env, dict):
            port_raw = env.get("PORT")
        parsed_port = None
        if isinstance(port_raw, str):
            try:
                parsed_port = int(port_raw)
            except ValueError:
                parsed_port = None
        if self.start_log_line and stdout_path:
            Path(stdout_path).parent.mkdir(parents=True, exist_ok=True)
            with Path(stdout_path).open("a", encoding="utf-8") as handle:
                handle.write(self.start_log_line + "\n")
        _ = stderr_path
        self._next_pid += 1
        pid = self._next_pid

        if parsed_port is not None and parsed_port in self.fail_start_ports:
            if stdout_path:
                Path(stdout_path).parent.mkdir(parents=True, exist_ok=True)
                with Path(stdout_path).open("a", encoding="utf-8") as handle:
                    handle.write("OSError: [Errno 48] Address already in use\n")
            return SimpleNamespace(pid=pid, poll=lambda: 1)

        if self.auto_track_listener_ports and parsed_port is not None:
            self._pid_listener_ports[pid] = parsed_port
        return SimpleNamespace(pid=pid, poll=lambda: None)

    def launch_diagnostics_summary(self) -> dict[str, object]:
        return {
            "tracked_launch_count": len(self.start_background_calls),
            "active_launch_count": len(self.start_background_calls),
            "launch_intent_counts": {"background_service": len(self.start_background_calls)}
            if self.start_background_calls
            else {},
            "controller_input_owners": [],
            "active_controller_input_owners": [],
            "tracked_launches": [],
        }

    def wait_for_port(self, _port: int, *, host: str = "127.0.0.1", timeout: float = 30.0) -> bool:
        _ = host, timeout
        self.wait_for_port_calls.append((_port, float(timeout)))
        return self.wait_for_port_overrides.get(_port, self.wait_for_port_result)

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
        sequence = self.wait_for_pid_port_sequences.get(_port)
        if sequence:
            return sequence.pop(0)
        if _port in self.wait_for_pid_port_overrides:
            return self.wait_for_pid_port_overrides[_port]
        if self.auto_track_listener_ports:
            listener_port = self._pid_listener_ports.get(_pid)
            if listener_port is not None:
                return listener_port == _port
        return self.wait_for_pid_port_result

    def find_pid_listener_port(
        self,
        _pid: int,
        _preferred_port: int,
        *,
        max_delta: int = 200,
    ) -> int | None:
        self.find_pid_listener_port_calls.append((_pid, _preferred_port, max_delta))
        if _preferred_port in self.find_pid_listener_port_overrides:
            return self.find_pid_listener_port_overrides[_preferred_port]
        if self.auto_track_listener_ports:
            listener_port = self._pid_listener_ports.get(_pid)
            if isinstance(listener_port, int):
                if _preferred_port <= 0:
                    return listener_port
                if abs(listener_port - _preferred_port) <= max(max_delta, 0):
                    return listener_port
        return self.find_pid_listener_port_result

    def is_pid_running(self, _pid: int) -> bool:
        if self.auto_track_listener_ports and _pid in self._pid_listener_ports:
            return True
        return self.pid_running_result

    def pid_owns_port(self, _pid: int, _port: int) -> bool:
        if not self.auto_track_listener_ports:
            return False
        listener_port = self._pid_listener_ports.get(_pid)
        return listener_port == _port

    def terminate(self, _pid: int, *, term_timeout: float = 2.0, kill_timeout: float = 1.0) -> bool:
        _ = term_timeout, kill_timeout
        if self.auto_track_listener_ports:
            self._pid_listener_ports.pop(_pid, None)
        return True

    def supports_process_tree_probe(self) -> bool:
        return self.process_tree_probe_supported


class _FakeSetupWorktreeRunner(_FakeProcessRunner):
    def __init__(self, *, fail_worktree_add: bool = False) -> None:
        super().__init__()
        self.fail_worktree_add = fail_worktree_add

    def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
        command = tuple(str(part) for part in cmd)
        if len(command) >= 5 and command[0] == "git" and "worktree" in command:
            worktree_index = command.index("worktree")
            if worktree_index + 1 >= len(command) or command[worktree_index + 1] != "add":
                return super().run(cmd, cwd=cwd, env=env, timeout=timeout)
            self.run_calls.append((tuple(cmd), str(cwd)))
            self.run_envs.append(dict(env) if env is not None else None)
            if self.fail_worktree_add:
                return SimpleNamespace(returncode=1, stdout="", stderr="simulated git worktree failure")
            target = Path(str(command[-1]))
            target.mkdir(parents=True, exist_ok=True)
            (target / ".git").write_text(FAKE_WORKTREE_GITDIR_CONTENT, encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return super().run(cmd, cwd=cwd, env=env, timeout=timeout)


class _EngineRuntimeRealStartupTestCase(unittest.TestCase):
    def _config(
        self,
        repo: Path,
        runtime: Path,
        extra: dict[str, str] | None = None,
        *,
        include_commands: bool = True,
    ):
        payload = {
            "RUN_REPO_ROOT": str(repo),
            "RUN_SH_RUNTIME_DIR": str(runtime),
        }
        if include_commands:
            python_bin = sys.executable
            payload.update(
                {
                    "MAIN_POSTGRES_ENABLE": "true",
                    "MAIN_REDIS_ENABLE": "true",
                    "MAIN_SUPABASE_ENABLE": "false",
                    "MAIN_N8N_ENABLE": "false",
                    "TREES_POSTGRES_ENABLE": "true",
                    "TREES_REDIS_ENABLE": "true",
                    "TREES_SUPABASE_ENABLE": "false",
                    "TREES_N8N_ENABLE": "true",
                    "ENVCTL_REQUIREMENT_POSTGRES_CMD": f'{python_bin} -c "import sys; sys.exit(0)"',
                    "ENVCTL_REQUIREMENT_REDIS_CMD": f'{python_bin} -c "import sys; sys.exit(0)"',
                    "ENVCTL_REQUIREMENT_N8N_CMD": f'{python_bin} -c "import sys; sys.exit(0)"',
                    "ENVCTL_REQUIREMENT_SUPABASE_CMD": f'{python_bin} -c "import sys; sys.exit(0)"',
                    "ENVCTL_BACKEND_START_CMD": f'{python_bin} -c "import time; time.sleep(1)"',
                    "ENVCTL_FRONTEND_START_CMD": f'{python_bin} -c "import time; time.sleep(1)"',
                }
            )
        if extra:
            payload.update(extra)
        return load_config(payload)

    @staticmethod
    def _planned_ports(engine: PythonEngineRuntime, project_name: str, *, index: int = 0) -> dict[str, PortPlan]:
        return engine.port_planner.plan_project_stack(project_name, index=index)

    @staticmethod
    def _frontend_envs(fake_runner: _FakeProcessRunner, frontend_dir: Path) -> list[dict[str, str]]:
        frontend_root = str(frontend_dir.resolve())
        return [
            env
            for call, env in zip(fake_runner.start_background_calls, fake_runner.start_background_envs, strict=True)
            if str(Path(call[1]).resolve()) == frontend_root and isinstance(env, dict)
        ]

    @staticmethod
    def _restart_route() -> object:
        route = parse_route(["--restart", "--batch"], env={"ENVCTL_DEFAULT_MODE": "main"})
        route.flags.update(
            {
                "services": ["Main Backend", "Main Frontend"],
                "restart_service_types": ["backend", "frontend"],
                "restart_include_requirements": False,
                "interactive_command": True,
            }
        )
        return route

    def _backend_frontend_only_config(self, repo: Path, runtime: Path):
        return self._config(
            repo,
            runtime,
            extra={
                "POSTGRES_MAIN_ENABLE": "false",
                "REDIS_ENABLE": "false",
                "N8N_ENABLE": "false",
                "SUPABASE_MAIN_ENABLE": "false",
                "MAIN_POSTGRES_ENABLE": "false",
                "MAIN_REDIS_ENABLE": "false",
                "MAIN_N8N_ENABLE": "false",
                "MAIN_SUPABASE_ENABLE": "false",
                "TREES_POSTGRES_ENABLE": "false",
                "TREES_REDIS_ENABLE": "false",
                "TREES_N8N_ENABLE": "false",
                "TREES_SUPABASE_ENABLE": "false",
                "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
            },
        )
