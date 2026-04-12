from __future__ import annotations

import json
from pathlib import Path

from envctl_engine.shared.hooks import legacy_shell_hook_issue
from envctl_engine.shared.reason_codes import GateFailureReason
from envctl_engine.runtime.runtime_readiness import evaluate_runtime_readiness
from envctl_engine.shared.parsing import parse_bool
from envctl_engine.ui.path_links import render_path_for_terminal


class DoctorRuntimeFacade:
    def __init__(self, runtime: object) -> None:
        self._runtime = runtime
        self.config = runtime.config  # type: ignore[attr-defined]
        self.env = runtime.env  # type: ignore[attr-defined]
        self.runtime_root = runtime.runtime_root  # type: ignore[attr-defined]
        self.partial_commands = list(runtime.PARTIAL_COMMANDS)  # type: ignore[attr-defined]

    def run_state_path(self) -> object:
        return self._runtime._run_state_path()  # type: ignore[attr-defined]

    def runtime_map_path(self) -> object:
        return self._runtime._runtime_map_path()  # type: ignore[attr-defined]

    def state_compat_mode(self) -> str:
        return str(self._runtime.state_repository.compat_mode)  # type: ignore[attr-defined]

    def latest_debug_bundle_path(self) -> str:
        return str(getattr(self._runtime, "_last_debug_bundle_path", None) or "none")

    def launch_diagnostics_summary(self) -> object:
        process_runtime = getattr(self._runtime, "process_runner", None)
        candidate = getattr(process_runtime, "launch_diagnostics_summary", None)
        if callable(candidate):
            return candidate()
        return {}

    def load_state(self) -> object | None:
        return self._runtime._try_load_existing_state()  # type: ignore[attr-defined]

    def state_has_synthetic_services(self, state: object) -> bool:
        return bool(self._runtime._state_has_synthetic_services(state))  # type: ignore[attr-defined]

    def parity_manifest_info(self) -> dict[str, str]:
        return self._runtime._parity_manifest_info()  # type: ignore[attr-defined]

    def lock_health_summary(self) -> str:
        return str(self._runtime._lock_health_summary())  # type: ignore[attr-defined]

    def pointer_status_summary(self) -> str:
        return str(self._runtime._pointer_status_summary())  # type: ignore[attr-defined]

    def write_runtime_readiness_report(self, *, readiness_result: object) -> None:
        self._runtime._write_runtime_readiness_report(readiness_result=readiness_result)  # type: ignore[attr-defined]

    def error_report_path(self) -> object:
        return self._runtime._error_report_path()  # type: ignore[attr-defined]

    def persist_events_snapshot(self) -> None:
        self._runtime._persist_events_snapshot()  # type: ignore[attr-defined]

    def parity_manifest_is_complete(self) -> bool:
        return bool(self._runtime._parity_manifest_is_complete())  # type: ignore[attr-defined]

    def reconcile_state_truth(self, state: object) -> list[str]:
        return self._runtime._reconcile_state_truth(state)  # type: ignore[attr-defined]

    def requirement_truth_issues(self, state: object) -> list[dict[str, object]]:
        return self._runtime._requirement_truth_issues(state)  # type: ignore[attr-defined]

    def emit(self, event: str, **payload: object) -> None:
        self._runtime._emit(event, **payload)  # type: ignore[attr-defined]

    def evaluate_shipability(self, *, enforce_runtime_readiness_contract: bool) -> object:
        return self._runtime._evaluate_shipability(  # type: ignore[attr-defined]
            enforce_runtime_readiness_contract=enforce_runtime_readiness_contract,
        )


