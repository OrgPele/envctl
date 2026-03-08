from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.runtime.engine_runtime_lifecycle_support import (  # noqa: E402
    blast_worktree_before_delete,
    release_requirement_ports,
    requirement_key_for_project,
    service_port,
    terminate_service_record,
    terminate_services_from_state,
)
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord  # noqa: E402


class EngineRuntimeLifecycleSupportTests(unittest.TestCase):
    def test_service_port_prefers_actual_then_requested(self) -> None:
        self.assertEqual(service_port(SimpleNamespace(actual_port=9000, requested_port=8000)), 9000)
        self.assertEqual(service_port(SimpleNamespace(actual_port=None, requested_port=8000)), 8000)
        self.assertIsNone(service_port(SimpleNamespace(actual_port=None, requested_port=None)))

    def test_release_requirement_ports_releases_enabled_final_ports(self) -> None:
        released: list[int] = []
        runtime = SimpleNamespace(port_planner=SimpleNamespace(release=lambda port: released.append(port)))
        requirements = RequirementsResult(
            project="Main",
            db={"enabled": True, "final": 5432},
            redis={"enabled": False, "final": 6379},
            n8n={"enabled": True, "final": 5678},
        )

        release_requirement_ports(runtime, requirements)

        self.assertEqual(released, [5432, 5678])

    def test_requirement_key_for_project_matches_case_insensitive(self) -> None:
        state = RunState(run_id="run-1", mode="main", requirements={"Main": RequirementsResult(project="Main")})
        self.assertEqual(requirement_key_for_project(state, "main"), "Main")

    def test_terminate_service_record_skips_self_and_parent(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(
            _emit=lambda event, **payload: events.append((event, payload)),
            process_runner=SimpleNamespace(),
        )

        with patch.object(os, "getpid", return_value=100), patch.object(os, "getppid", return_value=200):
            terminated = terminate_service_record(
                runtime,
                SimpleNamespace(name="Main Backend", pid=100, actual_port=8000),
                aggressive=False,
                verify_ownership=False,
            )

        self.assertFalse(terminated)
        self.assertEqual(events[0][0], "cleanup.skip")

    def test_terminate_services_from_state_releases_ports_for_terminated_services(self) -> None:
        released: list[int] = []
        terminated: list[int] = []
        runtime = SimpleNamespace(
            port_planner=SimpleNamespace(release=lambda port: released.append(port)),
            _terminate_service_record=lambda service, **kwargs: terminated.append(service.pid) or True,
        )
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd=".", pid=1, actual_port=8000),
                "Main Frontend": ServiceRecord(name="Main Frontend", type="frontend", cwd=".", pid=2, actual_port=9000),
            },
        )

        terminate_services_from_state(runtime, state, selected_services={"Main Backend"}, aggressive=True, verify_ownership=False)

        self.assertEqual(terminated, [1])
        self.assertEqual(released, [8000])

    def test_blast_worktree_before_delete_updates_state_and_emits_finish(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        saved_states: list[RunState] = []
        released: list[int] = []
        state = RunState(
            run_id="run-1",
            mode="trees",
            services={
                "Feature Backend": ServiceRecord(name="Feature Backend", type="backend", cwd=".", pid=10, actual_port=8000),
            },
            requirements={
                "Feature": RequirementsResult(project="Feature", db={"enabled": True, "final": 5432}),
            },
        )
        runtime = SimpleNamespace(
            _emit=lambda event, **payload: events.append((event, payload)),
            _try_load_existing_state=lambda **kwargs: state if kwargs["mode"] == "trees" else None,
            _project_name_from_service=lambda name: "Feature" if "Feature" in name else "",
            _terminate_services_from_state=lambda *args, **kwargs: None,
            port_planner=SimpleNamespace(release=lambda port: released.append(port)),
            state_repository=SimpleNamespace(save_selected_stop_state=lambda **kwargs: saved_states.append(kwargs["state"])),
            process_runner=SimpleNamespace(),
            env={},
        )

        with patch("envctl_engine.runtime.engine_runtime_lifecycle_support.container_exists", return_value=(False, None)):
            warnings = blast_worktree_before_delete(
                runtime,
                project_name="Feature",
                project_root=Path("."),
                source_command="delete-worktree",
            )

        self.assertEqual(warnings, [])
        self.assertEqual(released, [5432])
        self.assertEqual(saved_states[0].services, {})
        self.assertEqual(saved_states[0].requirements, {})
        self.assertEqual(events[-1][0], "cleanup.worktree.finish")


if __name__ == "__main__":
    unittest.main()
