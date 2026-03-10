from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.state import dump_state


class RuntimeScopeIsolationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
