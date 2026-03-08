from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.runtime.command_router import parse_route
from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime


class EngineRuntimePortReservationFailuresTests(unittest.TestCase):
    def test_start_returns_actionable_failure_when_reservation_is_exhausted(self) -> None:
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
            planner = engine.port_planner
            release_called = {"value": False}

            def fail_reserve(_start_port: int, owner: str) -> int:
                raise RuntimeError(f"no free port found for owner={owner}")

            original_release = planner.release_session

            def tracked_release() -> None:
                release_called["value"] = True
                original_release()

            planner.reserve_next = fail_reserve  # type: ignore[method-assign]
            planner.release_session = tracked_release  # type: ignore[method-assign]

            route = parse_route(["--plan", "feature-a"], env={})
            code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertTrue(release_called["value"])
            error_report = runtime / "python-engine" / "error_report.json"
            self.assertTrue(error_report.exists())
            payload = json.loads(error_report.read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(payload["errors"]), 1)
            self.assertIn("Port reservation failed", payload["errors"][0])


if __name__ == "__main__":
    unittest.main()
