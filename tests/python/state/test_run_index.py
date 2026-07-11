from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from envctl_engine.state.persistence import atomic_write_text
from envctl_engine.state.run_index import RunIndex, RunIndexCandidate, StateSelector


class RunIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.runtime_dir = Path(self.temporary_directory.name) / "runtime"
        self.runtime_root = self.runtime_dir / "repo-scope"
        self.index = RunIndex(
            runtime_root=self.runtime_root,
            runtime_dir=self.runtime_dir,
            runtime_scope_id="repo-scope",
        )
        self.revision_number = 0

    def _state_path(self, run_id: str) -> Path:
        self.revision_number += 1
        path = self.runtime_root / "runs" / run_id / "revisions" / f"revision-{self.revision_number}" / "run_state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
        return path

    def _record(self, run_id: str, *, mode: str = "trees", projects: list[str]) -> Path:
        path = self._state_path(run_id)
        self.index.record(
            state_path=path,
            run_id=run_id,
            mode=mode,
            project_names=projects,
        )
        return path.resolve()

    def test_new_records_replace_overlapping_project_owners_without_crossing_modes(self) -> None:
        _ = self._record("exact-old", projects=["Feature-A"])
        containing = self._record("containing", projects=["feature-a", "feature-b"])
        partial = self._record("partial-overlap", projects=["feature-c", "feature-d"])
        exact_new = self._record("exact-new", projects=["FEATURE-A"])
        _ = self._record("disjoint", projects=["feature-z"])
        wrong_mode = self._record("wrong-mode", mode="main", projects=["feature-a"])

        self.assertEqual(
            self.index.candidate_paths(StateSelector(mode="TREES", project_names=("feature-a",))),
            [exact_new],
        )
        self.assertEqual(
            self.index.candidate_paths(StateSelector(mode="trees", project_names=("feature-b",))),
            [containing],
        )
        self.assertEqual(
            self.index.candidate_paths(StateSelector(mode="main", project_names=("feature-a",))),
            [wrong_mode],
        )
        self.assertEqual(
            self.index.candidate_paths(StateSelector("trees", ("feature-a", "feature-c"))),
            [exact_new, partial],
        )

    def test_record_heals_multiple_historical_owners_for_the_same_project(self) -> None:
        run_a = self._state_path("run-a")
        run_b = self._state_path("run-b")
        self.index.replace_all(
            [
                RunIndexCandidate(run_a, "run-a", "main", ("main",), 1),
                RunIndexCandidate(run_b, "run-b", "main", ("main",), 2),
            ]
        )

        run_c = self._record("run-c", mode="main", projects=["Main"])

        self.assertEqual(
            self.index.candidate_paths(StateSelector("main", ("main",))),
            [run_c],
        )
        payload = json.loads(self.index.index_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["retired_run_ids"], ["run-a", "run-b"])

    def test_record_trims_mixed_historical_owner_without_losing_unrelated_project(self) -> None:
        run_a = self._state_path("run-a")
        run_b = self._state_path("run-b")
        self.index.replace_all(
            [
                RunIndexCandidate(run_a, "run-a", "trees", ("feature-x", "feature-y"), 1),
                RunIndexCandidate(run_b, "run-b", "trees", ("feature-x",), 2),
            ]
        )

        run_c = self._record("run-c", projects=["feature-x"])

        self.assertEqual(
            self.index.candidate_paths(StateSelector("trees", ("feature-x",))),
            [run_c],
        )
        self.assertEqual(
            self.index.candidate_paths(StateSelector("trees", ("feature-y",))),
            [run_a.resolve()],
        )
        payload = json.loads(self.index.index_path.read_text(encoding="utf-8"))
        entries = {entry["run_id"]: entry["project_names"] for entry in payload["entries"]}
        self.assertEqual(entries, {"run-a": ["feature-y"], "run-c": ["feature-x"]})
        self.assertEqual(payload["retired_run_ids"], ["run-b"])

    def test_preserves_independent_entries_during_concurrent_records(self) -> None:
        run_ids = [f"run-{index:02d}" for index in range(32)]
        state_paths = {run_id: self._state_path(run_id).resolve() for run_id in run_ids}

        def record(run_id: str) -> None:
            self.index.record(
                state_path=state_paths[run_id],
                run_id=run_id,
                mode="trees",
                project_names=[run_id],
            )

        with ThreadPoolExecutor(max_workers=12) as executor:
            list(executor.map(record, run_ids))

        candidates = self.index.candidate_paths(StateSelector(mode="trees", project_names=()))
        self.assertEqual(len(candidates), len(run_ids))
        self.assertEqual(set(candidates), set(state_paths.values()))
        payload = json.loads((self.runtime_root / "run_index.json").read_text(encoding="utf-8"))
        self.assertEqual(len(payload["entries"]), len(run_ids))

    def test_corrupt_index_fails_closed_and_later_record_replaces_it(self) -> None:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        index_path = self.runtime_root / "run_index.json"
        index_path.write_text('{"entries":', encoding="utf-8")

        self.assertEqual(self.index.candidate_paths(StateSelector(mode=None, project_names=())), [])

        recovered = self._record("recovered", projects=["feature-a"])
        self.assertEqual(
            self.index.candidate_paths(StateSelector(mode="trees", project_names=("feature-a",))),
            [recovered],
        )
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 4)
        self.assertGreaterEqual(payload["generation"], 1)

    def test_clean_registry_write_scavenges_only_its_crash_temp_targets(self) -> None:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        stale_primary = self.runtime_root / ".run_index.json.abcdefgh.tmp"
        stale_backup = self.runtime_root / ".run_index.backup.json.ijklmnop.tmp"
        unrelated = self.runtime_root / ".run_state.json.abcdefgh.tmp"
        for path in (stale_primary, stale_backup, unrelated):
            path.write_text("crash debris", encoding="utf-8")

        self.index.initialize_empty()

        self.assertFalse(stale_primary.exists())
        self.assertFalse(stale_backup.exists())
        self.assertTrue(unrelated.is_file())

    def test_rejects_record_paths_outside_runtime_dir(self) -> None:
        outside = Path(self.temporary_directory.name) / "runtime-sibling" / "run_state.json"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_text("{}\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "escapes runtime_root"):
            self.index.record(
                state_path=outside,
                run_id="outside",
                mode="trees",
                project_names=["feature-a"],
            )

    def test_rejects_state_path_from_another_runtime_scope(self) -> None:
        foreign = self.runtime_dir / "another-scope" / "runs" / "foreign" / "run_state.json"
        foreign.parent.mkdir(parents=True, exist_ok=True)
        foreign.write_text("{}\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "escapes runtime_root"):
            self.index.record(
                state_path=foreign,
                run_id="foreign",
                mode="trees",
                project_names=["feature-a"],
            )

    def test_rejects_symlinked_or_noncanonical_revision_paths(self) -> None:
        real_path = self._state_path("safe")
        alias_path = real_path.parent / "alias.json"
        alias_path.symlink_to(real_path)

        for path in (alias_path, real_path.parent / ".." / real_path.parent.name / real_path.name):
            with self.subTest(path=path):
                with self.assertRaisesRegex(ValueError, "canonical"):
                    self.index.record(
                        state_path=path,
                        run_id="safe",
                        mode="trees",
                        project_names=["feature-a"],
                    )

    def test_runtime_root_retarget_after_construction_is_rejected_without_external_writes(self) -> None:
        external = Path(self.temporary_directory.name) / "external"
        external.mkdir()
        sentinel = external / "sentinel.txt"
        sentinel.write_text("untouched", encoding="utf-8")
        self.runtime_root.parent.mkdir(parents=True, exist_ok=True)
        self.runtime_root.symlink_to(external, target_is_directory=True)

        with self.assertRaisesRegex(RuntimeError, "symlink"):
            self.index.candidates(StateSelector(mode=None, project_names=()))

        self.assertEqual(sentinel.read_text(encoding="utf-8"), "untouched")
        self.assertEqual(list(external.iterdir()), [sentinel])

    def test_traversal_entry_fails_closed_and_wrong_scope_is_not_loaded(self) -> None:
        safe = self._record("safe", projects=["feature-a"])
        index_path = self.runtime_root / "run_index.json"
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        payload["entries"].append(
            {
                "state_path": str(self.runtime_root / ".." / ".." / "escaped.json"),
                "run_id": "escaped",
                "mode": "trees",
                "project_names": ["feature-a"],
                "sequence": 2,
                "runtime_scope_id": "repo-scope",
            }
        )
        index_path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(self.index.candidate_paths(StateSelector("trees", ("feature-a",))), [safe])

        payload["entries"] = [entry for entry in payload["entries"] if entry["run_id"] == "safe"]
        payload["runtime_scope_id"] = "another-scope"
        index_path.write_text(json.dumps(payload), encoding="utf-8")
        (self.runtime_root / "run_index.backup.json").write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(self.index.candidate_paths(StateSelector("trees", ("feature-a",))), [])
        self.assertTrue(safe.is_file())

    def test_purge_removes_index_without_preventing_future_records(self) -> None:
        before = self._record("before-purge", projects=["feature-a"])
        self.index.purge()
        payload = json.loads((self.runtime_root / "run_index.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["entries"], [])
        self.assertEqual(payload["retired_run_ids"], ["before-purge"])
        self.assertEqual(self.index.candidate_paths(StateSelector(None, ())), [])

        with self.assertRaisesRegex(RuntimeError, "retired"):
            self.index.record(
                state_path=before,
                run_id="before-purge",
                mode="trees",
                project_names=["feature-a"],
            )

        after = self._record("after-purge", projects=["feature-b"])
        self.assertEqual(self.index.candidate_paths(StateSelector("trees", ("feature-b",))), [after])

    def test_empty_update_preserves_existing_project_ownership(self) -> None:
        state_path = self._record("run-a", projects=["feature-a"])

        self.index.record(
            state_path=state_path,
            run_id="run-a",
            mode="trees",
            project_names=[],
        )

        self.assertEqual(
            self.index.candidate_paths(StateSelector("trees", ("feature-a",))),
            [state_path],
        )

    def test_rejects_invalid_run_id_components_before_indexing(self) -> None:
        for run_id in (".", "..", "../other", "nested/run", "nested\\run", "/absolute"):
            with self.subTest(run_id=run_id):
                with self.assertRaisesRegex(ValueError, "path component"):
                    self.index.record(
                        state_path=self.runtime_root / "runs" / "safe" / "run_state.json",
                        run_id=run_id,
                        mode="trees",
                        project_names=["feature-a"],
                    )

    def test_remove_deactivates_only_requested_run(self) -> None:
        run_a = self._record("run-a", projects=["feature-a"])
        run_b = self._record("run-b", projects=["feature-b"])

        self.assertTrue(self.index.remove("run-a"))
        self.assertFalse(self.index.remove("run-a"))
        self.assertEqual(self.index.candidate_paths(StateSelector("trees", ("feature-a",))), [])
        self.assertEqual(self.index.candidate_paths(StateSelector("trees", ("feature-b",))), [run_b])
        self.assertTrue(run_a.is_file())

    def test_superseded_run_is_durably_fenced_from_reclaiming_ownership(self) -> None:
        run_a = self._record("run-a", projects=["feature-a"])
        run_b = self._state_path("run-b")
        self.index.record(
            state_path=run_b,
            run_id="run-b",
            mode="trees",
            project_names=["feature-a"],
            supersede_run_ids=["run-a"],
        )

        with self.assertRaisesRegex(RuntimeError, "retired"):
            self.index.record(
                state_path=run_a,
                run_id="run-a",
                mode="trees",
                project_names=["feature-a"],
            )

        self.assertEqual(
            self.index.candidate_paths(StateSelector("trees", ("feature-a",))),
            [run_b.resolve()],
        )

    def test_removing_untracked_source_id_still_fences_late_writer(self) -> None:
        self.index.initialize_empty()
        self.assertFalse(self.index.remove("late-source"))

        with self.assertRaisesRegex(RuntimeError, "retired"):
            self.index.record(
                state_path=self._state_path("late-source"),
                run_id="late-source",
                mode="trees",
                project_names=["feature-a"],
            )

    def test_single_copy_failure_keeps_newest_generation_readable_and_repairable(self) -> None:
        run_a = self._record("run-a", projects=["feature-a"])
        run_b = self._state_path("run-b")

        def write_backup_only(path: Path, text: str) -> None:
            if path == self.index.index_path:
                raise OSError("primary unavailable")
            atomic_write_text(path, text)

        with patch("envctl_engine.state.run_index.atomic_write_text", side_effect=write_backup_only):
            self.index.record(
                state_path=run_b,
                run_id="run-b",
                mode="trees",
                project_names=["feature-b"],
            )

        self.assertEqual(
            self.index.candidate_paths(StateSelector("trees", ())),
            [run_b.resolve(), run_a],
        )
        primary_before = json.loads(self.index.index_path.read_text(encoding="utf-8"))
        backup_before = json.loads(self.index.backup_path.read_text(encoding="utf-8"))
        self.assertGreater(backup_before["generation"], primary_before["generation"])

        self.index.repair_copies()

        primary_after = json.loads(self.index.index_path.read_text(encoding="utf-8"))
        backup_after = json.loads(self.index.backup_path.read_text(encoding="utf-8"))
        self.assertEqual(primary_after, backup_after)
        self.assertEqual(
            {entry["run_id"] for entry in primary_after["entries"]},
            {"run-a", "run-b"},
        )

    def test_equal_generation_divergence_fails_closed_without_overwriting_either_copy(self) -> None:
        self._record("run-a", projects=["feature-a"])
        indexed_entry = self.index.candidates(StateSelector("trees", ()))[0]
        primary_before = self.index.index_path.read_text(encoding="utf-8")
        backup_payload = json.loads(self.index.backup_path.read_text(encoding="utf-8"))
        backup_payload["entries"][0]["project_names"] = ["feature-b"]
        backup_before = json.dumps(backup_payload, indent=2, sort_keys=True) + "\n"
        self.index.backup_path.write_text(backup_before, encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "diverged at generation"):
            self.index.candidate_paths(StateSelector("trees", ()))
        with self.assertRaisesRegex(RuntimeError, "diverged at generation"):
            self.index.repair_copies()
        with self.assertRaisesRegex(RuntimeError, "diverged at generation"):
            self.index.initialize_empty()
        with self.assertRaisesRegex(RuntimeError, "diverged at generation"):
            self.index.replace_all([indexed_entry])

        self.assertEqual(self.index.index_path.read_text(encoding="utf-8"), primary_before)
        self.assertEqual(self.index.backup_path.read_text(encoding="utf-8"), backup_before)

    def test_total_registry_write_failure_preserves_last_committed_generation(self) -> None:
        run_a = self._record("run-a", projects=["feature-a"])
        run_b = self._state_path("run-b")

        with patch(
            "envctl_engine.state.run_index.atomic_write_text",
            side_effect=OSError("storage unavailable"),
        ):
            with self.assertRaisesRegex(OSError, "storage unavailable"):
                self.index.record(
                    state_path=run_b,
                    run_id="run-b",
                    mode="trees",
                    project_names=["feature-b"],
                )

        self.assertEqual(
            self.index.candidate_paths(StateSelector("trees", ())),
            [run_a],
        )

    def test_visible_registry_replace_is_commit_even_if_post_replace_fsync_reports_error(self) -> None:
        state_path = self._state_path("run-visible")

        def replace_then_report_error(path: Path, text: str) -> None:
            atomic_write_text(path, text)
            raise OSError("directory fsync result unknown")

        with patch(
            "envctl_engine.state.run_index.atomic_write_text",
            side_effect=replace_then_report_error,
        ):
            self.index.record(
                state_path=state_path,
                run_id="run-visible",
                mode="trees",
                project_names=["feature-a"],
            )

        self.assertEqual(
            self.index.candidate_paths(StateSelector("trees", ("feature-a",))),
            [state_path.resolve()],
        )
        self.assertTrue(state_path.is_file())


if __name__ == "__main__":
    unittest.main()
