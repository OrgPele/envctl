from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path
import sys
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

_models = importlib.import_module("envctl_engine.state.models")
_state = importlib.import_module("envctl_engine.state")
_state_repository = importlib.import_module("envctl_engine.state.repository")
RunState = _models.RunState
ServiceRecord = _models.ServiceRecord
dump_state = _state.dump_state
RuntimeStateRepository = _state_repository.RuntimeStateRepository


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
                write_shell_prune_report=None,
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
            self.assertEqual(
                main_pointer.read_text(encoding="utf-8").strip(),
                str(runtime_root / "runs" / "run-1" / "run_state.json"),
            )

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
            state = RunState(run_id="run-2", mode="trees", metadata={"repo_scope_id": "repo-123"})

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
            self.assertEqual(
                main_pointer_target,
                str(runtime_root / "runs" / "run-main-resume" / "run_state.json"),
            )

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
            self.assertEqual(tree_pointer.read_text(encoding="utf-8").strip(), str(tree_state_path))

            loaded_trees = repo.load_latest(mode="trees", strict_mode_match=True)
            self.assertIsNotNone(loaded_trees)
            assert loaded_trees is not None
            self.assertEqual(loaded_trees.run_id, "run-tree")
            self.assertEqual(loaded_trees.mode, "trees")

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
            self.assertEqual(main_pointer.read_text(encoding="utf-8").strip(), str(main_state_path))

            loaded_main = repo.load_latest(mode="main", strict_mode_match=True)
            self.assertIsNotNone(loaded_main)
            assert loaded_main is not None
            self.assertEqual(loaded_main.run_id, "run-main")
            self.assertEqual(loaded_main.mode, "main")

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

            test_summary = repo.test_results_dir_path("run-1", "run_20260309_100000") / "Main" / "failed_tests_summary.txt"
            test_summary.parent.mkdir(parents=True, exist_ok=True)
            test_summary.write_text("No failed tests.\n", encoding="utf-8")

            repo.purge(aggressive=False)
            self.assertTrue(test_summary.is_file())

            repo.purge(aggressive=True)
            self.assertFalse(repo.run_dir_path("run-1").exists())
            self.assertFalse(test_summary.exists())


if __name__ == "__main__":
    unittest.main()
