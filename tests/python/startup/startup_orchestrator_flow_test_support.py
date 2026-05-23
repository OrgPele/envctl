# ruff: noqa: F401
from __future__ import annotations

from contextlib import contextmanager, redirect_stdout
from io import StringIO
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from envctl_engine.config import load_config
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.planning.plan_agent_launch_support import (
    CreatedPlanWorktree,
    PlanAgentAttachTarget,
    PlanAgentLaunchOutcome,
    PlanAgentLaunchResult,
    PlanSelectionResult,
)
import envctl_engine.runtime.engine_runtime_startup_support as startup_support
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.startup.run_reuse_support import RunReuseDecision
from envctl_engine.startup.session import ProjectStartupResult
from envctl_engine.state.models import PortPlan, RequirementsResult, RunState, ServiceRecord
from envctl_engine.ui.status_symbols import STATUS_FAILURE
import envctl_engine.startup.lifecycle as startup_lifecycle


class StartupOrchestratorFlowTestCase(unittest.TestCase):
    def _engine(self, repo: Path, runtime: Path, *, extra: dict[str, str] | None = None) -> PythonEngineRuntime:
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(runtime),
                **(extra or {}),
            }
        )
        return PythonEngineRuntime(config, env={})

    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "backend").mkdir(parents=True, exist_ok=True)
        (repo / "frontend").mkdir(parents=True, exist_ok=True)
        return repo

    def _main_context(self, repo: Path) -> Any:
        return type(
            "Context",
            (),
            {
                "name": "Main",
                "root": repo,
                "ports": {
                    "backend": PortPlan("Main", 8000, 8000, 8000, "requested"),
                    "frontend": PortPlan("Main", 9000, 9000, 9000, "requested"),
                },
            },
        )()

    def _tree_context(self, repo: Path, name: str, tree_rel: str, *, backend_port: int, frontend_port: int) -> Any:
        root = repo / "trees" / tree_rel
        root.mkdir(parents=True, exist_ok=True)
        return type(
            "Context",
            (),
            {
                "name": name,
                "root": root,
                "ports": {
                    "backend": PortPlan(name, backend_port, backend_port, backend_port, "requested"),
                    "frontend": PortPlan(name, frontend_port, frontend_port, frontend_port, "requested"),
                    "db": PortPlan(name, backend_port - 2600, backend_port - 2600, backend_port - 2600, "planned"),
                    "redis": PortPlan(name, backend_port - 1600, backend_port - 1600, backend_port - 1600, "planned"),
                    "n8n": PortPlan(name, backend_port - 2300, backend_port - 2300, backend_port - 2300, "planned"),
                },
            },
        )()

    def _plan_agent_dependency_bootstrap_calls(self, extra_args: list[str]) -> list[tuple[tuple[str, ...], str]]:
        class _RecordingRunner:
            def __init__(self) -> None:
                self.run_calls: list[tuple[tuple[str, ...], str]] = []

            def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = env, timeout
                self.run_calls.append((tuple(str(part) for part in cmd), str(cwd)))
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(
                repo,
                runtime,
                extra={
                    "TREES_STARTUP_ENABLE": "false",
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                },
            )
            context = self._tree_context(repo, "feature-a-1", "feature-a/1", backend_port=8100, frontend_port=9100)
            backend = Path(context.root) / "backend"
            frontend = Path(context.root) / "frontend"
            backend.mkdir(parents=True, exist_ok=True)
            frontend.mkdir(parents=True, exist_ok=True)
            (backend / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            (frontend / "package.json").write_text('{"scripts":{"dev":"vite"}}', encoding="utf-8")
            (frontend / "package-lock.json").write_text("{}", encoding="utf-8")
            runner = _RecordingRunner()
            engine.process_runner = cast(Any, runner)
            engine._command_exists = (  # type: ignore[attr-defined]
                lambda executable: "/" in executable
                or executable in {"npm", "python", "python3", "python3.12", "sh"}
            )
            engine.planning_worktree_orchestrator._last_plan_selection_result = PlanSelectionResult(
                raw_projects=[(context.name, context.root)],
                selected_contexts=[context],
                created_worktrees=(
                    CreatedPlanWorktree(name=context.name, root=Path(context.root), plan_file="feature/task.md"),
                ),
            )
            calls_at_launch: list[tuple[tuple[str, ...], str]] = []

            def _launch(_runtime: object, *, route: object, created_worktrees: tuple[CreatedPlanWorktree, ...]):
                _ = route, created_worktrees
                calls_at_launch.extend(runner.run_calls)
                return PlanAgentLaunchResult(status="launched", reason="launched", outcomes=())

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch("envctl_engine.startup.lifecycle.launch_plan_agent_terminals", side_effect=_launch),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
                patch.object(engine, "_write_artifacts"),
            ):
                code = engine.dispatch(parse_route(["--plan", "feature-a", "--batch", *extra_args], env={}))

            self.assertEqual(code, 0)
            return calls_at_launch


__all__ = [name for name in globals() if not name.startswith("__")]
