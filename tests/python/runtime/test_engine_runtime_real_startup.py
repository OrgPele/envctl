from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.runtime.command_router import parse_route
from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.state.models import PortPlan, RequirementsResult, RunState, ServiceRecord
from envctl_engine.runtime.engine_runtime import ProjectContext
from envctl_engine.state import dump_state


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

    def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
        self.run_calls.append((tuple(cmd), str(cwd)))
        self.run_envs.append(dict(env) if env is not None else None)
        _ = env, timeout
        command = tuple(str(part) for part in cmd)
        if len(command) >= 5 and command[0] == "git" and command[3] == "worktree" and command[4] == "add":
            target = Path(str(command[-1]))
            target.mkdir(parents=True, exist_ok=True)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if self.fail_alembic and tuple(cmd[-3:]) == ("alembic", "upgrade", "head"):
            alembic_error = self.alembic_error_text
            if not isinstance(alembic_error, str) or not alembic_error.strip():
                alembic_error = "sqlalchemy.exc.InvalidRequestError: The asyncio extension requires an async driver to be used."
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
            "launch_intent_counts": {"background_service": len(self.start_background_calls)} if self.start_background_calls else {},
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
        if len(command) >= 5 and command[0] == "git" and command[3] == "worktree" and command[4] == "add":
            self.run_calls.append((tuple(cmd), str(cwd)))
            self.run_envs.append(dict(env) if env is not None else None)
            if self.fail_worktree_add:
                return SimpleNamespace(returncode=1, stdout="", stderr="simulated git worktree failure")
            target = Path(str(command[-1]))
            target.mkdir(parents=True, exist_ok=True)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return super().run(cmd, cwd=cwd, env=env, timeout=timeout)


