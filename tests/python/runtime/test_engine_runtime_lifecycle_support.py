from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.engine_runtime_lifecycle_support import (  # noqa: E402
    blast_worktree_before_delete,
    release_requirement_ports,
    requirement_key_for_project,
    service_port,
    terminate_service_record,
    terminate_services_from_state,
)
from envctl_engine.requirements.common import build_container_name  # noqa: E402
from envctl_engine.requirements.supabase import build_supabase_project_name  # noqa: E402
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

        terminate_services_from_state(
            runtime, state, selected_services={"Main Backend"}, aggressive=True, verify_ownership=False
        )

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

        with patch(
            "envctl_engine.runtime.engine_runtime_lifecycle_support.container_exists", return_value=(False, None)
        ):
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

    def test_blast_worktree_before_delete_blast_worktree_cleans_ports_supabase_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            project_root = root / "trees" / "feature-a" / "1"
            project_root.mkdir(parents=True, exist_ok=True)
            log_path = root / "runtime" / "runs" / "run-1" / "feature_backend.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("backend log\n", encoding="utf-8")
            summary_path = (
                root / "runtime" / "runs" / "run-1" / "test-results" / "run_1" / "Feature" / "failed_tests_summary.txt"
            )
            state_path = summary_path.parent / "test_state.txt"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text("summary\n", encoding="utf-8")
            state_path.write_text("state\n", encoding="utf-8")
            fingerprint_path = root / "runtime" / "supabase_fingerprints" / "feature.json"
            fingerprint_path.parent.mkdir(parents=True, exist_ok=True)
            fingerprint_path.write_text("fingerprint\n", encoding="utf-8")

            events: list[tuple[str, dict[str, object]]] = []
            saved_states: list[RunState] = []
            released: list[int] = []
            killed_pids: list[int] = []
            docker_commands: list[list[str]] = []

            postgres_name = build_container_name(
                prefix="envctl-postgres",
                project_root=project_root.resolve(),
                project_name="Feature",
            )
            supabase_prefix = build_supabase_project_name(
                project_root=project_root.resolve(),
                project_name="Feature",
            )

            class _Runner:
                def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
                    docker_commands.append(list(cmd))
                    if cmd[:5] == ["docker", "ps", "-a", "--format", "{{.ID}}|{{.Names}}"]:
                        stdout = f"cid-postgres|{postgres_name}\ncid-supabase|{supabase_prefix}-supabase-db-1\n"
                        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
                    if cmd[:4] == ["docker", "rm", "-f", "-v"]:
                        return SimpleNamespace(returncode=0, stdout="", stderr="")
                    if cmd[:3] == ["docker", "volume", "rm"]:
                        return SimpleNamespace(returncode=0, stdout="", stderr="")
                    raise AssertionError(f"unexpected command: {cmd}")

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "Feature Backend": ServiceRecord(
                        name="Feature Backend",
                        type="backend",
                        cwd=str(project_root),
                        pid=10,
                        actual_port=8000,
                        log_path=str(log_path),
                    ),
                },
                requirements={
                    "Feature": RequirementsResult(
                        project="Feature",
                        supabase={"enabled": True, "final": 5432},
                    ),
                },
                metadata={
                    "project_test_summaries": {
                        "Feature": {
                            "summary_path": str(summary_path),
                            "state_path": str(state_path),
                            "status": "failed",
                        }
                    },
                    "project_test_results_root": str(summary_path.parent.parent),
                    "project_pr_links": {"Feature": "https://example.test/pr/1"},
                    "project_roots": {"Feature": str(project_root)},
                },
            )

            runtime = SimpleNamespace(
                _emit=lambda event, **payload: events.append((event, payload)),
                _try_load_existing_state=lambda **kwargs: state if kwargs["mode"] == "trees" else None,
                _project_name_from_service=lambda name: "Feature" if "Feature" in name else "",
                _terminate_services_from_state=lambda *args, **kwargs: None,
                _blast_all_process_command=lambda pid: f"python service {pid}",
                _blast_all_kill_pid_tree=lambda pid: killed_pids.append(pid),
                _collect_container_volume_candidates=lambda cid, volumes: volumes.append(f"vol-{cid}"),
                _supabase_fingerprint_path=lambda project_name: fingerprint_path,
                port_planner=SimpleNamespace(release=lambda port: released.append(port)),
                state_repository=SimpleNamespace(
                    save_selected_stop_state=lambda **kwargs: saved_states.append(kwargs["state"])
                ),
                lifecycle_cleanup_orchestrator=SimpleNamespace(
                    run_best_effort_command=lambda cmd, timeout=None: (
                        0,
                        "111\n" if "-iTCP:8000" in cmd else ("222\n" if "-iTCP:5432" in cmd else ""),
                        "",
                    ),
                    looks_like_docker_process=lambda command: False,
                ),
                process_runner=_Runner(),
                env={},
            )

            warnings = blast_worktree_before_delete(
                runtime,
                project_name="Feature",
                project_root=project_root,
                source_command="blast-worktree",
            )

            self.assertEqual(warnings, [])
            self.assertEqual(released, [5432])
            self.assertCountEqual(killed_pids, [111, 222])
            self.assertEqual(saved_states[0].services, {})
            self.assertEqual(saved_states[0].requirements, {})
            self.assertNotIn("Feature", saved_states[0].metadata.get("project_pr_links", {}))
            self.assertNotIn("Feature", saved_states[0].metadata.get("project_roots", {}))
            self.assertNotIn("Feature", saved_states[0].metadata.get("project_test_summaries", {}))
            self.assertFalse(log_path.exists())
            self.assertFalse(summary_path.exists())
            self.assertFalse(state_path.exists())
            self.assertFalse(fingerprint_path.exists())
            self.assertIn(["docker", "rm", "-f", "-v", "cid-postgres"], docker_commands)
            self.assertIn(["docker", "rm", "-f", "-v", "cid-supabase"], docker_commands)
            self.assertIn(["docker", "volume", "rm", "vol-cid-postgres"], docker_commands)
            self.assertIn(["docker", "volume", "rm", "vol-cid-supabase"], docker_commands)
            self.assertEqual(events[-1][0], "cleanup.worktree.finish")

    def test_blast_worktree_before_delete_removes_legacy_truncated_dependency_container_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            project_root = (
                root / "trees" / "implementations_hebrew_rtl_full_app_localization_100_percent_gap_closure" / "1"
            )
            project_root.mkdir(parents=True, exist_ok=True)
            project_name = "implementations_hebrew_rtl_full_app_localization_100_percent_gap_closure-1"

            events: list[tuple[str, dict[str, object]]] = []
            docker_commands: list[list[str]] = []

            class _Runner:
                def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
                    docker_commands.append(list(cmd))
                    if cmd[:5] == ["docker", "ps", "-a", "--format", "{{.ID}}|{{.Names}}"]:
                        stdout = (
                            "cid-redis|envctl-redis-implementations-hebrew-rtl-full-app-localization-1\n"
                            "cid-n8n|envctl-n8n-implementations-hebrew-rtl-full-app-localization-100\n"
                            "cid-supabase|envctl-supabase-implementations-hebrew-rtl-full-app-localizatio-supabase-db-1\n"
                        )
                        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
                    if cmd[:4] == ["docker", "rm", "-f", "-v"]:
                        return SimpleNamespace(returncode=0, stdout="", stderr="")
                    if cmd[:3] == ["docker", "volume", "rm"]:
                        return SimpleNamespace(returncode=0, stdout="", stderr="")
                    raise AssertionError(f"unexpected command: {cmd}")

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={},
                requirements={
                    project_name: RequirementsResult(
                        project=project_name,
                        supabase={"enabled": True, "final": 5636},
                        redis={"enabled": True, "final": 6583},
                        n8n={"enabled": True, "final": 5882},
                    ),
                },
                metadata={"project_roots": {project_name: str(project_root)}},
            )

            runtime = SimpleNamespace(
                _emit=lambda event, **payload: events.append((event, payload)),
                _try_load_existing_state=lambda **kwargs: state if kwargs["mode"] == "trees" else None,
                _project_name_from_service=lambda name: "",
                _terminate_services_from_state=lambda *args, **kwargs: None,
                port_planner=SimpleNamespace(release=lambda _port: None),
                state_repository=SimpleNamespace(save_selected_stop_state=lambda **kwargs: None),
                process_runner=_Runner(),
                env={},
            )

            warnings = blast_worktree_before_delete(
                runtime,
                project_name=project_name,
                project_root=project_root,
                source_command="blast-worktree",
            )

            self.assertEqual(warnings, [])
            self.assertIn(["docker", "rm", "-f", "-v", "cid-redis"], docker_commands)
            self.assertIn(["docker", "rm", "-f", "-v", "cid-n8n"], docker_commands)
            self.assertIn(["docker", "rm", "-f", "-v", "cid-supabase"], docker_commands)


if __name__ == "__main__":
    unittest.main()
