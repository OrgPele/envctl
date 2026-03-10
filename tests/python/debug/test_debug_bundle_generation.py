from __future__ import annotations

import json
import tarfile
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.debug.debug_bundle import pack_debug_bundle, summarize_debug_bundle


class DebugBundleGenerationTests(unittest.TestCase):
    def test_pack_bundle_creates_redacted_runtime_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_scope = Path(tmpdir) / "runtime" / "python-engine" / "repo-123"
            debug_root = runtime_scope / "debug"
            session_id = "session-20240101010101-1234-acde"
            session_dir = debug_root / session_id
            session_dir.mkdir(parents=True, exist_ok=True)

            (session_dir / "events.debug.jsonl").write_text(
                json.dumps({"event": "ui.input.read.begin", "command_id": "cmd-1", "ts_mono_ns": 100})
                + "\n"
                + json.dumps({"event": "ui.input.dispatch.begin", "command_id": "cmd-1", "ts_mono_ns": 101})
                + "\n",
                encoding="utf-8",
            )
            (session_dir / "tty_context.json").write_text("{}", encoding="utf-8")
            (session_dir / "anomalies.jsonl").write_text("", encoding="utf-8")

            (runtime_scope / "events.jsonl").write_text(
                json.dumps({"event": "ui.input.submit", "command": "secret=abc"}) + "\n",
                encoding="utf-8",
            )

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
            summary = summarize_debug_bundle(bundle_path)
            self.assertEqual(summary.get("session_id"), session_id)

            self.assertTrue(bundle_path.is_file())
            with tarfile.open(bundle_path, "r:gz") as tar:
                names = tar.getnames()
                self.assertIn("events.runtime.redacted.jsonl", names)
                self.assertIn("timeline.jsonl", names)
                self.assertIn("diagnostics.json", names)
                self.assertIn("command_index.json", names)
                self.assertIn("bundle_contract.json", names)
                self.assertNotIn("events.runtime.jsonl", names)
                redacted_member = tar.extractfile("events.runtime.redacted.jsonl")
                assert redacted_member is not None
                redacted_line = redacted_member.read().decode("utf-8").strip()
                self.assertNotIn("secret=abc", redacted_line)

                diagnostics_member = tar.extractfile("diagnostics.json")
                assert diagnostics_member is not None
                diagnostics = json.loads(diagnostics_member.read().decode("utf-8"))
                self.assertIn("issues", diagnostics)

                command_index_member = tar.extractfile("command_index.json")
                assert command_index_member is not None
                command_index = json.loads(command_index_member.read().decode("utf-8"))
                self.assertIn("cmd-1", command_index)

    def test_diagnostics_ignore_input_phase_guard_and_non_fallback_tty_transition_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_scope = Path(tmpdir) / "runtime" / "python-engine" / "repo-guard"
            debug_root = runtime_scope / "debug"
            session_id = "session-20240101010101-4321-guard"
            session_dir = debug_root / session_id
            session_dir.mkdir(parents=True, exist_ok=True)

            (session_dir / "events.debug.jsonl").write_text(
                json.dumps({"event": "ui.spinner.disabled", "reason": "input_phase_guard"})
                + "\n"
                + json.dumps({"event": "ui.input.backend", "backend": "basic_input"})
                + "\n",
                encoding="utf-8",
            )
            (session_dir / "tty_context.json").write_text("{}", encoding="utf-8")
            (session_dir / "anomalies.jsonl").write_text("", encoding="utf-8")
            (runtime_scope / "events.jsonl").write_text("", encoding="utf-8")
            (debug_root / "latest").write_text(session_id, encoding="utf-8")

            bundle_path = pack_debug_bundle(
                runtime_scope_dir=runtime_scope,
                session_id=None,
                run_id=None,
                scope_id="repo-guard",
                output_dir=Path(tmpdir) / "out",
                strict=True,
                include_doctor=False,
                timeout=5.0,
            )

            with tarfile.open(bundle_path, "r:gz") as tar:
                diagnostics_member = tar.extractfile("diagnostics.json")
                assert diagnostics_member is not None
                diagnostics = json.loads(diagnostics_member.read().decode("utf-8"))

            probable = diagnostics.get("probable_root_causes", [])
            self.assertNotIn(
                "Spinner disabled by policy; inspect spinner_disabled_reasons for visibility root cause.",
                probable,
            )
            next_data_needed = diagnostics.get("next_data_needed", [])
            self.assertNotIn(
                "TTY transition events missing; verify terminal_session debug wiring.",
                next_data_needed,
            )

    def test_diagnostics_summarize_launch_intent_and_input_owner_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_scope = Path(tmpdir) / "runtime" / "python-engine" / "repo-launch"
            debug_root = runtime_scope / "debug"
            session_id = "session-20240101010101-5678-launch"
            session_dir = debug_root / session_id
            session_dir.mkdir(parents=True, exist_ok=True)

            (session_dir / "events.debug.jsonl").write_text("", encoding="utf-8")
            (session_dir / "tty_context.json").write_text("{}", encoding="utf-8")
            (session_dir / "anomalies.jsonl").write_text("", encoding="utf-8")
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
                        "pid": 4242,
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
            summary = summarize_debug_bundle(bundle_path)

            self.assertEqual(summary.get("launch_intent_counts"), {"background_service": 1, "interactive_child": 1})
            owners = summary.get("tracked_controller_input_owners", [])
            self.assertIsInstance(owners, list)
            self.assertEqual(len(owners), 1)
            self.assertEqual(owners[0]["launch_intent"], "interactive_child")
            self.assertEqual(summary.get("launch_policy_violations"), [])

    def test_diagnostics_report_background_launch_input_owner_violation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_scope = Path(tmpdir) / "runtime" / "python-engine" / "repo-launch-violation"
            debug_root = runtime_scope / "debug"
            session_id = "session-20240101010101-5678-launch-violation"
            session_dir = debug_root / session_id
            session_dir.mkdir(parents=True, exist_ok=True)

            (session_dir / "events.debug.jsonl").write_text("", encoding="utf-8")
            (session_dir / "tty_context.json").write_text("{}", encoding="utf-8")
            (session_dir / "anomalies.jsonl").write_text("", encoding="utf-8")
            (runtime_scope / "events.jsonl").write_text(
                json.dumps(
                    {
                        "event": "process.launch",
                        "launch_intent": "background_service",
                        "stdin_policy": "inherit",
                        "stdout_policy": "file",
                        "stderr_policy": "file",
                        "controller_input_owner_allowed": True,
                        "pid": 5150,
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
                scope_id="repo-launch-violation",
                output_dir=Path(tmpdir) / "out",
                strict=True,
                include_doctor=False,
                timeout=5.0,
            )

            with tarfile.open(bundle_path, "r:gz") as tar:
                diagnostics_member = tar.extractfile("diagnostics.json")
                assert diagnostics_member is not None
                diagnostics = json.loads(diagnostics_member.read().decode("utf-8"))

            issue_codes = {
                str(item.get("code", "")) for item in diagnostics.get("issues", []) if isinstance(item, dict)
            }
            self.assertIn("launch_policy_input_owner_violation", issue_codes)
            self.assertTrue(diagnostics.get("launch_policy_violations"))

    def test_diagnostics_report_selector_inactivity_without_spinner_noise(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_scope = Path(tmpdir) / "runtime" / "python-engine" / "repo-selector"
            debug_root = runtime_scope / "debug"
            session_id = "session-20240101010101-9876-selector"
            session_dir = debug_root / session_id
            session_dir.mkdir(parents=True, exist_ok=True)

            (session_dir / "events.debug.jsonl").write_text(
                json.dumps(
                    {
                        "event": "ui.selector.lifecycle",
                        "selector_id": "restart",
                        "prompt": "Restart",
                        "phase": "enter",
                        "ts_mono_ns": 1_000_000_000,
                    }
                )
                + "\n"
                + json.dumps({"event": "ui.screen.enter", "screen": "selector", "ts_mono_ns": 2_600_000_000})
                + "\n",
                encoding="utf-8",
            )
            (session_dir / "tty_context.json").write_text("{}", encoding="utf-8")
            (session_dir / "anomalies.jsonl").write_text("", encoding="utf-8")
            (runtime_scope / "events.jsonl").write_text("", encoding="utf-8")
            (debug_root / "latest").write_text(session_id, encoding="utf-8")

            bundle_path = pack_debug_bundle(
                runtime_scope_dir=runtime_scope,
                session_id=None,
                run_id=None,
                scope_id="repo-selector",
                output_dir=Path(tmpdir) / "out",
                strict=True,
                include_doctor=False,
                timeout=5.0,
            )

            with tarfile.open(bundle_path, "r:gz") as tar:
                diagnostics_member = tar.extractfile("diagnostics.json")
                assert diagnostics_member is not None
                diagnostics = json.loads(diagnostics_member.read().decode("utf-8"))

            issue_codes = {
                str(item.get("code", "")) for item in diagnostics.get("issues", []) if isinstance(item, dict)
            }
            self.assertIn("selector_input_inactive", issue_codes)
            probable = diagnostics.get("probable_root_causes", [])
            self.assertIn(
                "Selector entered but no key/mouse/focus events were observed; input/focus pipeline likely stalled.",
                probable,
            )
            self.assertNotIn(
                "Spinner disabled by policy; inspect spinner_disabled_reasons for visibility root cause.",
                probable,
            )

    def test_diagnostics_report_selector_low_throughput(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_scope = Path(tmpdir) / "runtime" / "python-engine" / "repo-selector-low"
            debug_root = runtime_scope / "debug"
            session_id = "session-20240101010101-1111-selector-low"
            session_dir = debug_root / session_id
            session_dir.mkdir(parents=True, exist_ok=True)

            (session_dir / "events.debug.jsonl").write_text(
                json.dumps(
                    {
                        "event": "ui.selector.lifecycle",
                        "selector_id": "test_targets",
                        "prompt": "Test targets",
                        "phase": "enter",
                        "ts_mono_ns": 1_000_000_000,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "ui.selector.key",
                        "selector_id": "test_targets",
                        "key": "down",
                        "ts_mono_ns": 1_200_000_000,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "ui.screen.enter",
                        "screen": "selector_prompt_toolkit_cursor",
                        "ts_mono_ns": 4_400_000_000,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (session_dir / "tty_context.json").write_text("{}", encoding="utf-8")
            (session_dir / "anomalies.jsonl").write_text("", encoding="utf-8")
            (runtime_scope / "events.jsonl").write_text("", encoding="utf-8")
            (debug_root / "latest").write_text(session_id, encoding="utf-8")

            bundle_path = pack_debug_bundle(
                runtime_scope_dir=runtime_scope,
                session_id=None,
                run_id=None,
                scope_id="repo-selector-low",
                output_dir=Path(tmpdir) / "out",
                strict=True,
                include_doctor=False,
                timeout=5.0,
            )

            with tarfile.open(bundle_path, "r:gz") as tar:
                diagnostics_member = tar.extractfile("diagnostics.json")
                assert diagnostics_member is not None
                diagnostics = json.loads(diagnostics_member.read().decode("utf-8"))

            issue_codes = {
                str(item.get("code", "")) for item in diagnostics.get("issues", []) if isinstance(item, dict)
            }
            self.assertIn("selector_input_low_throughput", issue_codes)
            probable = diagnostics.get("probable_root_causes", [])
            self.assertIn(
                "Selector key throughput is abnormally low for observed selector duration; investigate terminal input pipeline.",
                probable,
            )

    def test_diagnostics_count_selector_key_snapshot_towards_throughput(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_scope = Path(tmpdir) / "runtime" / "python-engine" / "repo-selector-snapshot"
            debug_root = runtime_scope / "debug"
            session_id = "session-20240101010101-1212-selector-snapshot"
            session_dir = debug_root / session_id
            session_dir.mkdir(parents=True, exist_ok=True)

            (session_dir / "events.debug.jsonl").write_text(
                json.dumps(
                    {
                        "event": "ui.selector.lifecycle",
                        "selector_id": "run_tests_for",
                        "prompt": "Run tests for",
                        "phase": "enter",
                        "ts_mono_ns": 1_000_000_000,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "ui.selector.focus",
                        "selector_id": "run_tests_for",
                        "reason": "mount",
                        "ts_mono_ns": 1_100_000_000,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "ui.selector.key.snapshot",
                        "selector_id": "run_tests_for",
                        "nav_event_counter": 5,
                        "handled_counts": {"down": 3, "up": 2},
                        "ts_mono_ns": 3_500_000_000,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "ui.screen.enter",
                        "screen": "selector",
                        "ts_mono_ns": 4_200_000_000,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (session_dir / "tty_context.json").write_text("{}", encoding="utf-8")
            (session_dir / "anomalies.jsonl").write_text("", encoding="utf-8")
            (runtime_scope / "events.jsonl").write_text("", encoding="utf-8")
            (debug_root / "latest").write_text(session_id, encoding="utf-8")

            bundle_path = pack_debug_bundle(
                runtime_scope_dir=runtime_scope,
                session_id=None,
                run_id=None,
                scope_id="repo-selector-snapshot",
                output_dir=Path(tmpdir) / "out",
                strict=True,
                include_doctor=False,
                timeout=5.0,
            )

            with tarfile.open(bundle_path, "r:gz") as tar:
                diagnostics_member = tar.extractfile("diagnostics.json")
                assert diagnostics_member is not None
                diagnostics = json.loads(diagnostics_member.read().decode("utf-8"))

            issue_codes = {
                str(item.get("code", "")) for item in diagnostics.get("issues", []) if isinstance(item, dict)
            }
            self.assertNotIn("selector_input_low_throughput", issue_codes)

    def test_diagnostics_skip_read_pipeline_gap_when_driver_has_non_key_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_scope = Path(tmpdir) / "runtime" / "python-engine" / "repo-selector-read-gap"
            debug_root = runtime_scope / "debug"
            session_id = "session-20240101010101-1313-selector-read-gap"
            session_dir = debug_root / session_id
            session_dir.mkdir(parents=True, exist_ok=True)

            (session_dir / "events.debug.jsonl").write_text(
                json.dumps(
                    {
                        "event": "ui.selector.lifecycle",
                        "selector_id": "run_tests_for",
                        "prompt": "Run tests for",
                        "phase": "enter",
                        "ts_mono_ns": 1_000_000_000,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "ui.selector.focus",
                        "selector_id": "run_tests_for",
                        "reason": "mount",
                        "ts_mono_ns": 1_100_000_000,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "ui.selector.key.snapshot",
                        "selector_id": "run_tests_for",
                        "nav_event_counter": 4,
                        "handled_counts": {"down": 4},
                        "ts_mono_ns": 1_200_000_000,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "ui.selector.key.driver.snapshot",
                        "selector_id": "run_tests_for",
                        "read_bytes": 120,
                        "escape_bytes": 40,
                        "key_events_total": 4,
                        "key_events_by_name": {"down": 4},
                        "non_key_messages": {"MouseMove": 50},
                        "ts_mono_ns": 1_300_000_000,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "ui.screen.enter",
                        "screen": "selector",
                        "ts_mono_ns": 4_100_000_000,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (session_dir / "tty_context.json").write_text("{}", encoding="utf-8")
            (session_dir / "anomalies.jsonl").write_text("", encoding="utf-8")
            (runtime_scope / "events.jsonl").write_text("", encoding="utf-8")
            (debug_root / "latest").write_text(session_id, encoding="utf-8")

            bundle_path = pack_debug_bundle(
                runtime_scope_dir=runtime_scope,
                session_id=None,
                run_id=None,
                scope_id="repo-selector-read-gap",
                output_dir=Path(tmpdir) / "out",
                strict=True,
                include_doctor=False,
                timeout=5.0,
            )

            with tarfile.open(bundle_path, "r:gz") as tar:
                diagnostics_member = tar.extractfile("diagnostics.json")
                assert diagnostics_member is not None
                diagnostics = json.loads(diagnostics_member.read().decode("utf-8"))

            issue_codes = {
                str(item.get("code", "")) for item in diagnostics.get("issues", []) if isinstance(item, dict)
            }
            self.assertNotIn("selector_read_pipeline_gap", issue_codes)
            self.assertEqual(diagnostics.get("selector_read_pipeline_gaps"), [])

    def test_diagnostics_report_selector_idle_after_activity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_scope = Path(tmpdir) / "runtime" / "python-engine" / "repo-selector-idle"
            debug_root = runtime_scope / "debug"
            session_id = "session-20240101010101-2222-selector-idle"
            session_dir = debug_root / session_id
            session_dir.mkdir(parents=True, exist_ok=True)

            (session_dir / "events.debug.jsonl").write_text(
                json.dumps(
                    {
                        "event": "ui.selector.lifecycle",
                        "selector_id": "run_tests_for",
                        "prompt": "Run tests for",
                        "phase": "enter",
                        "ts_mono_ns": 1_000_000_000,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "ui.selector.key.idle_after_activity",
                        "selector_id": "run_tests_for",
                        "idle_ms": 8200,
                        "nav_event_counter": 5,
                        "focused_widget_id": "selector-list",
                        "ts_mono_ns": 9_200_000_000,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (session_dir / "tty_context.json").write_text("{}", encoding="utf-8")
            (session_dir / "anomalies.jsonl").write_text("", encoding="utf-8")
            (runtime_scope / "events.jsonl").write_text("", encoding="utf-8")
            (debug_root / "latest").write_text(session_id, encoding="utf-8")

            bundle_path = pack_debug_bundle(
                runtime_scope_dir=runtime_scope,
                session_id=None,
                run_id=None,
                scope_id="repo-selector-idle",
                output_dir=Path(tmpdir) / "out",
                strict=True,
                include_doctor=False,
                timeout=5.0,
            )

            with tarfile.open(bundle_path, "r:gz") as tar:
                diagnostics_member = tar.extractfile("diagnostics.json")
                assert diagnostics_member is not None
                diagnostics = json.loads(diagnostics_member.read().decode("utf-8"))

            issue_codes = {
                str(item.get("code", "")) for item in diagnostics.get("issues", []) if isinstance(item, dict)
            }
            self.assertIn("selector_input_stalled_after_activity", issue_codes)
            probable = diagnostics.get("probable_root_causes", [])
            self.assertIn(
                "Selector accepted initial navigation keys but then went idle; inspect selector key driver snapshots and focus events.",
                probable,
            )
            idle_windows = diagnostics.get("selector_idle_after_activity", [])
            self.assertTrue(isinstance(idle_windows, list) and idle_windows)

    def test_diagnostics_report_state_change_and_spinner_activity_anomalies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_scope = Path(tmpdir) / "runtime" / "python-engine" / "repo-state-spinner"
            debug_root = runtime_scope / "debug"
            session_id = "session-20240101010101-3333-state-spinner"
            session_dir = debug_root / session_id
            session_dir.mkdir(parents=True, exist_ok=True)

            (session_dir / "events.debug.jsonl").write_text(
                json.dumps(
                    {
                        "event": "ui.anomaly.spinner_without_command_activity",
                        "severity": "medium",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (session_dir / "tty_context.json").write_text("{}", encoding="utf-8")
            (session_dir / "anomalies.jsonl").write_text(
                json.dumps(
                    {
                        "event": "ui.anomaly.state_changed_without_lifecycle_event",
                        "severity": "high",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (runtime_scope / "events.jsonl").write_text("", encoding="utf-8")
            (debug_root / "latest").write_text(session_id, encoding="utf-8")

            bundle_path = pack_debug_bundle(
                runtime_scope_dir=runtime_scope,
                session_id=None,
                run_id=None,
                scope_id="repo-state-spinner",
                output_dir=Path(tmpdir) / "out",
                strict=True,
                include_doctor=False,
                timeout=5.0,
            )

            with tarfile.open(bundle_path, "r:gz") as tar:
                diagnostics_member = tar.extractfile("diagnostics.json")
                assert diagnostics_member is not None
                diagnostics = json.loads(diagnostics_member.read().decode("utf-8"))

            issue_codes = {
                str(item.get("code", "")) for item in diagnostics.get("issues", []) if isinstance(item, dict)
            }
            self.assertIn("state_changed_without_lifecycle_event", issue_codes)
            self.assertIn("spinner_without_command_activity", issue_codes)
            probable = diagnostics.get("probable_root_causes", [])
            self.assertIn(
                "Run state fingerprint changed without a matching lifecycle event; inspect service truth reconciliation transitions.",
                probable,
            )
            self.assertIn(
                "Spinner policy was enabled for command dispatch but no spinner-starting activity events were observed.",
                probable,
            )
            anomaly_event_names = diagnostics.get("anomaly_event_names", [])
            self.assertIn("ui.anomaly.state_changed_without_lifecycle_event", anomaly_event_names)

    def test_diagnostics_include_startup_latency_breakdown_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_scope = Path(tmpdir) / "runtime" / "python-engine" / "repo-startup-latency"
            debug_root = runtime_scope / "debug"
            session_id = "session-20240101010101-4444-startup-latency"
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
                        "event": "state.auto_resume.skipped",
                        "reason": "project_selection_mismatch",
                        "ts_mono_ns": 1_100_000_000,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "requirements.timing.component",
                        "project": "Main",
                        "requirement": "postgres",
                        "duration_ms": 80000.0,
                        "success": True,
                        "ts_mono_ns": 2_000_000_000,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "requirements.timing.summary",
                        "project": "Main",
                        "duration_ms": 90000.0,
                        "failures": 0,
                        "ts_mono_ns": 2_100_000_000,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "service.timing.component",
                        "project": "Main",
                        "component": "start_project_with_attach",
                        "duration_ms": 5000.0,
                        "ts_mono_ns": 2_200_000_000,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "service.timing.summary",
                        "project": "Main",
                        "duration_ms": 6000.0,
                        "ts_mono_ns": 2_300_000_000,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "requirements.adapter",
                        "project": "Main",
                        "service": "postgres",
                        "stage_durations_ms": {"discover": 1000.0, "probe": 70000.0, "listener_wait": 15000.0},
                        "ts_mono_ns": 2_350_000_000,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "requirements.adapter.command_timing",
                        "project": "Main",
                        "service": "postgres",
                        "stage": "probe",
                        "duration_ms": 25000.0,
                        "returncode": 0,
                        "ts_mono_ns": 2_360_000_000,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (session_dir / "tty_context.json").write_text("{}", encoding="utf-8")
            (session_dir / "anomalies.jsonl").write_text("", encoding="utf-8")
            (runtime_scope / "events.jsonl").write_text("", encoding="utf-8")
            (debug_root / "latest").write_text(session_id, encoding="utf-8")

            bundle_path = pack_debug_bundle(
                runtime_scope_dir=runtime_scope,
                session_id=None,
                run_id=None,
                scope_id="repo-startup-latency",
                output_dir=Path(tmpdir) / "out",
                strict=True,
                include_doctor=False,
                timeout=5.0,
            )

            with tarfile.open(bundle_path, "r:gz") as tar:
                diagnostics_member = tar.extractfile("diagnostics.json")
                assert diagnostics_member is not None
                diagnostics = json.loads(diagnostics_member.read().decode("utf-8"))

            startup_breakdown = diagnostics.get("startup_breakdown", {})
            self.assertIsInstance(startup_breakdown, dict)
            self.assertEqual(startup_breakdown.get("execution_mode"), "sequential")
            self.assertGreater(float(startup_breakdown.get("requirements_total_ms", 0.0)), 80000.0)

            slowest_components = diagnostics.get("slowest_components", [])
            self.assertIsInstance(slowest_components, list)
            self.assertTrue(
                any(str(item.get("kind", "")) == "requirement" for item in slowest_components if isinstance(item, dict))
            )

            skip_reasons = diagnostics.get("resume_skip_reasons", {})
            self.assertIsInstance(skip_reasons, dict)
            self.assertIn("project_selection_mismatch", skip_reasons)

            hotspots = diagnostics.get("requirements_stage_hotspots", [])
            self.assertIsInstance(hotspots, list)
            self.assertTrue(any(str(item.get("stage", "")) == "probe" for item in hotspots if isinstance(item, dict)))

            summary = summarize_debug_bundle(bundle_path)
            self.assertIn("startup_breakdown", summary)
            self.assertIn("slowest_components", summary)
            self.assertIn("resume_skip_reasons", summary)
            self.assertIn("requirements_stage_hotspots", summary)

    def test_startup_latency_sections_use_session_debug_events_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_scope = Path(tmpdir) / "runtime" / "python-engine" / "repo-startup-scope"
            debug_root = runtime_scope / "debug"
            session_id = "session-20240101010101-7777-startup-scope"
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
                        "event": "requirements.timing.summary",
                        "project": "Main",
                        "duration_ms": 1200.0,
                        "ts_mono_ns": 2_000_000_000,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "service.timing.summary",
                        "project": "Main",
                        "duration_ms": 300.0,
                        "ts_mono_ns": 2_100_000_000,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (session_dir / "tty_context.json").write_text("{}", encoding="utf-8")
            (session_dir / "anomalies.jsonl").write_text("", encoding="utf-8")
            # Runtime event history intentionally contains huge startup timings from unrelated sessions.
            (runtime_scope / "events.jsonl").write_text(
                json.dumps(
                    {
                        "event": "requirements.timing.summary",
                        "project": "Other",
                        "duration_ms": 999999.0,
                        "ts_mono_ns": 9_000_000_000,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "service.timing.summary",
                        "project": "Other",
                        "duration_ms": 888888.0,
                        "ts_mono_ns": 9_100_000_000,
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
                scope_id="repo-startup-scope",
                output_dir=Path(tmpdir) / "out",
                strict=True,
                include_doctor=False,
                timeout=5.0,
            )

            with tarfile.open(bundle_path, "r:gz") as tar:
                diagnostics_member = tar.extractfile("diagnostics.json")
                assert diagnostics_member is not None
                diagnostics = json.loads(diagnostics_member.read().decode("utf-8"))

            startup_breakdown = diagnostics.get("startup_breakdown", {})
            self.assertIsInstance(startup_breakdown, dict)
            self.assertAlmostEqual(float(startup_breakdown.get("requirements_total_ms", 0.0)), 1200.0, places=2)
            self.assertAlmostEqual(float(startup_breakdown.get("service_total_ms", 0.0)), 300.0, places=2)


if __name__ == "__main__":
    unittest.main()
