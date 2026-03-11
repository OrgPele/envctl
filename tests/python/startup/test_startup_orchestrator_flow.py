from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from envctl_engine.config import load_config
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.startup.session import ProjectStartupResult
from envctl_engine.state.models import RequirementsResult, ServiceRecord


class StartupOrchestratorFlowTests(unittest.TestCase):
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

    def test_disabled_startup_writes_dashboard_state_without_starting_services(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime, extra={"MAIN_STARTUP_ENABLE": "false"})
            captured: dict[str, object] = {}

            route = parse_route([], env={"ENVCTL_DEFAULT_MODE": "main"})
            with (
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
                patch.object(
                    engine,
                    "_write_artifacts",
                    side_effect=lambda state, contexts, *, errors: captured.update(
                        {"state": state, "contexts": list(contexts), "errors": list(errors)}
                    ),
                ),
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            state = captured["state"]
            self.assertEqual(state.services, {})
            self.assertEqual(state.requirements, {})
            self.assertTrue(state.metadata["dashboard_runs_disabled"])
            self.assertIn("dashboard_banner", state.metadata)
            self.assertEqual(captured["errors"], [])

    def test_strict_truth_failure_terminates_started_services_and_writes_failed_state_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime, extra={"ENVCTL_RUNTIME_TRUTH_MODE": "strict"})

            route = parse_route(["start", "--batch"], env={"ENVCTL_DEFAULT_MODE": "main"})
            result = ProjectStartupResult(
                requirements=RequirementsResult(project="Main", health="healthy"),
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        pid=1234,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                warnings=[],
            )
            terminated: list[dict[str, ServiceRecord]] = []

            with (
                patch.object(engine, "_start_project_context", return_value=result),
                patch.object(engine, "_reconcile_state_truth", return_value=["Main Backend"]),
                patch.object(engine, "_write_artifacts") as write_artifacts_mock,
                patch.object(engine, "_terminate_started_services", side_effect=lambda services: terminated.append(services)),
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertEqual(len(terminated), 1)
            self.assertEqual(write_artifacts_mock.call_count, 1)
            written_state = write_artifacts_mock.call_args.args[0]
            self.assertTrue(written_state.metadata["failed"])
            self.assertIn("failure_message", written_state.metadata)
            self.assertIn("Main Backend", written_state.services)


if __name__ == "__main__":
    unittest.main()
