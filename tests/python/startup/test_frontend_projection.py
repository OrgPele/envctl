from __future__ import annotations

import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.state.runtime_map import build_runtime_map, build_runtime_projection
from envctl_engine.shared.services import frontend_env_for_project


class FrontendProjectionTests(unittest.TestCase):
    def _state(self) -> RunState:
        return RunState(
            run_id="run-1",
            mode="trees",
            services={
                "Tree Alpha Backend": ServiceRecord(
                    name="Tree Alpha Backend",
                    type="backend",
                    cwd="/tmp/tree-alpha/backend",
                    requested_port=8000,
                    actual_port=8111,
                    status="running",
                ),
                "Tree Alpha Frontend": ServiceRecord(
                    name="Tree Alpha Frontend",
                    type="frontend",
                    cwd="/tmp/tree-alpha/frontend",
                    requested_port=9000,
                    actual_port=9122,
                    status="running",
                ),
            },
        )

    def test_backend_final_port_projects_to_frontend_env(self) -> None:
        state = self._state()

        env = frontend_env_for_project(state, "Tree Alpha")

        self.assertEqual(env["VITE_BACKEND_URL"], "http://localhost:8111")

    def test_runtime_map_tracks_actual_frontend_rebound_port(self) -> None:
        state = self._state()

        runtime = build_runtime_map(state)

        self.assertEqual(
            runtime["projects"]["Tree Alpha"],
            {
                "backend_port": 8111,
                "frontend_port": 9122,
            },
        )
        self.assertEqual(runtime["service_to_actual_port"]["Tree Alpha Frontend"], 9122)
        self.assertEqual(runtime["port_to_service"][9122], "Tree Alpha Frontend")

    def test_multi_project_projection_uses_per_project_backend_port(self) -> None:
        state = RunState(
            run_id="run-2",
            mode="trees",
            services={
                "Tree Alpha Backend": ServiceRecord(
                    name="Tree Alpha Backend",
                    type="backend",
                    cwd="/tmp/tree-alpha/backend",
                    requested_port=8000,
                    actual_port=8100,
                    status="running",
                ),
                "Tree Alpha Frontend": ServiceRecord(
                    name="Tree Alpha Frontend",
                    type="frontend",
                    cwd="/tmp/tree-alpha/frontend",
                    requested_port=9000,
                    actual_port=9100,
                    status="running",
                ),
                "Tree Beta Backend": ServiceRecord(
                    name="Tree Beta Backend",
                    type="backend",
                    cwd="/tmp/tree-beta/backend",
                    requested_port=8020,
                    actual_port=8200,
                    status="running",
                ),
                "Tree Beta Frontend": ServiceRecord(
                    name="Tree Beta Frontend",
                    type="frontend",
                    cwd="/tmp/tree-beta/frontend",
                    requested_port=9020,
                    actual_port=9200,
                    status="running",
                ),
            },
        )

        alpha_env = frontend_env_for_project(state, "Tree Alpha")
        beta_env = frontend_env_for_project(state, "Tree Beta")
        projection = build_runtime_projection(state)

        self.assertEqual(alpha_env["VITE_BACKEND_URL"], "http://localhost:8100")
        self.assertEqual(beta_env["VITE_BACKEND_URL"], "http://localhost:8200")
        self.assertEqual(projection["Tree Alpha"]["frontend_url"], "http://localhost:9100")
        self.assertEqual(projection["Tree Beta"]["frontend_url"], "http://localhost:9200")

    def test_project_name_match_is_exact_not_prefix_based(self) -> None:
        state = RunState(
            run_id="run-3",
            mode="trees",
            services={
                "feature-a-1 Backend": ServiceRecord(
                    name="feature-a-1 Backend",
                    type="backend",
                    cwd="/tmp/feature-a/1/backend",
                    requested_port=8000,
                    actual_port=8101,
                    status="running",
                ),
                "feature-a-1 Frontend": ServiceRecord(
                    name="feature-a-1 Frontend",
                    type="frontend",
                    cwd="/tmp/feature-a/1/frontend",
                    requested_port=9000,
                    actual_port=9101,
                    status="running",
                ),
                "feature-a-10 Backend": ServiceRecord(
                    name="feature-a-10 Backend",
                    type="backend",
                    cwd="/tmp/feature-a/10/backend",
                    requested_port=8020,
                    actual_port=8110,
                    status="running",
                ),
            },
        )

        env = frontend_env_for_project(state, "feature-a-1")

        self.assertEqual(env["VITE_BACKEND_URL"], "http://localhost:8101")


if __name__ == "__main__":
    unittest.main()
