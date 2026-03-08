from __future__ import annotations

import io
import json
import os
import tarfile
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.runtime.command_router import parse_route
from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.state.models import RunState


class DebugPackRouteBehaviorTests(unittest.TestCase):
    def _runtime(self) -> PythonEngineRuntime:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
            }
        )
        return PythonEngineRuntime(config, env={})

    @staticmethod
    def _create_session(debug_root: Path, *, session_id: str, run_id: str | None) -> None:
        session_dir = debug_root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "session.json").write_text(
            json.dumps({"session_id": session_id, "run_id": run_id}),
            encoding="utf-8",
        )
        (session_dir / "events.debug.jsonl").write_text("", encoding="utf-8")
        (session_dir / "tty_context.json").write_text("{}", encoding="utf-8")
        (session_dir / "anomalies.jsonl").write_text("", encoding="utf-8")
        (session_dir / "tty_state_transitions.jsonl").write_text("", encoding="utf-8")

    def test_debug_pack_defaults_to_latest_run_session(self) -> None:
        runtime = self._runtime()
        debug_root = runtime.runtime_root / "debug"
        debug_root.mkdir(parents=True, exist_ok=True)

        stale_session = "session-20260101010101-1111-aaaa"
        current_session = "session-20260101010202-2222-bbbb"
        self._create_session(debug_root, session_id=stale_session, run_id="run-stale")
        self._create_session(debug_root, session_id=current_session, run_id="run-current")
        (debug_root / "latest").write_text(stale_session, encoding="utf-8")

        runtime.state_repository.load_latest = lambda mode=None, strict_mode_match=False: RunState(  # type: ignore[assignment]
            run_id="run-current",
            mode="main",
        )

        output = io.StringIO()
        with redirect_stdout(output):
            code = runtime.dispatch(parse_route(["--debug-pack"], env={}))

        self.assertEqual(code, 0)
        self.assertIn(current_session, output.getvalue())
        self.assertNotIn(stale_session, output.getvalue())

    def test_debug_pack_fails_when_latest_run_has_no_debug_session(self) -> None:
        runtime = self._runtime()
        debug_root = runtime.runtime_root / "debug"
        debug_root.mkdir(parents=True, exist_ok=True)

        stale_session = "session-20260101010101-1111-aaaa"
        self._create_session(debug_root, session_id=stale_session, run_id="run-stale")
        (debug_root / "latest").write_text(stale_session, encoding="utf-8")

        runtime.state_repository.load_latest = lambda mode=None, strict_mode_match=False: RunState(  # type: ignore[assignment]
            run_id="run-current",
            mode="main",
        )

        output = io.StringIO()
        with redirect_stdout(output):
            code = runtime.dispatch(parse_route(["--debug-pack"], env={}))

        self.assertEqual(code, 1)
        self.assertIn("run-current", output.getvalue())

    def test_debug_pack_include_doctor_writes_doctor_when_missing_in_session(self) -> None:
        runtime = self._runtime()
        debug_root = runtime.runtime_root / "debug"
        debug_root.mkdir(parents=True, exist_ok=True)

        session = "session-20260101010202-2222-bbbb"
        self._create_session(debug_root, session_id=session, run_id="run-current")
        (debug_root / "latest").write_text(session, encoding="utf-8")

        runtime.state_repository.load_latest = lambda mode=None, strict_mode_match=False: RunState(  # type: ignore[assignment]
            run_id="run-current",
            mode="main",
        )

        output = io.StringIO()
        with redirect_stdout(output):
            code = runtime.dispatch(parse_route(["--debug-pack", "--debug-ui-include-doctor"], env={}))

        self.assertEqual(code, 0)
        bundle_path = Path(output.getvalue().strip())
        self.assertTrue(bundle_path.is_file())
        with tarfile.open(bundle_path, "r:gz") as tar:
            names = tar.getnames()
            self.assertIn("doctor.txt", names)
            member = tar.extractfile("doctor.txt")
            assert member is not None
            doctor_text = member.read().decode("utf-8")
        self.assertTrue("parity_status:" in doctor_text or "doctor snapshot unavailable" in doctor_text)

    def test_debug_pack_run_id_uses_latest_matching_session(self) -> None:
        runtime = self._runtime()
        debug_root = runtime.runtime_root / "debug"
        debug_root.mkdir(parents=True, exist_ok=True)

        older = "session-20260101010101-1111-aaaa"
        newer = "session-20260101010102-2222-bbbb"
        self._create_session(debug_root, session_id=older, run_id="run-current")
        self._create_session(debug_root, session_id=newer, run_id="run-current")
        now = time.time()
        os.utime(debug_root / older, (now - 5.0, now - 5.0))
        os.utime(debug_root / newer, (now - 1.0, now - 1.0))

        output = io.StringIO()
        with redirect_stdout(output):
            code = runtime.dispatch(parse_route(["--debug-pack", "--run-id", "run-current"], env={}))

        self.assertEqual(code, 0)
        self.assertIn(newer, output.getvalue())
        self.assertNotIn(older, output.getvalue())

    def test_debug_pack_falls_back_to_latest_scope_session_when_current_scope_empty(self) -> None:
        runtime = self._runtime()
        shared_root = runtime.config.runtime_dir / "python-engine"
        other_scope = shared_root / "repo-other"
        other_debug = other_scope / "debug"
        other_debug.mkdir(parents=True, exist_ok=True)
        session = "session-20260101010202-2222-bbbb"
        self._create_session(other_debug, session_id=session, run_id=None)
        (other_debug / "latest").write_text(session, encoding="utf-8")

        # Ensure current scope has no debug sessions/pointers.
        current_debug = runtime.runtime_root / "debug"
        current_debug.mkdir(parents=True, exist_ok=True)
        latest = current_debug / "latest"
        if latest.exists():
            latest.unlink()

        output = io.StringIO()
        with redirect_stdout(output):
            code = runtime.dispatch(parse_route(["--debug-pack"], env={}))

        self.assertEqual(code, 0)
        self.assertIn(runtime.config.runtime_scope_id, output.getvalue())
        self.assertNotIn("repo-other", output.getvalue())

    def test_debug_pack_falls_back_when_local_latest_pointer_is_stale(self) -> None:
        runtime = self._runtime()
        shared_root = runtime.config.runtime_dir / "python-engine"
        other_scope = shared_root / "repo-other"
        other_debug = other_scope / "debug"
        other_debug.mkdir(parents=True, exist_ok=True)
        session = "session-20260101010202-2222-bbbb"
        self._create_session(other_debug, session_id=session, run_id=None)
        (other_debug / "latest").write_text(session, encoding="utf-8")

        local_debug = runtime.runtime_root / "debug"
        local_debug.mkdir(parents=True, exist_ok=True)
        (local_debug / "latest").write_text("session-stale-pointer", encoding="utf-8")

        output = io.StringIO()
        with redirect_stdout(output):
            code = runtime.dispatch(parse_route(["--debug-pack"], env={}))

        self.assertEqual(code, 0)
        self.assertIn(runtime.config.runtime_scope_id, output.getvalue())
        self.assertNotIn("repo-other", output.getvalue())

    def test_debug_report_prints_session_id(self) -> None:
        runtime = self._runtime()
        debug_root = runtime.runtime_root / "debug"
        debug_root.mkdir(parents=True, exist_ok=True)
        session = "session-20260101010202-2222-bbbb"
        self._create_session(debug_root, session_id=session, run_id="run-current")
        (debug_root / "latest").write_text(session, encoding="utf-8")

        output = io.StringIO()
        with redirect_stdout(output):
            code = runtime.dispatch(parse_route(["--debug-report", "--session-id", session], env={}))

        self.assertEqual(code, 0)
        self.assertIn(f"session_id: {session}", output.getvalue())


if __name__ == "__main__":
    unittest.main()
