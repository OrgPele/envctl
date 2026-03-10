from __future__ import annotations

import tarfile
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.debug.debug_bundle import pack_debug_bundle


class DoctorDebugBundleIntegrationTests(unittest.TestCase):
    def test_pack_bundle_includes_doctor_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_scope = Path(tmpdir) / "runtime" / "python-engine" / "repo-123"
            debug_root = runtime_scope / "debug"
            session_id = "session-20240101010101-1234-acde"
            session_dir = debug_root / session_id
            session_dir.mkdir(parents=True, exist_ok=True)

            (session_dir / "events.debug.jsonl").write_text("{}\n", encoding="utf-8")
            (session_dir / "tty_context.json").write_text("{}", encoding="utf-8")
            (session_dir / "doctor.txt").write_text("doctor output", encoding="utf-8")

            (runtime_scope / "events.jsonl").write_text("{}\n", encoding="utf-8")
            (debug_root / "latest").write_text(session_id, encoding="utf-8")

            bundle_path = pack_debug_bundle(
                runtime_scope_dir=runtime_scope,
                session_id=None,
                run_id=None,
                scope_id="repo-123",
                output_dir=Path(tmpdir) / "out",
                strict=True,
                include_doctor=True,
                timeout=5.0,
            )

            with tarfile.open(bundle_path, "r:gz") as tar:
                names = tar.getnames()
                self.assertIn("doctor.txt", names)


if __name__ == "__main__":
    unittest.main()
