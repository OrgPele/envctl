from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.runtime.engine_runtime_state_support import (  # noqa: E402
    load_state_artifact,
    on_port_event,
    run_state_to_json,
    state_has_synthetic_services,
)
from envctl_engine.state.models import RunState, ServiceRecord  # noqa: E402


class EngineRuntimeStateSupportTests(unittest.TestCase):
    def test_state_has_synthetic_services_checks_flag_and_status(self) -> None:
        synthetic_flag_state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=1,
                    synthetic=True,
                )
            },
        )
        synthetic_status_state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=1,
                    status="simulated",
                )
            },
        )

        self.assertTrue(state_has_synthetic_services(synthetic_flag_state))
        self.assertTrue(state_has_synthetic_services(synthetic_status_state))

    def test_on_port_event_forwards_payload_to_emit(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(_emit=lambda event, **payload: events.append((event, payload)))

        on_port_event(runtime, "port.lock.acquire", {"port": 8000, "owner": "proj"})

        self.assertEqual(events, [("port.lock.acquire", {"port": 8000, "owner": "proj"})])

    def test_load_state_artifact_and_run_state_to_json_round_trip(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=123,
                    status="running",
                )
            },
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            path.write_text(run_state_to_json(state), encoding="utf-8")

            payload = load_state_artifact(path)

        self.assertEqual(payload["run_id"], "run-1")
        self.assertEqual(payload["mode"], "main")
        self.assertIn("Main Backend", payload["services"])


if __name__ == "__main__":
    unittest.main()