class EngineRuntimeRealStartupTests(unittest.TestCase):
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
                    "ENVCTL_REQUIREMENT_POSTGRES_CMD": f"{python_bin} -c \"import sys; sys.exit(0)\"",
                    "ENVCTL_REQUIREMENT_REDIS_CMD": f"{python_bin} -c \"import sys; sys.exit(0)\"",
                    "ENVCTL_REQUIREMENT_N8N_CMD": f"{python_bin} -c \"import sys; sys.exit(0)\"",
                    "ENVCTL_REQUIREMENT_SUPABASE_CMD": f"{python_bin} -c \"import sys; sys.exit(0)\"",
                    "ENVCTL_BACKEND_START_CMD": f"{python_bin} -c \"import time; time.sleep(1)\"",
                    "ENVCTL_FRONTEND_START_CMD": f"{python_bin} -c \"import time; time.sleep(1)\"",
                }
            )
        if extra:
            payload.update(extra)
        return load_config(payload)

    @staticmethod
    def _planned_ports(engine: PythonEngineRuntime, project_name: str, *, index: int = 0) -> dict[str, PortPlan]:
        return engine.port_planner.plan_project_stack(project_name, index=index)

    def test_debug_session_materialized_when_debug_mode_off(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            self.assertIsNone(engine._debug_recorder)

            code = engine.dispatch(parse_route(["--help"], env={}))

            self.assertEqual(code, 0)
            self.assertIsNotNone(engine._debug_recorder)
            session_id = engine._current_session_id()
            self.assertIsInstance(session_id, str)
            assert isinstance(session_id, str)
            self.assertTrue(session_id.startswith("session-"))

    def test_trees_discovery_supports_nested_feature_iteration_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "2").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-b" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            contexts = engine._discover_projects(mode="trees")

            names = [ctx.name for ctx in contexts]
            roots = [ctx.root.resolve() for ctx in contexts]
            self.assertEqual(names, ["feature-a-1", "feature-a-2", "feature-b-1"])
            self.assertIn((repo / "trees" / "feature-a" / "1").resolve(), roots)
            self.assertIn((repo / "trees" / "feature-a" / "2").resolve(), roots)
            self.assertIn((repo / "trees" / "feature-b" / "1").resolve(), roots)

    def test_startup_uses_process_runner_for_requirements_and_services(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeSetupWorktreeRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertGreaterEqual(len(fake_runner.run_calls), 3)
            self.assertGreaterEqual(len(fake_runner.start_background_calls), 2)
            self.assertEqual(fake_runner.start_calls, [])
            shell_report_path = runtime / "python-engine" / "shell_prune_report.json"
            self.assertTrue(shell_report_path.is_file())
            shell_report = json.loads(shell_report_path.read_text(encoding="utf-8"))
            self.assertIn("passed", shell_report)
            self.assertIn("snapshot", shell_report)
            run_state = json.loads((runtime / "python-engine" / "run_state.json").read_text(encoding="utf-8"))
            pointers = run_state.get("pointers", {})
            self.assertIn("shell_prune_report", pointers)
            pointer_path = Path(str(pointers.get("shell_prune_report")))
            self.assertEqual(pointer_path.name, "shell_prune_report.json")
            self.assertEqual(pointer_path.parent.name, str(run_state.get("run_id", "")))
            self.assertTrue(pointer_path.is_file())

    def test_startup_emits_port_lock_reclaim_event_with_previous_owner_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            lock_path = engine.port_planner.lock_dir / "8000.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path.write_text(
                json.dumps(
                    {
                        "owner": "old-worker",
                        "session": "old-session",
                        "pid": 999999,
                        "created_at": "2000-01-01T00:00:00+00:00",
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            fake_runner = _FakeSetupWorktreeRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            reclaim_events = [event for event in engine.events if event.get("event") == "port.lock.reclaim"]
            self.assertTrue(reclaim_events)
            latest = reclaim_events[-1]
            self.assertEqual(latest.get("port"), 8000)
            self.assertEqual(latest.get("reclaimed_owner"), "old-worker")
            self.assertEqual(latest.get("reclaimed_session"), "old-session")
            self.assertEqual(latest.get("reclaimed_pid"), 999999)

    def test_port_event_handler_emits_events_with_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine._on_port_event("port.lock.acquire", {"port": 8000, "owner": "proj"})

            self.assertTrue(engine.events)
            last = engine.events[-1]
            self.assertEqual(last.get("event"), "port.lock.acquire")
            self.assertEqual(last.get("port"), 8000)
            self.assertEqual(last.get("owner"), "proj")

    def test_startup_fails_when_listener_cannot_be_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            config = self._config(
                repo,
                runtime,
                extra={"ENVCTL_RUNTIME_TRUTH_MODE": "strict"},
            )
            engine = PythonEngineRuntime(config, env={})
            engine.port_planner.availability_checker = lambda _port: True
            engine._command_exists = lambda _cmd: False  # type: ignore[method-assign]
            fake_runner = _FakeSetupWorktreeRunner()
            fake_runner.wait_for_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 1)
            run_state = json.loads((runtime / "python-engine" / "run_state.json").read_text(encoding="utf-8"))
            pointers = run_state.get("pointers", {})
            self.assertIn("shell_prune_report", pointers)
            pointer_path = Path(str(pointers.get("shell_prune_report")))
            self.assertEqual(pointer_path.name, "shell_prune_report.json")
            self.assertEqual(pointer_path.parent.name, str(run_state.get("run_id", "")))
            self.assertTrue(pointer_path.is_file())

    def test_startup_auto_truth_does_not_use_port_reachability_fallback_when_listener_probe_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_RUNTIME_TRUTH_MODE": "auto",
                    }
                ),
                env={
                    "ENVCTL_REQUIREMENT_POSTGRES_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_REDIS_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_N8N_CMD": "sh -lc true",
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 1'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 1'",
                },
            )
            engine._listener_probe_supported = True  # type: ignore[attr-defined]
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeSetupWorktreeRunner()
            fake_runner.wait_for_pid_port_result = False
            fake_runner.wait_for_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 1)

    def test_startup_auto_truth_uses_port_reachability_fallback_when_listener_probe_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_RUNTIME_TRUTH_MODE": "auto",
                    }
                ),
                env={
                    "ENVCTL_REQUIREMENT_POSTGRES_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_REDIS_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_N8N_CMD": "sh -lc true",
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 1'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 1'",
                },
            )
            engine._listener_probe_supported = False  # type: ignore[attr-defined]
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeSetupWorktreeRunner()
            fake_runner.wait_for_pid_port_result = False
            fake_runner.wait_for_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)

    def test_startup_auto_truth_uses_port_reachability_fallback_when_process_tree_probe_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_RUNTIME_TRUTH_MODE": "auto",
                    }
                ),
                env={
                    "ENVCTL_REQUIREMENT_POSTGRES_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_REDIS_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_N8N_CMD": "sh -lc true",
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 1'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 1'",
                },
            )
            engine._listener_probe_supported = True  # type: ignore[attr-defined]
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeSetupWorktreeRunner()
            fake_runner.process_tree_probe_supported = False
            fake_runner.wait_for_pid_port_result = False
            fake_runner.wait_for_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)

    def test_startup_strict_truth_does_not_use_port_reachability_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "strict",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_REQUIREMENT_POSTGRES_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_REDIS_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_N8N_CMD": "sh -lc true",
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 1'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 1'",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_pid_port_result = False
            fake_runner.wait_for_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 1)

    def test_listener_failure_surfaces_backend_log_root_cause(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            config = self._config(
                repo,
                runtime,
                extra={"ENVCTL_RUNTIME_TRUTH_MODE": "strict"},
            )
            engine = PythonEngineRuntime(config, env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = False
            fake_runner.start_log_line = "ModuleNotFoundError: No module named 'psycopg2'"
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("ModuleNotFoundError", out.getvalue())
            self.assertIn("psycopg2", out.getvalue())

    def test_startup_fails_when_service_loses_listener_immediately_after_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "strict",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 1'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 1'",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            plans = self._planned_ports(engine, "feature-a-1")
            fake_runner.wait_for_pid_port_sequences[plans["backend"].final] = [True, False]
            fake_runner.wait_for_pid_port_sequences[plans["frontend"].final] = [True, True]
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            rendered = out.getvalue()
            self.assertIn("backend became", rendered)
            self.assertIn("after startup", rendered)

    def test_startup_fails_when_service_truth_degrades_before_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "strict",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 1'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 1'",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_sequences[8000] = [True, True, True]
            fake_runner.wait_for_pid_port_sequences[9000] = [True, True, False]
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("service truth degraded after startup", out.getvalue())

    def test_auto_runtime_truth_degrades_when_lsof_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            with patch("envctl_engine.runtime.engine_runtime.shutil.which", return_value=None):
                engine = PythonEngineRuntime(self._config(repo, runtime), env={})
                engine.port_planner.availability_checker = lambda _port: True
                fake_runner = _FakeProcessRunner()
                fake_runner.wait_for_port_result = True
                fake_runner.wait_for_pid_port_result = False
                engine.process_runner = fake_runner  # type: ignore[attr-defined]
                route = parse_route(["--plan", "feature-a", "--batch"], env={})

                code = engine.dispatch(route)

            self.assertEqual(code, 0)

    def test_backend_requirements_bootstrap_installs_project_venv_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            (backend_dir / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "DB_USER": "svc_user",
                    "DB_PASSWORD": "svc_pass",
                    "DB_NAME": "svc_db",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            pip_install_calls = [
                call
                for call in fake_runner.run_calls
                if len(call[0]) >= 4
                and call[0][1:4] == ("-m", "pip", "install")
                and call[0][-2:] == ("-r", "requirements.txt")
            ]
            self.assertTrue(pip_install_calls)
            self.assertTrue(
                any(
                    len(call[0]) >= 3
                    and call[0][1:3] == ("-m", "venv")
                    and str(call[0][-1]).endswith("/backend/venv")
                    for call in fake_runner.run_calls
                )
            )
            alembic_calls = [call for call in fake_runner.run_calls if call[0][-3:] == ("alembic", "upgrade", "head")]
            self.assertTrue(alembic_calls)
            bootstrap_envs = [env for env in fake_runner.run_envs if isinstance(env, dict)]
            self.assertTrue(
                any(
                    env.get("DATABASE_URL")
                    == "postgresql+asyncpg://svc_user:svc_pass@localhost:5432/svc_db"
                    for env in bootstrap_envs
                )
            )
            self.assertTrue(any(env.get("DB_USER") == "svc_user" for env in bootstrap_envs))
            self.assertTrue(any(env.get("DB_PASSWORD") == "svc_pass" for env in bootstrap_envs))
            self.assertTrue(any(env.get("DB_NAME") == "svc_db" for env in bootstrap_envs))

    def test_backend_env_file_is_loaded_and_app_env_file_is_exported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            (backend_dir / ".env").write_text(
                "CUSTOM_BACKEND_FLAG=enabled\nREDIS_URL=redis://legacy:6379/0\n",
                encoding="utf-8",
            )

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            bootstrap_envs = [env for env in fake_runner.run_envs if isinstance(env, dict)]
            self.assertTrue(
                any(
                    isinstance(env.get("APP_ENV_FILE"), str)
                    and Path(str(env.get("APP_ENV_FILE"))).resolve() == (backend_dir / ".env").resolve()
                    for env in bootstrap_envs
                )
            )
            self.assertTrue(any(env.get("CUSTOM_BACKEND_FLAG") == "enabled" for env in bootstrap_envs))

    def test_backend_env_override_file_preserves_database_url_and_sets_app_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            override_file = repo / "config" / "backend.override.env"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            override_file.parent.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            override_file.write_text(
                "DATABASE_URL=postgresql+psycopg2://override_user:override_pass@db.internal/override_db\n"
                "CUSTOM_BACKEND_FLAG=override-enabled\n",
                encoding="utf-8",
            )

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"BACKEND_ENV_FILE_OVERRIDE": str(override_file)},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            bootstrap_envs = [env for env in fake_runner.run_envs if isinstance(env, dict)]
            self.assertTrue(
                any(
                    env.get("DATABASE_URL")
                    == "postgresql+psycopg2://override_user:override_pass@db.internal/override_db"
                    for env in bootstrap_envs
                )
            )
            self.assertTrue(any(env.get("CUSTOM_BACKEND_FLAG") == "override-enabled" for env in bootstrap_envs))
            self.assertTrue(
                any(
                    isinstance(env.get("APP_ENV_FILE"), str)
                    and Path(str(env.get("APP_ENV_FILE"))).resolve() == override_file.resolve()
                    for env in bootstrap_envs
                )
            )
            self.assertIn(
                "DATABASE_URL=postgresql+psycopg2://override_user:override_pass@db.internal/override_db",
                override_file.read_text(encoding="utf-8"),
            )

    def test_main_env_file_path_applies_backend_env_override_in_main_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "backend"
            main_env_file = repo / "config" / "main.backend.env"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            main_env_file.parent.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            main_env_file.write_text(
                "DATABASE_URL=postgresql+psycopg2://main_user:main_pass@main.db.internal/main_db\n",
                encoding="utf-8",
            )

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"MAIN_ENV_FILE_PATH": str(main_env_file)},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--main", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            bootstrap_envs = [env for env in fake_runner.run_envs if isinstance(env, dict)]
            self.assertTrue(
                any(
                    env.get("DATABASE_URL")
                    == "postgresql+psycopg2://main_user:main_pass@main.db.internal/main_db"
                    for env in bootstrap_envs
                )
            )
            self.assertTrue(
                any(
                    isinstance(env.get("APP_ENV_FILE"), str)
                    and Path(str(env.get("APP_ENV_FILE"))).resolve() == main_env_file.resolve()
                    for env in bootstrap_envs
                )
            )

    def test_backend_env_file_upserts_database_url_and_preserves_existing_redis_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            env_file = backend_dir / ".env"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            env_file.write_text(
                "KEEP_ME=1\nDATABASE_URL=postgresql://legacy\nREDIS_URL=redis://legacy\n",
                encoding="utf-8",
            )

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "DB_USER": "svc_user",
                    "DB_PASSWORD": "svc_pass",
                    "DB_NAME": "svc_db",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            content = env_file.read_text(encoding="utf-8")
            self.assertIn("KEEP_ME=1", content)
            self.assertIn("DATABASE_URL=postgresql+asyncpg://svc_user:svc_pass@localhost:5432/svc_db", content)
            self.assertIn("REDIS_URL=redis://legacy", content)

    def test_backend_service_start_env_includes_backend_env_file_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / ".env").write_text("CUSTOM_BACKEND_FLAG=enabled\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            backend_start_envs = [
                env
                for (cmd, _cwd), env in zip(fake_runner.start_background_calls, fake_runner.start_background_envs)
                if isinstance(env, dict) and "backend" in " ".join(cmd).lower()
            ]
            if not backend_start_envs:
                backend_start_envs = [env for env in fake_runner.start_background_envs if isinstance(env, dict)]
            self.assertTrue(any(env.get("CUSTOM_BACKEND_FLAG") == "enabled" for env in backend_start_envs))
            self.assertTrue(
                any(
                    isinstance(env.get("APP_ENV_FILE"), str)
                    and Path(str(env.get("APP_ENV_FILE"))).name == ".env"
                    for env in backend_start_envs
                )
            )

    def test_frontend_env_override_file_is_loaded_for_service_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            frontend_dir = repo / "trees" / "feature-a" / "1" / "frontend"
            frontend_override = repo / "config" / "frontend.override.env"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            frontend_dir.mkdir(parents=True, exist_ok=True)
            frontend_override.parent.mkdir(parents=True, exist_ok=True)
            frontend_override.write_text("CUSTOM_FRONTEND_FLAG=enabled\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"FRONTEND_ENV_FILE_OVERRIDE": str(frontend_override)},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            frontend_start_envs = [env for env in fake_runner.start_background_envs if isinstance(env, dict)]
            self.assertTrue(frontend_start_envs)
            self.assertTrue(any(env.get("CUSTOM_FRONTEND_FLAG") == "enabled" for env in frontend_start_envs))

    def test_startup_uses_configured_backend_and_frontend_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "api"
            frontend_dir = repo / "web"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            frontend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            (frontend_dir / "package.json").write_text(
                json.dumps({"name": "web", "scripts": {"dev": "vite"}}),
                encoding="utf-8",
            )
            (frontend_dir / "node_modules" / ".bin").mkdir(parents=True, exist_ok=True)
            (frontend_dir / "node_modules" / ".bin" / "vite").write_text("#!/bin/sh\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(
                    repo,
                    runtime,
                    extra={"BACKEND_DIR": "api", "FRONTEND_DIR": "web"},
                ),
                env={},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]

            code = engine.dispatch(parse_route(["--main", "--batch"], env={}))

            self.assertEqual(code, 0)
            cwd_values = {Path(cwd).resolve() for _cmd, cwd in fake_runner.start_background_calls}
            self.assertIn(backend_dir.resolve(), cwd_values)
            self.assertIn(frontend_dir.resolve(), cwd_values)

    def test_main_frontend_env_file_path_is_loaded_in_main_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "backend"
            frontend_dir = repo / "frontend"
            main_frontend_env = repo / "config" / "main.frontend.env"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            frontend_dir.mkdir(parents=True, exist_ok=True)
            main_frontend_env.parent.mkdir(parents=True, exist_ok=True)
            main_frontend_env.write_text("MAIN_FRONTEND_FLAG=active\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"MAIN_FRONTEND_ENV_FILE_PATH": str(main_frontend_env)},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--main", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            frontend_start_envs = [env for env in fake_runner.start_background_envs if isinstance(env, dict)]
            self.assertTrue(frontend_start_envs)
            self.assertTrue(any(env.get("MAIN_FRONTEND_FLAG") == "active" for env in frontend_start_envs))

    def test_frontend_api_env_is_injected_and_env_local_is_synced_per_project_backend_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            frontend_dir = repo / "trees" / "feature-a" / "1" / "frontend"
            env_local = frontend_dir / ".env.local"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            frontend_dir.mkdir(parents=True, exist_ok=True)
            (frontend_dir / "package.json").write_text(
                json.dumps({"name": "frontend", "scripts": {"dev": "vite"}}),
                encoding="utf-8",
            )
            (frontend_dir / "node_modules" / ".bin").mkdir(parents=True, exist_ok=True)
            (frontend_dir / "node_modules" / ".bin" / "vite").write_text("#!/bin/sh\n", encoding="utf-8")
            env_local.write_text("VITE_API_URL=http://localhost:9999/api/v1\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            plans = self._planned_ports(engine, "feature-a-1")
            expected_backend_url = f"http://localhost:{plans['backend'].final}"
            expected_api_url = f"http://localhost:{plans['backend'].final}/api/v1"
            synced = env_local.read_text(encoding="utf-8")
            self.assertIn(f"VITE_BACKEND_URL={expected_backend_url}", synced)
            self.assertIn(f"VITE_API_URL={expected_api_url}", synced)

            frontend_envs = [
                env
                for (_cmd, cwd), env in zip(fake_runner.start_background_calls, fake_runner.start_background_envs)
                if str(cwd).endswith("/frontend") and isinstance(env, dict)
            ]
            self.assertTrue(frontend_envs)
            self.assertEqual(frontend_envs[0].get("VITE_BACKEND_URL"), expected_backend_url)
            self.assertEqual(frontend_envs[0].get("VITE_API_URL"), expected_api_url)

    def test_frontend_bootstrap_installs_dependencies_when_node_modules_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            frontend_dir = repo / "trees" / "feature-a" / "1" / "frontend"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            frontend_dir.mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            (frontend_dir / "package.json").write_text(
                json.dumps({"name": "feature-a-frontend", "scripts": {"dev": "vite"}}),
                encoding="utf-8",
            )
            (frontend_dir / "package-lock.json").write_text("{}", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine._command_exists = (  # type: ignore[attr-defined]
                lambda executable: "/" in executable or executable in {"npm", "python3.12", "python3", "python", "sh"}
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            npm_calls = [cmd for cmd, _cwd in fake_runner.run_calls if cmd and cmd[0] == "npm"]
            self.assertTrue(any(cmd[:2] == ("npm", "ci") for cmd in npm_calls), msg=str(npm_calls))

    def test_frontend_bootstrap_skips_install_when_vite_binary_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            frontend_dir = repo / "trees" / "feature-a" / "1" / "frontend"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            vite_bin = frontend_dir / "node_modules" / ".bin" / "vite"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            frontend_dir.mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            vite_bin.parent.mkdir(parents=True, exist_ok=True)
            vite_bin.write_text("#!/bin/sh\n", encoding="utf-8")
            (frontend_dir / "package.json").write_text(
                json.dumps({"name": "feature-a-frontend", "scripts": {"dev": "vite"}}),
                encoding="utf-8",
            )
            (frontend_dir / "package-lock.json").write_text("{}", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine._command_exists = (  # type: ignore[attr-defined]
                lambda executable: "/" in executable or executable in {"npm", "python3.12", "python3", "python", "sh"}
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            npm_calls = [cmd for cmd, _cwd in fake_runner.run_calls if cmd and cmd[0] == "npm"]
            self.assertEqual(npm_calls, [])

    def test_service_listener_failure_detail_includes_log_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeProcessRunner()
            fake_runner.pid_running_result = False
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            log_path = Path(tmpdir) / "frontend.log"
            log_path.write_text('error: script "dev" exited with code 127\n', encoding="utf-8")

            detail = engine._service_listener_failure_detail(log_path=str(log_path), pid=4242)

            self.assertIsInstance(detail, str)
            assert isinstance(detail, str)
            self.assertIn("process 4242 exited", detail)
            self.assertIn(f"log_path: {log_path}", detail)
            self.assertIn('log: error: script "dev" exited with code 127', detail)

    def test_backend_alembic_failure_is_soft_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            (backend_dir / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.fail_alembic = True
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            output = out.getvalue()
            self.assertIn("Warning: backend migration step failed", output)
            self.assertIn("backend log:", output)

    def test_backend_alembic_missing_revision_warning_includes_actionable_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            (backend_dir / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.fail_alembic = True
            fake_runner.alembic_error_text = (
                "ERROR [alembic.util.messaging] Can't locate revision identified by 'e6f7a8b9c0d1'"
            )
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            output = out.getvalue()
            self.assertIn("Warning: backend migration step failed", output)
            self.assertIn("backend log:", output)
            self.assertIn("hint: alembic revision e6f7a8b9c0d1 is missing", output)

    def test_backend_alembic_failure_is_hard_when_bootstrap_strict_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            (backend_dir / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "ENVCTL_BACKEND_BOOTSTRAP_STRICT": "true",
                    "BACKEND_ENV_FILE_OVERRIDE": str(backend_dir / ".env"),
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.fail_alembic = True
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("backend bootstrap failed", out.getvalue())

    def test_backend_alembic_async_driver_mismatch_retries_with_asyncpg_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("sqlalchemy==2.0.31\nalembic==1.13.2\n", encoding="utf-8")
            (backend_dir / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
            (backend_dir / ".env").write_text(
                "DATABASE_URL=postgresql+psycopg2://svc_user:svc_pass@localhost:5432/svc_db\n",
                encoding="utf-8",
            )

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "ENVCTL_BACKEND_BOOTSTRAP_STRICT": "true",
                    "BACKEND_ENV_FILE_OVERRIDE": str(backend_dir / ".env"),
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.fail_alembic_async_mismatch_once = True
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            alembic_envs = [
                env
                for (cmd, _cwd), env in zip(fake_runner.run_calls, fake_runner.run_envs)
                if tuple(cmd[-3:]) == ("alembic", "upgrade", "head") and isinstance(env, dict)
            ]
            self.assertGreaterEqual(len(alembic_envs), 2)
            self.assertTrue(any("psycopg2" in str(env.get("DATABASE_URL", "")) for env in alembic_envs))
            self.assertTrue(any("postgresql+asyncpg://" in str(env.get("DATABASE_URL", "")) for env in alembic_envs))

    def test_startup_fails_when_requirements_are_unavailable_in_strict_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "ENVCTL_REQUIREMENT_REDIS_CMD": "sh -lc 'exit 1'",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertEqual(fake_runner.start_background_calls, [])

    def test_requirements_exit_zero_without_listener_fails_readiness_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "ENVCTL_REQUIREMENT_POSTGRES_CMD": "sh -lc 'exit 0'",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = False
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("probe timeout", out.getvalue())
            self.assertEqual(fake_runner.start_background_calls, [])

    def test_requirement_listener_probe_timeout_honors_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "ENVCTL_REQUIREMENT_POSTGRES_CMD": "sh -lc 'exit 0'",
                    "ENVCTL_REQUIREMENT_LISTENER_TIMEOUT_SECONDS": "25",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = False
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("probe timeout", out.getvalue())
            plans = self._planned_ports(engine, "feature-a-1")
            self.assertTrue(
                any(port == plans["db"].final and timeout == 25.0 for port, timeout in fake_runner.wait_for_port_calls),
                msg=fake_runner.wait_for_port_calls,
            )

    def test_startup_recovers_when_bind_conflicts_exceed_default_retry_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "ENVCTL_BACKEND_START_CMD": "sh -lc true",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_POSTGRES_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_REDIS_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_N8N_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_BIND_MAX_RETRIES": "8",
                    "ENVCTL_TEST_CONFLICT_POSTGRES": "4",
                    "ENVCTL_TEST_CONFLICT_REDIS": "4",
                    "ENVCTL_TEST_CONFLICT_N8N": "4",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            state = engine._try_load_existing_state(mode="trees")
            self.assertIsNotNone(state)
            assert state is not None
            requirements = state.requirements["feature-a-1"]
            self.assertGreaterEqual(int(requirements.db.get("retries", 0)), 4)
            self.assertGreaterEqual(int(requirements.redis.get("retries", 0)), 4)
            self.assertGreaterEqual(int(requirements.n8n.get("retries", 0)), 4)
            self.assertNotIn("Requirements unavailable", out.getvalue())

    def test_startup_allows_at_least_one_bind_retry_when_bind_retry_budget_is_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "ENVCTL_BACKEND_START_CMD": "sh -lc true",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_POSTGRES_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_REDIS_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_N8N_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_BIND_MAX_RETRIES": "0",
                    "ENVCTL_TEST_CONFLICT_POSTGRES": "1",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            state = engine._try_load_existing_state(mode="trees")
            self.assertIsNotNone(state)
            assert state is not None
            requirements = state.requirements["feature-a-1"]
            self.assertGreaterEqual(int(requirements.db.get("retries", 0)), 1)
            retry_events = [
                event
                for event in engine.events
                if event.get("event") == "requirements.retry" and event.get("service") == "postgres"
            ]
            self.assertTrue(retry_events, msg=engine.events)
            self.assertNotIn("Requirements unavailable", out.getvalue())

    def test_startup_emits_requirements_retry_events_for_bind_conflict_retries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "ENVCTL_REQUIREMENT_POSTGRES_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_REDIS_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_N8N_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_SUPABASE_CMD": "sh -lc true",
                    "ENVCTL_BACKEND_START_CMD": "sh -lc true",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc true",
                    "ENVCTL_TEST_CONFLICT_POSTGRES": "1",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            retry_events = [event for event in engine.events if event.get("event") == "requirements.retry"]
            self.assertTrue(retry_events)
            postgres_events = [event for event in retry_events if event.get("service") == "postgres"]
            self.assertTrue(postgres_events)
            latest = postgres_events[-1]
            self.assertEqual(latest.get("project"), "feature-a-1")
            self.assertEqual(latest.get("failure_class"), "bind_conflict_retryable")
            self.assertIsInstance(latest.get("failed_port"), int)
            self.assertIsInstance(latest.get("retry_port"), int)
            self.assertIsInstance(latest.get("attempt"), int)

    def test_startup_emits_service_retry_events_for_backend_and_frontend_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "ENVCTL_BACKEND_START_CMD": "sh -lc true",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_POSTGRES_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_REDIS_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_N8N_CMD": "sh -lc true",
                    "ENVCTL_TEST_CONFLICT_BACKEND": "1",
                    "ENVCTL_TEST_CONFLICT_FRONTEND": "1",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            retry_events = [event for event in engine.events if event.get("event") == "service.retry"]
            self.assertTrue(retry_events)
            self.assertTrue(any(event.get("service") == "backend" for event in retry_events))
            self.assertTrue(any(event.get("service") == "frontend" for event in retry_events))
            for event in retry_events:
                self.assertIsInstance(event.get("failed_port"), int)
                self.assertIsInstance(event.get("retry_port"), int)
                self.assertIsInstance(event.get("attempt"), int)

    def test_frontend_rebound_delta_uses_pid_scoped_listener_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            config = self._config(
                repo,
                runtime,
                extra={"ENVCTL_RUNTIME_TRUTH_MODE": "strict"},
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_TEST_FRONTEND_REBOUND_DELTA": "2",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            plans = self._planned_ports(engine, "feature-a-1")
            preferred_frontend = plans["frontend"].final
            fake_runner.wait_for_port_overrides[preferred_frontend + 2] = False
            fake_runner.wait_for_pid_port_overrides[preferred_frontend + 2] = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            runtime_map = (runtime / "python-engine" / "runtime_map.json").read_text(encoding="utf-8")
            self.assertIn(f'"frontend_port": {preferred_frontend + 2}', runtime_map)

    def test_frontend_rebound_delta_reserves_busy_launch_ports_before_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            config = self._config(
                repo,
                runtime,
                extra={"ENVCTL_RUNTIME_TRUTH_MODE": "strict"},
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_TEST_FRONTEND_REBOUND_DELTA": "200",
                },
            )
            blocked_launch_ports = {9200, 9201, 9202, 9203}
            engine.port_planner.availability_checker = lambda port: port not in blocked_launch_ports
            fake_runner = _FakeProcessRunner()
            fake_runner.auto_track_listener_ports = True
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = False
            fake_runner.fail_start_ports.update(blocked_launch_ports)
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            started_ports = {
                int(env["PORT"])
                for env in fake_runner.start_background_envs
                if isinstance(env, dict) and isinstance(env.get("PORT"), str)
            }
            self.assertTrue(blocked_launch_ports.isdisjoint(started_ports), started_ports)
            self.assertIn(9204, started_ports)
            runtime_map = (runtime / "python-engine" / "runtime_map.json").read_text(encoding="utf-8")
            self.assertIn('"frontend_port": 9204', runtime_map)

    def test_frontend_actual_port_discovery_handles_auto_rebound_without_test_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            config = self._config(
                repo,
                runtime,
                extra={"ENVCTL_RUNTIME_TRUTH_MODE": "strict"},
            )
            engine = PythonEngineRuntime(config, env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            plans = self._planned_ports(engine, "feature-a-1")
            preferred_frontend = plans["frontend"].final
            fake_runner.wait_for_pid_port_overrides[preferred_frontend] = False
            fake_runner.find_pid_listener_port_overrides[preferred_frontend] = preferred_frontend + 4
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            runtime_map = (runtime / "python-engine" / "runtime_map.json").read_text(encoding="utf-8")
            self.assertIn(f'"frontend_port": {preferred_frontend + 4}', runtime_map)
            self.assertTrue(any(call[1] == preferred_frontend for call in fake_runner.find_pid_listener_port_calls))

    def test_main_requirement_toggles_are_respected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "true",
                    "REDIS_MAIN_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                    "N8N_ENABLE": "true",
                    "N8N_MAIN_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            main_context = engine._discover_projects(mode="main")[0]

            requirements = engine._start_requirements_for_project(main_context, mode="main")

            self.assertFalse(requirements.db["enabled"])
            self.assertFalse(requirements.redis["enabled"])
            self.assertFalse(requirements.n8n["enabled"])
            self.assertFalse(requirements.supabase["enabled"])

    def test_main_services_local_flag_overrides_main_requirements_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = self._config(repo, runtime)
            engine = PythonEngineRuntime(config, env={})
            route = parse_route(["--main", "--main-services-local"], env={})

            self.assertFalse(engine._requirement_enabled("postgres", mode="main", route=route))
            self.assertTrue(engine._requirement_enabled("redis", mode="main", route=route))
            self.assertTrue(engine._requirement_enabled("n8n", mode="main", route=route))
            self.assertTrue(engine._requirement_enabled("supabase", mode="main", route=route))

    def test_main_services_remote_flag_disables_supabase_and_n8n(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "SUPABASE_MAIN_ENABLE": "true",
                    "N8N_MAIN_ENABLE": "true",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            route = parse_route(["--main", "--main-services-remote"], env={})

            self.assertFalse(engine._requirement_enabled("supabase", mode="main", route=route))
            self.assertFalse(engine._requirement_enabled("n8n", mode="main", route=route))
            self.assertTrue(engine._requirement_enabled("postgres", mode="main", route=route))

    def test_conflicting_main_requirements_flags_fail_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            route = parse_route(["--main-services-local", "--main-services-remote", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("Conflicting main requirements flags", out.getvalue())

    def test_command_resolution_fails_without_real_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})

            with self.assertRaises(RuntimeError):
                engine._requirement_command(service_name="postgres", port=5432)
            with self.assertRaises(RuntimeError):
                engine._service_start_command(service_name="backend")
            with self.assertRaises(RuntimeError):
                engine._service_start_command(service_name="frontend")

    def test_requirements_non_strict_allows_missing_requirement_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = self._config(
                repo,
                runtime,
                extra={"ENVCTL_REQUIREMENTS_STRICT": "false"},
                include_commands=False,
            )
            engine = PythonEngineRuntime(config, env={})
            engine.port_planner.availability_checker = lambda _port: True
            engine._command_exists = lambda _name: False

            plan = PortPlan(project="proj", requested=5432, assigned=5432, final=5432, source="test")
            context = ProjectContext(name="proj", root=repo, ports={"db": plan, "redis": plan, "n8n": plan, "supabase": plan, "backend": plan, "frontend": plan})

            outcome = engine._start_requirement_component(
                context,
                "postgres",
                plan,
                reserve_next=lambda port: port,
                route=None,
            )

            self.assertFalse(outcome.success)
            self.assertIn("missing_requirement_start_command", str(outcome.error))

    def test_startup_fails_without_real_commands_even_when_synthetic_envs_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "strict",
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_SYNTHETIC_TEST_MODE": "true",
                    "ENVCTL_SYNTHETIC_TEST_CONTEXT": "true",
                },
            )
            route = parse_route(["start", "--main", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("missing_service_start_command", out.getvalue())

    def test_requirements_use_native_adapters_before_command_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            engine._command_exists = lambda command: command == "docker"  # type: ignore[method-assign]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertNotIn("missing_requirement_start_command", out.getvalue())
            self.assertIn("missing_service_start_command", out.getvalue())
            self.assertTrue(any(call[0][:2] == ("docker", "ps") for call in fake_runner.run_calls))

    def test_start_fails_when_duplicate_project_identities_are_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a-1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("Duplicate project identities detected", out.getvalue())

    def test_startup_fails_with_actionable_error_when_no_real_service_commands_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertNotIn("missing_requirement_start_command", out.getvalue())
            self.assertIn("missing_service_start_command", out.getvalue())
            self.assertEqual(fake_runner.start_background_calls, [])

    def test_startup_records_real_commands_without_synthetic_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            state = engine._try_load_existing_state(mode="trees")
            self.assertIsNotNone(state)
            assert state is not None
            backend = state.services["feature-a-1 Backend"]
            frontend = state.services["feature-a-1 Frontend"]
            self.assertNotEqual(backend.status, "simulated")
            self.assertNotEqual(frontend.status, "simulated")
            self.assertFalse(state.requirements["feature-a-1"].db.get("simulated"))
            self.assertFalse(state.requirements["feature-a-1"].redis.get("simulated"))
            self.assertFalse(state.requirements["feature-a-1"].n8n.get("simulated"))
            self.assertNotIn("synthetic placeholder defaults", out.getvalue())

    def test_plan_planning_prs_runs_pr_action_and_skips_startup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_ACTION_PR_CMD": "sh -lc 'exit 0'"},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--planning-prs", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(fake_runner.start_background_calls, [])
            self.assertTrue(
                any(
                    len(call[0]) >= 2 and call[0][0] == "sh" and call[0][1] == "-lc"
                    for call in fake_runner.run_calls
                )
            )
            self.assertIn("Planning PR mode complete; skipping service startup.", out.getvalue())

    def test_plan_planning_prs_uses_default_pr_command_and_skips_startup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (repo / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--planning-prs", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(fake_runner.start_background_calls, [])
            self.assertIn("Planning PR mode complete; skipping service startup.", out.getvalue())

    def test_service_log_and_runner_flags_are_forwarded_to_service_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(
                [
                    "--plan",
                    "feature-a",
                    "--batch",
                    "--log-profile",
                    "debug",
                    "--log-level",
                    "info",
                    "--backend-log-level",
                    "warn",
                    "--frontend-log-profile",
                    "quiet",
                    "--frontend-test-runner",
                    "bun",
                ],
                env={},
            )

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertGreaterEqual(len(fake_runner.start_background_envs), 2)
            backend_env = fake_runner.start_background_envs[0] or {}
            frontend_env = fake_runner.start_background_envs[1] or {}
            self.assertEqual(backend_env.get("LOG_PROFILE_OVERRIDE"), "debug")
            self.assertEqual(backend_env.get("LOG_LEVEL_OVERRIDE"), "info")
            self.assertEqual(backend_env.get("BACKEND_LOG_LEVEL_OVERRIDE"), "warn")
            self.assertEqual(frontend_env.get("FRONTEND_LOG_PROFILE_OVERRIDE"), "quiet")
            self.assertEqual(frontend_env.get("FRONTEND_TEST_RUNNER"), "bun")

    def test_runtime_env_overrides_forward_docker_and_setup_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            route = parse_route(
                [
                    "--plan",
                    "feature-a",
                    "--docker",
                    "--setup-worktree-existing",
                    "--recreate-existing-worktree",
                    "--setup-include-worktrees",
                    "feature-a-1,feature-a-2",
                    "--seed-requirements-from-base",
                    "--stop-all-remove-volumes",
                ],
                env={},
            )

            env = engine._runtime_env_overrides(route)

            self.assertEqual(env.get("DOCKER_MODE"), "true")
            self.assertEqual(env.get("SETUP_WORKTREE_EXISTING"), "true")
            self.assertEqual(env.get("SETUP_WORKTREE_RECREATE"), "true")
            self.assertEqual(env.get("SETUP_INCLUDE_WORKTREES_RAW"), "feature-a-1,feature-a-2")
            self.assertEqual(env.get("SEED_REQUIREMENTS_FROM_BASE"), "true")
            self.assertEqual(env.get("RUN_SH_COMMAND_STOP_ALL_REMOVE_VOLUMES"), "true")

            route_no_seed = parse_route(
                [
                    "--plan",
                    "feature-a",
                    "--no-seed-requirements-from-base",
                ],
                env={},
            )
            env_no_seed = engine._runtime_env_overrides(route_no_seed)
            self.assertEqual(env_no_seed.get("SEED_REQUIREMENTS_FROM_BASE"), "false")

    def test_parallel_trees_flag_uses_parallel_startup_execution_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-b" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a,feature-b", "--parallel-trees", "--parallel-trees-max", "2", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            execution_events = [event for event in engine.events if event.get("event") == "startup.execution"]
            self.assertTrue(execution_events)
            latest = execution_events[-1]
            self.assertEqual(latest.get("mode"), "parallel")
            self.assertEqual(latest.get("workers"), 2)

    def test_startup_defaults_to_parallel_backend_frontend_attach(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]

            code = engine.dispatch(parse_route(["--batch"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            attach_events = [event for event in engine.events if event.get("event") == "service.attach.execution"]
            self.assertTrue(attach_events)
            self.assertEqual(attach_events[-1].get("mode"), "parallel")

    def test_service_sequential_flag_forces_sequential_backend_frontend_attach(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]

            code = engine.dispatch(
                parse_route(
                    ["--batch", "--service-sequential"],
                    env={"ENVCTL_DEFAULT_MODE": "main"},
                )
            )

            self.assertEqual(code, 0)
            attach_events = [event for event in engine.events if event.get("event") == "service.attach.execution"]
            self.assertTrue(attach_events)
            self.assertEqual(attach_events[-1].get("mode"), "sequential")

    def test_plan_mode_defaults_to_parallel_startup_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-b" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a,feature-b", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            execution_events = [event for event in engine.events if event.get("event") == "startup.execution"]
            self.assertTrue(execution_events)
            latest = execution_events[-1]
            self.assertEqual(latest.get("mode"), "parallel")
            self.assertEqual(latest.get("workers"), 2)

    def test_plan_mode_parallel_default_caps_workers_at_four(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            for branch in ("feature-a", "feature-b", "feature-c", "feature-d", "feature-e", "feature-f"):
                (repo / "trees" / branch / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(
                ["--plan", "feature-a,feature-b,feature-c,feature-d,feature-e,feature-f", "--batch"],
                env={},
            )

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            execution_events = [event for event in engine.events if event.get("event") == "startup.execution"]
            self.assertTrue(execution_events)
            latest = execution_events[-1]
            self.assertEqual(latest.get("mode"), "parallel")
            self.assertEqual(latest.get("workers"), 4)

    def test_no_parallel_trees_flag_forces_sequential_startup_execution_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-b" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={"RUN_SH_OPT_PARALLEL_TREES": "true"})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a,feature-b", "--no-parallel-trees", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            execution_events = [event for event in engine.events if event.get("event") == "startup.execution"]
            self.assertTrue(execution_events)
            latest = execution_events[-1]
            self.assertEqual(latest.get("mode"), "sequential")
            self.assertEqual(latest.get("workers"), 1)

    def test_start_trees_env_false_forces_sequential_startup_execution_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-b" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={"RUN_SH_OPT_PARALLEL_TREES": "false"})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(
                ["--trees", "--project", "feature-a-1", "--project", "feature-b-1", "--batch"],
                env={},
            )

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            execution_events = [event for event in engine.events if event.get("event") == "startup.execution"]
            self.assertTrue(execution_events)
            latest = execution_events[-1]
            self.assertEqual(latest.get("mode"), "sequential")
            self.assertEqual(latest.get("workers"), 1)

    def test_plan_ignores_parallel_trees_env_false_unless_explicitly_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-b" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={"RUN_SH_OPT_PARALLEL_TREES": "false"})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a,feature-b", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            execution_events = [event for event in engine.events if event.get("event") == "startup.execution"]
            self.assertTrue(execution_events)
            latest = execution_events[-1]
            self.assertEqual(latest.get("mode"), "parallel")
            self.assertEqual(latest.get("workers"), 2)

    def test_setup_worktrees_switches_start_to_trees_mode_and_targets_new_feature(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeSetupWorktreeRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--setup-worktrees", "feature-a", "2", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            route_events = [event for event in engine.events if event.get("event") == "command.route.selected"]
            self.assertTrue(route_events)
            latest_route = route_events[-1]
            self.assertEqual(latest_route.get("mode"), "main")
            self.assertEqual(latest_route.get("effective_mode"), "trees")
            state = engine._try_load_existing_state(mode="trees")
            self.assertIsNotNone(state)
            assert state is not None
            self.assertEqual(state.mode, "trees")
            project_roots = state.metadata.get("project_roots", {})
            self.assertIsInstance(project_roots, dict)
            self.assertIn("feature-a-1", project_roots)
            self.assertIn("feature-a-2", project_roots)
            self.assertIn("feature-a-1 Backend", state.services)
            self.assertIn("feature-a-2 Backend", state.services)

    def test_setup_worktree_existing_and_include_existing_filters_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "2").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-b" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(
                [
                    "--setup-worktree",
                    "feature-a",
                    "1",
                    "--setup-worktree-existing",
                    "--setup-include-worktrees",
                    "2",
                    "--batch",
                ],
                env={},
            )

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            state = engine._try_load_existing_state(mode="trees")
            self.assertIsNotNone(state)
            assert state is not None
            roots = state.metadata.get("project_roots", {})
            self.assertIsInstance(roots, dict)
            self.assertIn("feature-a-1", roots)
            self.assertIn("feature-a-2", roots)
            self.assertNotIn("feature-b-1", roots)

    def test_setup_worktree_existing_path_requires_existing_or_recreate_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--setup-worktree", "feature-a", "1", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("already exists", out.getvalue())

    def test_setup_worktree_uses_flat_trees_feature_root_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees-feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(
                [
                    "--setup-worktree",
                    "feature-a",
                    "1",
                    "--setup-worktree-existing",
                    "--batch",
                ],
                env={},
            )

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            state = engine._try_load_existing_state(mode="trees")
            self.assertIsNotNone(state)
            assert state is not None
            roots = state.metadata.get("project_roots", {})
            self.assertIsInstance(roots, dict)
            self.assertEqual(
                Path(str(roots.get("feature-a-1", ""))).resolve(),
                (repo / "trees-feature-a" / "1").resolve(),
            )
            self.assertIn("feature-a-1 Backend", state.services)

    def test_setup_worktrees_prefers_existing_flat_feature_root_for_new_iterations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees-feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeSetupWorktreeRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--setup-worktrees", "feature-a", "1", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            state = engine._try_load_existing_state(mode="trees")
            self.assertIsNotNone(state)
            assert state is not None
            roots = state.metadata.get("project_roots", {})
            self.assertIsInstance(roots, dict)
            self.assertEqual(
                Path(str(roots.get("feature-a-2", ""))).resolve(),
                (repo / "trees-feature-a" / "2").resolve(),
            )

    def test_setup_worktrees_parallel_flags_apply_in_effective_trees_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeSetupWorktreeRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(
                [
                    "--setup-worktrees",
                    "feature-a",
                    "2",
                    "--parallel-trees",
                    "--parallel-trees-max",
                    "2",
                    "--batch",
                ],
                env={},
            )

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            execution_events = [event for event in engine.events if event.get("event") == "startup.execution"]
            self.assertTrue(execution_events)
            latest = execution_events[-1]
            self.assertEqual(latest.get("mode"), "parallel")
            self.assertEqual(latest.get("workers"), 2)

    def test_setup_worktrees_use_trees_requirement_policy_not_main_route_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = self._config(
                repo,
                runtime,
                extra={
                    "N8N_ENABLE": "true",
                    "N8N_MAIN_ENABLE": "true",
                },
            )
            engine = PythonEngineRuntime(config, env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeSetupWorktreeRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(
                [
                    "--setup-worktrees",
                    "feature-a",
                    "1",
                    "--main-services-remote",
                    "--batch",
                ],
                env={},
            )

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            state = engine._try_load_existing_state(mode="trees")
            self.assertIsNotNone(state)
            assert state is not None
            requirements = state.requirements.get("feature-a-1")
            self.assertIsNotNone(requirements)
            assert requirements is not None
            self.assertTrue(requirements.n8n.get("enabled"))

    def test_setup_worktrees_fails_when_git_worktree_add_fails_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeSetupWorktreeRunner(fail_worktree_add=True)
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--setup-worktrees", "feature-a", "1", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("failed creating worktree feature-a/1", out.getvalue().lower())
            self.assertFalse((repo / "trees" / "feature-a" / "1" / ".envctl_worktree_placeholder").exists())

    def test_setup_worktrees_placeholder_fallback_can_be_enabled_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true"},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeSetupWorktreeRunner(fail_worktree_add=True)
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--setup-worktrees", "feature-a", "1", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertTrue((repo / "trees" / "feature-a" / "1" / ".envctl_worktree_placeholder").exists())
            fallback_events = [event for event in engine.events if event.get("event") == "setup.worktree.placeholder_fallback"]
            self.assertTrue(fallback_events)

    def test_plan_without_selection_and_without_planning_files_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            route = parse_route(["--plan"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 1)

    def test_plan_without_selection_uses_interactive_planning_choice_when_tty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "docs" / "planning" / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "docs" / "planning" / "backend" / "task.md").write_text("# task\n", encoding="utf-8")
            (repo / "trees" / "backend_task" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan"], env={})

            with (
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False),
                patch.object(engine, "_run_planning_selection_menu", return_value={"backend/task.md": 1}),
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0),
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)

    def test_start_enters_interactive_dashboard_loop_in_tty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a"], env={})

            with (
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False),
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0) as loop_mock,
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(loop_mock.call_count, 1)

    def test_start_skips_interactive_dashboard_loop_in_batch_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            with (
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False),
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0) as loop_mock,
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(loop_mock.call_count, 0)

    def test_start_skips_interactive_dashboard_loop_under_bats_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a"], env={})

            with (
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch.dict(
                    os.environ,
                    {"TERM": "xterm-256color", "BATS_TEST_FILENAME": "/tmp/sample.bats"},
                    clear=False,
                ),
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0) as loop_mock,
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(loop_mock.call_count, 0)

    def test_plan_auto_resumes_existing_run_when_selected_projects_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )

            route = parse_route(["--plan", "feature-a", "--batch"], env={})
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_resume", return_value=0) as resume_mock,
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(resume_mock.call_count, 1)

    def test_plan_auto_resumes_existing_run_when_selected_projects_are_subset_of_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-b" / "1").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "feature-b-1 Backend": ServiceRecord(
                        name="feature-b-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=2222,
                        requested_port=8020,
                        actual_port=8020,
                        status="running",
                    ),
                },
            )

            route = parse_route(["--plan", "feature-a", "--batch"], env={})
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_resume", return_value=0) as resume_mock,
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(resume_mock.call_count, 1)

    def test_plan_skips_auto_resume_when_selected_projects_do_not_match_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-b" / "1").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )

            route = parse_route(["--plan", "feature-b", "--batch"], env={})
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_resume", return_value=0) as resume_mock,
                patch.object(engine, "_start_project_context", side_effect=RuntimeError("expected startup path")),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertEqual(resume_mock.call_count, 0)
            self.assertIn("expected startup path", out.getvalue())

    def test_main_start_does_not_auto_resume_trees_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            trees_state = RunState(
                run_id="run-trees",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )
            dump_state(trees_state, str(engine.state_repository.run_state_path()))

            route = parse_route(["--main", "--batch"], env={})
            with (
                patch.object(engine, "_resume", return_value=0) as resume_mock,
                patch.object(engine, "_discover_projects", return_value=[]),
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertEqual(resume_mock.call_count, 0)

    def test_plan_snapshot_emits_real_path_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "ENVCTL_DEBUG_PLAN_SNAPSHOT": "1",
                },
            )
            engine.process_runner = _FakeProcessRunner()  # type: ignore[attr-defined]

            requirements = RequirementsResult(
                project="feature-a-1",
                components={
                    "redis": {"enabled": True, "success": True, "health": "healthy"},
                },
                health="healthy",
                failures=[],
            )
            services = {
                "feature-a-1 Backend": ServiceRecord(
                    name="feature-a-1 Backend",
                    type="backend",
                    cwd=str(repo),
                    pid=1111,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
                "feature-a-1 Frontend": ServiceRecord(
                    name="feature-a-1 Frontend",
                    type="frontend",
                    cwd=str(repo),
                    pid=1112,
                    requested_port=9000,
                    actual_port=9000,
                    status="running",
                ),
            }

            route = parse_route(["--plan", "feature-a"], env={})
            with (
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0),
                patch.object(engine, "_start_project_context", return_value=(requirements, services)),
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            checkpoints = [
                event.get("checkpoint")
                for event in engine.events
                if event.get("event") == "ui.plan_handoff.snapshot"
            ]
            self.assertIn("plan_selector_exit", checkpoints)
            self.assertIn("startup_branch_enter", checkpoints)
            self.assertIn("before_dashboard_entry", checkpoints)

    def test_plan_no_resume_flag_disables_auto_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )

            route = parse_route(["--plan", "feature-a", "--no-resume", "--batch"], env={})
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_resume", return_value=0) as resume_mock,
                patch.object(engine, "_start_project_context", side_effect=RuntimeError("expected startup path")),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertEqual(resume_mock.call_count, 0)
            self.assertIn("expected startup path", out.getvalue())

    def test_start_does_not_auto_resume_non_resumable_service_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "backend": ServiceRecord(
                        name="backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )

            route = parse_route(["--debug-ui", "--batch"], env={})
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_resume", return_value=0) as resume_mock,
                patch.object(engine, "_discover_projects", return_value=[]),
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertEqual(resume_mock.call_count, 0)

    def test_resume_rejects_state_without_resumable_services(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "backend": ServiceRecord(
                        name="backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )

            route = parse_route(["--resume", "--interactive"], env={})
            output = StringIO()
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0) as loop_mock,
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False),
                redirect_stdout(output),
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertEqual(loop_mock.call_count, 0)
            self.assertIn("No active services to resume.", output.getvalue())

    def test_dashboard_interactive_flag_enters_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )

            route = parse_route(["--dashboard", "--interactive"], env={})
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False),
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0) as loop_mock,
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(loop_mock.call_count, 1)

    def test_dashboard_defaults_to_interactive_in_tty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )

            route = parse_route(["--dashboard"], env={})
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False),
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0) as loop_mock,
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(loop_mock.call_count, 1)

    def test_dashboard_non_interactive_flag_skips_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )

            route = parse_route(["--dashboard", "--non-interactive"], env={})
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False),
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0) as loop_mock,
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(loop_mock.call_count, 0)

    def test_resume_defaults_to_interactive_in_tty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )

            route = parse_route(["--resume"], env={})
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_reconcile_state_truth", return_value=[]),
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False),
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0) as loop_mock,
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(loop_mock.call_count, 1)

    def test_resume_batch_flag_skips_interactive_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )

            route = parse_route(["--resume", "--batch"], env={})
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_reconcile_state_truth", return_value=[]),
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False),
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0) as loop_mock,
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(loop_mock.call_count, 0)

    def test_start_prints_loading_progress_per_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--plan", "feature-a"], env={}))

            self.assertEqual(code, 0)
            output = out.getvalue()
            self.assertIn("Starting project feature-a-1", output)
            self.assertIn("Services ready for feature-a-1", output)

    def test_interactive_command_start_suppresses_loading_progress_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]

            route = parse_route(["--plan", "feature-a"], env={})
            route.flags = {**route.flags, "interactive_command": True, "batch": True}

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            output = out.getvalue()
            self.assertNotIn("Starting project feature-a-1", output)
            self.assertNotIn("Requirements ready for feature-a-1", output)
            self.assertNotIn("Services ready for feature-a-1", output)
            self.assertNotIn("envctl Python engine run summary", output)

    def test_dashboard_snapshot_uses_grouped_shell_like_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo / "trees" / "feature-a" / "1" / "backend"),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        log_path="/tmp/backend.log",
                        status="running",
                    ),
                    "feature-a-1 Frontend": ServiceRecord(
                        name="feature-a-1 Frontend",
                        type="frontend",
                        cwd=str(repo / "trees" / "feature-a" / "1" / "frontend"),
                        pid=2222,
                        requested_port=9000,
                        actual_port=9002,
                        log_path="/tmp/frontend.log",
                        status="running",
                    ),
                },
                requirements={
                    "feature-a-1": RequirementsResult(
                        project="feature-a-1",
                        n8n={"enabled": True, "success": True, "final": 5678},
                        health="healthy",
                    )
                },
            )

            out = StringIO()
            with (
                patch.object(engine, "_reconcile_state_truth", return_value=[]),
                redirect_stdout(out),
            ):
                engine._print_dashboard_snapshot(state)

            plain = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", out.getvalue())
            self.assertIn("Development Environment - Interactive Mode", plain)
            self.assertIn("Running Services:", plain)
            self.assertIn("feature-a-1", plain)
            self.assertIn("Backend: http://localhost:8000 (PID: 1111)", plain)
            self.assertIn("Frontend: http://localhost:9002 (PID: 2222)", plain)
            self.assertIn("log: /tmp/backend.log", plain)
            self.assertIn("log: /tmp/frontend.log", plain)
            self.assertIn("n8n: http://localhost:5678 [Healthy]", plain)

    def test_plan_without_selection_and_without_tty_fails_when_planning_files_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "docs" / "planning" / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "docs" / "planning" / "backend" / "task.md").write_text("# task\n", encoding="utf-8")
            (repo / "trees" / "backend_task" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            route = parse_route(["--plan"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 1)

    def test_initial_plan_selected_counts_prefers_existing_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            selected = engine._initial_plan_selected_counts(
                planning_files=["backend/task-a.md", "backend/task-b.md"],
                existing_counts={"backend/task-a.md": 2, "backend/task-b.md": 1},
            )
            self.assertEqual(selected, {"backend/task-a.md": 2, "backend/task-b.md": 1})

    def test_initial_plan_selected_counts_uses_memory_when_existing_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            memory_path = runtime / "python-engine" / "planning_selection.json"
            memory_path.parent.mkdir(parents=True, exist_ok=True)
            memory_path.write_text(
                json.dumps({"selected_counts": {"backend/task-a.md": 3}}, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            selected = engine._initial_plan_selected_counts(
                planning_files=["backend/task-a.md", "backend/task-b.md"],
                existing_counts={},
            )
            self.assertEqual(selected, {"backend/task-a.md": 3, "backend/task-b.md": 0})

    def test_planning_menu_apply_key_supports_arrow_navigation_and_count_adjustment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            planning_files = ["backend/task-a.md", "frontend/task-b.md"]
            selected_counts = {"backend/task-a.md": 0, "frontend/task-b.md": 2}
            existing_counts = {"backend/task-a.md": 1, "frontend/task-b.md": 0}
            cursor = 0

            cursor, action, _ = engine._planning_menu_apply_key(
                key="down",
                cursor=cursor,
                planning_files=planning_files,
                selected_counts=selected_counts,
                existing_counts=existing_counts,
            )
            self.assertEqual((cursor, action), (1, "continue"))
            cursor, _, _ = engine._planning_menu_apply_key(
                key="right",
                cursor=cursor,
                planning_files=planning_files,
                selected_counts=selected_counts,
                existing_counts=existing_counts,
            )
            self.assertEqual(selected_counts["frontend/task-b.md"], 3)
            cursor, _, _ = engine._planning_menu_apply_key(
                key="left",
                cursor=cursor,
                planning_files=planning_files,
                selected_counts=selected_counts,
                existing_counts=existing_counts,
            )
            self.assertEqual(selected_counts["frontend/task-b.md"], 2)
            cursor, _, _ = engine._planning_menu_apply_key(
                key="up",
                cursor=cursor,
                planning_files=planning_files,
                selected_counts=selected_counts,
                existing_counts=existing_counts,
            )
            self.assertEqual(cursor, 0)
            cursor, _, _ = engine._planning_menu_apply_key(
                key="space",
                cursor=cursor,
                planning_files=planning_files,
                selected_counts=selected_counts,
                existing_counts=existing_counts,
            )
            self.assertEqual(selected_counts["backend/task-a.md"], 1)
            cursor, _, _ = engine._planning_menu_apply_key(
                key="space",
                cursor=cursor,
                planning_files=planning_files,
                selected_counts=selected_counts,
                existing_counts=existing_counts,
            )
            self.assertEqual(selected_counts["backend/task-a.md"], 0)
            _, action, _ = engine._planning_menu_apply_key(
                key="enter",
                cursor=cursor,
                planning_files=planning_files,
                selected_counts=selected_counts,
                existing_counts=existing_counts,
            )
            self.assertEqual(action, "submit")

    def test_run_planning_selection_menu_flushes_pending_input_before_raw_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            planning_files = ["backend/task-a.md"]
            selected_counts = {"backend/task-a.md": 1}
            existing_counts = {"backend/task-a.md": 0}

            with (
                patch.object(engine, "_flush_pending_interactive_input") as flush_mock,
                patch(
                    "envctl_engine.planning.worktree_domain.select_planning_counts_textual",
                    return_value={"backend/task-a.md": 1},
                ) as selector_mock,
                redirect_stdout(StringIO()),
            ):
                chosen = engine._run_planning_selection_menu(
                    planning_files=planning_files,
                    selected_counts=selected_counts,
                    existing_counts=existing_counts,
                )

            self.assertEqual(chosen, {"backend/task-a.md": 1})
            self.assertEqual(flush_mock.call_count, 1)
            selector_mock.assert_called_once()

    def test_read_planning_menu_key_parses_modified_arrow_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            reads = [b"\x1b", b"[", b"1", b";", b"5", b"C"]

            def fake_read(_fd: int, _count: int) -> bytes:
                return reads.pop(0) if reads else b""

            def fake_selector(_r, _w, _x, _timeout):  # noqa: ANN001
                if reads:
                    return ([_r[0]], [], [])
                return ([], [], [])

            with patch("os.read", side_effect=fake_read):
                key = engine._read_planning_menu_key(fd=7, selector=fake_selector)

            self.assertEqual(key, "right")

    def test_read_planning_menu_key_treats_unknown_escape_sequence_as_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            reads = [b"\x1b", b"[", b"2", b"0", b"0", b"~"]

            def fake_read(_fd: int, _count: int) -> bytes:
                return reads.pop(0) if reads else b""

            def fake_selector(_r, _w, _x, _timeout):  # noqa: ANN001
                if reads:
                    return ([_r[0]], [], [])
                return ([], [], [])

            with patch("os.read", side_effect=fake_read):
                key = engine._read_planning_menu_key(fd=7, selector=fake_selector)

            self.assertEqual(key, "noop")

    def test_read_planning_menu_key_ignores_csi_fragment_without_escape_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            reads = [b"[", b"A"]

            def fake_read(_fd: int, _count: int) -> bytes:
                return reads.pop(0) if reads else b""

            def fake_selector(_r, _w, _x, _timeout):  # noqa: ANN001
                if reads:
                    return ([_r[0]], [], [])
                return ([], [], [])

            with patch("os.read", side_effect=fake_read):
                key = engine._read_planning_menu_key(fd=7, selector=fake_selector)

            self.assertEqual(key, "noop")

    def test_read_planning_menu_key_ignores_ss3_fragment_without_escape_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            reads = [b"O", b"D"]

            def fake_read(_fd: int, _count: int) -> bytes:
                return reads.pop(0) if reads else b""

            def fake_selector(_r, _w, _x, _timeout):  # noqa: ANN001
                if reads:
                    return ([_r[0]], [], [])
                return ([], [], [])

            with patch("os.read", side_effect=fake_read):
                key = engine._read_planning_menu_key(fd=7, selector=fake_selector)

            self.assertEqual(key, "noop")

    def test_read_planning_menu_key_keeps_plain_escape_as_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            reads = [b"\x1b"]

            def fake_read(_fd: int, _count: int) -> bytes:
                return reads.pop(0) if reads else b""

            def fake_selector(_r, _w, _x, _timeout):  # noqa: ANN001
                return ([], [], [])

            with patch("os.read", side_effect=fake_read):
                key = engine._read_planning_menu_key(fd=7, selector=fake_selector)

            self.assertEqual(key, "esc")

    def test_read_planning_menu_key_maps_vim_navigation_letters(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            mapping = {
                b"j": "down",
                b"k": "up",
                b"h": "left",
                b"l": "right",
                b"x": "space",
                b"t": "space",
            }

            def fake_selector(_r, _w, _x, _timeout):  # noqa: ANN001
                return ([], [], [])

            for raw_byte, expected in mapping.items():
                with self.subTest(raw_byte=raw_byte):
                    reads = [raw_byte]

                    def fake_read(_fd: int, _count: int) -> bytes:
                        return reads.pop(0) if reads else b""

                    with patch("os.read", side_effect=fake_read):
                        key = engine._read_planning_menu_key(fd=7, selector=fake_selector)
                    self.assertEqual(key, expected)

    def test_planning_menu_render_respects_terminal_width_and_scrolls(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            planning_files = [f"implementations/super-long-plan-name-{idx:02d}-for-rendering-check.md" for idx in range(1, 31)]
            selected_counts = {name: 1 if idx % 5 == 0 else 0 for idx, name in enumerate(planning_files, start=1)}
            existing_counts = {planning_files[9]: 2}

            frame = engine._render_planning_selection_menu(
                planning_files=planning_files,
                selected_counts=selected_counts,
                existing_counts=existing_counts,
                cursor=20,
                message="",
                terminal_width=72,
                terminal_height=14,
            )
            plain = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", frame)
            lines = plain.splitlines()

            self.assertIn("Showing 17-24 of 30", plain)
            self.assertIn("super-long-plan-name-21", plain)
            self.assertNotIn("super-long-plan-name-01", plain)
            for line in lines:
                self.assertLessEqual(len(line), 72)

    def test_to_terminal_lines_uses_crlf_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            rendered = engine._to_terminal_lines("a\nb\nc")

            self.assertEqual(rendered, "a\r\nb\r\nc")

    def test_interactive_command_ignores_escape_only_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            dispatch_calls: list[str] = []

            def fake_dispatch(route):  # noqa: ANN001
                dispatch_calls.append(route.command)
                return 0

            engine.dispatch = fake_dispatch  # type: ignore[method-assign]
            with patch.object(engine, "_try_load_existing_state", return_value=state):
                should_continue, next_state = engine._run_interactive_command("\x1b[A", state)

            self.assertTrue(should_continue)
            self.assertIs(next_state, state)
            self.assertEqual(dispatch_calls, [])

    def test_interactive_loop_flushes_pending_input_after_noise_only_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            commands_seen: list[str] = []

            def fake_run_interactive(raw: str, current: RunState) -> tuple[bool, RunState]:
                commands_seen.append(raw)
                return False, current

            with (
                patch.object(engine, "_can_interactive_tty", return_value=True),
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_print_dashboard_snapshot"),
                patch.object(engine, "_read_interactive_command_line", side_effect=["\x1b[A", "q"]),
                patch.object(engine, "_run_interactive_command", side_effect=fake_run_interactive),
                patch.object(engine, "_flush_pending_interactive_input") as flush_mock,
                redirect_stdout(StringIO()),
            ):
                code = engine._run_interactive_dashboard_loop(state)

            self.assertEqual(code, 0)
            self.assertEqual(commands_seen, ["q"])
            self.assertEqual(flush_mock.call_count, 2)

    def test_interactive_loop_flushes_pending_input_after_partial_csi_fragment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            commands_seen: list[str] = []

            def fake_run_interactive(raw: str, current: RunState) -> tuple[bool, RunState]:
                commands_seen.append(raw)
                return False, current

            with (
                patch.object(engine, "_can_interactive_tty", return_value=True),
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_print_dashboard_snapshot"),
                patch.object(engine, "_read_interactive_command_line", side_effect=["[A", "q"]),
                patch.object(engine, "_run_interactive_command", side_effect=fake_run_interactive),
                patch.object(engine, "_flush_pending_interactive_input") as flush_mock,
                redirect_stdout(StringIO()),
            ):
                code = engine._run_interactive_dashboard_loop(state)

            self.assertEqual(code, 0)
            self.assertEqual(commands_seen, ["q"])
            self.assertEqual(flush_mock.call_count, 2)

    def test_interactive_loop_flushes_pending_input_after_bracketed_paste_fragment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            commands_seen: list[str] = []

            def fake_run_interactive(raw: str, current: RunState) -> tuple[bool, RunState]:
                commands_seen.append(raw)
                return False, current

            with (
                patch.object(engine, "_can_interactive_tty", return_value=True),
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_print_dashboard_snapshot"),
                patch.object(engine, "_read_interactive_command_line", side_effect=["[200~", "q"]),
                patch.object(engine, "_run_interactive_command", side_effect=fake_run_interactive),
                patch.object(engine, "_flush_pending_interactive_input") as flush_mock,
                redirect_stdout(StringIO()),
            ):
                code = engine._run_interactive_dashboard_loop(state)

            self.assertEqual(code, 0)
            self.assertEqual(commands_seen, ["q"])
            self.assertEqual(flush_mock.call_count, 2)

    def test_interactive_loop_does_not_flush_before_each_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            commands_seen: list[str] = []

            def fake_run_interactive(raw: str, current: RunState) -> tuple[bool, RunState]:
                commands_seen.append(raw)
                if raw == "q":
                    return False, current
                return True, current

            with (
                patch.object(engine, "_can_interactive_tty", return_value=True),
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_print_dashboard_snapshot"),
                patch.object(engine, "_read_interactive_command_line", side_effect=["help", "q"]),
                patch.object(engine, "_run_interactive_command", side_effect=fake_run_interactive),
                patch.object(engine, "_flush_pending_interactive_input") as flush_mock,
                redirect_stdout(StringIO()),
            ):
                code = engine._run_interactive_dashboard_loop(state)

            self.assertEqual(code, 0)
            self.assertEqual(commands_seen, ["help", "q"])
            self.assertEqual(flush_mock.call_count, 1)

    def test_interactive_loop_flushes_pending_input_after_empty_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            commands_seen: list[str] = []

            def fake_run_interactive(raw: str, current: RunState) -> tuple[bool, RunState]:
                commands_seen.append(raw)
                return False, current

            with (
                patch.object(engine, "_can_interactive_tty", return_value=True),
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_print_dashboard_snapshot"),
                patch.object(engine, "_read_interactive_command_line", side_effect=["", "q"]),
                patch.object(engine, "_run_interactive_command", side_effect=fake_run_interactive),
                patch.object(engine, "_flush_pending_interactive_input") as flush_mock,
                redirect_stdout(StringIO()),
            ):
                code = engine._run_interactive_dashboard_loop(state)

            self.assertEqual(code, 0)
            self.assertEqual(commands_seen, ["q"])
            self.assertEqual(flush_mock.call_count, 2)

    def test_interactive_command_strips_escape_prefix_before_alias_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            dispatch_calls: list[str] = []

            def fake_dispatch(route):  # noqa: ANN001
                dispatch_calls.append(route.command)
                return 0

            engine.dispatch = fake_dispatch  # type: ignore[method-assign]
            with patch.object(engine, "_try_load_existing_state", return_value=state):
                should_continue, next_state = engine._run_interactive_command("\x1b[As", state)

            self.assertTrue(should_continue)
            self.assertIs(next_state, state)
            self.assertEqual(dispatch_calls, ["stop"])

    def test_interactive_command_strips_partial_csi_prefix_before_alias_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            dispatch_calls: list[str] = []

            def fake_dispatch(route):  # noqa: ANN001
                dispatch_calls.append(route.command)
                return 0

            engine.dispatch = fake_dispatch  # type: ignore[method-assign]
            with patch.object(engine, "_try_load_existing_state", return_value=state):
                should_continue, next_state = engine._run_interactive_command("[As", state)

            self.assertTrue(should_continue)
            self.assertIs(next_state, state)
            self.assertEqual(dispatch_calls, ["stop"])

    def test_interactive_command_ignores_partial_csi_only_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            dispatch_calls: list[str] = []

            def fake_dispatch(route):  # noqa: ANN001
                dispatch_calls.append(route.command)
                return 0

            engine.dispatch = fake_dispatch  # type: ignore[method-assign]
            with patch.object(engine, "_try_load_existing_state", return_value=state):
                should_continue, next_state = engine._run_interactive_command("[A", state)

            self.assertTrue(should_continue)
            self.assertIs(next_state, state)
            self.assertEqual(dispatch_calls, [])

    def test_interactive_command_strips_bracket_fragment_before_alias_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            dispatch_calls: list[str] = []

            def fake_dispatch(route):  # noqa: ANN001
                dispatch_calls.append(route.command)
                return 0

            engine.dispatch = fake_dispatch  # type: ignore[method-assign]
            with patch.object(engine, "_try_load_existing_state", return_value=state):
                should_continue, next_state = engine._run_interactive_command("[s", state)

            self.assertTrue(should_continue)
            self.assertIs(next_state, state)
            self.assertEqual(dispatch_calls, ["stop"])

    def test_interactive_command_strips_ss3_escape_prefix_before_alias_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            dispatch_calls: list[str] = []

            def fake_dispatch(route):  # noqa: ANN001
                dispatch_calls.append(route.command)
                return 0

            engine.dispatch = fake_dispatch  # type: ignore[method-assign]
            with patch.object(engine, "_try_load_existing_state", return_value=state):
                should_continue, next_state = engine._run_interactive_command("\x1bOAs", state)

            self.assertTrue(should_continue)
            self.assertIs(next_state, state)
            self.assertEqual(dispatch_calls, ["stop"])

    def test_interactive_command_ignores_partial_ss3_only_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            dispatch_calls: list[str] = []

            def fake_dispatch(route):  # noqa: ANN001
                dispatch_calls.append(route.command)
                return 0

            engine.dispatch = fake_dispatch  # type: ignore[method-assign]
            with patch.object(engine, "_try_load_existing_state", return_value=state):
                should_continue, next_state = engine._run_interactive_command("OA", state)

            self.assertTrue(should_continue)
            self.assertIs(next_state, state)
            self.assertEqual(dispatch_calls, [])

    def test_interactive_command_ignores_bracketed_paste_fragment_without_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            dispatch_calls: list[str] = []

            def fake_dispatch(route):  # noqa: ANN001
                dispatch_calls.append(route.command)
                return 0

            engine.dispatch = fake_dispatch  # type: ignore[method-assign]
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                redirect_stdout(StringIO()) as buffer,
            ):
                should_continue, next_state = engine._run_interactive_command("[200~", state)

            self.assertTrue(should_continue)
            self.assertIs(next_state, state)
            self.assertEqual(dispatch_calls, [])
            self.assertEqual(buffer.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
