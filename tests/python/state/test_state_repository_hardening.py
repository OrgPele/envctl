from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from envctl_engine.state import dump_state, load_state
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord
from envctl_engine.state.persistence import fsync_directory
from envctl_engine.state.repository import RuntimeStateRepository
from envctl_engine.state.run_index import StateSelector


class StateRepositoryHardeningTests(unittest.TestCase):
    @staticmethod
    def _repository(
        root: Path,
        *,
        scope: str = "scope-a",
        compat_mode: str = RuntimeStateRepository.SCOPED_ONLY,
    ) -> RuntimeStateRepository:
        runtime_dir = root / "runtime"
        return RuntimeStateRepository(
            runtime_root=runtime_dir / scope,
            runtime_legacy_root=runtime_dir / "python-engine",
            runtime_dir=runtime_dir,
            runtime_scope_id=scope,
            compat_mode=compat_mode,
        )

    @staticmethod
    def _state(
        run_id: str,
        project: str,
        *,
        port: int = 8000,
        metadata: dict[str, object] | None = None,
    ) -> RunState:
        return RunState(
            run_id=run_id,
            mode="main" if project.casefold() == "main" else "trees",
            services={
                f"{project} Backend": ServiceRecord(
                    name=f"{project} Backend",
                    type="backend",
                    cwd=f"/tmp/{project}/backend",
                    project=project,
                    requested_port=port,
                    actual_port=port,
                    status="running",
                )
            },
            metadata=dict(metadata or {}),
        )

    @staticmethod
    def _context(root: Path, project: str, port: int) -> object:
        return SimpleNamespace(
            name=project,
            root=root / project,
            ports={
                "backend": SimpleNamespace(
                    requested=port,
                    assigned=port,
                    final=port,
                    source="requested",
                    retries=0,
                )
            },
        )

    @staticmethod
    def _save_resume(repo: RuntimeStateRepository, state: RunState) -> None:
        repo.save_resume_state(
            state=state,
            emit=lambda *_args, **_kwargs: None,
            runtime_map_builder=lambda saved: {"run_id": saved.run_id},
        )

    @staticmethod
    def _save_run(
        repo: RuntimeStateRepository,
        state: RunState,
        *,
        context: object,
        errors: list[str] | None = None,
    ) -> None:
        repo.save_run(
            state=state,
            contexts=[context],
            errors=list(errors or []),
            events=[{"event": state.run_id}],
            emit=lambda *_args, **_kwargs: None,
            runtime_map_builder=lambda saved: {"run_id": saved.run_id},
        )

    def test_clean_save_scavenges_crash_temps_for_rewritten_alias_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repository(root)
            state = self._state("run-a", "Main")
            self._save_resume(repo, state)
            run_dir = repo.run_dir_path("run-a")
            stale_root_alias = repo.runtime_root / ".run_state.json.abcdefgh.tmp"
            stale_run_alias = run_dir / ".run_state.json.ijklmnop.tmp"
            stale_index = repo.runtime_root / ".run_index.json.qrstuvwx.tmp"
            for path in (stale_root_alias, stale_run_alias, stale_index):
                path.write_text("crash debris", encoding="utf-8")

            self._save_resume(repo, state)

            self.assertFalse(stale_root_alias.exists())
            self.assertFalse(stale_run_alias.exists())
            self.assertFalse(stale_index.exists())

    def test_revision_retention_keeps_indexed_revision_and_one_grace_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repository(root)
            revisions_dir = repo.run_dir_path("run-a") / "revisions"
            external = root / "external"
            external.mkdir()

            with patch(
                "envctl_engine.state.repository.fsync_directory",
                wraps=fsync_directory,
            ) as synced_directory:
                for port in range(8100, 8106):
                    self._save_resume(repo, self._state("run-a", "feature-a", port=port))
                    real_revisions = [
                        path for path in revisions_dir.iterdir() if path.is_dir() and not path.is_symlink()
                    ]
                    self.assertLessEqual(len(real_revisions), 2)

            candidate = repo.run_index.candidates(StateSelector(mode="trees", project_names=()))[0]
            real_revisions = [path for path in revisions_dir.iterdir() if path.is_dir() and not path.is_symlink()]
            self.assertEqual(len(real_revisions), 2)
            self.assertIn(candidate.state_path.parent, real_revisions)
            self.assertTrue(any(call.args == (revisions_dir,) for call in synced_directory.call_args_list))

            external_sentinel = external / "sentinel"
            external_sentinel.write_text("safe", encoding="utf-8")
            revision_link = revisions_dir / "foreign-link"
            revision_link.symlink_to(external, target_is_directory=True)
            self._save_resume(repo, self._state("run-a", "feature-a", port=9000))
            self.assertTrue(revision_link.is_symlink())
            self.assertEqual(external_sentinel.read_text(encoding="utf-8"), "safe")

    def test_revision_pruning_is_deferred_until_failed_promotion_is_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repository(root)
            for port in (8100, 8101):
                self._save_resume(repo, self._state("run-a", "feature-a", port=port))
            revisions_dir = repo.run_dir_path("run-a") / "revisions"
            self.assertEqual(len([path for path in revisions_dir.iterdir() if path.is_dir()]), 2)

            with patch.object(
                repo,
                "_promote_latest_active_state",
                side_effect=OSError("alias promotion unavailable"),
            ):
                self._save_resume(repo, self._state("run-a", "feature-a", port=8102))
            self.assertEqual(len([path for path in revisions_dir.iterdir() if path.is_dir()]), 3)

            loaded = repo.load_latest(mode="trees", strict_mode_match=True)
            self.assertIsNotNone(loaded)
            self.assertEqual(len([path for path in revisions_dir.iterdir() if path.is_dir()]), 2)

    def test_supersession_prunes_failed_promotion_backlog_for_retired_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repository(root)
            for port in (8100, 8101):
                self._save_resume(repo, self._state("run-old", "feature-a", port=port))
            revisions_dir = repo.run_dir_path("run-old") / "revisions"
            with patch.object(
                repo,
                "_promote_latest_active_state",
                side_effect=OSError("alias promotion unavailable"),
            ):
                for port in (8102, 8103, 8104):
                    self._save_resume(repo, self._state("run-old", "feature-a", port=port))
            self.assertEqual(len([path for path in revisions_dir.iterdir() if path.is_dir()]), 5)

            replacement = self._state(
                "run-new",
                "feature-a",
                port=8200,
                metadata={"state_source_run_ids": ["run-old"]},
            )
            self._save_resume(repo, replacement)

            self.assertEqual(len([path for path in revisions_dir.iterdir() if path.is_dir()]), 2)
            payload = json.loads(repo.run_index.index_path.read_text(encoding="utf-8"))
            self.assertEqual([entry["run_id"] for entry in payload["entries"]], ["run-new"])
            self.assertIn("run-old", payload["retired_run_ids"])

    def test_revision_cleanup_io_failures_do_not_lose_state_and_are_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repository(root)
            for port in (8100, 8101):
                self._save_resume(repo, self._state("run-old", "feature-a", port=port))
            revisions_dir = repo.run_dir_path("run-old") / "revisions"
            with patch.object(
                repo,
                "_promote_latest_active_state",
                side_effect=OSError("alias promotion unavailable"),
            ):
                for port in (8102, 8103, 8104):
                    self._save_resume(repo, self._state("run-old", "feature-a", port=port))

            replacement = self._state(
                "run-new",
                "feature-a",
                port=8200,
                metadata={"state_source_run_ids": ["run-old"]},
            )
            with patch(
                "envctl_engine.state.repository.shutil.rmtree",
                side_effect=OSError("cleanup unavailable"),
            ):
                self._save_resume(repo, replacement)

            self.assertEqual(len([path for path in revisions_dir.iterdir() if path.is_dir()]), 5)
            cleanup_dir = repo.runtime_root / repo._REVISION_CLEANUP_DIR_NAME
            self.assertEqual(len(list(cleanup_dir.glob("*.json"))), 1)
            for index in range(100):
                clean_history = repo.run_dir_path(f"inactive-{index}") / "revisions" / "only-revision"
                clean_history.mkdir(parents=True)
            original_prune = repo._prune_run_revisions_unlocked
            inspected_run_ids: list[str] = []

            def recording_prune(candidate: object) -> None:
                inspected_run_ids.append(str(getattr(candidate, "run_id", "")))
                original_prune(candidate)  # type: ignore[arg-type]

            with patch.object(
                repo,
                "_prune_run_revisions_unlocked",
                side_effect=recording_prune,
            ):
                loaded = repo.load_latest(mode="trees", strict_mode_match=True)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.run_id, "run-new")
            self.assertEqual(len([path for path in revisions_dir.iterdir() if path.is_dir()]), 2)
            self.assertEqual(set(inspected_run_ids), {"run-new", "run-old"})
            self.assertFalse(cleanup_dir.exists())

            with patch(
                "envctl_engine.state.repository.fsync_directory",
                side_effect=OSError("directory fsync failed"),
            ):
                for port in (8201, 8202):
                    self._save_resume(repo, self._state("run-new", "feature-a", port=port))
            loaded = repo.load_latest(mode="trees", strict_mode_match=True)
            self.assertIsNotNone(loaded)
            self.assertLessEqual(
                len([path for path in (repo.run_dir_path("run-new") / "revisions").iterdir() if path.is_dir()]),
                2,
            )

    def test_superseded_cleanup_is_queued_when_alias_promotion_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repository(root)
            with patch.object(
                repo,
                "_promote_latest_active_state",
                side_effect=OSError("alias promotion unavailable"),
            ):
                for port in range(8100, 8105):
                    self._save_resume(repo, self._state("run-old", "feature-a", port=port))
                self._save_resume(
                    repo,
                    self._state(
                        "run-new",
                        "feature-a",
                        port=8200,
                        metadata={"state_source_run_ids": ["run-old"]},
                    ),
                )

            old_revisions = repo.run_dir_path("run-old") / "revisions"
            cleanup_dir = repo.runtime_root / repo._REVISION_CLEANUP_DIR_NAME
            self.assertEqual(
                len([path for path in old_revisions.iterdir() if path.is_dir()]),
                5,
            )
            self.assertEqual(len(list(cleanup_dir.glob("*.json"))), 1)

            loaded = repo.load_latest(mode="trees", strict_mode_match=True)

            self.assertIsNotNone(loaded)
            self.assertLessEqual(
                len([path for path in old_revisions.iterdir() if path.is_dir()]),
                2,
            )
            self.assertFalse(cleanup_dir.exists())

    def test_current_ancillary_alias_signatures_detect_tampering_and_source_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repository(
                root,
                compat_mode=RuntimeStateRepository.COMPAT_READ_WRITE,
            )
            self._save_run(
                repo,
                self._state("run-a", "Main"),
                context=self._context(root, "Main", 8000),
                errors=["expected error"],
            )
            self.assertTrue(
                repo.write_runtime_artifact(
                    run_id="run-a",
                    artifact_name="runtime_readiness_report.json",
                    text='{"passed": true}',
                )
            )
            candidate = repo.run_index.candidates(StateSelector(mode="main", project_names=()))[0]
            scoped_ports = repo.ports_manifest_path()
            expected_ports = scoped_ports.read_text(encoding="utf-8")
            scoped_ports.write_text("x" * len(expected_ports), encoding="utf-8")
            repo.load_latest()
            self.assertEqual(scoped_ports.read_text(encoding="utf-8"), expected_ports)

            legacy_error = repo.runtime_legacy_root / "error_report.json"
            expected_error = legacy_error.read_text(encoding="utf-8")
            legacy_error.write_text("x" * len(expected_error), encoding="utf-8")
            repo.load_latest()
            repaired_error = json.loads(legacy_error.read_text(encoding="utf-8"))
            self.assertEqual(repaired_error["errors"], ["expected error"])
            self.assertEqual(
                legacy_error.read_text(encoding="utf-8"),
                repo.error_report_path().read_text(encoding="utf-8"),
            )

            source_events = candidate.state_path.parent / "events.jsonl"
            updated_events = '{"event": "late-source-update"}\n'
            source_events.write_text(updated_events, encoding="utf-8")
            repo.load_latest()
            self.assertEqual(
                (repo.runtime_root / "events.jsonl").read_text(encoding="utf-8"),
                updated_events,
            )
            self.assertEqual(
                (repo.runtime_legacy_root / "events.jsonl").read_text(encoding="utf-8"),
                updated_events,
            )

    def test_per_run_alias_manifest_uses_signatures_and_repairs_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repository(root)
            self._save_run(
                repo,
                self._state("run-a", "Main"),
                context=self._context(root, "Main", 8000),
            )
            self.assertTrue(
                repo.write_runtime_artifact(
                    run_id="run-a",
                    artifact_name="runtime_readiness_report.json",
                    text='{"passed": true}',
                )
            )
            repo.load_latest()
            candidate = repo.run_index.candidates(StateSelector(mode="main", project_names=()))[0]

            observed_reads: list[Path] = []
            original_read_text = Path.read_text

            def recording_read_text(path: Path, *args: object, **kwargs: object) -> str:
                observed_reads.append(path)
                return original_read_text(path, *args, **kwargs)

            indexed = repo._load_valid_index_states(
                [candidate],
                allowed_root=str(repo.runtime_dir),
            )
            observed_reads.clear()
            with patch.object(Path, "read_text", recording_read_text):
                repo._reconcile_run_aliases_unlocked(indexed)

            source_dir = candidate.state_path.parent
            run_dir = repo.run_dir_path("run-a")
            compared_artifacts = {source_dir / artifact_name for artifact_name in repo._RUN_ALIAS_ARTIFACT_NAMES} | {
                run_dir / artifact_name for artifact_name in repo._RUN_ALIAS_ARTIFACT_NAMES
            }
            self.assertTrue(compared_artifacts.isdisjoint(observed_reads))

            tampered_alias = run_dir / "events.jsonl"
            expected_events = (source_dir / "events.jsonl").read_text(encoding="utf-8")
            tampered_alias.write_text("x" * len(expected_events), encoding="utf-8")
            repo.load_latest()
            self.assertEqual(tampered_alias.read_text(encoding="utf-8"), expected_events)

    def test_deactivate_does_not_retire_unknown_run_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = self._repository(Path(tmpdir))
            self._save_resume(repo, self._state("run-active", "Main"))

            self.assertFalse(repo.deactivate_run("never-active"))
            self.assertTrue(repo.deactivate_runs(["run-active", "also-never-active"]))

            payload = json.loads(repo.run_index.index_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["retired_run_ids"], ["run-active"])

    def test_legacy_migration_preserves_failed_health_state_and_all_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime_dir = root / "runtime"
            legacy_root = runtime_dir / "python-engine"
            legacy_root.mkdir(parents=True)
            failed_state = RunState(
                run_id="legacy-failed",
                mode="main",
                requirements={
                    "Main": RequirementsResult(
                        project="Main",
                        health="degraded",
                        failures=["redis unavailable"],
                        components={
                            "redis": {
                                "enabled": True,
                                "success": False,
                                "runtime_status": "unreachable",
                            }
                        },
                    )
                },
                metadata={"failed": True},
            )
            dump_state(failed_state, str(legacy_root / "run_state.json"))
            artifacts = {
                "runtime_map.json": '{"legacy": true}',
                "ports_manifest.json": '{"projects": [{"project": "Main", "ports": {}}]}',
                "error_report.json": '{"errors": ["redis unavailable"]}',
                "events.jsonl": '{"event": "failed"}\n',
                "runtime_readiness_report.json": '{"passed": false}',
            }
            for artifact_name, text in artifacts.items():
                (legacy_root / artifact_name).write_text(text, encoding="utf-8")

            repo = self._repository(
                root,
                compat_mode=RuntimeStateRepository.COMPAT_READ_ONLY,
            )
            loaded = repo.load_latest(mode="main", strict_mode_match=True)

            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertTrue(loaded.metadata["failed"])
            self.assertEqual(loaded.requirements["Main"].health, "degraded")
            self.assertEqual(
                loaded.requirements["Main"].component("redis")["runtime_status"],
                "unreachable",
            )
            candidate = repo.run_index.candidates(StateSelector(mode="main", project_names=()))[0]
            for artifact_name, expected in artifacts.items():
                self.assertEqual(
                    (candidate.state_path.parent / artifact_name).read_text(encoding="utf-8"),
                    expected,
                )

    def test_unbound_diagnostics_do_not_replace_active_aliases_and_purge_cleans_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repository(
                root,
                compat_mode=RuntimeStateRepository.COMPAT_READ_WRITE,
            )
            runtime_root = repo.runtime_root
            legacy_root = repo.runtime_legacy_root
            no_run_event = '{"event": "no-run"}\n'
            self.assertTrue(
                repo.write_runtime_artifact(
                    run_id=None,
                    artifact_name="events.jsonl",
                    text=no_run_event,
                )
            )
            self.assertEqual((runtime_root / "events.jsonl").read_text(encoding="utf-8"), no_run_event)
            self.assertEqual((legacy_root / "events.jsonl").read_text(encoding="utf-8"), no_run_event)

            self._save_run(
                repo,
                self._state("run-a", "Main"),
                context=self._context(root, "Main", 8000),
            )
            active_event = (runtime_root / "events.jsonl").read_text(encoding="utf-8")
            diagnostic_event = '{"event": "doctor"}\n'
            self.assertTrue(
                repo.write_runtime_artifact(
                    run_id=None,
                    artifact_name="events.jsonl",
                    text=diagnostic_event,
                )
            )
            self.assertEqual((runtime_root / "events.jsonl").read_text(encoding="utf-8"), active_event)
            self.assertEqual((legacy_root / "events.jsonl").read_text(encoding="utf-8"), active_event)
            self.assertEqual(
                (runtime_root / "diagnostics" / "events.jsonl").read_text(encoding="utf-8"),
                diagnostic_event,
            )

            repo.purge(aggressive=False)
            self.assertFalse((runtime_root / "diagnostics").exists())

    def test_shared_legacy_pointers_are_only_removed_by_their_own_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo_a = self._repository(
                root,
                scope="scope-a",
                compat_mode=RuntimeStateRepository.COMPAT_READ_WRITE,
            )
            repo_b = self._repository(
                root,
                scope="scope-b",
                compat_mode=RuntimeStateRepository.COMPAT_READ_WRITE,
            )
            self._save_run(
                repo_a,
                self._state("run-a", "feature-a"),
                context=self._context(root, "feature-a", 8100),
            )
            self._save_run(
                repo_b,
                self._state("run-b", "feature-b"),
                context=self._context(root, "feature-b", 8200),
            )
            legacy_root = repo_a.runtime_legacy_root
            pointer_b_name = repo_b._tree_pointer_name("feature-b")
            assert pointer_b_name is not None
            pointer_b = legacy_root / pointer_b_name
            generic_pointer = legacy_root / ".last_state"
            self.assertIn("scope-b", Path(pointer_b.read_text(encoding="utf-8")).parts)
            self.assertIn("scope-b", Path(generic_pointer.read_text(encoding="utf-8")).parts)

            self.assertTrue(repo_a.deactivate_run("run-a"))

            self.assertTrue(pointer_b.is_file())
            self.assertTrue(generic_pointer.is_file())
            self.assertIn("scope-b", Path(pointer_b.read_text(encoding="utf-8")).parts)
            self.assertIn("scope-b", Path(generic_pointer.read_text(encoding="utf-8")).parts)

    def test_partial_restart_ports_merge_current_context_with_preserved_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repository(root)
            initial = RunState(
                run_id="run-ab",
                mode="trees",
                services={
                    **self._state("unused", "feature-a", port=8100).services,
                    **self._state("unused", "feature-b", port=8200).services,
                },
            )
            repo.save_run(
                state=initial,
                contexts=[
                    self._context(root, "feature-a", 8100),
                    self._context(root, "feature-b", 8200),
                ],
                errors=[],
                events=[],
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda saved: {"run_id": saved.run_id},
            )
            restarted = RunState(
                run_id="run-restart-a",
                mode="trees",
                services={
                    **self._state("unused", "feature-a", port=8111).services,
                    **self._state("unused", "feature-b", port=8200).services,
                },
                metadata={"state_source_run_ids": ["run-ab"]},
            )
            self._save_run(
                repo,
                restarted,
                context=self._context(root, "feature-a", 8111),
            )

            payload = json.loads(repo.ports_manifest_path().read_text(encoding="utf-8"))
            ports_by_project = {
                project["project"]: project["ports"]["backend"]["final"] for project in payload["projects"]
            }
            self.assertEqual(ports_by_project, {"feature-a": 8111, "feature-b": 8200})

    def test_aggregate_aliases_merge_independent_owner_ports_and_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repository(root)
            self._save_run(
                repo,
                self._state("run-a", "feature-a", port=8100),
                context=self._context(root, "feature-a", 8100),
                errors=["feature-a failed"],
            )
            self._save_run(
                repo,
                self._state("run-b", "feature-b", port=8200),
                context=self._context(root, "feature-b", 8200),
                errors=["feature-b failed"],
            )

            current = load_state(str(repo.run_state_path()))
            self.assertEqual(set(current.services), {"feature-a Backend", "feature-b Backend"})
            ports = json.loads(repo.ports_manifest_path().read_text(encoding="utf-8"))
            errors = json.loads(repo.error_report_path().read_text(encoding="utf-8"))
            self.assertEqual(
                {project["project"] for project in ports["projects"]},
                {"feature-a", "feature-b"},
            )
            self.assertEqual(set(errors["errors"]), {"feature-a failed", "feature-b failed"})

            self.assertTrue(repo.deactivate_run("run-a"))
            remaining = load_state(str(repo.run_state_path()))
            ports = json.loads(repo.ports_manifest_path().read_text(encoding="utf-8"))
            errors = json.loads(repo.error_report_path().read_text(encoding="utf-8"))
            self.assertEqual(set(remaining.services), {"feature-b Backend"})
            self.assertEqual(
                {project["project"] for project in ports["projects"]},
                {"feature-b"},
            )
            self.assertEqual(errors["errors"], ["feature-b failed"])


if __name__ == "__main__":
    unittest.main()
