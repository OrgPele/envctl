from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.runtime.lifecycle_worktree_cleanup import WorktreeCleanupDependencies, blast_worktree_before_delete
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord


class LifecycleWorktreeCleanupTests(unittest.TestCase):
    def test_blast_worktree_before_delete_updates_matching_project_state(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        saved_states: list[RunState] = []
        released: list[int] = []
        state = RunState(
            run_id="run-1",
            mode="trees",
            services={
                "Feature Backend": ServiceRecord(
                    name="Feature Backend", type="backend", cwd=".", pid=10, actual_port=8000
                ),
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
            state_repository=SimpleNamespace(
                save_selected_stop_state=lambda **kwargs: saved_states.append(kwargs["state"])
            ),
            process_runner=SimpleNamespace(),
            env={},
        )

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

    def test_blast_worktree_before_delete_uses_injected_cleanup_dependencies(self) -> None:
        calls: list[str] = []
        state = RunState(run_id="run-1", mode="trees")
        runtime = SimpleNamespace(
            _emit=lambda *args, **kwargs: None,
            _try_load_existing_state=lambda **kwargs: state if kwargs["mode"] == "trees" else None,
            _project_name_from_service=lambda name: "",
            _terminate_services_from_state=lambda *args, **kwargs: None,
            state_repository=SimpleNamespace(save_selected_stop_state=lambda **kwargs: None),
            process_runner=SimpleNamespace(),
            env={},
        )

        dependencies = WorktreeCleanupDependencies(
            prune_project_metadata=lambda *args, **kwargs: calls.append("metadata") or [],
            blast_tree_listener_ports=lambda *args, **kwargs: calls.append("ports"),
            blast_tree_cwd_processes=lambda *args, **kwargs: calls.append("cwd"),
            cleanup_artifact_paths=lambda *args, **kwargs: calls.append("artifacts"),
            remove_tree_containers=lambda *args, **kwargs: calls.append("containers"),
        )

        warnings = blast_worktree_before_delete(
            runtime,
            project_name="Feature",
            project_root=Path("."),
            source_command="blast-worktree",
            dependencies=dependencies,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(calls, ["ports", "cwd", "artifacts", "containers"])


if __name__ == "__main__":
    unittest.main()
