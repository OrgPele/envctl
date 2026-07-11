from __future__ import annotations

import importlib
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import MappingProxyType
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
_models = importlib.import_module("envctl_engine.state.models")
_state = importlib.import_module("envctl_engine.state")
_state_repository = importlib.import_module("envctl_engine.state.repository")
_run_index = importlib.import_module("envctl_engine.state.run_index")
RunState = _models.RunState
ServiceRecord = _models.ServiceRecord
dump_state = _state.dump_state
load_state = _state.load_state
RuntimeStateRepository = _state_repository.RuntimeStateRepository
StateSelector = _run_index.StateSelector


class StateRepositoryContractTests(unittest.TestCase):
    def _context(self, root: Path) -> object:
        return SimpleNamespace(
            name="Main",
            root=root,
            ports={
                "backend": SimpleNamespace(requested=8000, assigned=8000, final=8000, source="requested", retries=0)
            },
        )

    def test_save_run_writes_scoped_and_legacy_in_read_write_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_root = Path(tmpdir) / "runtime" / "scope"
            legacy_root = Path(tmpdir) / "runtime" / "python-engine"
            runtime_root.mkdir(parents=True, exist_ok=True)
            legacy_root.mkdir(parents=True, exist_ok=True)
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=Path(tmpdir) / "runtime",
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.COMPAT_READ_WRITE,
            )

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd="/tmp",
                        pid=123,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                metadata={"repo_scope_id": "repo-123"},
            )

            repo.save_run(
                state=state,
                contexts=[self._context(Path(tmpdir))],
                errors=[],
                events=[{"event": "test"}],
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
                write_runtime_readiness_report=None,
            )

            self.assertTrue((runtime_root / "run_state.json").is_file())
            self.assertTrue((legacy_root / "run_state.json").is_file())
            loaded = repo.load_latest()
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.run_id, "run-1")

    def test_scoped_only_mode_does_not_write_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_root = Path(tmpdir) / "runtime" / "scope"
            legacy_root = Path(tmpdir) / "runtime" / "python-engine"
            runtime_root.mkdir(parents=True, exist_ok=True)
            legacy_root.mkdir(parents=True, exist_ok=True)
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=Path(tmpdir) / "runtime",
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )
            state = RunState(run_id="run-1", mode="main")

            repo.save_run(
                state=state,
                contexts=[self._context(Path(tmpdir))],
                errors=[],
                events=[],
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )

            self.assertTrue((runtime_root / "run_state.json").is_file())
            self.assertFalse((legacy_root / "run_state.json").exists())

    def test_save_run_ports_manifest_accepts_mapping_context_ports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_root = Path(tmpdir) / "runtime" / "scope"
            legacy_root = Path(tmpdir) / "runtime" / "python-engine"
            runtime_root.mkdir(parents=True, exist_ok=True)
            legacy_root.mkdir(parents=True, exist_ok=True)
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=Path(tmpdir) / "runtime",
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )
            context = SimpleNamespace(
                name="Main",
                root=Path(tmpdir),
                ports=MappingProxyType(
                    {
                        "backend": SimpleNamespace(
                            requested=8000,
                            assigned=8001,
                            final=8001,
                            source="retry",
                            retries=1,
                        )
                    }
                ),
            )

            repo.save_run(
                state=RunState(run_id="run-ports", mode="main"),
                contexts=[context],
                errors=[],
                events=[],
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )

            payload = json.loads((runtime_root / "ports_manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["projects"][0]["ports"]["backend"]["final"], 8001)
        self.assertEqual(payload["projects"][0]["ports"]["backend"]["retries"], 1)

    def test_load_latest_honors_requested_mode_over_latest_run_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            legacy_root = runtime_dir / "python-engine"
            runtime_root.mkdir(parents=True, exist_ok=True)
            legacy_root.mkdir(parents=True, exist_ok=True)

            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.COMPAT_READ_WRITE,
            )

            trees_state = RunState(run_id="run-trees", mode="trees")
            dump_state(trees_state, str(runtime_root / "run_state.json"))

            main_state_path = runtime_root / "runs" / "run-main" / "run_state.json"
            main_state_path.parent.mkdir(parents=True, exist_ok=True)
            dump_state(RunState(run_id="run-main", mode="main"), str(main_state_path))
            (runtime_root / ".last_state.main").write_text(str(main_state_path) + "\n", encoding="utf-8")

            loaded_main = repo.load_latest(mode="main")
            self.assertIsNotNone(loaded_main)
            assert loaded_main is not None
            self.assertEqual(loaded_main.mode, "main")
            self.assertEqual(loaded_main.run_id, "run-main")

            loaded_trees = repo.load_latest(mode="trees")
            self.assertIsNotNone(loaded_trees)
            assert loaded_trees is not None
            self.assertEqual(loaded_trees.mode, "trees")
            self.assertEqual(loaded_trees.run_id, "run-trees")

    def test_save_resume_state_updates_scoped_and_legacy_runtime_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_root = Path(tmpdir) / "runtime" / "scope"
            legacy_root = Path(tmpdir) / "runtime" / "python-engine"
            runtime_root.mkdir(parents=True, exist_ok=True)
            legacy_root.mkdir(parents=True, exist_ok=True)
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=Path(tmpdir) / "runtime",
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.COMPAT_READ_WRITE,
            )
            state = RunState(run_id="run-1", mode="main", metadata={"repo_scope_id": "repo-123"})

            runtime_map = repo.save_resume_state(
                state=state,
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {"Main": {"backend_url": "http://localhost:8000"}}},
            )

            self.assertIn("projection", runtime_map)
            self.assertTrue((runtime_root / "run_state.json").is_file())
            self.assertTrue((runtime_root / "runtime_map.json").is_file())
            self.assertTrue((legacy_root / "run_state.json").is_file())
            self.assertTrue((legacy_root / "runtime_map.json").is_file())
            main_pointer = runtime_root / ".last_state.main"
            self.assertTrue(main_pointer.is_file())
            pointer_target = Path(main_pointer.read_text(encoding="utf-8").strip())
            self.assertEqual(pointer_target.name, "run_state.json")
            self.assertEqual(pointer_target.parent.parent.name, "revisions")
            self.assertEqual(pointer_target.parent.parent.parent.name, "run-1")

    def test_save_selected_stop_state_updates_scoped_and_legacy_runtime_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_root = Path(tmpdir) / "runtime" / "scope"
            legacy_root = Path(tmpdir) / "runtime" / "python-engine"
            runtime_root.mkdir(parents=True, exist_ok=True)
            legacy_root.mkdir(parents=True, exist_ok=True)
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=Path(tmpdir) / "runtime",
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.COMPAT_READ_WRITE,
            )
            state = RunState(
                run_id="run-2",
                mode="trees",
                services={
                    "feature-a Backend": ServiceRecord(
                        name="feature-a Backend",
                        type="backend",
                        cwd="/tmp/feature-a/backend",
                        project="feature-a",
                    )
                },
                metadata={"repo_scope_id": "repo-123"},
            )

            repo.save_selected_stop_state(
                state=state,
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )

            self.assertTrue((runtime_root / "run_state.json").is_file())
            self.assertTrue((runtime_root / "runtime_map.json").is_file())
            self.assertTrue((legacy_root / "run_state.json").is_file())
            self.assertTrue((legacy_root / "runtime_map.json").is_file())

    def test_save_resume_main_pointer_survives_following_trees_runtime_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            legacy_root = runtime_dir / "python-engine"
            runtime_root.mkdir(parents=True, exist_ok=True)
            legacy_root.mkdir(parents=True, exist_ok=True)
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )

            main_state = RunState(
                run_id="run-main-resume",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd="/tmp",
                        pid=123,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd="/tmp",
                        pid=124,
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
                metadata={"repo_scope_id": "repo-123"},
            )
            repo.save_resume_state(
                state=main_state,
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )
            main_pointer = runtime_root / ".last_state.main"
            main_pointer_target = main_pointer.read_text(encoding="utf-8").strip()
            main_target = Path(main_pointer_target)
            self.assertEqual(main_target.name, "run_state.json")
            self.assertEqual(main_target.parent.parent.name, "revisions")
            self.assertEqual(main_target.parent.parent.parent.name, "run-main-resume")

            tree_state = RunState(
                run_id="run-tree-update",
                mode="trees",
                services={
                    "feature-a Backend": ServiceRecord(
                        name="feature-a Backend",
                        type="backend",
                        cwd="/tmp",
                        pid=321,
                        requested_port=8100,
                        actual_port=8100,
                        status="running",
                    ),
                    "feature-a Frontend": ServiceRecord(
                        name="feature-a Frontend",
                        type="frontend",
                        cwd="/tmp",
                        pid=322,
                        requested_port=9100,
                        actual_port=9100,
                        status="running",
                    ),
                },
                metadata={"repo_scope_id": "repo-123"},
            )
            repo.save_resume_state(
                state=tree_state,
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )

            self.assertEqual(main_pointer.read_text(encoding="utf-8").strip(), main_pointer_target)
            loaded_main = repo.load_latest(mode="main", strict_mode_match=True)
            self.assertIsNotNone(loaded_main)
            assert loaded_main is not None
            self.assertEqual(loaded_main.run_id, "run-main-resume")
            self.assertEqual(loaded_main.mode, "main")

    def test_save_run_main_preserves_existing_tree_pointers_for_mode_switch_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            legacy_root = runtime_dir / "python-engine"
            runtime_root.mkdir(parents=True, exist_ok=True)
            legacy_root.mkdir(parents=True, exist_ok=True)
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )

            tree_state_path = runtime_root / "runs" / "run-tree" / "run_state.json"
            tree_state_path.parent.mkdir(parents=True, exist_ok=True)
            dump_state(
                RunState(run_id="run-tree", mode="trees", metadata={"repo_scope_id": "repo-123"}),
                str(tree_state_path),
            )
            tree_pointer = runtime_root / ".last_state.trees.feature-a"
            tree_pointer.write_text(str(tree_state_path) + "\n", encoding="utf-8")

            state = RunState(run_id="run-main", mode="main", metadata={"repo_scope_id": "repo-123"})
            repo.save_run(
                state=state,
                contexts=[self._context(Path(tmpdir))],
                errors=[],
                events=[],
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )

            self.assertTrue(tree_pointer.is_file())
            migrated_target = Path(tree_pointer.read_text(encoding="utf-8").strip())
            self.assertEqual(load_state(str(migrated_target)).run_id, "run-tree")
            self.assertIn("revisions", migrated_target.parts)

    def test_load_latest_ignores_invalid_scoped_pointer_and_uses_next_valid_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            legacy_root = runtime_dir / "python-engine"
            runtime_root.mkdir(parents=True, exist_ok=True)
            legacy_root.mkdir(parents=True, exist_ok=True)
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.COMPAT_READ_WRITE,
            )

            bad_pointer = runtime_root / ".last_state.main"
            bad_pointer.write_text(str(runtime_dir / "missing" / "run_state.json") + "\n", encoding="utf-8")

            valid_state_path = runtime_root / "runs" / "run-valid" / "run_state.json"
            valid_state_path.parent.mkdir(parents=True, exist_ok=True)
            dump_state(RunState(run_id="run-valid", mode="main"), str(valid_state_path))
            generic_pointer = runtime_root / ".last_state"
            generic_pointer.write_text(str(valid_state_path) + "\n", encoding="utf-8")

            loaded = repo.load_latest(mode="main", strict_mode_match=True)

            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.run_id, "run-valid")

    def test_compat_read_only_mode_reads_legacy_state_without_writing_legacy_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            legacy_root = runtime_dir / "python-engine"
            runtime_root.mkdir(parents=True, exist_ok=True)
            legacy_root.mkdir(parents=True, exist_ok=True)
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.COMPAT_READ_ONLY,
            )

            legacy_state_path = legacy_root / "run_state.json"
            dump_state(RunState(run_id="legacy-run", mode="main"), str(legacy_state_path))

            loaded = repo.load_latest(mode="main", strict_mode_match=True)

            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.run_id, "legacy-run")

            repo.save_resume_state(
                state=RunState(run_id="scoped-run", mode="main", metadata={"repo_scope_id": "repo-123"}),
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )

            self.assertTrue((runtime_root / "run_state.json").is_file())
            self.assertEqual(load_state(str(legacy_state_path), allowed_root=str(runtime_dir)).run_id, "legacy-run")

            loaded_trees = repo.load_latest(mode="trees", strict_mode_match=True)
            self.assertIsNone(loaded_trees)

    def test_save_run_trees_preserves_existing_main_pointer_for_mode_switch_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            legacy_root = runtime_dir / "python-engine"
            runtime_root.mkdir(parents=True, exist_ok=True)
            legacy_root.mkdir(parents=True, exist_ok=True)
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )

            main_state_path = runtime_root / "runs" / "run-main" / "run_state.json"
            main_state_path.parent.mkdir(parents=True, exist_ok=True)
            dump_state(
                RunState(run_id="run-main", mode="main", metadata={"repo_scope_id": "repo-123"}),
                str(main_state_path),
            )
            main_pointer = runtime_root / ".last_state.main"
            main_pointer.write_text(str(main_state_path) + "\n", encoding="utf-8")

            tree_context = SimpleNamespace(name="feature-a", root=Path(tmpdir) / "trees" / "feature-a", ports={})
            state = RunState(run_id="run-tree", mode="trees", metadata={"repo_scope_id": "repo-123"})
            repo.save_run(
                state=state,
                contexts=[tree_context],
                errors=[],
                events=[],
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )

            self.assertTrue(main_pointer.is_file())
            migrated_target = Path(main_pointer.read_text(encoding="utf-8").strip())
            self.assertEqual(load_state(str(migrated_target)).run_id, "run-main")
            self.assertIn("revisions", migrated_target.parts)

            loaded_main = repo.load_latest(mode="main", strict_mode_match=True)
            self.assertIsNotNone(loaded_main)
            assert loaded_main is not None
            self.assertEqual(loaded_main.run_id, "run-main")
            self.assertEqual(loaded_main.mode, "main")

    def test_save_run_trees_uses_safe_pointer_filename_for_project_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            legacy_root = runtime_dir / "python-engine"
            runtime_root.mkdir(parents=True, exist_ok=True)
            legacy_root.mkdir(parents=True, exist_ok=True)
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )

            tree_context = SimpleNamespace(
                name="Feature/API v2", root=Path(tmpdir) / "trees" / "Feature_API_v2", ports={}
            )
            state = RunState(run_id="run-tree-safe-name", mode="trees", metadata={"repo_scope_id": "repo-123"})
            repo.save_run(
                state=state,
                contexts=[tree_context],
                errors=[],
                events=[],
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )

            pointer_name = repo._tree_pointer_name("Feature/API v2")
            self.assertIsNotNone(pointer_name)
            safe_pointer = runtime_root / str(pointer_name)
            unsafe_pointer_parent = runtime_root / ".last_state.trees.Feature"
            self.assertTrue(safe_pointer.is_file())
            self.assertIn("Feature_API_v2-", safe_pointer.name)
            self.assertFalse(unsafe_pointer_parent.exists())
            loaded = repo.load_latest(mode="trees", strict_mode_match=True)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.run_id, "run-tree-safe-name")

    def test_independent_tree_runs_remain_selection_addressable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )

            for project_name in ("feature-zeta", "feature-alpha"):
                state = RunState(
                    run_id=f"run-{project_name}",
                    mode="trees",
                    services={
                        f"{project_name} Backend": ServiceRecord(
                            name=f"{project_name} Backend",
                            type="backend",
                            cwd=f"/tmp/{project_name}",
                            pid=123,
                            requested_port=8000,
                            actual_port=8000,
                            status="running",
                        )
                    },
                    metadata={"repo_scope_id": "repo-123"},
                )
                repo.save_resume_state(
                    state=state,
                    emit=lambda *_args, **_kwargs: None,
                    runtime_map_builder=lambda _state: {"projection": {}},
                )

            self.assertTrue((runtime_root / ".last_state.trees.feature-zeta").is_file())
            self.assertTrue((runtime_root / ".last_state.trees.feature-alpha").is_file())
            zeta = repo.load_latest(
                mode="trees",
                strict_mode_match=True,
                project_names=["feature-zeta"],
            )
            alpha = repo.load_latest(
                mode="trees",
                strict_mode_match=True,
                project_names=["feature-alpha"],
            )

        self.assertIsNotNone(zeta)
        self.assertIsNotNone(alpha)
        assert zeta is not None and alpha is not None
        self.assertEqual(zeta.run_id, "run-feature-zeta")
        self.assertEqual(alpha.run_id, "run-feature-alpha")

    def test_selection_aware_lookup_uses_new_owner_when_superset_supersedes_exact_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )

            exact_context = SimpleNamespace(name="feature-a", root=Path(tmpdir) / "feature-a", ports={})
            repo.save_run(
                state=RunState(run_id="run-exact", mode="trees", metadata={"repo_scope_id": "repo-123"}),
                contexts=[exact_context],
                errors=[],
                events=[],
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )
            superset_contexts = [
                exact_context,
                SimpleNamespace(name="feature-b", root=Path(tmpdir) / "feature-b", ports={}),
            ]
            repo.save_run(
                state=RunState(run_id="run-superset", mode="trees", metadata={"repo_scope_id": "repo-123"}),
                contexts=superset_contexts,
                errors=[],
                events=[],
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )

            loaded = repo.load_latest(
                mode="trees",
                strict_mode_match=True,
                project_names=["feature-a"],
            )

        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.run_id, "run-superset")

    def test_save_run_atomically_supersedes_every_source_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            repo = RuntimeStateRepository(
                runtime_root=runtime_dir / "scope",
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )
            contexts = [
                SimpleNamespace(name="feature-a", root=Path(tmpdir) / "feature-a", ports={}),
                SimpleNamespace(name="feature-b", root=Path(tmpdir) / "feature-b", ports={}),
            ]
            old_state = RunState(
                run_id="run-old",
                mode="trees",
                services={
                    "feature-a Backend": ServiceRecord(
                        name="feature-a Backend",
                        type="backend",
                        cwd="/tmp/feature-a",
                        project="feature-a",
                    ),
                    "feature-b Backend": ServiceRecord(
                        name="feature-b Backend",
                        type="backend",
                        cwd="/tmp/feature-b",
                        project="feature-b",
                    ),
                },
                metadata={"repo_scope_id": "repo-123"},
            )
            repo.save_run(
                state=old_state,
                contexts=contexts,
                errors=[],
                events=[],
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )
            replacement = RunState(
                run_id="run-new",
                mode="trees",
                services=dict(old_state.services),
                metadata={
                    "repo_scope_id": "repo-123",
                    "state_source_run_ids": ["run-old"],
                },
            )

            repo.save_run(
                state=replacement,
                contexts=[contexts[0]],
                errors=[],
                events=[],
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )

            self.assertEqual([state.run_id for state in repo.load_all(mode="trees")], ["run-new"])
            loaded_b = repo.load_latest(
                mode="trees",
                strict_mode_match=True,
                project_names=["feature-b"],
            )
            self.assertIsNotNone(loaded_b)
            assert loaded_b is not None
            self.assertEqual(loaded_b.run_id, "run-new")
            self.assertEqual(set(loaded_b.services), {"feature-a Backend", "feature-b Backend"})
            with self.assertRaisesRegex(RuntimeError, "retired"):
                repo.save_run(
                    state=old_state,
                    contexts=contexts,
                    errors=[],
                    events=[],
                    emit=lambda *_args, **_kwargs: None,
                    runtime_map_builder=lambda _state: {"projection": {}},
                )

    def test_merged_state_uses_most_recently_activated_run_for_global_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            repo = RuntimeStateRepository(
                runtime_root=runtime_dir / "scope",
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )

            def save(project: str, run_id: str, marker: str) -> None:
                repo.save_resume_state(
                    state=RunState(
                        run_id=run_id,
                        mode="trees",
                        services={
                            f"{project} Backend": ServiceRecord(
                                name=f"{project} Backend",
                                type="backend",
                                cwd=f"/tmp/{project}",
                                project=project,
                            )
                        },
                        metadata={"repo_scope_id": "repo-123", "activation_marker": marker},
                    ),
                    emit=lambda *_args, **_kwargs: None,
                    runtime_map_builder=lambda _state: {"projection": {}},
                )

            save("feature-a", "run-a", "a-original")
            save("feature-b", "run-b", "b-newer-sequence")
            save("feature-a", "run-a", "a-reactivated")
            loaded = repo.load_latest(mode="trees", strict_mode_match=True)

        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.run_id, "run-a")
        self.assertEqual(loaded.metadata["activation_marker"], "a-reactivated")
        self.assertEqual(set(loaded.services), {"feature-a Backend", "feature-b Backend"})

    def test_selection_aware_lookup_does_not_return_disjoint_latest_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )
            context = SimpleNamespace(name="feature-a", root=Path(tmpdir) / "feature-a", ports={})
            repo.save_run(
                state=RunState(run_id="run-a", mode="trees", metadata={"repo_scope_id": "repo-123"}),
                contexts=[context],
                errors=[],
                events=[],
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )

            loaded = repo.load_latest(
                mode="trees",
                strict_mode_match=True,
                project_names=["feature-b"],
            )

        self.assertIsNone(loaded)

    def test_multi_project_lookup_consolidates_disjoint_active_runs_without_losing_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )

            for project_name in ("feature-a", "feature-b"):
                repo.save_resume_state(
                    state=RunState(
                        run_id=f"run-{project_name}",
                        mode="trees",
                        services={
                            f"{project_name} Backend": ServiceRecord(
                                name=f"{project_name} Backend",
                                type="backend",
                                cwd=f"/tmp/{project_name}/backend",
                                project=project_name,
                                pid=100 if project_name == "feature-a" else 200,
                            )
                        },
                    ),
                    emit=lambda *_args, **_kwargs: None,
                    runtime_map_builder=lambda _state: {"projection": {}},
                )

            merged = repo.load_latest(
                mode="trees",
                strict_mode_match=True,
                project_names=["feature-a", "feature-b"],
            )
            self.assertIsNotNone(merged)
            assert merged is not None
            self.assertEqual(set(merged.services), {"feature-a Backend", "feature-b Backend"})
            self.assertEqual(set(merged.metadata["project_names"]), {"feature-a", "feature-b"})

            repo.save_resume_state(
                state=merged,
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )

            active = repo.load_all(mode="trees")
            self.assertEqual([state.run_id for state in active], ["run-feature-b"])
            self.assertTrue((runtime_root / "runs" / "run-feature-a" / "run_state.json").is_file())

    def test_load_all_filters_projects_subtracted_from_a_mixed_historical_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )
            mixed_services = {
                f"{project} Backend": ServiceRecord(
                    name=f"{project} Backend",
                    type="backend",
                    cwd=f"/tmp/{project}/backend",
                    project=project,
                )
                for project in ("feature-a", "feature-b")
            }
            repo.save_resume_state(
                state=RunState(run_id="run-mixed", mode="trees", services=mixed_services),
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda state: {"run_id": state.run_id},
            )
            repo.save_resume_state(
                state=RunState(
                    run_id="run-new-a",
                    mode="trees",
                    services={"feature-a Backend": mixed_services["feature-a Backend"]},
                ),
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda state: {"run_id": state.run_id},
            )

            active = {state.run_id: set(state.services) for state in repo.load_all(mode="trees")}

            self.assertEqual(
                active,
                {
                    "run-mixed": {"feature-b Backend"},
                    "run-new-a": {"feature-a Backend"},
                },
            )

    def test_aggregate_and_subset_saves_keep_project_metadata_owned_by_live_projects(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )

            for project_name, service_type in (("feature-a", "backend"), ("feature-b", "frontend")):
                repo.save_resume_state(
                    state=RunState(
                        run_id=f"run-{project_name}",
                        mode="trees",
                        services={
                            f"{project_name} {service_type}": ServiceRecord(
                                name=f"{project_name} {service_type}",
                                type=service_type,
                                cwd=f"/tmp/{project_name}/{service_type}",
                                project=project_name,
                            )
                        },
                        metadata={
                            "project_roots": {
                                project_name: f"/tmp/{project_name}",
                                "stale-project": "/tmp/stale",
                            },
                            "project_pr_links": {
                                project_name: f"pr-{project_name}",
                                "stale-project": "pr-stale",
                            },
                            "project_test_summaries": {
                                project_name: {"failed": 0},
                                "stale-project": {"failed": 99},
                            },
                            "project_test_results_root": f"/tmp/results/{project_name}",
                            "project_test_results_updated_at": project_name,
                            "project_action_reports": {
                                project_name: {"test": {"status": "success"}},
                                "stale-project": {"test": {"status": "failed"}},
                            },
                            "dashboard_project_configured_services": {
                                project_name: [service_type],
                                "stale-project": ["worker"],
                            },
                            "dashboard_configured_service_types": [service_type, "worker"],
                            "dashboard_stopped_services": [
                                {
                                    "name": f"{project_name} stopped",
                                    "project": project_name,
                                    "type": service_type,
                                },
                                {
                                    "name": "stale stopped",
                                    "project": "stale-project",
                                    "type": "worker",
                                },
                            ],
                            "startup_identity": {
                                "mode": "trees",
                                "projects": [
                                    {"name": project_name, "root": f"/tmp/{project_name}"},
                                    {"name": "stale-project", "root": "/tmp/stale"},
                                ],
                                "fingerprint": project_name,
                            },
                        },
                    ),
                    emit=lambda *_args, **_kwargs: None,
                    runtime_map_builder=lambda _state: {"projection": {}},
                )

            merged = repo.load_latest(mode="trees", strict_mode_match=True)
            self.assertIsNotNone(merged)
            assert merged is not None
            for key in (
                "project_roots",
                "project_pr_links",
                "project_test_summaries",
                "project_action_reports",
                "dashboard_project_configured_services",
            ):
                self.assertEqual(set(merged.metadata[key]), {"feature-a", "feature-b"})
            self.assertEqual(
                {item["project"] for item in merged.metadata["dashboard_stopped_services"]},
                {"feature-a", "feature-b"},
            )
            self.assertEqual(
                merged.metadata["dashboard_configured_service_types"],
                ["backend", "frontend"],
            )
            self.assertEqual(
                {project["name"] for project in merged.metadata["startup_identity"]["projects"]},
                {"feature-a", "feature-b"},
            )
            self.assertNotIn("project_test_results_root", merged.metadata)
            self.assertNotIn("project_test_results_updated_at", merged.metadata)

            selected = repo.load_latest(
                mode="trees",
                strict_mode_match=True,
                project_names=["feature-a"],
            )
            self.assertIsNotNone(selected)
            assert selected is not None
            for key in (
                "project_roots",
                "project_pr_links",
                "project_test_summaries",
                "project_action_reports",
                "dashboard_project_configured_services",
            ):
                self.assertEqual(set(selected.metadata[key]), {"feature-a"})
            self.assertEqual(
                {item["project"] for item in selected.metadata["dashboard_stopped_services"]},
                {"feature-a"},
            )
            self.assertEqual(selected.metadata["dashboard_configured_service_types"], ["backend"])

            merged.services = {
                name: service for name, service in merged.services.items() if service.project == "feature-a"
            }
            repo.save_resume_state(
                state=merged,
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )

            saved_subset = repo.load_latest(
                mode="trees",
                strict_mode_match=True,
                project_names=["feature-a"],
            )
            self.assertIsNotNone(saved_subset)
            assert saved_subset is not None
            for key in (
                "project_roots",
                "project_pr_links",
                "project_test_summaries",
                "project_action_reports",
                "dashboard_project_configured_services",
            ):
                self.assertEqual(set(saved_subset.metadata[key]), {"feature-a"})
            self.assertEqual(
                {item["project"] for item in saved_subset.metadata["dashboard_stopped_services"]},
                {"feature-a"},
            )
            self.assertIsNone(
                repo.load_latest(
                    mode="trees",
                    strict_mode_match=True,
                    project_names=["feature-b"],
                )
            )

    def test_deactivate_run_preserves_other_active_run_and_historical_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )

            for project_name in ("feature-a", "feature-b"):
                repo.save_resume_state(
                    state=RunState(
                        run_id=f"run-{project_name}",
                        mode="trees",
                        services={
                            f"{project_name} Backend": ServiceRecord(
                                name=f"{project_name} Backend",
                                type="backend",
                                cwd=f"/tmp/{project_name}/backend",
                                project=project_name,
                            )
                        },
                    ),
                    emit=lambda *_args, **_kwargs: None,
                    runtime_map_builder=lambda state: {"run_id": state.run_id},
                )

            self.assertTrue(repo.deactivate_run("run-feature-b"))
            self.assertFalse(repo.deactivate_run("run-feature-b"))
            self.assertIsNone(repo.load_latest(mode="trees", strict_mode_match=True, project_names=["feature-b"]))
            remaining = repo.load_latest(
                mode="trees",
                strict_mode_match=True,
                project_names=["feature-a"],
            )
            self.assertIsNotNone(remaining)
            assert remaining is not None
            self.assertEqual(remaining.run_id, "run-feature-a")
            self.assertEqual(load_state(str(runtime_root / "run_state.json")).run_id, "run-feature-a")
            self.assertTrue((runtime_root / "runs" / "run-feature-b" / "run_state.json").is_file())

            self.assertTrue(repo.deactivate_run("run-feature-a"))
            self.assertEqual(repo.load_all(mode="trees"), [])
            self.assertFalse((runtime_root / "run_state.json").exists())
            self.assertTrue((runtime_root / "runs" / "run-feature-a" / "run_state.json").is_file())

    def test_concurrent_saves_publish_coherent_current_snapshot_and_keep_both_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )
            first_builder_entered = Event()
            release_first_builder = Event()
            second_builder_entered = Event()

            def save(project_name: str) -> None:
                state = RunState(
                    run_id=f"run-{project_name}",
                    mode="trees",
                    services={
                        f"{project_name} Backend": ServiceRecord(
                            name=f"{project_name} Backend",
                            type="backend",
                            cwd=f"/tmp/{project_name}/backend",
                            project=project_name,
                        )
                    },
                )

                def runtime_map_builder(_state: RunState) -> dict[str, object]:
                    if project_name == "feature-a":
                        first_builder_entered.set()
                        self.assertTrue(release_first_builder.wait(timeout=2))
                    else:
                        second_builder_entered.set()
                    return {"run_id": state.run_id}

                repo.save_resume_state(
                    state=state,
                    emit=lambda *_args, **_kwargs: None,
                    runtime_map_builder=runtime_map_builder,
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(save, "feature-a")
                self.assertTrue(first_builder_entered.wait(timeout=2))
                second = executor.submit(save, "feature-b")
                self.assertTrue(second_builder_entered.wait(timeout=0.1))
                release_first_builder.set()
                first.result(timeout=2)
                second.result(timeout=2)

            current_state = load_state(str(runtime_root / "run_state.json"))
            current_map = json.loads((runtime_root / "runtime_map.json").read_text(encoding="utf-8"))
            self.assertEqual(current_state.run_id, current_map["run_id"])
            self.assertEqual(
                {state.run_id for state in repo.load_all(mode="trees")}, {"run-feature-a", "run-feature-b"}
            )
            self.assertEqual(list(runtime_root.rglob("*.tmp")), [])

    def test_purge_deactivates_index_without_deleting_history_unless_aggressive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )
            repo.save_resume_state(
                state=RunState(run_id="run-a", mode="main"),
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )
            historical_state = runtime_root / "runs" / "run-a" / "run_state.json"

            repo.purge(aggressive=False)

            self.assertIsNone(repo.load_latest())
            index_payload = json.loads((runtime_root / "run_index.json").read_text(encoding="utf-8"))
            self.assertEqual(index_payload["entries"], [])
            self.assertTrue(historical_state.is_file())

            repo.purge(aggressive=True)
            self.assertFalse(historical_state.exists())

    def test_invalid_run_ids_and_artifact_components_cannot_escape_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            for run_id in (".", "..", "../escaped", "nested/run", "nested\\run", "/absolute"):
                with self.subTest(run_id=run_id):
                    runtime_root = runtime_dir / f"scope-{abs(hash(run_id))}"
                    repo = RuntimeStateRepository(
                        runtime_root=runtime_root,
                        runtime_legacy_root=runtime_dir / "python-engine",
                        runtime_dir=runtime_dir,
                        runtime_scope_id=f"scope-{abs(hash(run_id))}",
                        compat_mode=RuntimeStateRepository.SCOPED_ONLY,
                    )
                    with self.assertRaisesRegex(ValueError, "path component"):
                        repo.save_resume_state(
                            state=RunState(run_id=run_id, mode="trees"),
                            emit=lambda *_args, **_kwargs: None,
                            runtime_map_builder=lambda _state: {},
                        )
                    self.assertFalse(runtime_root.exists())

            repo = RuntimeStateRepository(
                runtime_root=runtime_dir / "safe-scope",
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="safe-scope",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )
            for invalid_component in ("..", "../escaped", "/absolute", "nested/name"):
                with self.subTest(component=invalid_component):
                    with self.assertRaisesRegex(ValueError, "path component"):
                        repo.test_results_dir_path("run-a", invalid_component)
                    with self.assertRaisesRegex(ValueError, "path component"):
                        repo.tree_diffs_dir_path("run-a", invalid_component)

    def test_missing_or_corrupt_index_is_rebuilt_from_scoped_run_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )
            for project_name in ("feature-a", "feature-b"):
                state_path = runtime_root / "runs" / f"run-{project_name}" / "run_state.json"
                state_path.parent.mkdir(parents=True, exist_ok=True)
                dump_state(
                    RunState(
                        run_id=f"run-{project_name}",
                        mode="trees",
                        services={
                            f"{project_name} Backend": ServiceRecord(
                                name=f"{project_name} Backend",
                                type="backend",
                                cwd=f"/tmp/{project_name}/backend",
                                project=project_name,
                            )
                        },
                    ),
                    str(state_path),
                )

            recovered_a = repo.load_latest(
                mode="trees",
                strict_mode_match=True,
                project_names=["feature-a"],
            )
            self.assertIsNotNone(recovered_a)
            assert recovered_a is not None
            self.assertEqual(recovered_a.run_id, "run-feature-a")
            self.assertEqual({state.run_id for state in repo.load_all()}, {"run-feature-a", "run-feature-b"})

            (runtime_root / "run_index.json").write_text('{"entries":', encoding="utf-8")
            recovered_b = repo.load_latest(
                mode="trees",
                strict_mode_match=True,
                project_names=["feature-b"],
            )
            self.assertIsNotNone(recovered_b)
            assert recovered_b is not None
            self.assertEqual(recovered_b.run_id, "run-feature-b")
            rebuilt_payload = json.loads((runtime_root / "run_index.json").read_text(encoding="utf-8"))
            self.assertEqual(len(rebuilt_payload["entries"]), 2)

    def test_resume_orchestrator_does_not_write_legacy_state_files_directly(self) -> None:
        resume_path = REPO_ROOT / "python/envctl_engine/startup/resume_orchestrator.py"
        raw = resume_path.read_text(encoding="utf-8")
        self.assertNotIn('runtime_legacy_root / "run_state.json"', raw)
        self.assertNotIn('runtime_legacy_root / "runtime_map.json"', raw)

    def test_lifecycle_cleanup_orchestrator_does_not_write_legacy_state_files_directly(self) -> None:
        cleanup_path = REPO_ROOT / "python/envctl_engine/runtime/lifecycle_cleanup_orchestrator.py"
        raw = cleanup_path.read_text(encoding="utf-8")
        self.assertNotIn('runtime_legacy_root / "run_state.json"', raw)
        self.assertNotIn('runtime_legacy_root / "runtime_map.json"', raw)

    def test_engine_runtime_legacy_compat_helper_is_removed(self) -> None:
        runtime_path = REPO_ROOT / "python/envctl_engine/runtime/engine_runtime.py"
        raw = runtime_path.read_text(encoding="utf-8")
        self.assertNotIn("def _write_legacy_runtime_compat_files(", raw)

    def test_aggressive_purge_removes_runtime_scoped_test_results_with_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            legacy_root = runtime_dir / "python-engine"
            runtime_root.mkdir(parents=True, exist_ok=True)
            legacy_root.mkdir(parents=True, exist_ok=True)
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )

            run_state = RunState(run_id="run-1", mode="main", metadata={"repo_scope_id": "repo-123"})
            repo.save_resume_state(
                state=run_state,
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )

            test_summary = (
                repo.test_results_dir_path("run-1", "run_20260309_100000") / "Main" / "failed_tests_summary.txt"
            )
            test_summary.parent.mkdir(parents=True, exist_ok=True)
            test_summary.write_text("No failed tests.\n", encoding="utf-8")

            repo.purge(aggressive=False)
            self.assertTrue(test_summary.is_file())

            repo.purge(aggressive=True)
            self.assertFalse(repo.run_dir_path("run-1").exists())
            self.assertFalse(test_summary.exists())

    def test_tree_diffs_dir_path_scopes_to_run_and_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            legacy_root = runtime_dir / "python-engine"
            runtime_root.mkdir(parents=True, exist_ok=True)
            legacy_root.mkdir(parents=True, exist_ok=True)
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )

            self.assertEqual(repo.tree_diffs_dir_path(), (runtime_root / "tree-diffs").resolve())
            self.assertEqual(
                repo.tree_diffs_dir_path("run-1", "review"),
                (runtime_root / "runs" / "run-1" / "tree-diffs" / "review").resolve(),
            )

    def test_runtime_artifact_writer_updates_active_revision_and_derived_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            legacy_root = runtime_dir / "python-engine"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.COMPAT_READ_WRITE,
            )
            state = RunState(run_id="run-1", mode="main")
            repo.save_run(
                state=state,
                contexts=[self._context(Path(tmpdir))],
                errors=[],
                events=[],
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )

            accepted = repo.write_runtime_artifact(
                run_id="run-1",
                artifact_name="runtime_readiness_report.json",
                text='{"passed": true}',
            )

            self.assertTrue(accepted)
            candidate = repo.run_index.candidates(_state_repository.StateSelector(mode=None, project_names=()))[0]
            artifact_paths = (
                candidate.state_path.parent / "runtime_readiness_report.json",
                repo.run_dir_path("run-1") / "runtime_readiness_report.json",
                runtime_root / "runtime_readiness_report.json",
                legacy_root / "runtime_readiness_report.json",
            )
            for path in artifact_paths:
                with self.subTest(path=path):
                    self.assertEqual(path.read_text(encoding="utf-8"), '{"passed": true}')

    def test_retired_runtime_artifact_writer_cannot_recreate_files_after_deactivation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            legacy_root = runtime_dir / "python-engine"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.COMPAT_READ_WRITE,
            )
            repo.save_run(
                state=RunState(run_id="run-retired", mode="main"),
                contexts=[self._context(Path(tmpdir))],
                errors=[],
                events=[],
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )
            self.assertTrue(repo.deactivate_run("run-retired"))

            accepted = repo.write_runtime_artifact(
                run_id="run-retired",
                artifact_name="runtime_readiness_report.json",
                text='{"stale": true}',
            )

            self.assertFalse(accepted)
            self.assertFalse((repo.run_dir_path("run-retired") / "runtime_readiness_report.json").exists())
            self.assertFalse((runtime_root / "runtime_readiness_report.json").exists())
            self.assertFalse((legacy_root / "runtime_readiness_report.json").exists())

    def test_stale_runtime_artifact_writer_cannot_recreate_files_after_aggressive_purge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            legacy_root = runtime_dir / "python-engine"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.COMPAT_READ_WRITE,
            )
            repo.save_run(
                state=RunState(run_id="run-purged", mode="main"),
                contexts=[self._context(Path(tmpdir))],
                errors=[],
                events=[],
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )
            repo.purge(aggressive=True)

            readiness_accepted = repo.write_runtime_artifact(
                run_id="run-purged",
                artifact_name="runtime_readiness_report.json",
                text='{"stale": true}',
            )
            events_accepted = repo.write_runtime_artifact(
                run_id="run-purged",
                artifact_name="events.jsonl",
                text='{"event": "stale"}\n',
            )

            self.assertFalse(readiness_accepted)
            self.assertFalse(events_accepted)
            self.assertFalse(repo.run_dir_path("run-purged").exists())
            for root in (runtime_root, legacy_root):
                with self.subTest(root=root):
                    self.assertFalse((root / "runtime_readiness_report.json").exists())
                    self.assertFalse((root / "events.jsonl").exists())

    def test_purge_waits_for_inflight_runtime_artifact_write_and_removes_its_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )
            repo.save_run(
                state=RunState(run_id="run-racing", mode="main"),
                contexts=[self._context(Path(tmpdir))],
                errors=[],
                events=[],
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )
            artifact_write_started = Event()
            release_artifact_write = Event()
            original_write_text = repo._write_text

            def blocking_write_text(path: Path, text: str) -> None:
                if (
                    path.name == "runtime_readiness_report.json"
                    and "revisions" in path.parts
                    and not artifact_write_started.is_set()
                ):
                    artifact_write_started.set()
                    self.assertTrue(release_artifact_write.wait(timeout=2))
                original_write_text(path, text)

            repo._write_text = blocking_write_text  # type: ignore[method-assign]
            with ThreadPoolExecutor(max_workers=2) as executor:
                writer = executor.submit(
                    repo.write_runtime_artifact,
                    run_id="run-racing",
                    artifact_name="runtime_readiness_report.json",
                    text='{"passed": true}',
                )
                self.assertTrue(artifact_write_started.wait(timeout=2))
                purge = executor.submit(repo.purge, aggressive=True)
                release_artifact_write.set()
                self.assertTrue(writer.result(timeout=2))
                purge.result(timeout=2)

            self.assertFalse(repo.run_dir_path("run-racing").exists())
            self.assertFalse((runtime_root / "runtime_readiness_report.json").exists())

    def test_unbound_runtime_artifact_is_scoped_and_artifact_name_is_allowlisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            legacy_root = runtime_dir / "python-engine"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )

            accepted = repo.write_runtime_artifact(
                run_id=None,
                artifact_name="events.jsonl",
                text='{"event": "doctor"}\n',
            )

            self.assertTrue(accepted)
            self.assertEqual(
                (runtime_root / "events.jsonl").read_text(encoding="utf-8"),
                '{"event": "doctor"}\n',
            )
            self.assertFalse((legacy_root / "events.jsonl").exists())
            with self.assertRaisesRegex(ValueError, "unsupported mutable runtime artifact"):
                repo.write_runtime_artifact(
                    run_id=None,
                    artifact_name="run_state.json",
                    text="{}",
                )
            with self.assertRaisesRegex(ValueError, "path component"):
                repo.write_runtime_artifact(
                    run_id=None,
                    artifact_name="../events.jsonl",
                    text="",
                )

    def test_unbound_runtime_artifact_never_attaches_to_an_active_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )
            repo.save_run(
                state=RunState(run_id="run-active", mode="main"),
                contexts=[self._context(Path(tmpdir))],
                errors=[],
                events=[{"event": "run-bound"}],
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )
            candidate = repo.run_index.candidates(_state_repository.StateSelector(mode=None, project_names=()))[0]

            accepted = repo.write_runtime_artifact(
                run_id=None,
                artifact_name="events.jsonl",
                text='{"event": "scope-diagnostic"}\n',
            )

            self.assertTrue(accepted)
            self.assertEqual(
                (runtime_root / "events.jsonl").read_text(encoding="utf-8"),
                json.dumps({"event": "run-bound"}, sort_keys=True) + "\n",
            )
            self.assertEqual(
                (runtime_root / "diagnostics" / "events.jsonl").read_text(encoding="utf-8"),
                '{"event": "scope-diagnostic"}\n',
            )
            expected_run_text = json.dumps({"event": "run-bound"}, sort_keys=True) + "\n"
            self.assertEqual(
                (repo.run_dir_path("run-active") / "events.jsonl").read_text(encoding="utf-8"),
                expected_run_text,
            )
            self.assertEqual(
                (candidate.state_path.parent / "events.jsonl").read_text(encoding="utf-8"),
                expected_run_text,
            )

    def test_retired_overlapping_run_artifact_writer_is_fenced_from_current_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            legacy_root = runtime_dir / "python-engine"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.COMPAT_READ_WRITE,
            )
            for run_id in ("run-old", "run-new"):
                repo.save_run(
                    state=RunState(run_id=run_id, mode="main"),
                    contexts=[self._context(Path(tmpdir))],
                    errors=[],
                    events=[{"event": run_id}],
                    emit=lambda *_args, **_kwargs: None,
                    runtime_map_builder=lambda _state: {"projection": {}},
                )

            accepted = repo.write_runtime_artifact(
                run_id="run-old",
                artifact_name="events.jsonl",
                text='{"event": "late-old-writer"}\n',
            )

            self.assertFalse(accepted)
            self.assertEqual(
                (repo.run_dir_path("run-old") / "events.jsonl").read_text(encoding="utf-8"),
                json.dumps({"event": "run-old"}, sort_keys=True) + "\n",
            )
            expected_current = json.dumps({"event": "run-new"}, sort_keys=True) + "\n"
            self.assertEqual((runtime_root / "events.jsonl").read_text(encoding="utf-8"), expected_current)
            self.assertEqual((legacy_root / "events.jsonl").read_text(encoding="utf-8"), expected_current)

    def test_corrupt_authoritative_revision_does_not_reactivate_retired_project_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )
            for run_id, pid in (("run-old", 101), ("run-new", 202)):
                repo.save_resume_state(
                    state=RunState(
                        run_id=run_id,
                        mode="trees",
                        services={
                            "feature-a Backend": ServiceRecord(
                                name="feature-a Backend",
                                type="backend",
                                cwd="/tmp/feature-a/backend",
                                project="feature-a",
                                pid=pid,
                            )
                        },
                    ),
                    emit=lambda *_args, **_kwargs: None,
                    runtime_map_builder=lambda state: {"run_id": state.run_id},
                )

            candidates = repo.run_index.candidates(_state_repository.StateSelector(mode="trees", project_names=()))
            new_candidate = next(candidate for candidate in candidates if candidate.run_id == "run-new")
            new_candidate.state_path.write_text('{"broken":', encoding="utf-8")

            loaded = repo.load_latest(
                mode="trees",
                strict_mode_match=True,
                project_names=["feature-a"],
            )

            self.assertIsNone(loaded)
            self.assertFalse((runtime_root / "run_state.json").exists())
            self.assertFalse((runtime_root / ".last_state").exists())

    def test_generic_lookup_skips_corrupt_newest_mode_and_returns_newest_valid_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )
            repo.save_resume_state(
                state=RunState(
                    run_id="run-main",
                    mode="main",
                    services={
                        "Main Backend": ServiceRecord(
                            name="Main Backend",
                            type="backend",
                            cwd="/tmp/main/backend",
                            project="Main",
                        )
                    },
                ),
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {},
            )
            repo.save_resume_state(
                state=RunState(
                    run_id="run-trees",
                    mode="trees",
                    services={
                        "feature-a Backend": ServiceRecord(
                            name="feature-a Backend",
                            type="backend",
                            cwd="/tmp/feature-a/backend",
                            project="feature-a",
                        )
                    },
                ),
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {},
            )
            corrupt_candidate = repo.run_index.candidates(
                _state_repository.StateSelector(mode="trees", project_names=())
            )[0]
            corrupt_candidate.state_path.write_text('{"broken":', encoding="utf-8")

            loaded = repo.load_latest()

            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual((loaded.run_id, loaded.mode), ("run-main", "main"))
            self.assertEqual(load_state(str(runtime_root / "run_state.json")).run_id, "run-main")

    def test_resuming_older_mode_reactivates_it_without_changing_project_ownership_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )
            main_state = RunState(
                run_id="run-main",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd="/tmp/main/backend",
                        project="Main",
                    )
                },
            )
            tree_state = RunState(
                run_id="run-tree",
                mode="trees",
                services={
                    "FeatureA Backend": ServiceRecord(
                        name="FeatureA Backend",
                        type="backend",
                        cwd="/tmp/FeatureA/backend",
                        project="FeatureA",
                    )
                },
            )
            for state in (main_state, tree_state):
                repo.save_resume_state(
                    state=state,
                    emit=lambda *_args, **_kwargs: None,
                    runtime_map_builder=lambda _state: {},
                )
            self.assertEqual(repo.load_latest().run_id, "run-tree")  # type: ignore[union-attr]

            repo.save_resume_state(
                state=main_state,
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {},
            )

            current = repo.load_latest()
            self.assertIsNotNone(current)
            assert current is not None
            self.assertEqual((current.run_id, current.mode), ("run-main", "main"))
            tree = repo.load_latest(
                mode="trees",
                strict_mode_match=True,
                project_names=["FeatureA"],
            )
            self.assertIsNotNone(tree)
            assert tree is not None
            self.assertEqual(tree.run_id, "run-tree")

    def test_corrupt_primary_and_backup_after_deactivation_fails_closed_without_resurrection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )
            repo.save_resume_state(
                state=RunState(
                    run_id="retired-run",
                    mode="main",
                    services={
                        "Main Backend": ServiceRecord(
                            name="Main Backend",
                            type="backend",
                            cwd="/tmp/backend",
                            project="Main",
                        )
                    },
                ),
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {},
            )
            self.assertTrue(repo.deactivate_run("retired-run"))
            historical_state = repo.run_dir_path("retired-run") / "run_state.json"
            self.assertTrue(historical_state.is_file())
            repo.run_index.index_path.write_text('{"broken":', encoding="utf-8")
            repo.run_index.backup_path.write_text('{"broken":', encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "both the primary and backup"):
                repo.load_latest()

            self.assertTrue(historical_state.is_file())
            self.assertFalse((runtime_root / "run_state.json").exists())

    def test_failed_legacy_registry_publish_cleans_staged_revision_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            legacy_state = runtime_root / "runs" / "legacy-run" / "run_state.json"
            legacy_state.parent.mkdir(parents=True, exist_ok=True)
            dump_state(
                RunState(
                    run_id="legacy-run",
                    mode="main",
                    services={
                        "Main Backend": ServiceRecord(
                            name="Main Backend",
                            type="backend",
                            cwd="/tmp/backend",
                            project="Main",
                        )
                    },
                ),
                str(legacy_state),
            )
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )

            with patch.object(repo.run_index, "replace_all", side_effect=OSError("registry unavailable")):
                with self.assertRaisesRegex(OSError, "registry unavailable"):
                    repo.load_latest()

            revisions = legacy_state.parent / "revisions"
            self.assertEqual(list(revisions.iterdir()) if revisions.is_dir() else [], [])
            self.assertTrue(legacy_state.is_file())
            self.assertFalse((runtime_root / "run_registry.json").exists())

    def test_read_only_and_scoped_purges_never_mutate_legacy_runtime(self) -> None:
        for compat_mode in (
            RuntimeStateRepository.COMPAT_READ_ONLY,
            RuntimeStateRepository.SCOPED_ONLY,
        ):
            with self.subTest(compat_mode=compat_mode), tempfile.TemporaryDirectory() as tmpdir:
                runtime_dir = Path(tmpdir) / "runtime"
                runtime_root = runtime_dir / "scope"
                legacy_root = runtime_dir / "python-engine"
                legacy_run = legacy_root / "runs" / "legacy-run"
                legacy_run.mkdir(parents=True, exist_ok=True)
                sentinels = {
                    legacy_root / "run_state.json": "legacy-state",
                    legacy_root / "events.jsonl": "legacy-event",
                    legacy_root / ".last_state": "legacy-pointer",
                    legacy_run / "run_state.json": "legacy-history",
                    legacy_root / ".events.jsonl.stale.tmp": "legacy-temp",
                }
                for path, text in sentinels.items():
                    path.write_text(text, encoding="utf-8")
                repo = RuntimeStateRepository(
                    runtime_root=runtime_root,
                    runtime_legacy_root=legacy_root,
                    runtime_dir=runtime_dir,
                    runtime_scope_id="repo-123",
                    compat_mode=compat_mode,
                )

                repo.purge(aggressive=True)

                for path, expected in sentinels.items():
                    self.assertEqual(path.read_text(encoding="utf-8"), expected)

    def test_first_operation_read_only_purge_cannot_reimport_legacy_after_index_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            legacy_root = runtime_dir / "python-engine"
            legacy_root.mkdir(parents=True)
            legacy_state = legacy_root / "run_state.json"
            dump_state(RunState(run_id="legacy-run", mode="main"), str(legacy_state))
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.COMPAT_READ_ONLY,
            )

            repo.purge(aggressive=False)
            self.assertTrue(legacy_state.is_file())
            self.assertTrue((runtime_root / "run_registry.json").is_file())
            repo.run_index.index_path.unlink()
            repo.run_index.backup_path.unlink()

            with self.assertRaisesRegex(RuntimeError, "both the primary and backup"):
                repo.load_latest()

            self.assertTrue(legacy_state.is_file())
            self.assertFalse((runtime_root / "run_state.json").exists())

    def test_runtime_artifact_directories_reject_symlink_redirection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            external = Path(tmpdir) / "external"
            external.mkdir()
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )
            runs_root = repo.run_dir_path(None)
            runs_root.mkdir(parents=True)
            run_link = runs_root / "run-a"
            run_link.symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                repo.run_dir_path("run-a")
            run_link.unlink()

            run_dir = repo.run_dir_path("run-a")
            run_dir.mkdir()
            for name, resolver in (
                ("test-results", lambda: repo.test_results_dir_path("run-a")),
                ("tree-diffs", lambda: repo.tree_diffs_dir_path("run-a")),
            ):
                with self.subTest(name=name):
                    link = run_dir / name
                    link.symlink_to(external, target_is_directory=True)
                    with self.assertRaisesRegex(ValueError, "symlink"):
                        resolver()
                    link.unlink()

            root_tree_diffs = runtime_root / "tree-diffs"
            root_tree_diffs.symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                repo.tree_diffs_dir_path()
            self.assertEqual(list(external.iterdir()), [])

    def test_runtime_root_retarget_is_rejected_before_lock_or_purge_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            legacy_root = runtime_dir / "python-engine"
            runtime_root.mkdir(parents=True)
            legacy_root.mkdir()
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.COMPAT_READ_WRITE,
            )
            external = Path(tmpdir) / "external"
            external.mkdir()
            sentinel = external / "run_state.json"
            sentinel.write_text("outside-sentinel", encoding="utf-8")
            runtime_root.rmdir()
            runtime_root.symlink_to(external, target_is_directory=True)

            with self.assertRaisesRegex(RuntimeError, "symlink"):
                repo.purge(aggressive=True)

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "outside-sentinel")
            self.assertEqual(list(external.iterdir()), [sentinel])

    def test_legacy_root_retarget_is_rejected_before_compatibility_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            legacy_root = runtime_dir / "python-engine"
            runtime_root.mkdir(parents=True)
            legacy_root.mkdir()
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.COMPAT_READ_WRITE,
            )
            external = Path(tmpdir) / "external"
            external.mkdir()
            sentinel = external / "run_state.json"
            sentinel.write_text("outside-sentinel", encoding="utf-8")
            legacy_root.rmdir()
            legacy_root.symlink_to(external, target_is_directory=True)

            with self.assertRaisesRegex(RuntimeError, "symlink"):
                repo.save_resume_state(
                    state=RunState(run_id="run-a", mode="main"),
                    emit=lambda *_args, **_kwargs: None,
                    runtime_map_builder=lambda _state: {},
                )

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "outside-sentinel")
            self.assertEqual(list(external.iterdir()), [sentinel])

    def test_runtime_update_carries_forward_ports_errors_events_and_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            legacy_root = runtime_dir / "python-engine"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.COMPAT_READ_WRITE,
            )
            state = RunState(
                run_id="run-a",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd="/tmp/backend",
                        project="Main",
                        pid=123,
                    )
                },
            )
            repo.save_run(
                state=state,
                contexts=[self._context(Path(tmpdir))],
                errors=["diagnostic"],
                events=[{"event": "initial"}],
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {}},
            )
            self.assertTrue(
                repo.write_runtime_artifact(
                    run_id="run-a",
                    artifact_name="runtime_readiness_report.json",
                    text='{"passed": true}',
                )
            )
            artifact_names = (
                "ports_manifest.json",
                "error_report.json",
                "events.jsonl",
                "runtime_readiness_report.json",
            )
            expected = {name: (runtime_root / name).read_text(encoding="utf-8") for name in artifact_names}

            repo.save_resume_state(
                state=state,
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {"projection": {"Main": {}}},
            )

            candidate = repo.run_index.candidates(_state_repository.StateSelector(mode="main", project_names=()))[0]
            for artifact_name, expected_text in expected.items():
                for root in (runtime_root, legacy_root, candidate.state_path.parent):
                    with self.subTest(artifact_name=artifact_name, root=root):
                        actual_text = (root / artifact_name).read_text(encoding="utf-8")
                        if artifact_name == "error_report.json":
                            payload = json.loads(actual_text)
                            self.assertEqual(payload["errors"], ["diagnostic"])
                            self.assertEqual(payload["source_run_ids"], ["run-a"])
                        else:
                            self.assertEqual(actual_text, expected_text)

    def test_partial_tree_stop_rebuilds_pointer_inventory_without_resurrecting_removed_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            legacy_root = runtime_dir / "python-engine"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.COMPAT_READ_WRITE,
            )
            state = RunState(
                run_id="run-ab",
                mode="trees",
                services={
                    project: ServiceRecord(
                        name=project,
                        type="backend",
                        cwd=f"/tmp/{project}/backend",
                        project=project,
                    )
                    for project in ("FeatureA", "FeatureB")
                },
            )
            repo.save_resume_state(
                state=state,
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {},
            )
            pointer_a_name = repo._tree_pointer_name("FeatureA")
            pointer_b_name = repo._tree_pointer_name("FeatureB")
            assert pointer_a_name is not None and pointer_b_name is not None
            old_target = Path((runtime_root / pointer_a_name).read_text(encoding="utf-8").strip())
            self.assertTrue(old_target.is_file())

            state.services.pop("FeatureA")
            repo.save_selected_stop_state(
                state=state,
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {},
            )

            for root in (runtime_root, legacy_root):
                self.assertFalse((root / pointer_a_name).exists())
                self.assertTrue((root / pointer_b_name).is_file())
            self.assertTrue(old_target.is_file())
            self.assertIsNone(
                repo.load_latest(
                    mode="trees",
                    strict_mode_match=True,
                    project_names=["FeatureA"],
                )
            )
            remaining = repo.load_latest(
                mode="trees",
                strict_mode_match=True,
                project_names=["FeatureB"],
            )
            self.assertIsNotNone(remaining)
            assert remaining is not None
            self.assertEqual(set(remaining.services), {"FeatureB"})
            ports_payload = json.loads((runtime_root / "ports_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                [project["project"] for project in ports_payload["projects"]],
                ["FeatureB"],
            )

    def test_selected_stop_can_preserve_authoritative_metadata_only_tree_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            legacy_root = runtime_dir / "python-engine"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.COMPAT_READ_WRITE,
            )
            state = RunState(
                run_id="run-metadata-ab",
                mode="trees",
                metadata={
                    "project_names": ["FeatureA", "FeatureB"],
                    "project_roots": {
                        "FeatureA": "/tmp/FeatureA",
                        "FeatureB": "/tmp/FeatureB",
                    },
                },
            )
            repo.save_selected_stop_state(
                state=state,
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {},
                authoritative_project_names=["FeatureA", "FeatureB"],
            )

            state.metadata["project_names"] = ["FeatureB"]
            state.metadata["project_roots"] = {"FeatureB": "/tmp/FeatureB"}
            repo.save_selected_stop_state(
                state=state,
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {},
                authoritative_project_names=["FeatureB"],
            )

            candidates = repo.run_index.candidates(StateSelector(mode="trees", project_names=()))
            self.assertEqual(
                [(candidate.run_id, candidate.project_names) for candidate in candidates],
                [("run-metadata-ab", ("featureb",))],
            )
            self.assertIsNone(
                repo.load_latest(
                    mode="trees",
                    strict_mode_match=True,
                    project_names=["FeatureA"],
                )
            )
            remaining = repo.load_latest(
                mode="trees",
                strict_mode_match=True,
                project_names=["FeatureB"],
            )
            self.assertIsNotNone(remaining)
            assert remaining is not None
            self.assertEqual(remaining.services, {})
            self.assertEqual(remaining.requirements, {})
            self.assertEqual(remaining.metadata["project_names"], ["FeatureB"])
            self.assertEqual(remaining.metadata["project_roots"], {"FeatureB": "/tmp/FeatureB"})
            current = json.loads(repo.run_state_path().read_text(encoding="utf-8"))
            self.assertEqual(current["metadata"]["project_names"], ["FeatureB"])
            pointer_a = repo._tree_pointer_name("FeatureA")
            pointer_b = repo._tree_pointer_name("FeatureB")
            assert pointer_a is not None and pointer_b is not None
            self.assertFalse((runtime_root / pointer_a).exists())
            self.assertTrue((runtime_root / pointer_b).exists())

    def test_lossy_tree_names_and_mixed_case_get_distinct_stable_pointers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )
            projects = ("Feature/API v2", "Feature_API_v2")
            for index, project in enumerate(projects, start=1):
                repo.save_run(
                    state=RunState(run_id=f"run-{index}", mode="trees"),
                    contexts=[SimpleNamespace(name=project, root=Path(tmpdir) / f"tree-{index}", ports={})],
                    errors=[],
                    events=[],
                    emit=lambda *_args, **_kwargs: None,
                    runtime_map_builder=lambda _state: {},
                )

            pointer_names = [repo._tree_pointer_name(project) for project in projects]
            self.assertTrue(all(pointer_names))
            self.assertEqual(len(set(pointer_names)), 2)
            pointed_runs = {
                load_state((runtime_root / str(pointer_name)).read_text(encoding="utf-8").strip()).run_id
                for pointer_name in pointer_names
            }
            self.assertEqual(pointed_runs, {"run-1", "run-2"})
            self.assertEqual(
                {pointer.name for pointer in runtime_root.glob(".last_state.trees.*")},
                set(pointer_names),
            )

    def test_post_commit_per_run_alias_failure_is_repaired_on_next_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            repo = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=runtime_dir / "python-engine",
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )
            run_alias = repo.run_dir_path("run-a") / "run_state.json"
            original_write_text = repo._write_text
            failed = False

            def fail_first_run_alias(path: Path, text: str) -> None:
                nonlocal failed
                if path == run_alias and not failed:
                    failed = True
                    raise OSError("alias unavailable")
                original_write_text(path, text)

            repo._write_text = fail_first_run_alias  # type: ignore[method-assign]
            repo.save_run(
                state=RunState(run_id="run-a", mode="main"),
                contexts=[self._context(Path(tmpdir))],
                errors=[],
                events=[],
                emit=lambda *_args, **_kwargs: None,
                runtime_map_builder=lambda _state: {},
            )
            self.assertTrue(failed)
            self.assertFalse(run_alias.exists())
            repo._write_text = original_write_text  # type: ignore[method-assign]

            loaded = repo.load_latest()

            self.assertIsNotNone(loaded)
            self.assertTrue(run_alias.is_file())
            self.assertEqual(load_state(str(run_alias)).run_id, "run-a")


if __name__ == "__main__":
    unittest.main()
