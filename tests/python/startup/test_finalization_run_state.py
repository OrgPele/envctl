from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.config import load_config
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.startup.finalization_run_state import build_planning_dashboard_state


class FinalizationRunStateTests(unittest.TestCase):
    def test_build_planning_dashboard_state_marks_runs_disabled_and_pointer_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(Path(tmpdir) / "repo"),
                    "RUN_SH_RUNTIME_DIR": str(Path(tmpdir) / "runtime"),
                }
            )
        runtime = SimpleNamespace(
            config=config,
            _run_dir_path=lambda run_id: Path("/runtime") / "runs" / str(run_id),
        )
        route = parse_route(["dashboard"], env={})

        run_state = build_planning_dashboard_state(
            runtime,
            route=route,
            runtime_mode="trees",
            run_id="run-1",
            project_contexts=[SimpleNamespace(name="Feature", root=Path("/repo/trees/feature"))],
            configured_service_types=["backend", "frontend"],
            base_metadata={"source": "test"},
        )

        self.assertEqual(run_state.run_id, "run-1")
        self.assertEqual(run_state.mode, "trees")
        self.assertTrue(run_state.metadata["dashboard_runs_disabled"])
        self.assertEqual(run_state.metadata["dashboard_configured_service_types"], ["backend", "frontend"])
        self.assertEqual(run_state.metadata["source"], "test")
        self.assertEqual(run_state.pointers["run_state"], "/runtime/runs/run-1/run_state.json")
        self.assertEqual(run_state.pointers["events"], "/runtime/runs/run-1/events.jsonl")


if __name__ == "__main__":
    unittest.main()
