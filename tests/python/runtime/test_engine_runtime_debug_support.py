from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.engine_runtime_debug_support import (  # noqa: E402
    debug_pack,
    debug_report,
    debug_doctor_snapshot_text,
    debug_last,
    latest_debug_scope_session,
    latest_scope_session_id,
    scope_latest_run_id,
)
from envctl_engine.test_output.parser_base import strip_ansi  # noqa: E402


class _TtyStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


class EngineRuntimeDebugSupportTests(unittest.TestCase):
    def test_debug_pack_is_available_without_shell_runtime_mode_checks(self) -> None:
        runtime = SimpleNamespace(
            env={},
            config=SimpleNamespace(runtime_scope_id="repo-1", runtime_dir=Path("/tmp/runtime")),
            runtime_root=Path("/tmp/runtime/python-engine/repo-1"),
            state_repository=SimpleNamespace(load_latest=lambda mode=None, strict_mode_match=False: None),
            _scope_latest_run_id=lambda scope_dir: None,
            _latest_scope_session_id=lambda scope_dir: None,
            _latest_debug_scope_session=lambda: None,
            _debug_doctor_snapshot_text=lambda: "doctor snapshot\n",
            _last_debug_bundle_path=None,
        )
        route = SimpleNamespace(flags={})

        with (
            redirect_stdout(io.StringIO()),
            patch(
                "envctl_engine.runtime.engine_runtime_debug_support.pack_debug_bundle",
                return_value=Path("/tmp/bundle.tar.gz"),
            ),
        ):
            code = debug_pack(runtime, route)

        self.assertEqual(code, 0)

    def test_scope_latest_run_id_reads_run_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scope_dir = Path(tmpdir)
            (scope_dir / "run_state.json").write_text(json.dumps({"run_id": "run-123"}), encoding="utf-8")

            run_id = scope_latest_run_id(scope_dir)

        self.assertEqual(run_id, "run-123")

    def test_debug_doctor_snapshot_text_falls_back_when_empty(self) -> None:
        runtime = SimpleNamespace(doctor_orchestrator=SimpleNamespace(execute=lambda: None))

        text = debug_doctor_snapshot_text(runtime)

        self.assertEqual(text, "doctor snapshot unavailable\n")

    def test_debug_last_prints_latest_bundle_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_root = Path(tmpdir)
            debug_dir = runtime_root / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            (debug_dir / "latest_bundle").write_text("/tmp/bundle.tar.gz", encoding="utf-8")
            runtime = SimpleNamespace(_last_debug_bundle_path=None, runtime_root=runtime_root)

            out = io.StringIO()
            with redirect_stdout(out):
                code = debug_last(runtime, route=None)

        self.assertEqual(code, 0)
        self.assertIn("/tmp/bundle.tar.gz", out.getvalue())

    def test_debug_pack_and_report_hyperlink_bundle_paths_when_enabled(self) -> None:
        runtime = SimpleNamespace(
            env={"ENVCTL_UI_HYPERLINK_MODE": "on"},
            config=SimpleNamespace(runtime_scope_id="repo-1", runtime_dir=Path("/tmp/runtime")),
            runtime_root=Path("/tmp/runtime/python-engine/repo-1"),
            state_repository=SimpleNamespace(load_latest=lambda mode=None, strict_mode_match=False: None),
            _scope_latest_run_id=lambda scope_dir: None,
            _latest_scope_session_id=lambda scope_dir: None,
            _latest_debug_scope_session=lambda: None,
            _debug_doctor_snapshot_text=lambda: "doctor snapshot\n",
            _last_debug_bundle_path=None,
            _debug_pack=lambda _route: 0,
        )
        route = SimpleNamespace(flags={})

        with patch(
            "envctl_engine.runtime.engine_runtime_debug_support.pack_debug_bundle",
            return_value=Path("/tmp/bundle.tar.gz"),
        ):
            out = _TtyStringIO()
            with redirect_stdout(out):
                code = debug_pack(runtime, route)
        self.assertEqual(code, 0)
        self.assertIn("\x1b]8;;file://", out.getvalue())
        self.assertIn("/tmp/bundle.tar.gz", strip_ansi(out.getvalue()))

        report_runtime = SimpleNamespace(
            env={"ENVCTL_UI_HYPERLINK_MODE": "on"},
            _debug_pack=lambda _route: 0,
            _last_debug_bundle_path="/tmp/bundle.tar.gz",
            runtime_root=Path("/tmp/runtime-root"),
        )
        report_out = _TtyStringIO()
        with (
            redirect_stdout(report_out),
            patch(
                "envctl_engine.debug.debug_bundle.summarize_debug_bundle",
                return_value={
                    "session_id": "session-1",
                    "events": 2,
                    "anomalies": 0,
                    "probable_root_causes": [],
                    "next_data_needed": [],
                },
            ),
        ):
            report_code = debug_report(report_runtime, route=None)

        self.assertEqual(report_code, 0)
        self.assertIn("\x1b]8;;file://", report_out.getvalue())
        self.assertIn("/tmp/bundle.tar.gz", strip_ansi(report_out.getvalue()))

    def test_latest_scope_session_id_prefers_latest_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scope_dir = Path(tmpdir)
            debug_dir = scope_dir / "debug"
            debug_dir.mkdir()
            (debug_dir / "session-old").mkdir()
            (debug_dir / "session-new").mkdir()
            (debug_dir / "latest").write_text("session-new", encoding="utf-8")

            session_id = latest_scope_session_id(scope_dir)

        self.assertEqual(session_id, "session-new")

    def test_latest_debug_scope_session_selects_newest_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir)
            root = runtime_dir / "python-engine"
            scope_a = root / "repo-a" / "debug" / "session-a"
            scope_b = root / "repo-b" / "debug" / "session-b"
            scope_a.mkdir(parents=True)
            scope_b.mkdir(parents=True)
            (scope_a.parent / "latest").write_text("session-a", encoding="utf-8")
            (scope_b.parent / "latest").write_text("session-b", encoding="utf-8")
            older = scope_a.stat().st_mtime - 10
            newer = scope_b.stat().st_mtime + 10
            import os

            os.utime(scope_a, (older, older))
            os.utime(scope_b, (newer, newer))
            runtime = SimpleNamespace(config=SimpleNamespace(runtime_dir=runtime_dir))

            selected = latest_debug_scope_session(runtime)

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected[0], "repo-b")
        self.assertEqual(selected[2], "session-b")

    def test_debug_report_prints_launch_policy_sections(self) -> None:
        runtime = SimpleNamespace(
            _debug_pack=lambda _route: 0,
            _last_debug_bundle_path="/tmp/bundle.tar.gz",
            runtime_root=Path("/tmp/runtime-root"),
        )

        out = io.StringIO()
        with (
            redirect_stdout(out),
            patch(
                "envctl_engine.debug.debug_bundle.summarize_debug_bundle",
                return_value={
                    "session_id": "session-1",
                    "events": 2,
                    "anomalies": 0,
                    "probable_root_causes": [],
                    "next_data_needed": [],
                    "launch_intent_counts": {"background_service": 2, "probe": 4},
                    "tracked_controller_input_owners": [
                        {"launch_intent": "interactive_child", "pid": 333, "stdin_policy": "inherit"}
                    ],
                    "launch_policy_violations": [
                        {
                            "launch_intent": "background_service",
                            "pid": 444,
                            "stdin_policy": "inherit",
                            "controller_input_owner_allowed": True,
                        }
                    ],
                },
            ),
        ):
            code = debug_report(runtime, route=None)

        self.assertEqual(code, 0)
        output = out.getvalue()
        self.assertIn("launch_intent_counts:", output)
        self.assertIn("tracked_controller_input_owners:", output)
        self.assertIn("launch_policy_violations:", output)


if __name__ == "__main__":
    unittest.main()
