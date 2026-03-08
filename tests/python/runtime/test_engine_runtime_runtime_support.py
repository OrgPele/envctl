from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.runtime.engine_runtime_runtime_support import (  # noqa: E402
    conflict_count,
    lock_inventory,
    new_run_id,
    normalize_log_line,
)


class EngineRuntimeRuntimeSupportTests(unittest.TestCase):
    def test_lock_inventory_and_conflict_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_dir = Path(tmpdir)
            (lock_dir / "a.lock").write_text("", encoding="utf-8")
            (lock_dir / "b.lock").write_text("", encoding="utf-8")
            runtime = SimpleNamespace(
                port_planner=SimpleNamespace(lock_dir=lock_dir),
                env={"ENVCTL_TEST_CONFLICT_BACKEND": "3"},
            )

            self.assertEqual(lock_inventory(runtime), ["a.lock", "b.lock"])
            self.assertEqual(conflict_count(runtime, "BACKEND"), 3)

    def test_new_run_id_binds_id(self) -> None:
        bound: list[str] = []
        runtime = SimpleNamespace(_bind_debug_run_id=lambda run_id: bound.append(run_id))

        run_id = new_run_id(runtime)

        self.assertTrue(run_id.startswith("run-"))
        self.assertEqual(bound, [run_id])

    def test_normalize_log_line_strips_ansi_when_requested(self) -> None:
        line = "\x1b[31merror\x1b[0m"

        self.assertEqual(normalize_log_line(line, no_color=True), "error")
        self.assertEqual(normalize_log_line(line, no_color=False), line)


if __name__ == "__main__":
    unittest.main()
