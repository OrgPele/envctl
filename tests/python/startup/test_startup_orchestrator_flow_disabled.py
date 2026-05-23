# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.startup.startup_orchestrator_flow_test_support import *


class StartupOrchestratorFlowDisabledTests(StartupOrchestratorFlowTestCase):
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
            state = cast(RunState, captured["state"])
            self.assertEqual(state.services, {})
            self.assertEqual(state.requirements, {})
            self.assertTrue(state.metadata["dashboard_runs_disabled"])
            self.assertIn("dashboard_banner", state.metadata)
            self.assertEqual(captured["errors"], [])
