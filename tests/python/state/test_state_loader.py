from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.state import StateValidationError, load_state, merge_states


class StateLoaderTests(unittest.TestCase):
    def test_load_state_rejects_missing_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "run_id": "run-1",
                        "mode": "trees",
                        "services": {},
                        "pointers": {},
                        "metadata": {},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(StateValidationError):
                load_state(str(state_path), allowed_root=tmpdir)

    def test_load_state_rejects_path_outside_allowed_root(self) -> None:
        with tempfile.TemporaryDirectory() as root_a, tempfile.TemporaryDirectory() as root_b:
            state_path = Path(root_b) / "state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": "run-1",
                        "mode": "trees",
                        "services": {},
                        "pointers": {},
                        "metadata": {},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(StateValidationError):
                load_state(str(state_path), allowed_root=root_a)

    def test_merge_states_prefers_later_state_on_conflicts(self) -> None:
        state_a = RunState(
            run_id="run-a",
            mode="trees",
            services={
                "Tree Alpha Backend": ServiceRecord(
                    name="Tree Alpha Backend",
                    type="backend",
                    cwd="/tmp/tree-alpha/backend",
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                )
            },
            metadata={"updated_at": "2026-02-24T10:00:00Z"},
        )
        state_b = RunState(
            run_id="run-b",
            mode="trees",
            services={
                "Tree Alpha Backend": ServiceRecord(
                    name="Tree Alpha Backend",
                    type="backend",
                    cwd="/tmp/tree-alpha/backend",
                    requested_port=8000,
                    actual_port=8010,
                    status="running",
                )
            },
            metadata={"updated_at": "2026-02-24T10:05:00Z"},
        )

        merged = merge_states([state_a, state_b])

        self.assertEqual(merged.run_id, "run-b")
        self.assertEqual(merged.services["Tree Alpha Backend"].actual_port, 8010)


if __name__ == "__main__":
    unittest.main()
