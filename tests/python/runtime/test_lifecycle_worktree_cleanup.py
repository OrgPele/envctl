from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.runtime.lifecycle_worktree_containers import legacy_container_name, remove_tree_containers
from envctl_engine.runtime.lifecycle_worktree_cleanup import WorktreeCleanupDependencies, blast_worktree_before_delete
from envctl_engine.runtime.lifecycle_worktree_metadata import cleanup_artifact_paths, prune_project_metadata
from envctl_engine.runtime.lifecycle_worktree_processes import blast_tree_listener_ports
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

    def test_worktree_delete_aborts_and_retains_authority_when_service_exit_is_unconfirmed(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        saved_states: list[RunState] = []
        released: list[int] = []
        service = ServiceRecord(
            name="Feature Backend",
            type="backend",
            cwd="/repo/feature/backend",
            pid=10,
            actual_port=8000,
        )
        requirements = RequirementsResult(
            project="Feature",
            db={"enabled": True, "final": 5432},
        )
        state = RunState(
            run_id="run-1",
            mode="trees",
            services={service.name: service},
            requirements={"Feature": requirements},
            metadata={"project_roots": {"Feature": "/repo/feature"}},
        )
        runtime = SimpleNamespace(
            _emit=lambda event, **payload: events.append((event, payload)),
            _try_load_existing_state=lambda **kwargs: state if kwargs["mode"] == "trees" else None,
            _project_name_from_service=lambda name: "Feature" if "Feature" in name else "",
            _terminate_services_from_state=lambda *args, **kwargs: {service.name},
            port_planner=SimpleNamespace(release=lambda port: released.append(port)),
            state_repository=SimpleNamespace(
                save_selected_stop_state=lambda **kwargs: saved_states.append(kwargs["state"])
            ),
            process_runner=SimpleNamespace(),
            env={},
        )

        with self.assertRaisesRegex(RuntimeError, "could not confirm service exit"):
            blast_worktree_before_delete(
                runtime,
                project_name="Feature",
                project_root=Path("/repo/feature"),
                source_command="delete-worktree",
            )

        self.assertEqual(len(saved_states), 1)
        self.assertIs(saved_states[0].services[service.name], service)
        self.assertIs(saved_states[0].requirements["Feature"], requirements)
        self.assertEqual(saved_states[0].metadata["project_roots"], {"Feature": "/repo/feature"})
        self.assertEqual(released, [])
        self.assertEqual(events[-1][0], "cleanup.worktree.warning")

    def test_prune_project_metadata_returns_test_artifacts_and_removes_empty_keys(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="trees",
            metadata={
                "project_pr_links": {"Feature": "https://example.test/pr"},
                "project_roots": {"Feature": "/tmp/feature"},
                "project_test_summaries": {
                    "Feature": {
                        "summary_path": "/tmp/results/summary.json",
                        "short_summary_path": "/tmp/results/short.txt",
                    }
                },
                "project_test_results_root": "/tmp/results",
                "project_test_results_updated_at": "now",
            },
        )

        removed = prune_project_metadata(state, project_name="Feature")

        self.assertEqual(removed, [Path("/tmp/results/summary.json"), Path("/tmp/results/short.txt")])
        self.assertNotIn("project_pr_links", state.metadata)
        self.assertNotIn("project_roots", state.metadata)
        self.assertNotIn("project_test_summaries", state.metadata)
        self.assertNotIn("project_test_results_root", state.metadata)
        self.assertNotIn("project_test_results_updated_at", state.metadata)

    def test_cleanup_artifact_paths_removes_files_and_empty_parents(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        root = Path(self.id()).name
        with self.subTest(root=root):
            import tempfile

            with tempfile.TemporaryDirectory() as tmpdir:
                artifact = Path(tmpdir) / "nested" / "summary.json"
                artifact.parent.mkdir()
                artifact.write_text("{}", encoding="utf-8")
                warnings: list[str] = []
                runtime = SimpleNamespace(_emit=lambda event, **payload: events.append((event, payload)))

                cleanup_artifact_paths(runtime, project_name="Feature", paths={artifact}, warnings=warnings)

                self.assertEqual(warnings, [])
                self.assertFalse(artifact.exists())
                self.assertFalse(artifact.parent.exists())
                self.assertEqual(events[0][0], "cleanup.worktree.artifact.removed")

    def test_blast_tree_listener_ports_skips_docker_processes_and_kills_owned_listeners(self) -> None:
        killed: list[int] = []
        events: list[tuple[str, dict[str, object]]] = []
        orchestrator = SimpleNamespace(
            run_best_effort_command=lambda *args, **kwargs: (0, "111\n222\n", ""),
            looks_like_docker_process=lambda command: "docker" in command,
        )
        runtime = SimpleNamespace(
            lifecycle_cleanup_orchestrator=orchestrator,
            _blast_all_process_command=lambda pid: "docker proxy" if pid == 111 else "python app.py",
            _blast_all_kill_pid_tree=lambda pid: killed.append(pid),
            _emit=lambda event, **payload: events.append((event, payload)),
        )

        warnings: list[str] = []
        blast_tree_listener_ports(runtime, project_name="Feature", ports={8000}, warnings=warnings)

        self.assertEqual(warnings, [])
        self.assertEqual(killed, [222])
        self.assertEqual(
            [event for event, _payload in events], ["cleanup.worktree.port.skip", "cleanup.worktree.port.kill"]
        )

    def test_remove_tree_containers_matches_hashed_and_legacy_names_and_removes_volumes(self) -> None:
        calls: list[list[str]] = []
        events: list[tuple[str, dict[str, object]]] = []

        class Runner:
            def run(self, command: list[str], **kwargs: object) -> SimpleNamespace:
                calls.append(command)
                if command[1:4] == ["ps", "-a", "--format"]:
                    return SimpleNamespace(
                        returncode=0,
                        stdout=(
                            f"abc|{legacy_container_name(prefix='envctl-redis', project_name='Feature')}\n"
                            "ignored|unrelated\n"
                        ),
                        stderr="",
                    )
                return SimpleNamespace(returncode=0, stdout="", stderr="")

        runtime = SimpleNamespace(
            process_runner=Runner(),
            env={},
            _collect_container_volume_candidates=lambda cid, volumes: volumes.append("envctl-volume"),
            _emit=lambda event, **payload: events.append((event, payload)),
        )
        warnings: list[str] = []

        remove_tree_containers(
            runtime,
            project_name="Feature",
            project_root=Path("."),
            include_supabase=False,
            remove_named_volumes=True,
            warnings=warnings,
        )

        self.assertEqual(warnings, [])
        self.assertIn(["docker", "rm", "-f", "-v", "abc"], calls)
        self.assertIn(["docker", "volume", "rm", "envctl-volume"], calls)
        self.assertEqual(
            [event for event, _payload in events],
            ["cleanup.worktree.container.removed", "cleanup.worktree.volume.removed"],
        )


if __name__ == "__main__":
    unittest.main()
