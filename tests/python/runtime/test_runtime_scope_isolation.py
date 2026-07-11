from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.config import discover_local_config_state, load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.state import dump_state


class RuntimeScopeIsolationTests(unittest.TestCase):
    def test_runtime_uses_repository_canonical_root_through_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            real_runtime_dir = root / "real-runtime"
            runtime_alias = root / "runtime-alias"
            repo = root / "repo"
            real_runtime_dir.mkdir()
            runtime_alias.symlink_to(real_runtime_dir, target_is_directory=True)
            (repo / ".git").mkdir(parents=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime_alias),
                }
            )

            runtime = PythonEngineRuntime(config, env={})

            self.assertEqual(runtime.runtime_root, runtime.state_repository.runtime_root)
            self.assertEqual(runtime.runtime_legacy_root, runtime.state_repository.runtime_legacy_root)
            self.assertEqual(runtime.runtime_root, config.runtime_scope_dir.resolve())
            self.assertEqual(runtime.port_planner.lock_dir, runtime.runtime_root / "locks")

    def test_managed_linked_worktree_uses_main_repo_runtime_scope_and_lock_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime_dir = root / "runtime"
            repo = root / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            gitdir = repo / ".git" / "worktrees" / "feature-a-1"
            gitdir.mkdir(parents=True, exist_ok=True)
            worktree.mkdir(parents=True, exist_ok=True)
            (repo / ".git").mkdir(exist_ok=True)
            (repo / ".envctl").write_text("ENVCTL_DEFAULT_MODE=main\n", encoding="utf-8")
            (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")

            main_config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime_dir)})
            worktree_config = load_config({"RUN_REPO_ROOT": str(worktree), "RUN_SH_RUNTIME_DIR": str(runtime_dir)})
            main_runtime = PythonEngineRuntime(main_config, env={})
            worktree_runtime = PythonEngineRuntime(worktree_config, env={"ENVCTL_INVOCATION_CWD": str(worktree)})

            self.assertEqual(worktree_config.base_dir, repo.resolve())
            self.assertEqual(worktree_config.runtime_scope_id, main_config.runtime_scope_id)
            self.assertEqual(worktree_config.runtime_scope_dir, main_config.runtime_scope_dir)
            self.assertEqual(worktree_runtime.runtime_root, main_runtime.runtime_root)
            self.assertEqual(worktree_runtime.port_planner.lock_dir, main_runtime.port_planner.lock_dir)

    def test_managed_linked_worktree_uses_parent_config_path_even_before_parent_envctl_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime_dir = root / "runtime"
            repo = root / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            gitdir = repo / ".git" / "worktrees" / "feature-a-1"
            gitdir.mkdir(parents=True, exist_ok=True)
            worktree.mkdir(parents=True, exist_ok=True)
            (repo / ".git").mkdir(exist_ok=True)
            (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
            provenance = worktree / ".envctl-state" / "worktree-provenance.json"
            provenance.parent.mkdir(parents=True, exist_ok=True)
            provenance.write_text('{"schema_version": 1}\n', encoding="utf-8")

            config = load_config({"RUN_REPO_ROOT": str(worktree), "RUN_SH_RUNTIME_DIR": str(runtime_dir)})
            local_state = discover_local_config_state(config.base_dir)

            self.assertEqual(config.base_dir, repo.resolve())
            self.assertEqual(local_state.config_file_path, repo.resolve() / ".envctl")
            self.assertFalse(local_state.config_file_exists)

    def test_managed_linked_worktree_keeps_main_mode_execution_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime_dir = root / "runtime"
            repo = root / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            gitdir = repo / ".git" / "worktrees" / "feature-a-1"
            gitdir.mkdir(parents=True, exist_ok=True)
            worktree.mkdir(parents=True, exist_ok=True)
            (worktree / "api").mkdir(parents=True, exist_ok=True)
            (worktree / "api" / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
            (repo / ".git").mkdir(exist_ok=True)
            (repo / ".envctl").write_text("ENVCTL_DEFAULT_MODE=main\n", encoding="utf-8")
            (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")

            config = load_config({"RUN_REPO_ROOT": str(worktree), "RUN_SH_RUNTIME_DIR": str(runtime_dir)})
            runtime = PythonEngineRuntime(config, env={"ENVCTL_INVOCATION_CWD": str(worktree)})

            self.assertEqual(config.base_dir, repo.resolve())
            self.assertEqual(config.execution_root, worktree.resolve())
            self.assertEqual(config.backend_dir_name, "api")
            self.assertEqual(runtime._discover_projects(mode="main")[0].root, worktree.resolve())

    def test_runtime_scope_ids_are_repo_specific(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime_dir = root / "runtime"
            repo_a = root / "repo-a"
            repo_b = root / "repo-b"
            (repo_a / ".git").mkdir(parents=True, exist_ok=True)
            (repo_b / ".git").mkdir(parents=True, exist_ok=True)

            cfg_a = load_config(
                {
                    "RUN_REPO_ROOT": str(repo_a),
                    "RUN_SH_RUNTIME_DIR": str(runtime_dir),
                }
            )
            cfg_b = load_config(
                {
                    "RUN_REPO_ROOT": str(repo_b),
                    "RUN_SH_RUNTIME_DIR": str(runtime_dir),
                }
            )

            self.assertNotEqual(cfg_a.runtime_scope_id, cfg_b.runtime_scope_id)
            self.assertNotEqual(cfg_a.runtime_scope_dir, cfg_b.runtime_scope_dir)
            self.assertEqual(cfg_a.runtime_scope_dir.parent, runtime_dir / "python-engine")
            self.assertEqual(cfg_b.runtime_scope_dir.parent, runtime_dir / "python-engine")

    def test_legacy_fallback_ignores_foreign_scoped_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime_dir = root / "runtime"
            repo_a = root / "repo-a"
            repo_b = root / "repo-b"
            (repo_a / ".git").mkdir(parents=True, exist_ok=True)
            (repo_b / ".git").mkdir(parents=True, exist_ok=True)

            cfg_a = load_config(
                {
                    "RUN_REPO_ROOT": str(repo_a),
                    "RUN_SH_RUNTIME_DIR": str(runtime_dir),
                }
            )
            cfg_b = load_config(
                {
                    "RUN_REPO_ROOT": str(repo_b),
                    "RUN_SH_RUNTIME_DIR": str(runtime_dir),
                }
            )
            runtime_a = PythonEngineRuntime(cfg_a, env={})
            runtime_b = PythonEngineRuntime(cfg_b, env={})

            legacy_state_path = runtime_dir / "python-engine" / "run_state.json"
            legacy_state_path.parent.mkdir(parents=True, exist_ok=True)
            dump_state(
                RunState(
                    run_id="run-a",
                    mode="main",
                    services={
                        "Main Backend": ServiceRecord(
                            name="Main Backend",
                            type="backend",
                            cwd=str(repo_a),
                            pid=123,
                            requested_port=8000,
                            actual_port=8000,
                            status="running",
                        )
                    },
                    metadata={"repo_scope_id": cfg_a.runtime_scope_id},
                ),
                str(legacy_state_path),
            )

            loaded_a = runtime_a._try_load_existing_state()
            loaded_b = runtime_b._try_load_existing_state()
            self.assertIsNotNone(loaded_a)
            self.assertIsNone(loaded_b)

    def test_lock_dir_is_scoped_and_legacy_lock_view_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime_dir = root / "runtime"
            repo = root / "repo"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            cfg = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime_dir),
                }
            )
            runtime = PythonEngineRuntime(cfg, env={})

            self.assertEqual(runtime.port_planner.lock_dir, runtime.runtime_root / "locks")
            self.assertTrue((runtime_dir / "python-engine" / "locks").exists())

    def test_stale_legacy_lock_symlink_is_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime_dir = root / "runtime"
            repo = root / "repo"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            legacy_root = runtime_dir / "python-engine"
            legacy_root.mkdir(parents=True, exist_ok=True)
            stale_target = runtime_dir / "python-engine" / "missing-scope" / "locks"
            (legacy_root / "locks").symlink_to(stale_target, target_is_directory=True)
            cfg = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime_dir),
                }
            )

            runtime = PythonEngineRuntime(cfg, env={})

            legacy_locks = runtime_dir / "python-engine" / "locks"
            self.assertTrue(legacy_locks.is_symlink())
            self.assertEqual(
                legacy_locks.resolve(strict=False),
                (runtime.runtime_root / "locks").resolve(strict=False),
            )

    def test_scoped_and_read_only_construction_preserve_legacy_artifacts_and_lock_view(self) -> None:
        for compat_mode in ("scoped_only", "compat_read_only"):
            with self.subTest(compat_mode=compat_mode), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                runtime_dir = root / "runtime"
                repo = root / "repo"
                (repo / ".git").mkdir(parents=True)
                legacy_root = runtime_dir / "python-engine"
                legacy_root.mkdir(parents=True)
                sentinel = legacy_root / "run_state.json"
                sentinel.write_text("legacy-sentinel", encoding="utf-8")
                config = load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime_dir),
                    }
                )

                runtime = PythonEngineRuntime(
                    config,
                    env={"ENVCTL_STATE_COMPAT_MODE": compat_mode},
                )

                self.assertEqual(sentinel.read_text(encoding="utf-8"), "legacy-sentinel")
                self.assertFalse((legacy_root / "locks").exists())
                self.assertTrue(runtime.runtime_root.is_dir())

    def test_construction_rejects_preexisting_scoped_root_symlink_before_external_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime_dir = root / "runtime"
            repo = root / "repo"
            (repo / ".git").mkdir(parents=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime_dir),
                }
            )
            external = root / "external"
            external.mkdir()
            sentinel = external / "sentinel.txt"
            sentinel.write_text("untouched", encoding="utf-8")
            config.runtime_scope_dir.parent.mkdir(parents=True, exist_ok=True)
            config.runtime_scope_dir.symlink_to(external, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "symlink"):
                PythonEngineRuntime(config, env={})

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "untouched")
            self.assertEqual(list(external.iterdir()), [sentinel])

    def test_construction_rejects_preexisting_legacy_root_symlink_before_external_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime_dir = root / "runtime"
            repo = root / "repo"
            (repo / ".git").mkdir(parents=True)
            external = root / "external"
            external.mkdir()
            sentinel = external / "sentinel.txt"
            sentinel.write_text("untouched", encoding="utf-8")
            runtime_dir.mkdir()
            (runtime_dir / "python-engine").symlink_to(external, target_is_directory=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime_dir),
                }
            )

            with self.assertRaisesRegex(ValueError, "symlink"):
                PythonEngineRuntime(config, env={})

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "untouched")
            self.assertEqual(list(external.iterdir()), [sentinel])


if __name__ == "__main__":
    unittest.main()
