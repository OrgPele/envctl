from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from io import StringIO
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.command_router import list_supported_commands
from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
import envctl_engine.runtime.engine_runtime_startup_support as startup_support
from envctl_engine.startup.session import ProjectStartupResult
from envctl_engine.state.models import RunState, ServiceRecord


class EngineRuntimeCommandParityTests(unittest.TestCase):
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

    def test_non_start_commands_do_not_silently_route_to_start(self) -> None:
        runtime = self._runtime()

        def fail_start(_route):
            self.fail("_start should not be used for direct command actions")

        runtime._start = fail_start  # type: ignore[assignment]

        commands = [
            "--doctor",
            "--dashboard",
            "--logs",
            "--health",
            "--errors",
            "--test",
            "--pr",
            "--commit",
            "--review",
            "--migrate",
            "--delete-worktree",
            "--blast-worktree",
        ]
        for token in commands:
            route = parse_route([token], env={})
            code = runtime.dispatch(route)
            self.assertIn(code, {0, 1}, msg=token)

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
                "envctl_engine.runtime.engine_runtime.evaluate_shipability",
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

    def test_start_family_routes_to_start_path(self) -> None:
        runtime = self._runtime()
        seen: list[str] = []

        def fake_start(route):
            seen.append(route.command)
            return 0

        runtime.startup_orchestrator.execute = fake_start  # type: ignore[assignment]

        for token in ("start", "--plan", "--restart"):
            route = parse_route([token], env={})
            code = runtime.dispatch(route)
            self.assertEqual(code, 0, msg=token)

        self.assertEqual(seen, ["start", "plan", "restart"])

    def test_start_method_delegates_to_startup_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["start"], env={})

        def fake_execute(r):  # noqa: ANN001
            self.assertEqual(r.command, "start")
            return 91

        runtime.startup_orchestrator.execute = fake_execute  # type: ignore[assignment]

        code = runtime._start(route)

        self.assertEqual(code, 91)

    def test_resume_method_delegates_to_resume_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["--resume"], env={})

        def fake_execute(r):  # noqa: ANN001
            self.assertEqual(r.command, "resume")
            return 73

        runtime.resume_orchestrator.execute = fake_execute  # type: ignore[assignment]

        code = runtime._resume(route)

        self.assertEqual(code, 73)

    def test_doctor_method_delegates_to_doctor_orchestrator(self) -> None:
        runtime = self._runtime()

        def fake_execute():  # noqa: ANN202
            return 64

        runtime.doctor_orchestrator.execute = fake_execute  # type: ignore[assignment]

        code = runtime._doctor()

        self.assertEqual(code, 64)

    def test_dashboard_method_delegates_to_dashboard_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["--dashboard"], env={})

        def fake_execute(r):  # noqa: ANN001
            self.assertEqual(r.command, "dashboard")
            return 58

        runtime.dashboard_orchestrator.execute = fake_execute  # type: ignore[assignment]

        code = runtime._dashboard(route)

        self.assertEqual(code, 58)

    def test_state_action_method_delegates_to_state_action_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["--health"], env={})

        def fake_execute(r):  # noqa: ANN001
            self.assertEqual(r.command, "health")
            return 39

        runtime.state_action_orchestrator.execute = fake_execute  # type: ignore[assignment]

        code = runtime._state_action(route)

        self.assertEqual(code, 39)

    def test_action_command_method_delegates_to_action_command_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["test", "--project", "feature-a-1"], env={})

        def fake_execute(r):  # noqa: ANN001
            self.assertEqual(r.command, "test")
            return 27

        runtime.action_command_orchestrator.execute = fake_execute  # type: ignore[assignment]

        code = runtime._run_action_command(route)

        self.assertEqual(code, 27)

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

    def test_resume_restore_missing_method_delegates_to_resume_orchestrator(self) -> None:
        runtime = self._runtime()
        state = RunState(run_id="run-1", mode="main")
        missing = ["Main Backend"]
        expected = ["Main: restore failed"]

        def fake_restore(s, m, *, route=None):  # noqa: ANN001
            self.assertIs(s, state)
            self.assertEqual(m, missing)
            self.assertIsNone(route)
            return expected

        runtime.resume_orchestrator.restore_missing = fake_restore  # type: ignore[assignment]

        errors = runtime._resume_restore_missing(state, missing, route=None)

        self.assertEqual(errors, expected)

    def test_resolve_action_targets_method_delegates_to_action_command_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["test", "--project", "feature-a-1"], env={})
        expected_targets: list[object] = []
        expected_error = "missing targets"

        def fake_resolve(r, *, trees_only):  # noqa: ANN001
            self.assertEqual(r.command, "test")
            self.assertFalse(trees_only)
            return expected_targets, expected_error

        runtime.action_command_orchestrator.resolve_targets = fake_resolve  # type: ignore[assignment]

        targets, error = runtime._resolve_action_targets(route, trees_only=False)

        self.assertEqual(targets, expected_targets)
        self.assertEqual(error, expected_error)

    def test_run_test_action_method_delegates_to_action_command_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["test"], env={})
        expected_code = 12

        def fake_run(r, targets):  # noqa: ANN001
            self.assertEqual(r.command, "test")
            self.assertEqual(targets, [])
            return expected_code

        runtime.action_command_orchestrator.run_test_action = fake_run  # type: ignore[assignment]

        code = runtime._run_test_action(route, [])

        self.assertEqual(code, expected_code)

    def test_run_project_action_method_delegates_to_action_command_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["pr"], env={})
        expected_code = 19

        def fake_run_project(r, targets, **kwargs):  # noqa: ANN001
            self.assertEqual(r.command, "pr")
            self.assertEqual(targets, [])
            self.assertEqual(kwargs["command_name"], "pr")
            self.assertEqual(kwargs["env_key"], "ENVCTL_ACTION_PR_CMD")
            return expected_code

        runtime.action_command_orchestrator.run_project_action = fake_run_project  # type: ignore[assignment]

        code = runtime._run_project_action(
            route,
            [],
            command_name="pr",
            env_key="ENVCTL_ACTION_PR_CMD",
            default_command=None,
            default_cwd=runtime.config.base_dir,
            default_append_project_path=False,
            extra_env={},
        )

        self.assertEqual(code, expected_code)

    def test_run_migrate_action_method_delegates_to_action_command_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["migrate"], env={})
        expected_code = 33

        def fake_migrate(r, targets):  # noqa: ANN001
            self.assertEqual(r.command, "migrate")
            self.assertEqual(targets, [])
            return expected_code

        runtime.action_command_orchestrator.run_migrate_action = fake_migrate  # type: ignore[assignment]

        code = runtime._run_migrate_action(route, [])

        self.assertEqual(code, expected_code)

    def test_run_delete_worktree_action_method_delegates_to_action_command_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["delete-worktree", "--project", "feature-a-1"], env={})
        expected_code = 44

        def fake_delete(r):  # noqa: ANN001
            self.assertEqual(r.command, "delete-worktree")
            return expected_code

        runtime.action_command_orchestrator.run_delete_worktree_action = fake_delete  # type: ignore[assignment]

        code = runtime._run_delete_worktree_action(route)

        self.assertEqual(code, expected_code)

    def test_resume_context_for_project_method_delegates_to_resume_orchestrator(self) -> None:
        runtime = self._runtime()
        state = RunState(run_id="run-1", mode="trees")
        expected = SimpleNamespace(name="feature-a-1")

        def fake_context_for_project(s, p):  # noqa: ANN001
            self.assertIs(s, state)
            self.assertEqual(p, "feature-a-1")
            return expected

        runtime.resume_orchestrator.context_for_project = fake_context_for_project  # type: ignore[assignment]

        context = runtime._resume_context_for_project(state, "feature-a-1")

        self.assertIs(context, expected)

    def test_resume_project_root_method_delegates_to_resume_orchestrator(self) -> None:
        runtime = self._runtime()
        state = RunState(run_id="run-1", mode="trees")
        expected = Path("/tmp/feature-a-1")

        def fake_project_root(s, p):  # noqa: ANN001
            self.assertIs(s, state)
            self.assertEqual(p, "feature-a-1")
            return expected

        runtime.resume_orchestrator.project_root = fake_project_root  # type: ignore[assignment]

        root = runtime._resume_project_root(state, "feature-a-1")

        self.assertEqual(root, expected)

    def test_apply_resume_ports_to_context_method_delegates_to_resume_orchestrator(self) -> None:
        runtime = self._runtime()
        state = RunState(run_id="run-1", mode="trees")
        context = SimpleNamespace(name="feature-a-1")
        seen: list[object] = []

        def fake_apply(c, s):  # noqa: ANN001
            seen.extend([c, s])

        runtime.resume_orchestrator.apply_ports_to_context = fake_apply  # type: ignore[assignment]

        runtime._apply_resume_ports_to_context(context, state)  # type: ignore[arg-type]

        self.assertEqual(seen, [context, state])

    def test_clear_runtime_state_method_delegates_to_lifecycle_cleanup_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["--stop-all"], env={})
        seen: dict[str, object] = {}

        def fake_clear(*, command, aggressive=False, route=None):  # noqa: ANN001
            seen["command"] = command
            seen["aggressive"] = aggressive
            seen["route"] = route

        runtime.lifecycle_cleanup_orchestrator.clear_runtime_state = fake_clear  # type: ignore[assignment]

        runtime._clear_runtime_state(command="stop-all", aggressive=True, route=route)

        self.assertEqual(seen["command"], "stop-all")
        self.assertEqual(seen["aggressive"], True)
        self.assertIs(seen["route"], route)

    def test_blast_all_port_range_method_delegates_to_lifecycle_cleanup_orchestrator(self) -> None:
        runtime = self._runtime()
        expected = [8100, 8101, 8102]

        def fake_port_range():  # noqa: ANN202
            return expected

        runtime.lifecycle_cleanup_orchestrator.blast_all_port_range = fake_port_range  # type: ignore[assignment]

        ports = runtime._blast_all_port_range()

        self.assertEqual(ports, expected)

    def test_blast_all_docker_cleanup_method_delegates_to_lifecycle_cleanup_orchestrator(self) -> None:
        runtime = self._runtime()
        route = parse_route(["--blast-all"], env={})
        expected = 7

        def fake_cleanup(*, route=None):  # noqa: ANN001
            self.assertIs(route, route_arg)
            return expected

        route_arg = route
        runtime.lifecycle_cleanup_orchestrator.blast_all_docker_cleanup = fake_cleanup  # type: ignore[assignment]

        removed = runtime._blast_all_docker_cleanup(route=route)

        self.assertEqual(removed, expected)

    def test_enforce_runtime_readiness_contract_method_delegates_to_doctor_orchestrator(self) -> None:
        runtime = self._runtime()
        seen: dict[str, object] = {}

        def fake_enforce(*, scope, strict_required=None):  # noqa: ANN001
            seen["scope"] = scope
            seen["strict_required"] = strict_required
            return False

        runtime.doctor_orchestrator.enforce_runtime_readiness_contract = fake_enforce  # type: ignore[assignment]

        passed = runtime._enforce_runtime_readiness_contract(scope="resume", strict_required=True)

        self.assertFalse(passed)
        self.assertEqual(seen, {"scope": "resume", "strict_required": True})

    def test_doctor_should_check_tests_method_delegates_to_doctor_orchestrator(self) -> None:
        runtime = self._runtime()

        runtime.doctor_orchestrator.doctor_should_check_tests = lambda: True  # type: ignore[assignment]

        self.assertTrue(runtime._doctor_should_check_tests())

    def test_start_project_context_method_delegates_to_startup_orchestrator(self) -> None:
        runtime = self._runtime()
        context = SimpleNamespace(name="feature-a-1")
        route = parse_route(["start"], env={})
        expected_requirements = SimpleNamespace(project="feature-a-1")
        expected_services = {"feature-a-1 Backend": object()}
        expected_warnings = ["Warning: backend migration step failed; continuing without migration (...)"]

        def fake_start_project_context(*, context, mode, route, run_id):  # noqa: ANN001
            self.assertEqual(getattr(context, "name", ""), "feature-a-1")
            self.assertEqual(mode, "trees")
            self.assertEqual(route.command, "start")
            self.assertEqual(run_id, "run-42")
            return ProjectStartupResult(
                requirements=expected_requirements,
                services=expected_services,
                warnings=expected_warnings,
            )

        runtime.startup_orchestrator.start_project_context = fake_start_project_context  # type: ignore[assignment]

        result = runtime._start_project_context(
            context=context,  # type: ignore[arg-type]
            mode="trees",
            route=route,
            run_id="run-42",
        )

        self.assertIs(result.requirements, expected_requirements)
        self.assertIs(result.services, expected_services)
        self.assertEqual(result.warnings, expected_warnings)

    def test_start_requirements_for_project_method_delegates_to_startup_orchestrator(self) -> None:
        runtime = self._runtime()
        context = SimpleNamespace(name="Main")
        route = parse_route(["start"], env={})
        expected = SimpleNamespace(project="Main")

        def fake_start_requirements(c, *, mode, route=None):  # noqa: ANN001
            self.assertIs(c, context)
            self.assertEqual(mode, "main")
            self.assertIs(route, route_arg)
            return expected

        route_arg = route
        runtime.startup_orchestrator.start_requirements_for_project = fake_start_requirements  # type: ignore[assignment]

        result = runtime._start_requirements_for_project(context, mode="main", route=route)  # type: ignore[arg-type]

        self.assertIs(result, expected)

    def test_start_project_services_method_delegates_to_startup_orchestrator(self) -> None:
        runtime = self._runtime()
        context = SimpleNamespace(name="Main")
        requirements = SimpleNamespace(project="Main")
        route = parse_route(["start"], env={})
        expected = {"Main Backend": object()}

        def fake_start_services(c, *, requirements, run_id, route=None):  # noqa: ANN001
            self.assertIs(c, context)
            self.assertIs(requirements, requirements_arg)
            self.assertEqual(run_id, "run-99")
            self.assertIs(route, route_arg)
            return expected

        requirements_arg = requirements
        route_arg = route
        runtime.startup_orchestrator.start_project_services = fake_start_services  # type: ignore[assignment]

        services = runtime._start_project_services(
            context,  # type: ignore[arg-type]
            requirements=requirements,  # type: ignore[arg-type]
            run_id="run-99",
            route=route,
        )

        self.assertIs(services, expected)

    def test_parity_manifest_marks_operational_actions_complete(self) -> None:
        manifest_path = REPO_ROOT / "contracts" / "python_engine_parity_manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        for command in ("test", "delete-worktree", "blast-worktree", "pr", "commit", "review", "migrate"):
            self.assertEqual(payload["commands"][command], "python_complete", msg=command)

    def test_list_commands_returns_all_supported_commands(self) -> None:
        runtime = self._runtime()
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--list-commands"], env={}))

        self.assertEqual(code, 0)
        output = buffer.getvalue()
        lines = [line.strip() for line in output.strip().split("\n") if line.strip()]

        # Verify all supported commands are present
        expected_commands = {
            "plan",
            "start",
            "restart",
            "resume",
            "stop",
            "stop-all",
            "blast-all",
            "config",
            "dashboard",
            "doctor",
            "test",
            "logs",
            "clear-logs",
            "health",
            "errors",
            "delete-worktree",
            "blast-worktree",
            "pr",
            "commit",
            "review",
            "migrate",
            "migrate-hooks",
            "install-prompts",
            "list-commands",
            "list-targets",
            "list-trees",
            "show-config",
            "show-state",
            "explain-startup",
            "help",
            "debug-pack",
            "debug-report",
            "debug-last",
        }
        self.assertEqual(set(lines), expected_commands)
        self.assertEqual(len(lines), 33, "Should have exactly 33 commands")

    def test_public_command_inventory_matches_supported_commands(self) -> None:
        self.assertEqual(
            set(list_supported_commands()),
            {
                "start",
                "plan",
                "resume",
                "dashboard",
                "config",
                "doctor",
                "migrate-hooks",
                "install-prompts",
                "debug-pack",
                "debug-report",
                "debug-last",
                "help",
                "list-commands",
                "list-targets",
                "list-trees",
                "show-config",
                "show-state",
                "explain-startup",
                "test",
                "pr",
                "commit",
                "review",
                "migrate",
                "logs",
                "clear-logs",
                "health",
                "errors",
                "delete-worktree",
                "blast-worktree",
                "stop",
                "restart",
                "stop-all",
                "blast-all",
            },
        )

    def test_help_output_lists_same_command_inventory(self) -> None:
        runtime = self._runtime()
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--help"], env={}))

        self.assertEqual(code, 0)
        lines = [line.strip() for line in buffer.getvalue().splitlines() if line.strip()]
        self.assertGreaterEqual(len(lines), 3)
        self.assertEqual(lines[0], "envctl Python runtime")
        self.assertTrue(lines[1].startswith("Commands: "))
        help_commands = {item.strip() for item in lines[1].split("Commands: ", 1)[1].split(",") if item.strip()}
        self.assertEqual(help_commands, set(list_supported_commands()))
        self.assertIn("Mode flags: --main, --tree, --trees, trees=true, main=true", lines[2])
        self.assertIn("Non-interactive: --headless (preferred), --batch (compatibility alias)", lines[3])

    def test_generated_parity_manifest_matches_repository_file(self) -> None:
        manifest_path = REPO_ROOT / "contracts" / "python_engine_parity_manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        generated_at = str(payload["generated_at"])
        completed = subprocess.run(
            [
                "python3",
                str(REPO_ROOT / "scripts" / "generate_python_engine_parity_manifest.py"),
                "--repo",
                str(REPO_ROOT),
                "--stdout",
                "--timestamp",
                generated_at,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        generated = json.loads(completed.stdout)
        self.assertEqual(generated, payload)

    def test_list_targets_discovers_projects_in_main_mode(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / ".envctl").write_text("ENVCTL_DEFAULT_MODE=main\n")
        config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime")})
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--list-targets", "--main"], env={}))
        self.assertEqual(code, 0)
        output = buffer.getvalue()
        # In main mode with a .envctl file, should discover at least the main project
        self.assertIn("Main", output)  # Project name is capitalized

    def test_list_targets_discovers_projects_in_trees_mode(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        trees_dir = repo / "trees"
        trees_dir.mkdir(exist_ok=True)
        feature_dir = trees_dir / "feature" / "1"
        feature_dir.mkdir(parents=True, exist_ok=True)
        (feature_dir / ".envctl").write_text("ENVCTL_DEFAULT_MODE=trees\n")
        config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime")})
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--list-targets", "--trees"], env={}))
        self.assertEqual(code, 0)
        output = buffer.getvalue()
        # Should discover the feature/1 worktree
        lines = [line.strip() for line in output.strip().split("\n") if line.strip()]
        self.assertGreater(len(lines), 0, "Should discover at least one project in trees mode")

    def test_list_trees_discovers_projects_in_trees_mode(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        trees_dir = repo / "trees"
        trees_dir.mkdir(exist_ok=True)
        feature_dir = trees_dir / "feature" / "1"
        feature_dir.mkdir(parents=True, exist_ok=True)
        (feature_dir / ".envctl").write_text("ENVCTL_DEFAULT_MODE=trees\n")
        config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime")})
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--list-trees"], env={}))
        self.assertEqual(code, 0)
        lines = [line.strip() for line in buffer.getvalue().strip().split("\n") if line.strip()]
        self.assertGreater(len(lines), 0, "Should discover at least one project via --list-trees")

    def test_list_trees_json_includes_preselected_and_running(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        runtime_root = Path(tmpdir.name) / "runtime"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        trees_dir = repo / "trees"
        trees_dir.mkdir(exist_ok=True)
        feature_dir = trees_dir / "feature" / "1"
        feature_dir.mkdir(parents=True, exist_ok=True)
        (feature_dir / ".envctl").write_text("ENVCTL_DEFAULT_MODE=trees\n")
        config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime_root)})
        runtime = PythonEngineRuntime(config, env={})
        runtime.state_repository.save_resume_state(
            state=RunState(
                run_id="run-prev",
                mode="trees",
                services={"feature-1 Backend": ServiceRecord(name="feature-1 Backend", type="backend", cwd=".")},
                requirements={},
                metadata={"repo_scope_id": config.runtime_scope_id},
            ),
            emit=lambda *args, **kwargs: None,
            runtime_map_builder=lambda _state: {},
        )

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--list-trees", "--json"], env={}))
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["mode"], "trees")
        self.assertGreaterEqual(payload["count"], 1)
        self.assertTrue(any(project["preselected"] for project in payload["projects"]))

    def test_show_config_json_prints_effective_payload(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / ".envctl").write_text("ENVCTL_DEFAULT_MODE=trees\nBACKEND_DIR=api\nMAIN_STARTUP_ENABLE=false\n")
        config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime")})
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--show-config", "--json"], env={}))
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["effective"]["default_mode"], "trees")
        self.assertEqual(payload["effective"]["directories"]["backend"], "api")
        self.assertEqual(payload["effective"]["profiles"]["main"]["startup_enabled"], False)

    def test_runtime_uses_legacy_spacing_strategy_when_requested(self) -> None:
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
        runtime = PythonEngineRuntime(config, env={"ENVCTL_PORT_PREFERRED_STRATEGY": "legacy_spacing"})

        self.assertEqual(runtime.port_planner.preferred_port_strategy, "legacy_spacing")
        plans = runtime.port_planner.plan_project_stack("tree-beta", index=2)
        self.assertEqual(plans["backend"].final, 8040)
        self.assertEqual(plans["frontend"].final, 9040)
        self.assertEqual(plans["db"].final, 5434)

    def test_show_config_plain_output_reports_preferred_port_strategy(self) -> None:
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
        runtime = PythonEngineRuntime(config, env={"ENVCTL_PORT_PREFERRED_STRATEGY": "legacy_spacing"})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--show-config"], env={}))
        self.assertEqual(code, 0)
        self.assertIn("preferred_port_strategy: legacy_spacing", buffer.getvalue())
        self.assertIn("main_startup_enabled: True", buffer.getvalue())
        self.assertIn("trees_startup_enabled: True", buffer.getvalue())

    def test_show_state_json_reports_missing_state(self) -> None:
        runtime = self._runtime()

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--show-state", "--json"], env={}))
        self.assertEqual(code, 1)
        payload = json.loads(buffer.getvalue())
        self.assertFalse(payload["found"])

    def test_explain_startup_json_reports_headless_tree_selection_requirement(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        trees_dir = repo / "trees"
        trees_dir.mkdir(exist_ok=True)
        (trees_dir / "feature" / "1").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "ENVCTL_DEFAULT_MODE": "trees",
            }
        )
        runtime = PythonEngineRuntime(config, env={})

        with patch.object(runtime, "_can_interactive_tty", return_value=False):
            buffer = StringIO()
            with redirect_stdout(buffer):
                code = runtime.dispatch(parse_route(["--explain-startup", "--trees", "--headless", "--json"], env={}))
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["headless"])
        self.assertEqual(payload["selection"]["reason"], "headless_tree_start_requires_explicit_selection")

    def test_explain_startup_json_reports_disabled_startup(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "MAIN_STARTUP_ENABLE": "false",
            }
        )
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--explain-startup", "--json"], env={}))
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["mode"], "main")
        self.assertEqual(payload["startup_enabled"], False)
        self.assertEqual(payload["reason"], "config_startup_disabled")
        self.assertEqual(payload["dependencies"], [])
        self.assertEqual(payload["services"], {"backend": False, "frontend": False})

    def test_explain_startup_json_reports_dashboard_reuse_decision_for_disabled_startup(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        runtime_root = Path(tmpdir.name) / "runtime"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(runtime_root),
                "MAIN_STARTUP_ENABLE": "false",
            }
        )
        runtime = PythonEngineRuntime(config, env={})
        context = runtime._discover_projects(mode="main")[0]
        metadata = startup_support.build_startup_identity_metadata(
            runtime,
            runtime_mode="main",
            project_contexts=[context],
        )
        runtime.state_repository.save_resume_state(
            state=RunState(
                run_id="run-dashboard",
                mode="main",
                services={},
                requirements={},
                metadata={
                    **metadata,
                    "dashboard_runs_disabled": True,
                    "repo_scope_id": config.runtime_scope_id,
                },
            ),
            emit=lambda *args, **kwargs: None,
            runtime_map_builder=lambda _state: {},
        )

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--explain-startup", "--json"], env={}))
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["mode"], "main")
        self.assertEqual(payload["run_reuse"]["decision_kind"], "resume_dashboard_exact")
        self.assertEqual(payload["run_reuse"]["reason"], "exact_match")
        self.assertEqual(payload["run_reuse"]["run_id"], "run-dashboard")

    def test_explain_startup_json_preserves_plan_selection_semantics(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "ENVCTL_DEFAULT_MODE": "trees",
            }
        )
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--explain-startup", "--plan", "--json"], env={}))

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["command"], "plan")
        self.assertEqual(payload["selection"]["reason"], "no_planning_files")
        self.assertEqual(payload["selection"]["selected_projects"], [])

    def test_explain_startup_json_reports_plan_agent_launch_state(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
            }
        )
        runtime = PythonEngineRuntime(config, env={"CMUX_WORKSPACE_ID": "workspace:4"})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--explain-startup", "--plan", "feature/task", "--json"], env={}))

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["plan_agent_launch"]["enabled"])
        self.assertEqual(payload["plan_agent_launch"]["cli"], "codex")
        self.assertEqual(payload["plan_agent_launch"]["preset"], "implement_task")
        self.assertEqual(payload["plan_agent_launch"]["configured_workspace"], None)
        self.assertEqual(payload["plan_agent_launch"]["workspace_id"], None)
        self.assertEqual(payload["plan_agent_launch"]["reason"], "awaiting_new_worktrees")

    def test_explain_startup_json_reports_plan_agent_workspace_override(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "workspace:9",
            }
        )
        runtime = PythonEngineRuntime(config, env={})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--explain-startup", "--plan", "feature/task", "--json"], env={}))

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["plan_agent_launch"]["enabled"])
        self.assertEqual(payload["plan_agent_launch"]["preset"], "implement_task")
        self.assertEqual(payload["plan_agent_launch"]["workspace_id"], "workspace:9")
        self.assertEqual(payload["plan_agent_launch"]["configured_workspace"], "workspace:9")
        self.assertEqual(payload["plan_agent_launch"]["reason"], "awaiting_new_worktrees")

    def test_explain_startup_json_reports_cmux_alias_enablement(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
        (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "CMUX": "true",
            }
        )
        runtime = PythonEngineRuntime(config, env={"CMUX_WORKSPACE_ID": "workspace:4"})

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--explain-startup", "--plan", "feature/task", "--json"], env={}))

        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["plan_agent_launch"]["enabled"])
        self.assertEqual(payload["plan_agent_launch"]["preset"], "implement_task")
        self.assertEqual(payload["plan_agent_launch"]["workspace_id"], None)
        self.assertEqual(payload["plan_agent_launch"]["configured_workspace"], None)
        self.assertEqual(payload["plan_agent_launch"]["reason"], "awaiting_new_worktrees")


if __name__ == "__main__":
    unittest.main()
