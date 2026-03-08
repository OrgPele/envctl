from __future__ import annotations

import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.shared.services import frontend_env_for_project


class FrontendEnvProjectionRealPortsTests(unittest.TestCase):
    def test_frontend_env_uses_backend_actual_listener_port(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="trees",
            services={
                "feature-a-1 Backend": ServiceRecord(
                    name="feature-a-1 Backend",
                    type="backend",
                    cwd="/tmp/feature-a-1/backend",
                    requested_port=8000,
                    actual_port=8014,
                    status="running",
                ),
                "feature-a-1 Frontend": ServiceRecord(
                    name="feature-a-1 Frontend",
                    type="frontend",
                    cwd="/tmp/feature-a-1/frontend",
                    requested_port=9000,
                    actual_port=9002,
                    status="running",
                ),
            },
        )

        env = frontend_env_for_project(state, "feature-a-1")

        self.assertEqual(env["VITE_BACKEND_URL"], "http://localhost:8014")


if __name__ == "__main__":
    unittest.main()
