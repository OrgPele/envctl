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
import sys
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

command_router = importlib.import_module("envctl_engine.runtime.command_router")
config_module = importlib.import_module("envctl_engine.config")
runtime_module = importlib.import_module("envctl_engine.runtime.engine_runtime")
models_module = importlib.import_module("envctl_engine.state.models")
state_module = importlib.import_module("envctl_engine.state")

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


class LifecycleParityTests(unittest.TestCase):
    def test_blast_all_port_range_includes_frontend_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "BACKEND_PORT_BASE": "8100",
                    "FRONTEND_PORT_BASE": "9100",
                    "PORT_SPACING": "20",
                }
            )
            engine = PythonEngineRuntime(config, env={})

            ports = engine._blast_all_port_range()

            self.assertIn(8100, ports)
            self.assertIn(9100, ports)
            self.assertIn(9300, ports)

    def test_blast_all_kills_orphan_envctl_processes_but_skips_other_blast_commands(self) -> None:
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
            tracking_runner = _TrackingRunner()
            tracking_runner.ps_stdout = (
                "2222 /usr/bin/python -m envctl_engine.runtime.cli --repo /tmp/repo --plan\n"
                "7777 /usr/bin/node /tmp/repo/frontend/node_modules/.bin/vite\n"
                "3333 /usr/bin/python -m envctl_engine.runtime.cli --repo /tmp/repo blast-all\n"
                "4444 /usr/bin/python -m envctl_engine.runtime.cli --tree\n"
            )
            tracking_runner.ps_tree_stdout = "2222 1\n7777 2222\n3333 1\n4444 1\n"
            engine.process_runner = tracking_runner  # type: ignore[assignment]

            engine._blast_all_kill_orchestrator_processes()

            self.assertIn(("kill", "-9", "2222"), tracking_runner.run_calls)
            self.assertIn(("kill", "-9", "7777"), tracking_runner.run_calls)
            self.assertIn(("kill", "-9", "4444"), tracking_runner.run_calls)
            self.assertNotIn(("kill", "-9", "3333"), tracking_runner.run_calls)

    def test_restart_prefers_requested_mode_when_loading_previous_state(self) -> None:
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

            main_state = RunState(run_id="run-main", mode="main")
            trees_state = RunState(run_id="run-trees", mode="trees")
            seen_lookup_modes: list[str | None] = []
            seen_discovery_modes: list[str] = []

            def fake_load_state(*, mode: str | None = None):
                seen_lookup_modes.append(mode)
                if mode == "trees":
                    return trees_state
                return main_state

            def fake_discover_projects(*, mode: str):
                seen_discovery_modes.append(mode)
                return []

            engine._try_load_existing_state = fake_load_state  # type: ignore[method-assign]
            engine._discover_projects = fake_discover_projects  # type: ignore[method-assign]

            code = engine.dispatch(parse_route(["--restart", "--tree", "--batch"], env={}))

            self.assertEqual(code, 1)
            self.assertEqual(seen_lookup_modes, ["trees"])
            self.assertEqual(seen_discovery_modes, ["trees"])

    def test_restart_setup_worktrees_uses_effective_trees_mode_for_state_lookup(self) -> None:
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

            main_state = RunState(run_id="run-main", mode="main")
            trees_state = RunState(run_id="run-trees", mode="trees")
            seen_lookup_modes: list[str | None] = []
            seen_discovery_modes: list[str] = []

            def fake_load_state(*, mode: str | None = None):
                seen_lookup_modes.append(mode)
                if mode == "trees":
                    return trees_state
                return main_state

            def fake_discover_projects(*, mode: str):
                seen_discovery_modes.append(mode)
                return []

            engine._try_load_existing_state = fake_load_state  # type: ignore[method-assign]
            engine._discover_projects = fake_discover_projects  # type: ignore[method-assign]

            code = engine.dispatch(
                parse_route(
                    ["--restart", "--setup-worktrees", "feature-a", "1", "--batch"],
                    env={},
                )
            )

            self.assertEqual(code, 1)
            self.assertEqual(seen_lookup_modes, ["trees"])
            self.assertEqual(seen_discovery_modes, ["trees"])

    def test_restart_preserves_effective_mode_when_loaded_state_mode_mismatches(self) -> None:
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

            mismatched_state = RunState(run_id="run-trees", mode="trees")
            seen_lookup_modes: list[str | None] = []
            seen_discovery_modes: list[str] = []

            def fake_load_state(*, mode: str | None = None):
                seen_lookup_modes.append(mode)
                return mismatched_state

            def fake_discover_projects(*, mode: str):
                seen_discovery_modes.append(mode)
                return []

            engine._try_load_existing_state = fake_load_state  # type: ignore[method-assign]
            engine._discover_projects = fake_discover_projects  # type: ignore[method-assign]

            code = engine.dispatch(parse_route(["--restart", "--main", "--batch"], env={}))

            self.assertEqual(code, 1)
            self.assertEqual(seen_lookup_modes, ["main"])
            self.assertEqual(seen_discovery_modes, ["main"])

    def test_restart_does_not_terminate_cross_mode_loaded_state(self) -> None:
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

            mismatched_state = RunState(
                run_id="run-trees",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo / "trees" / "feature-a" / "1" / "backend"),
                        pid=12345,
                        requested_port=8020,
                        actual_port=8020,
                        status="running",
                    )
                },
            )
            terminate_calls: list[str] = []
            seen_discovery_modes: list[str] = []

            engine._try_load_existing_state = (  # type: ignore[method-assign]
                lambda mode=None, strict_mode_match=False: mismatched_state
            )
            engine._terminate_services_from_state = (  # type: ignore[method-assign]
                lambda state, selected_services, aggressive, verify_ownership: terminate_calls.append(state.mode)
            )

            def fake_discover_projects(*, mode: str):
                seen_discovery_modes.append(mode)
                return []

            engine._discover_projects = fake_discover_projects  # type: ignore[method-assign]

            code = engine.dispatch(parse_route(["--restart", "--main", "--batch"], env={}))

            self.assertEqual(code, 1)
            self.assertEqual(seen_discovery_modes, ["main"])
            self.assertEqual(terminate_calls, [])

    def test_start_blocks_when_mode_startup_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "MAIN_STARTUP_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            engine._discover_projects = lambda **_kwargs: self.fail("project discovery should not run")  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["start"], env={}))

            self.assertEqual(code, 1)
            self.assertIn("envctl runs are disabled for main in .envctl", out.getvalue())

    def test_restart_blocks_when_mode_startup_is_disabled_before_prestop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "MAIN_STARTUP_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            engine._try_load_existing_state = lambda **_kwargs: self.fail("state lookup should not run")  # type: ignore[assignment]
            engine._terminate_services_from_state = lambda *args, **kwargs: self.fail("pre-stop should not run")  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--restart", "--main", "--batch"], env={}))

            self.assertEqual(code, 1)
            self.assertIn("envctl runs are disabled for main in .envctl", out.getvalue())

    def test_resume_blocks_when_mode_startup_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "MAIN_STARTUP_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            engine._try_load_existing_state = lambda **_kwargs: RunState(run_id="run-main", mode="main")  # type: ignore[assignment]
            engine._reconcile_state_truth = lambda _state: self.fail("reconcile should not run")  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume", "--main", "--batch"], env={}))

            self.assertEqual(code, 1)
            self.assertIn("envctl runs are disabled for main in .envctl", out.getvalue())

    def test_plan_allows_worktree_setup_when_mode_runs_are_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "TREES_STARTUP_ENABLE": "false",
                    "ENVCTL_DEFAULT_MODE": "trees",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            seen_modes: list[str] = []

            def fake_discover_projects(*, mode: str):  # noqa: ANN202
                seen_modes.append(mode)
                return []

            engine._discover_projects = fake_discover_projects  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--plan", "--batch"], env={"ENVCTL_DEFAULT_MODE": "trees"}))

            self.assertEqual(code, 1)
            self.assertEqual(seen_modes, ["trees"])
            self.assertNotIn("envctl runs are disabled for trees in .envctl", out.getvalue())
            self.assertIn("No projects discovered for selected mode.", out.getvalue())

    def test_plan_skips_service_startup_when_mode_runs_are_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "TREES_STARTUP_ENABLE": "false",
                    "ENVCTL_DEFAULT_MODE": "trees",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            context = ProjectContext(
                name="feature-a-1",
                root=repo / "trees" / "feature-a-1",
                ports={
                    "backend": PortPlan("feature-a-1", 8000, 8000, 8000, "requested"),
                    "frontend": PortPlan("feature-a-1", 9000, 9000, 9000, "requested"),
                    "db": PortPlan("feature-a-1", 5432, 5432, 5432, "requested"),
                    "redis": PortPlan("feature-a-1", 6379, 6379, 6379, "requested"),
                    "n8n": PortPlan("feature-a-1", 5678, 5678, 5678, "requested"),
                },
            )
            engine._discover_projects = lambda **_kwargs: [context]  # type: ignore[assignment]
            engine._select_plan_projects = lambda route, contexts: contexts  # type: ignore[assignment]
            engine._start_project_context = lambda **_kwargs: self.fail("project startup should not run")  # type: ignore[assignment]
            engine._try_load_existing_state = lambda **_kwargs: self.fail("auto-resume should not run")  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--plan", "--batch"], env={"ENVCTL_DEFAULT_MODE": "trees"}))

            self.assertEqual(code, 0)
            self.assertIn(
                "Planning mode complete; skipping service startup because envctl runs are disabled for trees.",
                out.getvalue(),
            )

    def test_implicit_start_opens_dashboard_when_main_runs_are_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "MAIN_STARTUP_ENABLE": "false",
                    "ENVCTL_DEFAULT_MODE": "main",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            context = ProjectContext(
                name="Main",
                root=repo,
                ports={
                    "backend": PortPlan("Main", 8000, 8000, 8000, "requested"),
                    "frontend": PortPlan("Main", 9000, 9000, 9000, "requested"),
                },
            )
            engine._discover_projects = lambda **_kwargs: [context]  # type: ignore[assignment]
            engine._start_project_context = lambda **_kwargs: self.fail("project startup should not run")  # type: ignore[assignment]
            engine._try_load_existing_state = lambda **_kwargs: self.fail("auto-resume should not run")  # type: ignore[assignment]
            engine._write_artifacts = lambda *_args, **_kwargs: None  # type: ignore[assignment]
            engine._should_enter_post_start_interactive = lambda _route: True  # type: ignore[assignment]

            seen_state: list[RunState] = []

            def fake_dashboard_loop(state: RunState) -> int:
                seen_state.append(state)
                return 0

            engine._run_interactive_dashboard_loop = fake_dashboard_loop  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--main"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            self.assertNotIn("opening dashboard without starting services", out.getvalue())
            self.assertEqual(len(seen_state), 1)
            self.assertEqual(seen_state[0].mode, "main")
            self.assertEqual(seen_state[0].metadata.get("dashboard_configured_service_types"), ["backend", "frontend"])

    def test_explicit_start_still_blocks_when_main_runs_are_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "MAIN_STARTUP_ENABLE": "false",
                    "ENVCTL_DEFAULT_MODE": "main",
                }
            )
            engine = PythonEngineRuntime(config, env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["start", "--main", "--batch"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 1)
            self.assertIn("envctl runs are disabled for main in .envctl", out.getvalue())

    def test_resume_does_not_fallback_to_cross_mode_state(self) -> None:
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
            seen_calls: list[tuple[str | None, bool]] = []
            trees_state = RunState(
                run_id="run-trees",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1234,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )

            def fake_load(*, mode=None, strict_mode_match=False):  # noqa: ANN001
                seen_calls.append((mode, strict_mode_match))
                if mode == "main" and not strict_mode_match:
                    return trees_state
                return None

            engine._try_load_existing_state = fake_load  # type: ignore[method-assign]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume", "--main", "--batch"], env={}))

            self.assertEqual(code, 1)
            self.assertIn("No previous state found to resume.", out.getvalue())
            self.assertEqual(seen_calls, [("main", True)])

    def test_resume_without_explicit_mode_falls_back_to_latest_state_mode(self) -> None:
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
            seen_calls: list[tuple[str | None, bool]] = []
            trees_state = RunState(
                run_id="run-trees",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1234,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )

            def fake_load(*, mode=None, strict_mode_match=False):  # noqa: ANN001
                seen_calls.append((mode, strict_mode_match))
                if mode == "main" and not strict_mode_match:
                    return trees_state
                return None

            engine._try_load_existing_state = fake_load  # type: ignore[method-assign]
            engine._reconcile_state_truth = lambda state: []  # type: ignore[method-assign]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertIn("Resumed run_id=run-trees session_id=", out.getvalue())
            self.assertEqual(seen_calls, [("main", False)])
            self.assertEqual(engine.env.get("ENVCTL_DEBUG_UI_RUN_ID"), "run-trees")

    def test_resume_interactive_suppresses_resumed_projection_banner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-interactive",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1234,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )
            dump_state(state, str(run_dir / "run_state.json"))

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})
            engine._should_enter_resume_interactive = lambda _route: True  # type: ignore[method-assign]
            engine._run_interactive_dashboard_loop = lambda _state: 0  # type: ignore[method-assign]
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume"], env={}))

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertNotIn("Resumed run_id=", rendered)
            self.assertNotIn("backend=http://", rendered)

    def test_state_actions_use_strict_mode_lookup(self) -> None:
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
            seen_calls: list[tuple[str | None, bool]] = []
            trees_state = RunState(run_id="run-trees", mode="trees")

            def fake_load(*, mode=None, strict_mode_match=False):  # noqa: ANN001
                seen_calls.append((mode, strict_mode_match))
                if mode == "main" and not strict_mode_match:
                    return trees_state
                return None

            engine._try_load_existing_state = fake_load  # type: ignore[method-assign]

            for command in ("--health", "--errors", "--logs"):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(parse_route([command, "--main"], env={}))
                self.assertEqual(code, 1)
                self.assertIn("No previous state found", out.getvalue())

            self.assertEqual(
                seen_calls,
                [
                    ("main", True),
                    ("main", True),
                    ("main", True),
                ],
            )

    def test_stop_does_not_fallback_to_cross_mode_state(self) -> None:
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
            seen_calls: list[tuple[str | None, bool]] = []
            terminate_calls: list[str] = []
            trees_state = RunState(
                run_id="run-trees",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo / "trees" / "feature-a" / "1" / "backend"),
                        pid=12345,
                        requested_port=8020,
                        actual_port=8020,
                        status="running",
                    )
                },
            )

            def fake_load(*, mode=None, strict_mode_match=False):  # noqa: ANN001
                seen_calls.append((mode, strict_mode_match))
                if mode == "main" and not strict_mode_match:
                    return trees_state
                return None

            engine._try_load_existing_state = fake_load  # type: ignore[method-assign]
            engine._terminate_services_from_state = (  # type: ignore[method-assign]
                lambda state, selected_services, aggressive, verify_ownership: terminate_calls.append(state.mode)
            )

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["stop", "--main", "--yes"], env={}))

            self.assertEqual(code, 0)
            self.assertIn("No active runtime state found.", out.getvalue())
            self.assertEqual(seen_calls, [("main", True)])
            self.assertEqual(terminate_calls, [])

    def test_stop_without_explicit_mode_falls_back_to_latest_state_mode(self) -> None:
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
            seen_calls: list[tuple[str | None, bool]] = []
            trees_state = RunState(run_id="run-trees", mode="trees")

            def fake_load(*, mode=None, strict_mode_match=False):  # noqa: ANN001
                seen_calls.append((mode, strict_mode_match))
                if mode == "main" and not strict_mode_match:
                    return trees_state
                return None

            engine._try_load_existing_state = fake_load  # type: ignore[method-assign]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["stop", "--yes"], env={}))

            self.assertEqual(code, 0)
            self.assertIn("Stopped runtime state.", out.getvalue())
            self.assertGreaterEqual(len(seen_calls), 1)
            self.assertEqual(seen_calls[0], ("main", False))

    def test_dashboard_does_not_fallback_to_cross_mode_state(self) -> None:
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
            seen_calls: list[tuple[str | None, bool]] = []
            trees_state = RunState(run_id="run-trees", mode="trees")

            def fake_load(*, mode=None, strict_mode_match=False):  # noqa: ANN001
                seen_calls.append((mode, strict_mode_match))
                if mode == "main" and not strict_mode_match:
                    return trees_state
                return None

            engine._try_load_existing_state = fake_load  # type: ignore[method-assign]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--dashboard", "--main"], env={}))

            self.assertEqual(code, 0)
            self.assertIn("No active run state found.", out.getvalue())
            self.assertEqual(seen_calls, [("main", True)])

    def test_stop_and_blast_emit_cleanup_events_and_clear_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            runs_dir = run_dir / "runs" / "run-1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            runs_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        pid=999999,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )
            dump_state(state, str(run_dir / "run_state.json"))
            dump_state(state, str(runs_dir / "run_state.json"))
            (run_dir / "runtime_map.json").write_text("{}", encoding="utf-8")
            (run_dir / "ports_manifest.json").write_text("{}", encoding="utf-8")
            (run_dir / "runtime_readiness_report.json").write_text("{}", encoding="utf-8")
            (run_dir / ".last_state.main").write_text(str(runs_dir / "run_state.json"), encoding="utf-8")

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})
            planner = _NoopPlanner()
            engine.port_planner = planner  # type: ignore[assignment]

            stop_code = engine.dispatch(parse_route(["stop"], env={}))
            self.assertEqual(stop_code, 0)
            self.assertTrue(planner.released)
            self.assertFalse((run_dir / "run_state.json").exists())
            self.assertFalse((run_dir / "runtime_readiness_report.json").exists())
            self.assertTrue(any(event["event"] == "cleanup.stop" for event in engine.events))

            (run_dir / "runs" / "run-1").mkdir(parents=True, exist_ok=True)
            tracking_runner = _TrackingRunner()
            engine.process_runner = tracking_runner  # type: ignore[assignment]
            out = StringIO()
            with redirect_stdout(out):
                blast_code = engine.dispatch(parse_route(["blast-all"], env={}))
            self.assertEqual(blast_code, 0)
            self.assertFalse((run_dir / "runs").exists())
            self.assertTrue(any(event["event"] == "cleanup.blast" for event in engine.events))
            self.assertTrue(
                any(call[:3] == ("pkill", "-9", "-f") for call in tracking_runner.run_calls),
                msg=tracking_runner.run_calls,
            )
            self.assertTrue(
                any(
                    call[:4] == ("pkill", "-9", "-f", "envctl_engine\\.cli.*--plan")
                    for call in tracking_runner.run_calls
                ),
                msg=tracking_runner.run_calls,
            )
            self.assertTrue(
                any(
                    call[:4] == ("pkill", "-9", "-f", "lib/engine/main\\.sh.*--plan")
                    for call in tracking_runner.run_calls
                ),
                msg=tracking_runner.run_calls,
            )
            self.assertTrue(
                any(call[:4] == ("docker", "ps", "-a", "--format") for call in tracking_runner.run_calls),
                msg=tracking_runner.run_calls,
            )
            self.assertTrue(
                any(
                    call[:4] == ("docker", "rm", "-f", "cid1") or call[:5] == ("docker", "rm", "-f", "-v", "cid1")
                    for call in tracking_runner.run_calls
                ),
                msg=tracking_runner.run_calls,
            )
            self.assertIn("BLAST-ALL", out.getvalue())

    def test_resume_reconciles_missing_service_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        pid=999999,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )
            dump_state(state, str(run_dir / "run_state.json"))

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})
            code = engine.dispatch(parse_route(["--resume"], env={}))

            self.assertEqual(code, 0)
            reconciled = json.loads((run_dir / "runtime_map.json").read_text(encoding="utf-8"))
            self.assertEqual(reconciled["run_id"], "run-1")
            self.assertTrue(any(event["event"] == "state.reconcile" for event in engine.events))

    def test_resume_fails_fast_for_conflicting_main_requirement_mode_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        pid=999999,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )
            dump_state(state, str(run_dir / "run_state.json"))

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})
            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(
                    parse_route(
                        ["--resume", "--main-services-local", "--main-services-remote", "--batch"],
                        env={},
                    )
                )

            self.assertEqual(code, 1)
            self.assertIn("Conflicting main requirements flags", out.getvalue())

    def test_stop_all_remove_volumes_runs_docker_volume_cleanup(self) -> None:
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
            tracking_runner = _TrackingRunner()
            tracking_runner.docker_ps_stdout = "cid1|postgres:16|repo-postgres\n"
            tracking_runner.inspect_volumes_by_cid = {"cid1": "repo_postgres_data\n"}
            engine.process_runner = tracking_runner  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["stop-all", "--stop-all-remove-volumes"], env={}))

            self.assertEqual(code, 0)
            self.assertTrue(
                any(call[:4] == ("docker", "ps", "-a", "--format") for call in tracking_runner.run_calls),
                msg=tracking_runner.run_calls,
            )
            self.assertTrue(
                any(call[:5] == ("docker", "rm", "-f", "-v", "cid1") for call in tracking_runner.run_calls),
                msg=tracking_runner.run_calls,
            )
            self.assertTrue(
                any(call[:4] == ("docker", "volume", "rm", "repo_postgres_data") for call in tracking_runner.run_calls),
                msg=tracking_runner.run_calls,
            )
            self.assertIn("Stopped runtime state.", out.getvalue())

    def test_resume_restarts_missing_services_when_commands_are_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        pid=999999,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )
            dump_state(state, str(run_dir / "run_state.json"))

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 5'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 5'",
                },
            )
            restore_runner = _ResumeRestoreRunner()
            engine.process_runner = restore_runner  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertTrue(any("Restoring stale services..." in line for line in out.getvalue().splitlines()))
            resumed_state = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
            services = resumed_state["services"]
            self.assertIn("Main Backend", services)
            self.assertIn("Main Frontend", services)
            self.assertNotEqual(services["Main Backend"]["pid"], 999999)
            self.assertGreater(len(restore_runner.start_calls), 0)

    def test_resume_interactive_restarts_missing_services_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-2",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        pid=999999,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )
            dump_state(state, str(run_dir / "run_state.json"))

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 5'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 5'",
                },
            )
            restore_runner = _ResumeRestoreRunner()
            engine.process_runner = restore_runner  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume"], env={}))

            self.assertEqual(code, 0)
            self.assertTrue(any("Restoring stale services..." in line for line in out.getvalue().splitlines()))
            resumed_state = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
            services = resumed_state["services"]
            self.assertIn("Main Backend", services)
            self.assertIn("Main Frontend", services)
            self.assertGreater(len(restore_runner.start_calls), 0)

    def test_resume_reuses_healthy_requirements_when_only_services_are_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-5",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        pid=999999,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                requirements={
                    "Main": RequirementsResult(
                        project="Main",
                        db={
                            "requested": 5432,
                            "final": 5432,
                            "retries": 0,
                            "success": True,
                            "enabled": True,
                            "simulated": False,
                        },
                        redis={
                            "requested": 6379,
                            "final": 6379,
                            "retries": 0,
                            "success": True,
                            "enabled": True,
                            "simulated": False,
                        },
                        n8n={
                            "requested": 5678,
                            "final": 5678,
                            "retries": 0,
                            "success": True,
                            "enabled": False,
                            "simulated": False,
                        },
                        supabase={
                            "requested": 5432,
                            "final": 5432,
                            "retries": 0,
                            "success": True,
                            "enabled": False,
                            "simulated": False,
                        },
                        health="healthy",
                        failures=[],
                    )
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )
            dump_state(state, str(run_dir / "run_state.json"))

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                    "POSTGRES_MAIN_ENABLE": "true",
                    "REDIS_ENABLE": "true",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 5'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 5'",
                    "ENVCTL_DEBUG_RESTORE_TIMING": "true",
                },
            )
            restore_runner = _ResumeRestoreRunner()
            engine.process_runner = restore_runner  # type: ignore[assignment]
            engine._reconcile_project_requirement_truth = lambda *_args, **_kwargs: []  # type: ignore[method-assign]

            def fail_requirements_start(*_args, **_kwargs):  # noqa: ANN001
                raise AssertionError("requirements should have been reused and not restarted")

            engine._start_requirements_for_project = fail_requirements_start  # type: ignore[method-assign]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertIn("start_requirements=0.0ms", out.getvalue())
            self.assertTrue(any(event.get("event") == "resume.restore.requirements_reuse" for event in engine.events))
            self.assertGreater(len(restore_runner.start_calls), 0)

    def test_resume_restore_skips_backend_migration_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            backend_dir = repo / "backend"
            frontend_dir = repo / "frontend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            frontend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            (backend_dir / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-resume-migrate",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(backend_dir),
                        pid=999999,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )
            dump_state(state, str(run_dir / "run_state.json"))

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 5'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 5'",
                },
            )
            restore_runner = _ResumeRestoreRunner()
            restore_runner.fail_alembic = True
            engine.process_runner = restore_runner  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertNotIn("Warning: backend migration step failed", out.getvalue())
            self.assertFalse(
                any(command[-3:] == ("alembic", "upgrade", "head") for command in restore_runner.run_calls)
            )

    def test_resume_restore_does_not_reuse_requirements_when_project_root_reveals_owner_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            backend_dir = repo / "backend"
            frontend_dir = repo / "frontend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            frontend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-resume-owner-mismatch",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(backend_dir),
                        pid=999999,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(frontend_dir),
                        pid=999998,
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
                requirements={
                    "Main": RequirementsResult(
                        project="Main",
                        db={
                            "requested": 5432,
                            "final": 5432,
                            "retries": 0,
                            "success": False,
                            "enabled": False,
                            "simulated": False,
                        },
                        redis={
                            "requested": 6379,
                            "final": 6379,
                            "retries": 0,
                            "success": True,
                            "enabled": True,
                            "simulated": False,
                            "runtime_status": "healthy",
                        },
                        supabase={
                            "requested": 5432,
                            "final": 5432,
                            "retries": 0,
                            "success": False,
                            "enabled": False,
                            "simulated": False,
                        },
                        n8n={
                            "requested": 5678,
                            "final": 5678,
                            "retries": 0,
                            "success": False,
                            "enabled": False,
                            "simulated": False,
                        },
                        health="healthy",
                        failures=[],
                    )
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )
            dump_state(state, str(run_dir / "run_state.json"))

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "REDIS_ENABLE": "true",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                    "POSTGRES_MAIN_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 1'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 1'",
                    "ENVCTL_DEBUG_RESTORE_TIMING": "true",
                },
            )
            restore_runner = _ResumeRestoreRunner()
            engine.process_runner = restore_runner  # type: ignore[assignment]

            def fake_reconcile(project: str, requirements: RequirementsResult, *, project_root: Path | None = None):  # noqa: ANN001
                self.assertEqual(project, "Main")
                self.assertEqual(project_root, repo)
                return [{"component": "redis", "status": "unreachable"}]

            engine._reconcile_project_requirement_truth = fake_reconcile  # type: ignore[method-assign]

            started_requirements: list[str] = []

            def fake_start_requirements(_context: object, *, mode: str, route):  # noqa: ANN001
                _ = mode, route
                started_requirements.append("Main")
                return RequirementsResult(
                    project="Main",
                    db={
                        "requested": 5432,
                        "final": 5432,
                        "retries": 0,
                        "success": False,
                        "enabled": False,
                        "simulated": False,
                    },
                    redis={
                        "requested": 6380,
                        "final": 6380,
                        "retries": 0,
                        "success": True,
                        "enabled": True,
                        "simulated": False,
                        "runtime_status": "healthy",
                    },
                    supabase={
                        "requested": 5432,
                        "final": 5432,
                        "retries": 0,
                        "success": False,
                        "enabled": False,
                        "simulated": False,
                    },
                    n8n={
                        "requested": 5678,
                        "final": 5678,
                        "retries": 0,
                        "success": False,
                        "enabled": False,
                        "simulated": False,
                    },
                    health="healthy",
                    failures=[],
                )

            engine._start_requirements_for_project = fake_start_requirements  # type: ignore[method-assign]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertEqual(started_requirements, ["Main"])
            reuse_event = next(
                event for event in engine.events if event.get("event") == "resume.restore.requirements_reuse"
            )
            self.assertFalse(bool(reuse_event.get("reused")))
            self.assertEqual(reuse_event.get("reason"), "dependency_endpoint_changed")

    def test_resume_restore_uses_spinner_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-3",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        pid=999999,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )
            dump_state(state, str(run_dir / "run_state.json"))

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 5'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 5'",
                },
            )
            restore_runner = _ResumeRestoreRunner()
            engine.process_runner = restore_runner  # type: ignore[assignment]
            original_start_requirements = engine._start_requirements_for_project

            def reporting_start_requirements(context, mode, route=None):  # noqa: ANN001
                spinner_update = None if route is None else route.flags.get("_spinner_update")
                if callable(spinner_update):
                    spinner_update("Loading requirements: redis | queued: supabase")
                return original_start_requirements(context, mode=mode, route=route)

            engine._start_requirements_for_project = reporting_start_requirements  # type: ignore[method-assign]

            spinner_calls: list[tuple[str, str] | tuple[str, str, bool]] = []

            class _SpinnerStub:
                def update(self, message: str) -> None:
                    spinner_calls.append(("update", message))

                def succeed(self, message: str) -> None:
                    spinner_calls.append(("succeed", message))

                def fail(self, message: str) -> None:
                    spinner_calls.append(("fail", message))

            @contextmanager
            def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
                _ = start_immediately
                spinner_calls.append(("start", message, enabled))
                yield _SpinnerStub()

            out = StringIO()
            with (
                patch("envctl_engine.startup.resume_orchestrator.spinner_enabled", return_value=True),
                patch("envctl_engine.startup.resume_orchestrator.spinner", side_effect=fake_spinner),
                redirect_stdout(out),
            ):
                code = engine.dispatch(parse_route(["--resume", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertIn(("start", "Preparing stale restore for 1 project(s)...", True), spinner_calls)
            self.assertIn(("update", "[1/1] Restoring stale services..."), spinner_calls)
            self.assertIn(("update", "[1/1] Loading requirements: redis | queued: supabase"), spinner_calls)
            self.assertIn(("succeed", "stale services restored"), spinner_calls)
            self.assertNotIn("Restoring stale services...", out.getvalue())

    def test_resume_restore_uses_project_spinner_group_for_multi_project_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            tree_a = repo / "trees" / "feature-a" / "1"
            tree_b = repo / "trees" / "feature-b" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (tree_a / "backend").mkdir(parents=True, exist_ok=True)
            (tree_a / "frontend").mkdir(parents=True, exist_ok=True)
            (tree_b / "backend").mkdir(parents=True, exist_ok=True)
            (tree_b / "frontend").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-5",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(tree_a / "backend"),
                        pid=999999,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "feature-b-1 Backend": ServiceRecord(
                        name="feature-b-1 Backend",
                        type="backend",
                        cwd=str(tree_b / "backend"),
                        pid=999998,
                        requested_port=8010,
                        actual_port=8010,
                        status="running",
                    ),
                },
                metadata={
                    "project_roots": {
                        "feature-a-1": str(tree_a),
                        "feature-b-1": str(tree_b),
                    }
                },
            )
            dump_state(state, str(run_dir / "run_state.json"))

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 5'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 5'",
                    "ENVCTL_UI_SPINNER_MODE": "on",
                },
            )
            restore_runner = _ResumeRestoreRunner()
            engine.process_runner = restore_runner  # type: ignore[assignment]

            def reporting_start_requirements(context, mode, route=None):  # noqa: ANN001
                project_update = None if route is None else route.flags.get("_spinner_update_project")
                if callable(project_update):
                    project_update(context.name, "Loading requirements: postgres")
                return RequirementsResult(
                    project=context.name,
                    db={"enabled": True, "success": True, "requested": 5432, "final": 5432},
                    redis={"enabled": False, "success": True},
                    n8n={"enabled": False, "success": True},
                    supabase={"enabled": False, "success": True},
                    health="healthy",
                )

            engine._start_requirements_for_project = reporting_start_requirements  # type: ignore[method-assign]

            group_calls: list[tuple[str, str, str]] = []

            class _GroupStub:
                def __init__(self, projects, **_kwargs):  # noqa: ANN001
                    self._projects = list(projects)

                def __enter__(self):
                    group_calls.append(("enter", ",".join(self._projects), ""))
                    return self

                def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
                    _ = exc_type, exc, tb
                    group_calls.append(("exit", "", ""))
                    return False

                def update_project(self, project: str, message: str) -> None:
                    group_calls.append(("update", project, message))

                def mark_success(self, project: str, message: str) -> None:
                    group_calls.append(("success", project, message))

                def mark_failure(self, project: str, message: str) -> None:
                    group_calls.append(("failure", project, message))

            with (
                patch("envctl_engine.startup.resume_orchestrator.spinner_enabled", return_value=True),
                patch("envctl_engine.startup.resume_orchestrator._ResumeProjectSpinnerGroup", _GroupStub),
                patch("envctl_engine.startup.resume_orchestrator.resolve_spinner_policy") as policy_mock,
            ):
                policy_mock.side_effect = lambda *_args, **_kwargs: type(
                    "_Policy",
                    (),
                    {
                        "mode": "on",
                        "enabled": True,
                        "reason": "",
                        "backend": "rich",
                        "min_ms": 120,
                        "verbose_events": False,
                        "style": "dots",
                    },
                )()
                code = engine.dispatch(parse_route(["--resume", "--tree", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertTrue(any(kind == "enter" for kind, _project, _msg in group_calls))
            updated_projects = {project for kind, project, _msg in group_calls if kind == "update"}
            self.assertIn("feature-a-1", updated_projects)
            self.assertIn("feature-b-1", updated_projects)
            update_messages = [msg for kind, _project, msg in group_calls if kind == "update"]
            self.assertTrue(any("Loading requirements: postgres" in msg for msg in update_messages))
            succeeded_projects = {project for kind, project, _msg in group_calls if kind == "success"}
            self.assertIn("feature-a-1", succeeded_projects)
            self.assertIn("feature-b-1", succeeded_projects)
            execution_events = [event for event in engine.events if event.get("event") == "resume.restore.execution"]
            self.assertTrue(execution_events)
            self.assertEqual(execution_events[-1].get("mode"), "parallel")

    def test_resume_restore_failure_marks_existing_requirements_unreachable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            tree = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (tree / "backend").mkdir(parents=True, exist_ok=True)
            (tree / "frontend").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-fail",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(tree / "backend"),
                        pid=1234,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                },
                requirements={
                    "feature-a-1": RequirementsResult(
                        project="feature-a-1",
                        redis={
                            "enabled": True,
                            "success": True,
                            "final": 6384,
                            "container_name": "envctl-redis-feature-a",
                        },
                        n8n={"enabled": True, "success": True, "final": 5683, "container_name": "envctl-n8n-feature-a"},
                        supabase={
                            "enabled": True,
                            "success": True,
                            "final": 5437,
                            "container_name": "envctl-supabase-feature-a-supabase-db-1",
                        },
                    )
                },
                metadata={"project_roots": {"feature-a-1": str(tree)}},
            )
            dump_state(state, str(run_dir / "run_state.json"))

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            restore_runner = _ResumeRestoreRunner()
            engine.process_runner = restore_runner  # type: ignore[assignment]

            def fail_requirements(*_args, **_kwargs):  # noqa: ANN001
                raise RuntimeError("requirements unavailable: redis failed, n8n failed")

            engine._start_requirements_for_project = fail_requirements  # type: ignore[method-assign]
            errors = engine._resume_restore_missing(
                state, ["feature-a-1 Backend"], route=parse_route(["--resume", "--batch"], env={})
            )

            self.assertTrue(errors)
            requirements = state.requirements["feature-a-1"]
            self.assertEqual(requirements.health, "degraded")
            self.assertTrue(requirements.failures)
            self.assertEqual(requirements.redis["runtime_status"], "unreachable")
            self.assertEqual(requirements.n8n["runtime_status"], "unreachable")
            self.assertEqual(requirements.supabase["runtime_status"], "unreachable")

    def test_resume_restore_runs_projects_in_parallel_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            tree_a = repo / "trees" / "feature-a" / "1"
            tree_b = repo / "trees" / "feature-b" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (tree_a / "backend").mkdir(parents=True, exist_ok=True)
            (tree_a / "frontend").mkdir(parents=True, exist_ok=True)
            (tree_b / "backend").mkdir(parents=True, exist_ok=True)
            (tree_b / "frontend").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-6",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(tree_a / "backend"),
                        pid=999999,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "feature-b-1 Backend": ServiceRecord(
                        name="feature-b-1 Backend",
                        type="backend",
                        cwd=str(tree_b / "backend"),
                        pid=999998,
                        requested_port=8010,
                        actual_port=8010,
                        status="running",
                    ),
                },
                metadata={
                    "project_roots": {
                        "feature-a-1": str(tree_a),
                        "feature-b-1": str(tree_b),
                    }
                },
            )
            dump_state(state, str(run_dir / "run_state.json"))

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                    "RUN_SH_OPT_PARALLEL_TREES": "true",
                    "RUN_SH_OPT_PARALLEL_TREES_MAX": "4",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 5'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 5'",
                    "ENVCTL_UI_SPINNER_MODE": "off",
                },
            )
            restore_runner = _ResumeRestoreRunner()
            engine.process_runner = restore_runner  # type: ignore[assignment]
            engine._start_requirements_for_project = (  # type: ignore[method-assign]
                lambda context, mode, route=None: RequirementsResult(
                    project=context.name,
                    db={"enabled": True, "success": True, "requested": 5432, "final": 5432},
                    redis={"enabled": False, "success": True},
                    n8n={"enabled": False, "success": True},
                    supabase={"enabled": False, "success": True},
                    health="healthy",
                )
            )

            active_lock = threading.Lock()
            active_calls = 0
            max_concurrency = 0

            def fake_start_project_services(context, *, requirements, run_id, route=None):  # noqa: ANN001
                _ = requirements, run_id, route
                nonlocal active_calls, max_concurrency
                with active_lock:
                    active_calls += 1
                    if active_calls > max_concurrency:
                        max_concurrency = active_calls
                time.sleep(0.2)
                with active_lock:
                    active_calls -= 1
                backend_name = f"{context.name} Backend"
                frontend_name = f"{context.name} Frontend"
                return {
                    backend_name: ServiceRecord(
                        name=backend_name,
                        type="backend",
                        cwd=str(context.root / "backend"),
                        pid=42001,
                        requested_port=context.ports["backend"].requested,
                        actual_port=context.ports["backend"].final,
                        status="running",
                    ),
                    frontend_name: ServiceRecord(
                        name=frontend_name,
                        type="frontend",
                        cwd=str(context.root / "frontend"),
                        pid=42002,
                        requested_port=context.ports["frontend"].requested,
                        actual_port=context.ports["frontend"].final,
                        status="running",
                    ),
                }

            engine._start_project_services = fake_start_project_services  # type: ignore[method-assign]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume", "--trees", "--batch"], env={}))

            self.assertEqual(code, 0)
            execution_event = next(event for event in engine.events if event.get("event") == "resume.restore.execution")
            self.assertEqual(execution_event.get("mode"), "parallel")
            self.assertEqual(execution_event.get("workers"), 2)

    def test_resume_restore_emits_timing_events_and_prints_summary_in_debug_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-4",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        pid=999999,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )
            dump_state(state, str(run_dir / "run_state.json"))

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 5'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 5'",
                    "ENVCTL_DEBUG_UI_MODE": "deep",
                },
            )
            restore_runner = _ResumeRestoreRunner()
            engine.process_runner = restore_runner  # type: ignore[assignment]

            out = StringIO()
            with (
                patch("envctl_engine.startup.resume_orchestrator.spinner_enabled", return_value=False),
                redirect_stdout(out),
            ):
                code = engine.dispatch(parse_route(["--resume", "--batch"], env={}))

            self.assertEqual(code, 0)
            output = out.getvalue()
            self.assertIn("Restore timing summary:", output)
            self.assertIn("Total restore time:", output)
            self.assertIn("Requirements timing for Main:", output)
            self.assertIn("Service timing for Main:", output)
            self.assertTrue(any(event.get("event") == "resume.restore.step" for event in engine.events))
            self.assertTrue(any(event.get("event") == "requirements.timing.component" for event in engine.events))
            self.assertTrue(any(event.get("event") == "requirements.timing.summary" for event in engine.events))
            self.assertTrue(any(event.get("event") == "service.timing.summary" for event in engine.events))
            timing_events = [event for event in engine.events if event.get("event") == "resume.restore.timing"]
            self.assertEqual(len(timing_events), 1)

    def test_resume_restore_suppresses_timing_lines_when_spinner_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-4b",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        pid=999999,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )
            dump_state(state, str(run_dir / "run_state.json"))

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 5'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 5'",
                    "ENVCTL_DEBUG_UI_MODE": "deep",
                },
            )
            restore_runner = _ResumeRestoreRunner()
            engine.process_runner = restore_runner  # type: ignore[assignment]

            @contextmanager
            def fake_spinner(_message: str, *, enabled: bool, start_immediately: bool = True):
                _ = enabled, start_immediately

                class _SpinnerStub:
                    @staticmethod
                    def update(_inner_message: str) -> None:
                        return None

                    @staticmethod
                    def succeed(_inner_message: str) -> None:
                        return None

                    @staticmethod
                    def fail(_inner_message: str) -> None:
                        return None

                yield _SpinnerStub()

            out = StringIO()
            with (
                patch("envctl_engine.startup.resume_orchestrator.spinner_enabled", return_value=True),
                patch("envctl_engine.startup.resume_orchestrator.spinner", side_effect=fake_spinner),
                redirect_stdout(out),
            ):
                code = engine.dispatch(parse_route(["--resume", "--batch"], env={}))

            self.assertEqual(code, 0)
            output = out.getvalue()
            self.assertNotIn("Restore timing summary:", output)
            self.assertNotIn("Requirements timing for Main:", output)
            self.assertNotIn("Service timing for Main:", output)
            self.assertNotIn("Startup summary:", output)
            self.assertTrue(any(event.get("event") == "resume.restore.step" for event in engine.events))
            self.assertTrue(any(event.get("event") == "requirements.timing.summary" for event in engine.events))
            self.assertTrue(any(event.get("event") == "service.timing.summary" for event in engine.events))

    def test_resume_restore_uses_ownership_verification_when_terminating_stale_services(self) -> None:
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

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        pid=12345,
                        requested_port=8000,
                        actual_port=8000,
                        status="stale",
                    )
                },
                requirements={"Main": RequirementsResult(project="Main")},
            )

            seen_verify_flags: list[bool] = []
            seen_aggressive_flags: list[bool] = []

            def fake_terminate(_service, *, aggressive: bool, verify_ownership: bool):  # noqa: ANN001
                seen_aggressive_flags.append(aggressive)
                seen_verify_flags.append(verify_ownership)
                return False

            context = ProjectContext(
                name="Main",
                root=repo,
                ports={
                    "backend": PortPlan("Main", 8000, 8000, 8000, "requested"),
                    "frontend": PortPlan("Main", 9000, 9000, 9000, "requested"),
                    "db": PortPlan("Main", 5432, 5432, 5432, "requested"),
                    "redis": PortPlan("Main", 6379, 6379, 6379, "requested"),
                    "n8n": PortPlan("Main", 5678, 5678, 5678, "requested"),
                },
            )

            engine._terminate_service_record = fake_terminate  # type: ignore[method-assign]
            engine._resume_context_for_project = lambda _state, _project: context  # type: ignore[method-assign]
            engine._reserve_project_ports = lambda _context: None  # type: ignore[method-assign]
            engine._start_requirements_for_project = (  # type: ignore[method-assign]
                lambda _context, mode, route=None: RequirementsResult(project="Main")
            )
            engine._start_project_services = (  # type: ignore[method-assign]
                lambda _context, requirements, run_id, route=None: {}
            )

            engine._resume_restore_missing(state, ["Main Backend"], route=None)

            self.assertEqual(seen_verify_flags, [True])
            self.assertEqual(seen_aggressive_flags, [True])

    def test_resume_legacy_shell_state_skips_restore_startup(self) -> None:
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
            legacy_state = RunState(
                run_id="legacy-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        pid=12345,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                metadata={"legacy_state": True},
            )

            restore_calls: list[list[str]] = []
            engine._try_load_existing_state = lambda mode=None, strict_mode_match=False: legacy_state  # type: ignore[method-assign]
            engine._reconcile_state_truth = lambda _state: ["Main Backend"]  # type: ignore[method-assign]
            engine._resume_restore_missing = (  # type: ignore[method-assign]
                lambda _state, missing, route=None: restore_calls.append(list(missing)) or []
            )

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertEqual(restore_calls, [])
            self.assertIn("Warning: stale services detected during resume", out.getvalue())

    def test_resume_legacy_shell_state_sanitizes_service_pids_before_truth_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})
            legacy_state = RunState(
                run_id="legacy-2",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        pid=os.getpid(),
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo / "frontend"),
                        pid=os.getpid(),
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
                metadata={"legacy_state": True},
            )

            engine._try_load_existing_state = lambda mode=None, strict_mode_match=False: legacy_state  # type: ignore[method-assign]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertIsNone(legacy_state.services["Main Backend"].pid)
            self.assertIsNone(legacy_state.services["Main Frontend"].pid)
            saved = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
            self.assertIsNone(saved["services"]["Main Backend"]["pid"])
            self.assertIsNone(saved["services"]["Main Frontend"]["pid"])

    def test_terminate_service_record_never_terminates_current_process(self) -> None:
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
            tracking_runner = _TrackingRunner()
            engine.process_runner = tracking_runner  # type: ignore[assignment]

            service = ServiceRecord(
                name="Main Backend",
                type="backend",
                cwd=str(repo / "backend"),
                pid=os.getpid(),
                requested_port=8000,
                actual_port=8000,
                status="running",
            )

            terminated = engine._terminate_service_record(
                service,
                aggressive=False,
                verify_ownership=False,
            )

            self.assertFalse(terminated)
            self.assertEqual(tracking_runner.terminated, [])

    def test_terminate_service_record_verify_ownership_skips_when_port_is_unknown(self) -> None:
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
            tracking_runner = _TrackingRunner()
            engine.process_runner = tracking_runner  # type: ignore[assignment]

            service = ServiceRecord(
                name="Main Backend",
                type="backend",
                cwd=str(repo / "backend"),
                pid=12345,
                requested_port=None,
                actual_port=None,
                status="running",
            )

            terminated = engine._terminate_service_record(
                service,
                aggressive=False,
                verify_ownership=True,
            )

            self.assertFalse(terminated)
            self.assertEqual(tracking_runner.terminated, [])

    def test_terminate_service_record_verify_ownership_checks_in_best_effort_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            deny_runner = _OwnershipDenyRunner()
            engine.process_runner = deny_runner  # type: ignore[assignment]

            service = ServiceRecord(
                name="Main Backend",
                type="backend",
                cwd=str(repo / "backend"),
                pid=12345,
                requested_port=8000,
                actual_port=8000,
                status="running",
            )

            terminated = engine._terminate_service_record(
                service,
                aggressive=False,
                verify_ownership=True,
            )

            self.assertFalse(terminated)
            self.assertEqual(deny_runner.terminated, [])

    def test_resume_skip_startup_flag_disables_restore_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=999999,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )
            dump_state(state, str(run_dir / "run_state.json"))

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})
            restore_runner = _ResumeRestoreRunner()
            engine.process_runner = restore_runner  # type: ignore[assignment]

            code = engine.dispatch(parse_route(["--resume", "--skip-startup", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertEqual(restore_runner.start_calls, [])

    def test_blast_all_docker_volume_policy_defaults_and_overrides(self) -> None:
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

            engine = PythonEngineRuntime(config, env={"DOCKER_PROJECT_NAME": "envctl"})
            planner = _NoopPlanner()
            engine.port_planner = planner  # type: ignore[assignment]
            runner = _TrackingRunner()
            runner.docker_ps_stdout = "cid-main|postgres:16|envctl-postgres\ncid-tree|redis:7|feature-a-1-redis\n"
            runner.inspect_volumes_by_cid = {
                "cid-main": "mainvol\n",
                "cid-tree": "treevol1\ntreevol2\n",
            }
            engine.process_runner = runner  # type: ignore[assignment]

            out_default = StringIO()
            with redirect_stdout(out_default):
                engine.dispatch(parse_route(["blast-all"], env={}))

            self.assertIn("Worktree Docker volumes: remove (default)", out_default.getvalue())
            self.assertIn("Main Docker volumes: keep", out_default.getvalue())

            self.assertIn(("docker", "rm", "-f", "cid-main"), runner.run_calls)
            self.assertIn(
                (
                    "docker",
                    "inspect",
                    "-f",
                    '{{range .Mounts}}{{if eq .Type "volume"}}{{println .Name}}{{end}}{{end}}',
                    "cid-tree",
                ),
                runner.run_calls,
            )
            self.assertIn(("docker", "rm", "-f", "-v", "cid-tree"), runner.run_calls)
            self.assertIn(("docker", "volume", "rm", "treevol1"), runner.run_calls)
            self.assertIn(("docker", "volume", "rm", "treevol2"), runner.run_calls)
            self.assertNotIn(("docker", "rm", "-f", "-v", "cid-main"), runner.run_calls)
            self.assertNotIn(("docker", "volume", "rm", "mainvol"), runner.run_calls)

            engine2 = PythonEngineRuntime(config, env={"DOCKER_PROJECT_NAME": "envctl"})
            engine2.port_planner = _NoopPlanner()  # type: ignore[assignment]
            runner2 = _TrackingRunner()
            runner2.docker_ps_stdout = runner.docker_ps_stdout
            runner2.inspect_volumes_by_cid = runner.inspect_volumes_by_cid
            engine2.process_runner = runner2  # type: ignore[assignment]

            out_override = StringIO()
            with redirect_stdout(out_override):
                engine2.dispatch(
                    parse_route(
                        ["blast-all", "--blast-keep-worktree-volumes", "--blast-remove-main-volumes"],
                        env={},
                    )
                )

            self.assertIn(
                (
                    "docker",
                    "inspect",
                    "-f",
                    '{{range .Mounts}}{{if eq .Type "volume"}}{{println .Name}}{{end}}{{end}}',
                    "cid-main",
                ),
                runner2.run_calls,
            )
            self.assertIn(("docker", "rm", "-f", "-v", "cid-main"), runner2.run_calls)
            self.assertIn(("docker", "volume", "rm", "mainvol"), runner2.run_calls)
            self.assertNotIn(("docker", "rm", "-f", "-v", "cid-tree"), runner2.run_calls)
            self.assertNotIn(("docker", "volume", "rm", "treevol1"), runner2.run_calls)
            self.assertIn("Worktree Docker volumes: keep (override enabled)", out_override.getvalue())
            self.assertIn("Main Docker volumes: remove", out_override.getvalue())

    def test_blast_all_purges_shell_legacy_pointers_and_lock_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "utils").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            # Shell-style state pointers live at runtime root, not python-engine runtime dir.
            (runtime / ".last_state").write_text("/tmp/does-not-matter", encoding="utf-8")
            (runtime / ".last_state.main").write_text("/tmp/does-not-matter", encoding="utf-8")
            (runtime / ".last_state.trees.sample").write_text("/tmp/does-not-matter", encoding="utf-8")

            # Legacy reservation dirs from older shell paths.
            (repo / ".run-sh-port-reservations").mkdir(parents=True, exist_ok=True)
            (repo / "utils" / ".run-sh-port-reservations").mkdir(parents=True, exist_ok=True)

            # Stray shell state pointers historically left around in repo subdirs.
            nested_state = repo / "tmp" / "nested" / ".last_state"
            nested_state.parent.mkdir(parents=True, exist_ok=True)
            nested_state.write_text("/tmp/legacy-state", encoding="utf-8")

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={"ENVCTL_BLAST_ALL_ECOSYSTEM": "false"})
            engine.port_planner = _NoopPlanner()  # type: ignore[assignment]
            engine.process_runner = _TrackingRunner()  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["blast-all"], env={}))

            self.assertEqual(code, 0)
            self.assertFalse((runtime / ".last_state").exists())
            self.assertFalse((runtime / ".last_state.main").exists())
            self.assertFalse((runtime / ".last_state.trees.sample").exists())
            self.assertFalse((repo / ".run-sh-port-reservations").exists())
            self.assertFalse((repo / "utils" / ".run-sh-port-reservations").exists())
            self.assertFalse(nested_state.exists())
            self.assertIn("Purging leftover state pointers and locks", out.getvalue())

    def test_blast_all_uses_batched_lsof_port_sweep(self) -> None:
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
            engine = PythonEngineRuntime(config, env={"DOCKER_PROJECT_NAME": "envctl"})
            engine.port_planner = _NoopPlanner()  # type: ignore[assignment]
            runner = _TrackingRunner()
            engine.process_runner = runner  # type: ignore[assignment]

            engine.dispatch(parse_route(["blast-all"], env={}))

            self.assertIn(("lsof", "-nP", "-iTCP", "-sTCP:LISTEN"), runner.run_calls)
            self.assertFalse(
                any(
                    len(call) >= 3 and call[0] == "lsof" and call[1] == "-t" and str(call[2]).startswith("-iTCP:")
                    for call in runner.run_calls
                ),
                msg=runner.run_calls,
            )

    def test_blast_all_kills_child_processes_of_orphan_listener_pids(self) -> None:
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
            runner = _TrackingRunner()
            runner.ps_stdout = (
                "5000 /usr/bin/python -m uvicorn app.main:app\n"
                "5001 /usr/bin/node /tmp/frontend/node_modules/vite/bin/vite.js\n"
            )
            runner.ps_tree_stdout = "5000 1\n5001 5000\n"
            engine.process_runner = runner  # type: ignore[assignment]

            engine._blast_all_print_and_kill_listener_maps(
                kill_pid_ports={5000: {8060}},
                docker_pid_ports={},
            )

            self.assertIn(("kill", "-9", "5000"), runner.run_calls)
            self.assertIn(("kill", "-9", "5001"), runner.run_calls)

    def test_stop_with_project_selector_only_stops_selected_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo / "trees" / "feature-a" / "1" / "backend"),
                        pid=12001,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "feature-b-1 Backend": ServiceRecord(
                        name="feature-b-1 Backend",
                        type="backend",
                        cwd=str(repo / "trees" / "feature-b" / "1" / "backend"),
                        pid=13001,
                        requested_port=8020,
                        actual_port=8020,
                        status="running",
                    ),
                },
            )
            dump_state(state, str(run_dir / "run_state.json"))

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})
            planner = _NoopPlanner()
            engine.port_planner = planner  # type: ignore[assignment]
            tracking_runner = _TrackingRunner()
            engine.process_runner = tracking_runner  # type: ignore[assignment]

            code = engine.dispatch(parse_route(["stop", "--tree", "--project", "feature-a-1"], env={}))

            self.assertEqual(code, 0)
            self.assertIn(12001, tracking_runner.terminated)
            self.assertNotIn(13001, tracking_runner.terminated)
            persisted = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
            self.assertIn("feature-b-1 Backend", persisted["services"])
            self.assertNotIn("feature-a-1 Backend", persisted["services"])

    def test_stop_returns_zero_when_no_state_exists(self) -> None:
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
            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["stop"], env={}))
            self.assertEqual(code, 0)
            self.assertIn("No active runtime state found.", out.getvalue())

    def test_health_and_errors_report_failed_run_without_services(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-failed",
                mode="main",
                metadata={"failed": True},
            )
            dump_state(state, str(run_dir / "run_state.json"))
            (run_dir / "error_report.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-failed",
                        "errors": ["Startup failed: Requirements unavailable for Main: postgres bind failure"],
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})

            health_out = StringIO()
            with redirect_stdout(health_out):
                health_code = engine.dispatch(parse_route(["health", "--main"], env={}))

            errors_out = StringIO()
            with redirect_stdout(errors_out):
                errors_code = engine.dispatch(parse_route(["errors", "--main"], env={}))

            self.assertEqual(health_code, 1)
            self.assertEqual(errors_code, 1)
            self.assertIn("Startup failed: Requirements unavailable for Main", health_out.getvalue())
            self.assertIn("Startup failed: Requirements unavailable for Main", errors_out.getvalue())

    def test_health_and_errors_support_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-healthy",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend", type="backend", cwd="/tmp/main", status="running", actual_port=8000
                    ),
                },
                requirements={
                    "Main": RequirementsResult(
                        project="Main",
                        redis={"enabled": True, "runtime_status": "healthy", "final": 6380, "success": True},
                        failures=[],
                    )
                },
            )
            dump_state(state, str(run_dir / "run_state.json"))

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})

            health_out = StringIO()
            with (
                patch.object(engine, "_reconcile_state_truth", return_value=[]),
                patch.object(engine, "_requirement_truth_issues", return_value=[]),
                patch.object(engine, "_recent_failure_messages", return_value=[]),
                redirect_stdout(health_out),
            ):
                health_code = engine.dispatch(parse_route(["health", "--main", "--json"], env={}))

            errors_out = StringIO()
            with (
                patch.object(engine, "_reconcile_state_truth", return_value=[]),
                patch.object(engine, "_requirement_truth_issues", return_value=[]),
                patch.object(engine, "_recent_failure_messages", return_value=[]),
                redirect_stdout(errors_out),
            ):
                errors_code = engine.dispatch(parse_route(["errors", "--main", "--json"], env={}))

            health_payload = json.loads(health_out.getvalue())
            errors_payload = json.loads(errors_out.getvalue())
            self.assertEqual(health_code, 0)
            self.assertEqual(errors_code, 0)
            self.assertTrue(health_payload["healthy"])
            self.assertEqual(health_payload["dependencies"][0]["component"], "redis")
            self.assertTrue(errors_payload["ok"])

    def test_stop_clears_failed_run_state_when_no_services_are_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-failed",
                mode="main",
                metadata={"failed": True},
            )
            dump_state(state, str(run_dir / "run_state.json"))

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["stop", "--main", "--yes"], env={}))

            self.assertEqual(code, 0)
            self.assertIn("Stopped runtime state.", out.getvalue())
            self.assertFalse((run_dir / "run_state.json").exists())

    def test_stop_all_is_idempotent_when_no_state_exists(self) -> None:
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
            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["stop-all"], env={}))
            self.assertEqual(code, 0)
            self.assertIn("Stopped runtime state.", out.getvalue())

    def test_blast_all_is_idempotent_when_no_state_exists(self) -> None:
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
            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["blast-all"], env={}))
            self.assertEqual(code, 0)
            self.assertIn("Stopped runtime state.", out.getvalue())


if __name__ == "__main__":
    unittest.main()
