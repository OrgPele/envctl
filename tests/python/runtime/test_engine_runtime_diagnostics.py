from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime import engine_runtime_diagnostics as diagnostics  # noqa: E402


class EngineRuntimeDiagnosticsTests(unittest.TestCase):
    def test_parity_manifest_helpers_report_generated_at_and_completeness(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            manifest_dir = repo_root / "contracts"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / "python_engine_parity_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-06T10:00:00Z",
                        "commands": {"start": "python_complete", "doctor": "python_complete"},
                    }
                ),
                encoding="utf-8",
            )
            runtime = SimpleNamespace(config=SimpleNamespace(base_dir=repo_root))

            info = diagnostics.parity_manifest_info(runtime)
            payload = diagnostics.read_parity_manifest(runtime)
            complete = diagnostics.parity_manifest_is_complete(runtime)

            self.assertEqual(info["generated_at"], "2026-03-06T10:00:00Z")
            self.assertEqual(str(payload["generated_at"]), "2026-03-06T10:00:00Z")
            self.assertTrue(complete)

    def test_pointer_status_summary_counts_valid_and_broken(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_root = Path(tmpdir) / "runtime"
            runtime_root.mkdir(parents=True, exist_ok=True)
            valid_target = runtime_root / "run_state.json"
            valid_target.write_text("{}", encoding="utf-8")
            (runtime_root / ".last_state").write_text(str(valid_target), encoding="utf-8")
            (runtime_root / ".last_state.main").write_text("/missing/target.json\n", encoding="utf-8")
            (runtime_root / ".last_state.trees.feature-a").write_text("\n", encoding="utf-8")
            runtime = SimpleNamespace(runtime_root=runtime_root)

            summary = diagnostics.pointer_status_summary(runtime)

            self.assertEqual(summary, "valid=1 broken=2")

    def test_lock_health_summary_counts_stale_locks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_dir = Path(tmpdir) / "locks"
            lock_dir.mkdir(parents=True, exist_ok=True)
            stale_lock = lock_dir / "a.lock"
            fresh_lock = lock_dir / "b.lock"
            stale_lock.write_text("", encoding="utf-8")
            fresh_lock.write_text("", encoding="utf-8")

            class _Planner:
                def __init__(self, root: Path) -> None:
                    self.lock_dir = root

                @staticmethod
                def _lock_is_stale(path: Path) -> bool:  # noqa: SLF001
                    return path.name == "a.lock"

            runtime = SimpleNamespace(port_planner=_Planner(lock_dir))

            summary = diagnostics.lock_health_summary(runtime)

            self.assertEqual(summary, "total=2 stale=1")


if __name__ == "__main__":
    unittest.main()
