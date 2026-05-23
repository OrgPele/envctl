# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.runtime.engine_runtime_command_parity_test_support import *


class EngineRuntimeCommandParityDoctorTests(EngineRuntimeCommandParityTestCase):
    def test_doctor_reports_parity_and_recent_failures(self) -> None:
        runtime = self._runtime()
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--doctor"], env={}))

        self.assertEqual(code, 0)
        self.assertTrue((runtime.runtime_root / "runtime_readiness_report.json").is_file())
        output = buffer.getvalue()
        self.assertIn("parity_status:", output)
        self.assertNotIn("partial_commands:", output)
        self.assertIn("recent_failures:", output)
        self.assertIn("readiness.command_parity:", output)
        self.assertIn("readiness.runtime_truth:", output)
        self.assertIn("readiness.lifecycle:", output)
        self.assertIn("readiness.shipability:", output)
        self.assertIn("parity_manifest_sha256:", output)
        self.assertIn("state_compat_mode:", output)
        self.assertIn("lock_health:", output)
        self.assertIn("pointer_status:", output)
        self.assertIn("synthetic_state_detected:", output)
        self.assertIn("runtime_readiness_status:", output)
        self.assertIn("runtime_gap_report_path:", output)
        self.assertIn("runtime_feature_matrix_path:", output)
        self.assertIn("runtime_gap_blocking_count:", output)
        events_path = runtime.runtime_root / "events.jsonl"
        self.assertTrue(events_path.is_file())
        legacy_events_path = runtime.runtime_legacy_root / "events.jsonl"
        self.assertTrue(legacy_events_path.is_file())
        event_names = {
            str(json.loads(line).get("event", ""))
            for line in events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        self.assertIn("cutover.gate.evaluate", event_names)

    def test_show_config_show_state_and_doctor_hyperlink_path_fields_when_enabled(self) -> None:
        runtime = self._runtime()
        runtime.env["ENVCTL_UI_HYPERLINK_MODE"] = "on"
        state = RunState(run_id="run-1", mode="main")
        runtime.state_repository.save_resume_state(
            state=state,
            emit=runtime._emit,
            runtime_map_builder=engine_runtime_module.build_runtime_map,
        )

        show_config_out = _TtyStringIO()
        with redirect_stdout(show_config_out):
            show_config_code = runtime.dispatch(parse_route(["show-config"], env={}))
        self.assertEqual(show_config_code, 0)
        self.assertIn("\x1b]8;;file://", show_config_out.getvalue())
        self.assertIn("config_file:", strip_ansi(show_config_out.getvalue()))

        show_state_out = _TtyStringIO()
        with redirect_stdout(show_state_out):
            show_state_code = runtime.dispatch(parse_route(["show-state"], env={}))
        self.assertEqual(show_state_code, 0)
        self.assertIn("\x1b]8;;file://", show_state_out.getvalue())
        self.assertIn("run_state_path:", strip_ansi(show_state_out.getvalue()))

        doctor_out = _TtyStringIO()
        with redirect_stdout(doctor_out):
            doctor_code = runtime.dispatch(parse_route(["--doctor"], env={}))
        self.assertEqual(doctor_code, 0)
        self.assertIn("\x1b]8;;file://", doctor_out.getvalue())
        self.assertIn("runtime_gap_report_path:", strip_ansi(doctor_out.getvalue()))
        self.assertIn("runtime_feature_matrix_path:", strip_ansi(doctor_out.getvalue()))

    def test_doctor_supports_json_output(self) -> None:
        runtime = self._runtime()
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--doctor", "--json"], env={}))

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertIn("runtime_root", payload)
        self.assertIn("state_file", payload)
        self.assertIn("parity_status", payload)
        self.assertIn("recent_failures", payload)

    def test_doctor_output_reports_synthetic_state_detection_true(self) -> None:
        runtime = self._runtime()
        runtime._parity_manifest_is_complete = lambda: True  # type: ignore[assignment]
        synthetic_state = RunState(
            run_id="run-synthetic",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd="/tmp/backend",
                    pid=1234,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                    synthetic=True,
                )
            },
        )
        runtime._try_load_existing_state = lambda mode=None: synthetic_state  # type: ignore[assignment]
        runtime._reconcile_state_truth = lambda _state: []  # type: ignore[assignment]

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--doctor"], env={}))

        self.assertEqual(code, 0)
        output = buffer.getvalue()
        self.assertIn("synthetic_state_detected: true", output)

    def test_doctor_readiness_command_parity_fails_for_synthetic_state(self) -> None:
        runtime = self._runtime()
        runtime._parity_manifest_is_complete = lambda: True  # type: ignore[assignment]
        synthetic_state = RunState(
            run_id="run-synthetic",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd="/tmp/backend",
                    pid=1234,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                    synthetic=True,
                )
            },
        )
        runtime._try_load_existing_state = lambda mode=None: synthetic_state  # type: ignore[assignment]
        runtime._reconcile_state_truth = lambda _state: []  # type: ignore[assignment]

        readiness = runtime._doctor_readiness_gates()

        self.assertTrue(len(runtime.PARTIAL_COMMANDS) == 0)
        self.assertFalse(readiness["command_parity"])
        event_names = [str(event.get("event", "")) for event in runtime.events]
        self.assertIn("synthetic.execution.blocked", event_names)
        self.assertIn("cutover.gate.fail_reason", event_names)
        self.assertIn("cutover.gate.evaluate", event_names)

    def test_doctor_readiness_emits_cutover_gate_evaluation_event(self) -> None:
        runtime = self._runtime()
        runtime._parity_manifest_is_complete = lambda: True  # type: ignore[assignment]
        runtime._try_load_existing_state = lambda mode=None: None  # type: ignore[assignment]

        with patch(
            "envctl_engine.debug.doctor_orchestrator.evaluate_runtime_readiness",
            return_value=SimpleNamespace(
                passed=True,
                blocking_gap_count=0,
                errors=[],
                warnings=[],
                report_path=Path("/tmp/contracts/python_runtime_gap_report.json"),
                report_generated_at="2026-03-09T00:00:00Z",
                report_sha256="gap123",
                high_gap_count=0,
                medium_gap_count=0,
                low_gap_count=0,
            ),
        ):
            readiness = runtime._doctor_readiness_gates()

        self.assertTrue(readiness["command_parity"])
        evaluate_events = [event for event in runtime.events if event.get("event") == "cutover.gate.evaluate"]
        self.assertEqual(len(evaluate_events), 1)
        event = evaluate_events[0]
        self.assertEqual(event.get("command_parity"), True)
        self.assertEqual(event.get("synthetic_state"), False)
        self.assertEqual(event.get("state_compat_mode"), runtime.state_repository.compat_mode)
        self.assertEqual(event.get("runtime_readiness_contract_passed"), True)
        self.assertEqual(event.get("runtime_readiness_blocking_gap_count"), 0)

    def test_doctor_reports_state_compat_mode_from_env(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "ENVCTL_STATE_COMPAT_MODE": "scoped_only",
            }
        )
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--doctor"], env={}))

        self.assertEqual(code, 0)
        output = buffer.getvalue()
        self.assertIn("state_compat_mode: scoped_only", output)

    def test_doctor_readiness_records_runtime_readiness_failure_details(self) -> None:
        runtime = self._runtime()
        runtime._parity_manifest_is_complete = lambda: True  # type: ignore[assignment]
        runtime._try_load_existing_state = lambda mode=None: None  # type: ignore[assignment]

        with patch(
            "envctl_engine.debug.doctor_orchestrator.evaluate_runtime_readiness",
            return_value=SimpleNamespace(
                passed=False,
                blocking_gap_count=2,
                errors=["blocking gap"],
                warnings=[],
                report_path=Path("/tmp/contracts/python_runtime_gap_report.json"),
                report_generated_at="2026-03-09T00:00:00Z",
                report_sha256="gap123",
                high_gap_count=1,
                medium_gap_count=1,
                low_gap_count=0,
            ),
        ):
            readiness = runtime._doctor_readiness_gates()

        self.assertFalse(readiness["shipability"])
        evaluate_events = [event for event in runtime.events if event.get("event") == "cutover.gate.evaluate"]
        self.assertEqual(len(evaluate_events), 1)
        event = evaluate_events[0]
        self.assertEqual(event.get("runtime_readiness_contract_passed"), False)
        self.assertEqual(event.get("runtime_readiness_blocking_gap_count"), 2)

    def test_doctor_readiness_emits_shipability_fail_reason_event(self) -> None:
        runtime = self._runtime()
        runtime._parity_manifest_is_complete = lambda: True  # type: ignore[assignment]
        runtime._try_load_existing_state = lambda mode=None: None  # type: ignore[assignment]

        with (
            patch(
                "envctl_engine.debug.doctor_orchestrator.evaluate_runtime_readiness",
                return_value=SimpleNamespace(
                    passed=True,
                    blocking_gap_count=0,
                    errors=[],
                    warnings=[],
                    report_path=Path("/tmp/contracts/python_runtime_gap_report.json"),
                    report_generated_at="2026-03-09T00:00:00Z",
                    report_sha256="gap123",
                    high_gap_count=0,
                    medium_gap_count=0,
                    low_gap_count=0,
                ),
            ),
            patch(
                "envctl_engine.runtime.engine_runtime_doctor_support.evaluate_shipability",
                return_value=SimpleNamespace(passed=False, errors=["strict gate failed"], warnings=[]),
            ),
        ):
            readiness = runtime._doctor_readiness_gates()

        self.assertFalse(readiness["shipability"])
        fail_events = [
            event
            for event in runtime.events
            if event.get("event") == "cutover.gate.fail_reason" and event.get("gate") == "shipability"
        ]
        self.assertTrue(any(event.get("reason") == "strict gate failed" for event in fail_events))

    def test_doctor_readiness_passes_runtime_readiness_failures_through_shipability(self) -> None:
        runtime = self._runtime()
        runtime._parity_manifest_is_complete = lambda: True  # type: ignore[assignment]
        runtime._try_load_existing_state = lambda mode=None: None  # type: ignore[assignment]

        with patch(
            "envctl_engine.debug.doctor_orchestrator.evaluate_runtime_readiness",
            return_value=SimpleNamespace(
                passed=False,
                blocking_gap_count=1,
                errors=["runtime readiness blocked"],
                warnings=[],
                report_path=Path("/tmp/contracts/python_runtime_gap_report.json"),
                report_generated_at="2026-03-09T00:00:00Z",
                report_sha256="gap123",
                high_gap_count=1,
                medium_gap_count=0,
                low_gap_count=0,
            ),
        ):
            readiness = runtime._doctor_readiness_gates()

        self.assertFalse(readiness["shipability"])
        fail_events = [
            event
            for event in runtime.events
            if event.get("event") == "cutover.gate.fail_reason" and event.get("gate") == "shipability"
        ]
        self.assertTrue(any(event.get("reason") == "runtime_readiness_contract_failed" for event in fail_events))

    def test_doctor_method_delegates_to_doctor_orchestrator(self) -> None:
        runtime = self._runtime()

        def fake_execute():  # noqa: ANN202
            return 64

        runtime.doctor_orchestrator.execute = fake_execute  # type: ignore[assignment]

        code = runtime._doctor()

        self.assertEqual(code, 64)

    def test_doctor_readiness_gates_method_delegates_to_doctor_orchestrator(self) -> None:
        runtime = self._runtime()

        expected = {
            "command_parity": True,
            "runtime_truth": False,
            "lifecycle": True,
            "shipability": False,
        }

        def fake_readiness():  # noqa: ANN202
            return expected

        runtime.doctor_orchestrator.readiness_gates = fake_readiness  # type: ignore[assignment]

        readiness = runtime._doctor_readiness_gates()

        self.assertEqual(readiness, expected)

    def test_doctor_should_check_tests_method_delegates_to_doctor_orchestrator(self) -> None:
        runtime = self._runtime()

        runtime.doctor_orchestrator.doctor_should_check_tests = lambda: True  # type: ignore[assignment]

        self.assertTrue(runtime._doctor_should_check_tests())