class DoctorOrchestrator:
    def __init__(self, runtime: object) -> None:
        self.runtime = DoctorRuntimeFacade(runtime)

    def execute(self, *, json_output: bool = False) -> int:
        rt = self.runtime
        payload: dict[str, object] = {}

        def write_field(key: str, value: object) -> None:
            payload[key] = value
            if not json_output:
                text = str(value)
                if (
                    isinstance(value, (str, Path))
                    and (key.endswith("_path") or key.endswith("_file") or "bundle" in key)
                    and text
                    and (text.startswith("/") or text.startswith("~"))
                ):
                    print(f"{key}:")
                    print(render_path_for_terminal(text, env=rt.env))
                else:
                    print(f"{key}: {value}")

        if not json_output:
            print("envctl Python runtime diagnostics")
        hook_issue = legacy_shell_hook_issue(rt.config.base_dir)
        write_field("hook_migration_status", "fail" if hook_issue else "pass")
        if hook_issue:
            write_field("hook_migration_error", hook_issue)
        write_field("runtime_root", str(rt.runtime_root))
        write_field("state_file", str(rt.run_state_path()))
        write_field("runtime_map_file", str(rt.runtime_map_path()))
        write_field("runtime_truth_mode", rt.config.runtime_truth_mode)
        write_field("state_compat_mode", rt.state_compat_mode())
        debug_mode = rt.env.get("ENVCTL_DEBUG_UI_MODE") or rt.config.raw.get("ENVCTL_DEBUG_UI_MODE") or "off"
        debug_auto_pack = rt.env.get("ENVCTL_DEBUG_AUTO_PACK") or rt.config.raw.get("ENVCTL_DEBUG_AUTO_PACK") or "off"
        write_field("debug_mode", debug_mode)
        write_field("debug_auto_pack", debug_auto_pack)
        write_field("debug_latest_bundle", rt.latest_debug_bundle_path())
        write_field("debug_tty_context", "present" if (rt.runtime_root / "debug").is_dir() else "missing")
        launch_summary = rt.launch_diagnostics_summary()
        if isinstance(launch_summary, dict) and launch_summary:
            tracked_launch_count = int(launch_summary.get("tracked_launch_count", 0) or 0)
            active_launch_count = int(launch_summary.get("active_launch_count", 0) or 0)
            launch_intent_counts = launch_summary.get("launch_intent_counts", {})
            active_input_owners = launch_summary.get("active_controller_input_owners", [])
            write_field("tracked_launch_count", tracked_launch_count)
            write_field("active_launch_count", active_launch_count)
            if isinstance(launch_intent_counts, dict):
                write_field("launch_intent_counts", json.dumps(launch_intent_counts, sort_keys=True))
                payload["launch_intent_counts"] = dict(launch_intent_counts)
            if isinstance(active_input_owners, list) and active_input_owners:
                owners = [
                    {
                        "launch_intent": str(item.get("launch_intent", "")),
                        "pid": item.get("pid"),
                        "stdin_policy": str(item.get("stdin_policy", "")),
                    }
                    for item in active_input_owners
                    if isinstance(item, dict)
                ]
                write_field("active_controller_input_owners", json.dumps(owners, sort_keys=True))
                payload["active_controller_input_owners"] = owners
            else:
                write_field("active_controller_input_owners", "none")
                payload["active_controller_input_owners"] = []
        latest_anomalies = 0
        latest_pointer = rt.runtime_root / "debug" / "latest"  # type: ignore[attr-defined]
        if latest_pointer.is_file():
            session_id = latest_pointer.read_text(encoding="utf-8").strip()
            if session_id:
                anomalies_path = rt.runtime_root / "debug" / session_id / "anomalies.jsonl"  # type: ignore[attr-defined]
                if anomalies_path.is_file():
                    latest_anomalies = sum(
                        1 for line in anomalies_path.read_text(encoding="utf-8").splitlines() if line.strip()
                    )
        write_field("debug_last_session_anomalies", latest_anomalies)
        doctor_state = rt.load_state()
        synthetic_state_detected = doctor_state is not None and rt.state_has_synthetic_services(doctor_state)
        write_field("synthetic_state_detected", "true" if synthetic_state_detected else "false")

        readiness = self.readiness_gates()
        parity_status = "complete" if all(readiness.values()) else "gated"
        write_field("parity_status", parity_status)
        if rt.partial_commands:
            write_field("partial_commands", ",".join(rt.partial_commands))
        for key in ("command_parity", "runtime_truth", "lifecycle", "shipability"):
            gate_status = "pass" if readiness.get(key, False) else "fail"
            write_field(f"readiness.{key}", gate_status)

        manifest_info = rt.parity_manifest_info()
        write_field("parity_manifest_path", manifest_info["path"])
        write_field("parity_manifest_generated_at", manifest_info["generated_at"])
        write_field("parity_manifest_sha256", manifest_info["sha256"])
        write_field("lock_health", rt.lock_health_summary())
        write_field("pointer_status", rt.pointer_status_summary())
        readiness = evaluate_runtime_readiness(rt.config.base_dir)
        readiness_status = "pass" if readiness.passed else "fail"
        write_field("runtime_readiness_status", readiness_status)
        write_field("runtime_gap_report_path", str(readiness.report_path))
        write_field("runtime_gap_report_generated_at", readiness.report_generated_at)
        write_field("runtime_gap_report_sha256", readiness.report_sha256)
        write_field("runtime_feature_matrix_path", str(getattr(readiness, "matrix_path", "")))
        write_field("runtime_feature_matrix_generated_at", str(getattr(readiness, "matrix_generated_at", "")))
        write_field("runtime_feature_matrix_sha256", str(getattr(readiness, "matrix_sha256", "")))
        write_field("runtime_gap_high_count", readiness.high_gap_count)
        write_field("runtime_gap_medium_count", readiness.medium_gap_count)
        write_field("runtime_gap_low_count", readiness.low_gap_count)
        write_field("runtime_gap_blocking_count", readiness.blocking_gap_count)
        rt.write_runtime_readiness_report(readiness_result=readiness)

        failures: list[str] = []
        error_report_path = rt.error_report_path()
        if error_report_path.is_file():
            try:
                payload = json.loads(error_report_path.read_text(encoding="utf-8"))
                for raw in payload.get("errors", [])[:5]:
                    text = str(raw)
                    failures.append(text)
            except (OSError, json.JSONDecodeError):
                pass
        if failures:
            payload["recent_failures"] = failures
            if not json_output:
                print("recent_failures:")
                for failure in failures:
                    print(f"- {failure}")
        else:
            payload["recent_failures"] = []
            if not json_output:
                print("recent_failures: none")
        rt.persist_events_snapshot()
        if json_output:
            print(json.dumps(payload, indent=2, sort_keys=True))
        return 1 if hook_issue else 0

    def readiness_gates(self) -> dict[str, bool]:
        rt = self.runtime
        parity_manifest_complete = rt.parity_manifest_is_complete()
        partial_commands = list(rt.partial_commands)
        synthetic_state = False
        runtime_truth = True
        state = rt.load_state()
        failing_services: list[str] = []
        requirement_issues: list[dict[str, object]] = []
        if state is not None:
            synthetic_state = rt.state_has_synthetic_services(state)
            failing_services = rt.reconcile_state_truth(state)
            requirement_issues = rt.requirement_truth_issues(state)
            rt.emit(
                "state.reconcile",
                run_id=state.run_id,
                source="doctor",
                missing_count=len(failing_services),
                missing_services=failing_services,
                requirement_issue_count=len(requirement_issues),
            )
            runtime_truth = not failing_services and not requirement_issues
        command_parity = len(partial_commands) == 0 and parity_manifest_complete and not synthetic_state
        if not parity_manifest_complete:
            rt.emit(
                "cutover.gate.fail_reason",
                gate="command_parity",
                reason="parity_manifest_incomplete",
                reason_code=GateFailureReason.PARITY_MANIFEST_INCOMPLETE.value,
            )
        if partial_commands:
            rt.emit(
                "cutover.gate.fail_reason",
                gate="command_parity",
                reason="partial_commands_present",
                reason_code=GateFailureReason.PARTIAL_COMMANDS_PRESENT.value,
                partial_commands=partial_commands,
            )
        if synthetic_state:
            rt.emit(
                "synthetic.execution.blocked",
                command="doctor",
                reason_code="synthetic_state_detected",
            )
            rt.emit(
                "cutover.gate.fail_reason",
                gate="command_parity",
                reason="synthetic_state_detected",
            )
        lifecycle = hasattr(
            getattr(rt, "_runtime", None).process_runner
            if hasattr(getattr(rt, "_runtime", None), "process_runner")
            else None,
            "terminate",
        )
        if state is not None:
            lifecycle = lifecycle and runtime_truth
        readiness_contract = evaluate_runtime_readiness(rt.config.base_dir)
        shipability_result = rt.evaluate_shipability(enforce_runtime_readiness_contract=True)
        shipability = shipability_result.passed
        if not readiness_contract.passed:
            shipability = False
            rt.emit(
                "cutover.gate.fail_reason",
                gate="shipability",
                reason="runtime_readiness_contract_failed",
                reason_code=GateFailureReason.SHELL_MIGRATION_FAILED.value,
                blocking_gap_count=readiness_contract.blocking_gap_count,
            )
        if not runtime_truth:
            runtime_reason = "service_or_requirement_truth_failed"
            rt.emit(
                "cutover.gate.fail_reason",
                gate="runtime_truth",
                reason=runtime_reason,
                reason_code=GateFailureReason.RUNTIME_TRUTH_FAILED.value,
                failing_services=failing_services,
                failing_requirements=requirement_issues,
            )
        if not lifecycle:
            rt.emit(
                "cutover.gate.fail_reason",
                gate="lifecycle",
                reason="process_runner_missing_terminate_or_runtime_truth_failed",
            )
        if not shipability:
            first_error = (
                str(shipability_result.errors[0]).strip()
                if getattr(shipability_result, "errors", None)
                else "shipability_failed"
            )
            rt.emit(
                "cutover.gate.fail_reason",
                gate="shipability",
                reason=first_error or "shipability_failed",
            )
        readiness = {
            "command_parity": command_parity,
            "runtime_truth": runtime_truth,
            "lifecycle": lifecycle,
            "shipability": shipability,
        }
        rt.emit(
            "cutover.gate.evaluate",
            command_parity=command_parity,
            runtime_truth=runtime_truth,
            lifecycle=lifecycle,
            shipability=shipability,
            synthetic_state=synthetic_state,
            parity_manifest_complete=parity_manifest_complete,
            partial_commands=len(partial_commands),
            state_compat_mode=rt.state_compat_mode(),
            runtime_readiness_contract_passed=readiness_contract.passed,
            runtime_readiness_blocking_gap_count=readiness_contract.blocking_gap_count,
        )
        return readiness

    def doctor_should_check_tests(self) -> bool:
        rt = self.runtime
        for key in ("ENVCTL_DOCTOR_CHECK_TESTS", "ENVCTL_RELEASE_CHECK_TESTS"):
            raw = rt.env.get(key) or rt.config.raw.get(key)  # type: ignore[attr-defined]
            if raw is None:
                continue
            return parse_bool(raw, False)
        return False

    @staticmethod
    def _parse_nonnegative_budget(raw: object) -> int | None:
        if raw is None or str(raw).strip() == "":
            return None
        try:
            value = int(str(raw).strip())
        except ValueError:
            return None
        return max(0, value)

    def enforce_runtime_readiness_contract(self, *, scope: str, strict_required: bool | None = None) -> bool:
        rt = self.runtime
        readiness = evaluate_runtime_readiness(rt.config.base_dir)
        requested_enforcement = (
            bool(strict_required) if strict_required is not None else rt.config.runtime_truth_mode == "strict"  # type: ignore[attr-defined]
        )
        contract_present = readiness.report_path.is_file() or readiness.parity_manifest_path.is_file()
        enforced = requested_enforcement and contract_present
        shipability = readiness.passed if enforced else True
        if enforced and not shipability:
            rt.emit(
                "cutover.gate.fail_reason",
                gate="shipability",
                reason="runtime_readiness_contract_failed",
                scope=scope,
                blocking_gap_count=readiness.blocking_gap_count,
            )
        rt.emit(
            "cutover.gate.evaluate",
            scope=scope,
            shipability=shipability,
            runtime_readiness_contract_enforced=enforced,
            runtime_readiness_contract_passed=readiness.passed,
            runtime_readiness_blocking_gap_count=readiness.blocking_gap_count,
        )
        return shipability
