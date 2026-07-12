from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord
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
                        port_lock_session="planner-session-1",
                        listener_pids=[12345, 12346],
                        status="running",
                        started_at=1234.5,
                        runtime_kind="docker",
                        container_id="sha256:abc",
                        container_name="envctl-app-tree-alpha-backend",
                        container_image="envctl/example-backend:dev",
                        container_launch_token="launch-token-123",
                        container_cleanup_pending_since=1_700_000_000.25,
                    )
                },
                requirements={
                    "Tree Alpha": RequirementsResult(
                        project="Tree Alpha",
                        db={
                            "enabled": True,
                            "final": 5432,
                            "port_lock_session": "planner-session-1",
                        },
                    )
                },
                metadata={"source": "python"},
            )

            dump_state(state, str(path))
            loaded = load_state(str(path), allowed_root=tmpdir)

            self.assertEqual(loaded.run_id, "run-123")
            self.assertEqual(loaded.services["Tree Alpha Backend"].actual_port, 8001)
            self.assertEqual(
                loaded.services["Tree Alpha Backend"].port_lock_session,
                "planner-session-1",
            )
            self.assertEqual(loaded.services["Tree Alpha Backend"].listener_pids, [12345, 12346])
            self.assertEqual(loaded.services["Tree Alpha Backend"].started_at, 1234.5)
            self.assertEqual(
                loaded.requirements["Tree Alpha"].db["port_lock_session"],
                "planner-session-1",
            )
            self.assertEqual(loaded.services["Tree Alpha Backend"].runtime_kind, "docker")
            self.assertEqual(loaded.services["Tree Alpha Backend"].container_id, "sha256:abc")
            self.assertEqual(
                loaded.services["Tree Alpha Backend"].container_name,
                "envctl-app-tree-alpha-backend",
            )
            self.assertEqual(
                loaded.services["Tree Alpha Backend"].container_image,
                "envctl/example-backend:dev",
            )
            self.assertEqual(
                loaded.services["Tree Alpha Backend"].container_launch_token,
                "launch-token-123",
            )
            self.assertEqual(
                loaded.services["Tree Alpha Backend"].container_cleanup_pending_since,
                1_700_000_000.25,
            )
            self.assertEqual(loaded.metadata["source"], "python")

    def test_requirement_storage_key_roundtrip_preserves_authoritative_owner_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "run_state.json"
            state = RunState(
                run_id="run-collision",
                mode="main",
                requirements={
                    "Main Restart Collision": RequirementsResult(
                        project="Main",
                        redis={"enabled": True, "success": True, "final": 6381},
                    )
                },
            )

            dump_state(state, str(path))
            loaded = load_state(str(path), allowed_root=tmpdir)

            self.assertEqual(loaded.requirements["Main Restart Collision"].project, "Main")
            self.assertEqual(loaded.requirements["Main Restart Collision"].redis["final"], 6381)

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

    def test_merge_states_preserves_same_storage_name_owned_by_distinct_projects(self) -> None:
        alpha = ServiceRecord(
            name="Opaque Shared Runtime",
            type="worker",
            cwd="/alpha",
            pid=101,
            project="Alpha",
        )
        beta = ServiceRecord(
            name="Opaque Shared Runtime",
            type="worker",
            cwd="/beta",
            pid=202,
            project="Beta",
        )

        merged = merge_states(
            [
                RunState(run_id="alpha", mode="trees", services={alpha.name: alpha}),
                RunState(run_id="beta", mode="trees", services={beta.name: beta}),
            ]
        )

        self.assertEqual({service.pid for service in merged.services.values()}, {101, 202})
        self.assertEqual(len(merged.services), 2)


if __name__ == "__main__":
    unittest.main()
