from __future__ import annotations

import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.debug.debug_bundle import pack_debug_bundle


class DebugBundleAnalyzerTests(unittest.TestCase):
    def test_analyzer_reports_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_scope = Path(tmpdir) / "runtime" / "python-engine" / "repo-123"
            debug_root = runtime_scope / "debug"
            session_id = "session-20240101010101-1234-acde"
            session_dir = debug_root / session_id
            session_dir.mkdir(parents=True, exist_ok=True)

            (session_dir / "events.debug.jsonl").write_text(
                json.dumps({"event": "ui.input.read.begin"}) + "\n",
                encoding="utf-8",
            )
            (session_dir / "tty_context.json").write_text("{}", encoding="utf-8")
            (runtime_scope / "events.jsonl").write_text("{}\n", encoding="utf-8")
            (debug_root / "latest").write_text(session_id, encoding="utf-8")

            bundle_path = pack_debug_bundle(
                runtime_scope_dir=runtime_scope,
                session_id=None,
                run_id=None,
                scope_id="repo-123",
                output_dir=Path(tmpdir) / "out",
                strict=True,
                include_doctor=False,
                timeout=5.0,
            )

            script = REPO_ROOT / "scripts" / "analyze_debug_bundle.py"
            result = subprocess.run(
                [sys.executable, str(script), str(bundle_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("events.debug.jsonl", result.stdout)

    def test_analyzer_surfaces_spinner_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_scope = Path(tmpdir) / "runtime" / "python-engine" / "repo-456"
            debug_root = runtime_scope / "debug"
            session_id = "session-20240101010101-1234-abcd"
            session_dir = debug_root / session_id
            session_dir.mkdir(parents=True, exist_ok=True)

            (session_dir / "events.debug.jsonl").write_text(
                json.dumps({"event": "ui.spinner.policy", "enabled": False, "reason": "non_tty"})
                + "\n"
                + json.dumps({"event": "ui.input.read.begin"})
                + "\n",
                encoding="utf-8",
            )
            (session_dir / "tty_context.json").write_text("{}", encoding="utf-8")
            (runtime_scope / "events.jsonl").write_text("{}\n", encoding="utf-8")
            (debug_root / "latest").write_text(session_id, encoding="utf-8")

            bundle_path = pack_debug_bundle(
                runtime_scope_dir=runtime_scope,
                session_id=None,
                run_id=None,
                scope_id="repo-456",
                output_dir=Path(tmpdir) / "out",
                strict=True,
                include_doctor=False,
                timeout=5.0,
            )

            script = REPO_ROOT / "scripts" / "analyze_debug_bundle.py"
            result = subprocess.run(
                [sys.executable, str(script), str(bundle_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("spinner_disabled_reasons", result.stdout)
            self.assertIn("non_tty", result.stdout)

    def test_bundle_diagnostics_detect_spinner_lifecycle_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_scope = Path(tmpdir) / "runtime" / "python-engine" / "repo-789"
            debug_root = runtime_scope / "debug"
            session_id = "session-20240101010101-1234-fail"
            session_dir = debug_root / session_id
            session_dir.mkdir(parents=True, exist_ok=True)

            (session_dir / "events.debug.jsonl").write_text(
                json.dumps({"event": "ui.spinner.lifecycle", "state": "start"})
                + "\n"
                + json.dumps({"event": "ui.spinner.lifecycle", "state": "fail"})
                + "\n",
                encoding="utf-8",
            )
            (session_dir / "tty_context.json").write_text("{}", encoding="utf-8")
            (runtime_scope / "events.jsonl").write_text("{}\n", encoding="utf-8")
            (debug_root / "latest").write_text(session_id, encoding="utf-8")

            bundle_path = pack_debug_bundle(
                runtime_scope_dir=runtime_scope,
                session_id=None,
                run_id=None,
                scope_id="repo-789",
                output_dir=Path(tmpdir) / "out",
                strict=True,
                include_doctor=False,
                timeout=5.0,
            )

            with tarfile.open(bundle_path, "r:gz") as archive:
                diagnostics = json.loads(
                    archive.extractfile("diagnostics.json").read().decode("utf-8")  # type: ignore[union-attr]
                )

            issue_codes = {item.get("code") for item in diagnostics.get("issues", [])}
            self.assertIn("spinner_fail", issue_codes)

    def test_analyzer_prints_launch_policy_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_scope = Path(tmpdir) / "runtime" / "python-engine" / "repo-launch"
            debug_root = runtime_scope / "debug"
            session_id = "session-20240101010101-1234-launch"
            session_dir = debug_root / session_id
            session_dir.mkdir(parents=True, exist_ok=True)

            (session_dir / "events.debug.jsonl").write_text("", encoding="utf-8")
            (session_dir / "tty_context.json").write_text("{}", encoding="utf-8")
            (runtime_scope / "events.jsonl").write_text(
                json.dumps(
                    {
                        "event": "process.launch",
                        "launch_intent": "background_service",
                        "stdin_policy": "devnull",
                        "stdout_policy": "file",
                        "stderr_policy": "file",
                        "controller_input_owner_allowed": False,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "process.launch",
                        "launch_intent": "interactive_child",
                        "stdin_policy": "inherit",
                        "stdout_policy": "inherit",
                        "stderr_policy": "inherit",
                        "controller_input_owner_allowed": True,
                        "pid": 4444,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (debug_root / "latest").write_text(session_id, encoding="utf-8")

            bundle_path = pack_debug_bundle(
                runtime_scope_dir=runtime_scope,
                session_id=None,
                run_id=None,
                scope_id="repo-launch",
                output_dir=Path(tmpdir) / "out",
                strict=True,
                include_doctor=False,
                timeout=5.0,
            )

            script = REPO_ROOT / "scripts" / "analyze_debug_bundle.py"
            result = subprocess.run(
                [sys.executable, str(script), str(bundle_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("launch_intent_counts", result.stdout)
            self.assertIn("tracked_controller_input_owners", result.stdout)

    def test_analyzer_prints_startup_latency_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_scope = Path(tmpdir) / "runtime" / "python-engine" / "repo-startup"
            debug_root = runtime_scope / "debug"
            session_id = "session-20240101010101-1234-startup"
            session_dir = debug_root / session_id
            session_dir.mkdir(parents=True, exist_ok=True)

            (session_dir / "events.debug.jsonl").write_text(
                json.dumps(
                    {
                        "event": "startup.execution",
                        "mode": "sequential",
                        "workers": 1,
                        "projects": ["Main"],
                        "ts_mono_ns": 1_000_000_000,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "startup.phase",
                        "phase": "project_selection",
                        "duration_ms": 120.0,
                        "status": "ok",
                        "ts_mono_ns": 1_100_000_000,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "requirements.timing.summary",
                        "project": "Main",
                        "duration_ms": 90000.0,
                        "ts_mono_ns": 2_000_000_000,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "service.timing.summary",
                        "project": "Main",
                        "duration_ms": 5000.0,
                        "ts_mono_ns": 2_100_000_000,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "service.bootstrap.phase",
                        "project": "Main",
                        "component": "backend",
                        "phase": "dependency_install",
                        "duration_ms": 2500.0,
                        "ts_mono_ns": 2_020_000_000,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "service.attach.phase",
                        "project": "Main",
                        "component": "backend",
                        "phase": "process_launch",
                        "duration_ms": 1800.0,
                        "ts_mono_ns": 2_030_000_000,
                    }
                )
                + "\n"
                + json.dumps({"event": "artifacts.write", "duration_ms": 350.0, "ts_mono_ns": 2_120_000_000})
                + "\n"
                + json.dumps(
                    {
                        "event": "requirements.adapter",
                        "project": "Main",
                        "service": "postgres",
                        "stage_durations_ms": {"probe": 70000.0},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (session_dir / "tty_context.json").write_text("{}", encoding="utf-8")
            (runtime_scope / "events.jsonl").write_text("{}\n", encoding="utf-8")
            (debug_root / "latest").write_text(session_id, encoding="utf-8")

            bundle_path = pack_debug_bundle(
                runtime_scope_dir=runtime_scope,
                session_id=None,
                run_id=None,
                scope_id="repo-startup",
                output_dir=Path(tmpdir) / "out",
                strict=True,
                include_doctor=False,
                timeout=5.0,
            )

            script = REPO_ROOT / "scripts" / "analyze_debug_bundle.py"
            result = subprocess.run(
                [sys.executable, str(script), str(bundle_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("startup_breakdown", result.stdout)
            self.assertIn("slowest_components", result.stdout)
            self.assertIn("requirements_stage_hotspots", result.stdout)
            self.assertIn("phase_breakdown", result.stdout)
            self.assertIn("project_selection", result.stdout)
            self.assertIn("service_bootstrap_hotspots", result.stdout)
            self.assertIn("service_attach_hotspots", result.stdout)


if __name__ == "__main__":
    unittest.main()
