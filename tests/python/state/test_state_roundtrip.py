from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.state import dump_state, load_legacy_shell_state, load_state, merge_states


class StateRoundtripTests(unittest.TestCase):
    def test_json_state_roundtrip_preserves_services(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "run_state.json"
            state = RunState(
                run_id="run-123",
                mode="trees",
                services={
                    "Tree Alpha Backend": ServiceRecord(
                        name="Tree Alpha Backend",
                        type="backend",
                        cwd="/tmp/tree-alpha/backend",
                        pid=12345,
                        requested_port=8000,
                        actual_port=8001,
                        listener_pids=[12345, 12346],
                        status="running",
                        started_at=1234.5,
                    )
                },
                metadata={"source": "python"},
            )

            dump_state(state, str(path))
            loaded = load_state(str(path), allowed_root=tmpdir)

            self.assertEqual(loaded.run_id, "run-123")
            self.assertEqual(loaded.services["Tree Alpha Backend"].actual_port, 8001)
            self.assertEqual(loaded.services["Tree Alpha Backend"].listener_pids, [12345, 12346])
            self.assertEqual(loaded.services["Tree Alpha Backend"].started_at, 1234.5)
            self.assertEqual(loaded.metadata["source"], "python")

    def test_legacy_shell_state_is_loaded_without_source_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy = Path(tmpdir) / "legacy.state"
            legacy.write_text(
                "RUN_ID=legacy-1\n"
                "TREES_MODE=true\n"
                "SERVICE_Tree_Alpha_Backend_TYPE=backend\n"
                "SERVICE_Tree_Alpha_Backend_CWD=/tmp/tree-alpha/backend\n"
                "SERVICE_Tree_Alpha_Backend_REQUESTED_PORT=8000\n"
                "SERVICE_Tree_Alpha_Backend_ACTUAL_PORT=8002\n",
                encoding="utf-8",
            )

            loaded = load_legacy_shell_state(str(legacy), allowed_root=tmpdir)

            self.assertEqual(loaded.run_id, "legacy-1")
            self.assertEqual(loaded.mode, "trees")
            self.assertEqual(loaded.services["Tree Alpha Backend"].actual_port, 8002)

    def test_merge_states_roundtrip_keeps_latest_ports(self) -> None:
        a = RunState(
            run_id="run-a",
            mode="trees",
            services={
                "Tree Alpha Frontend": ServiceRecord(
                    name="Tree Alpha Frontend",
                    type="frontend",
                    cwd="/tmp/tree-alpha/frontend",
                    requested_port=9000,
                    actual_port=9000,
                    status="running",
                )
            },
        )
        b = RunState(
            run_id="run-b",
            mode="trees",
            services={
                "Tree Alpha Frontend": ServiceRecord(
                    name="Tree Alpha Frontend",
                    type="frontend",
                    cwd="/tmp/tree-alpha/frontend",
                    requested_port=9000,
                    actual_port=9002,
                    status="running",
                )
            },
        )

        merged = merge_states([a, b])
        self.assertEqual(merged.run_id, "run-b")
        self.assertEqual(merged.services["Tree Alpha Frontend"].actual_port, 9002)


if __name__ == "__main__":
    unittest.main()
