from __future__ import annotations

import json

from envctl_engine.shared.reason_codes import GateFailureReason
from envctl_engine.shell.shell_prune import evaluate_shell_prune_contract
from envctl_engine.shared.parsing import parse_bool


class DoctorOrchestrator:
    def __init__(self, runtime: object) -> None:
        self.runtime = runtime

    def execute(self, *, json_output: bool = False) -> int:
        rt = self.runtime
        payload: dict[str, object] = {}

        def write_field(key: str, value: object) -> None:
            payload[key] = value
            if not json_output:
                print(f"{key}: {value}")

        if not json_output:
            print("envctl Python runtime diagnostics")
        write_field("runtime_root", str(rt.runtime_root))  # type: ignore[attr-defined]
        write_field("state_file", str(rt._run_state_path()))  # type: ignore[attr-defined]
        write_field("runtime_map_file", str(rt._runtime_map_path()))  # type: ignore[attr-defined]
        write_field("runtime_truth_mode", rt.config.runtime_truth_mode)  # type: ignore[attr-defined]
        write_field("state_compat_mode", rt.state_repository.compat_mode)  # type: ignore[attr-defined]
        debug_mode = (rt.env.get("ENVCTL_DEBUG_UI_MODE") or rt.config.raw.get("ENVCTL_DEBUG_UI_MODE") or "off")  # type: ignore[attr-defined]
        debug_auto_pack = (rt.env.get("ENVCTL_DEBUG_AUTO_PACK") or rt.config.raw.get("ENVCTL_DEBUG_AUTO_PACK") or "off")  # type: ignore[attr-defined]
        write_field("debug_mode", debug_mode)
        write_field("debug_auto_pack", debug_auto_pack)
        write_field("debug_latest_bundle", rt._last_debug_bundle_path or "none")  # type: ignore[attr-defined]
        write_field("debug_tty_context", "present" if (rt.runtime_root / "debug").is_dir() else "missing")  # type: ignore[attr-defined]
        launch_summary_fn = getattr(rt.process_runner, "launch_diagnostics_summary", None)  # type: ignore[attr-defined]
        launch_summary = launch_summary_fn() if callable(launch_summary_fn) else {}
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
                    latest_anomalies = sum(1 for line in anomalies_path.read_text(encoding="utf-8").splitlines() if line.strip())
        write_field("debug_last_session_anomalies", latest_anomalies)
        doctor_state = rt._try_load_existing_state()  # type: ignore[attr-defined]
        synthetic_state_detected = doctor_state is not None and rt._state_has_synthetic_services(doctor_state)  # type: ignore[attr-defined]
        write_field("synthetic_state_detected", "true" if synthetic_state_detected else "false")

        readiness = self.readiness_gates()
        parity_status = "complete" if all(readiness.values()) else "gated"
        write_field("parity_status", parity_status)
        if rt.PARTIAL_COMMANDS:  # type: ignore[attr-defined]
            write_field("partial_commands", ",".join(rt.PARTIAL_COMMANDS))  # type: ignore[attr-defined]
        for key in ("command_parity", "runtime_truth", "lifecycle", "shipability"):
            gate_status = "pass" if readiness.get(key, False) else "fail"
            write_field(f"readiness.{key}", gate_status)

        manifest_info = rt._parity_manifest_info()  # type: ignore[attr-defined]
        write_field("parity_manifest_path", manifest_info["path"])
        write_field("parity_manifest_generated_at", manifest_info["generated_at"])
        write_field("parity_manifest_sha256", manifest_info["sha256"])
        write_field("lock_health", rt._lock_health_summary())  # type: ignore[attr-defined]
        write_field("pointer_status", rt._pointer_status_summary())  # type: ignore[attr-defined]
        (
            shell_budget,
            shell_partial_keep_budget,
            shell_intentional_keep_budget,
            shell_phase,
        ) = self.shell_prune_budget_profile()
        strict_budget_required = rt.config.runtime_truth_mode == "strict"  # type: ignore[attr-defined]
        shell_budget_profile_complete = self.is_shell_budget_profile_complete(
            shell_budget=shell_budget,
            shell_partial_keep_budget=shell_partial_keep_budget,
            shell_intentional_keep_budget=shell_intentional_keep_budget,
        )
        shell_migration = evaluate_shell_prune_contract(
            rt.config.base_dir,  # type: ignore[attr-defined]
            enforce_manifest_coverage=True,
            max_unmigrated=shell_budget,
            max_partial_keep=shell_partial_keep_budget,
            max_intentional_keep=shell_intentional_keep_budget,
            phase=shell_phase,
        )
        if shell_migration.ledger_exists:
            rt._emit(  # type: ignore[attr-defined]
                "shell.ledger.loaded",
                path=str(shell_migration.ledger_path),
                sha256=shell_migration.ledger_hash,
                generated_at=shell_migration.ledger_generated_at,
            )
        if shell_migration.errors:
            rt._emit(  # type: ignore[attr-defined]
                "shell.ledger.mismatch",
                error_count=len(shell_migration.errors),
                first_errors=shell_migration.errors[:5],
            )
        shell_status = "pass" if shell_migration.passed else "fail"
        write_field("shell_migration_status", shell_status)
        write_field("shell_ledger_path", str(shell_migration.ledger_path))
        write_field("shell_ledger_generated_at", shell_migration.ledger_generated_at)
        write_field("shell_ledger_hash", shell_migration.ledger_hash)
        write_field("shell_unmigrated_count", int(shell_migration.status_counts.get("unmigrated", 0)))
        shell_unmigrated_actual = int(shell_migration.status_counts.get("unmigrated", 0))
        write_field("shell_unmigrated_actual", shell_unmigrated_actual)
        write_field("shell_intentional_keep_count", int(shell_migration.status_counts.get("shell_intentional_keep", 0)))
        shell_intentional_keep_actual = int(shell_migration.intentional_keep_budget_actual)
        write_field("shell_intentional_keep_actual", shell_intentional_keep_actual)
        write_field("shell_partial_keep_count", int(shell_migration.status_counts.get("python_partial_keep_temporarily", 0)))
        write_field("shell_partial_keep_covered_count", shell_migration.partial_keep_covered_count)
        write_field("shell_partial_keep_uncovered_count", shell_migration.partial_keep_uncovered_count)
        shell_partial_keep_actual = int(shell_migration.partial_keep_budget_actual)
        write_field("shell_partial_keep_actual", shell_partial_keep_actual)
        write_field("shell_partial_keep_budget_basis", shell_migration.partial_keep_budget_basis)
        if shell_budget is not None:
            shell_unmigrated_status = "pass" if shell_unmigrated_actual <= shell_budget else "fail"
            shell_budget_text = str(shell_budget)
        else:
            shell_unmigrated_status = "fail" if strict_budget_required else "unchecked"
            shell_budget_text = "none"
        if shell_partial_keep_budget is not None:
            shell_partial_keep_status = "pass" if shell_partial_keep_actual <= shell_partial_keep_budget else "fail"
            shell_partial_keep_budget_text = str(shell_partial_keep_budget)
        else:
            shell_partial_keep_status = "fail" if strict_budget_required else "unchecked"
            shell_partial_keep_budget_text = "none"
        if shell_intentional_keep_budget is not None:
            shell_intentional_keep_status = (
                "pass" if shell_intentional_keep_actual <= shell_intentional_keep_budget else "fail"
            )
            shell_intentional_keep_budget_text = str(shell_intentional_keep_budget)
        else:
            shell_intentional_keep_status = "fail" if strict_budget_required else "unchecked"
            shell_intentional_keep_budget_text = "none"
        write_field("shell_unmigrated_budget", shell_budget_text)
        write_field("shell_unmigrated_status", shell_unmigrated_status)
        write_field("shell_unmigrated_budget_status", shell_unmigrated_status)
        write_field("shell_partial_keep_budget", shell_partial_keep_budget_text)
        write_field("shell_partial_keep_status", shell_partial_keep_status)
        write_field("shell_partial_keep_budget_status", shell_partial_keep_status)
        write_field("shell_intentional_keep_budget", shell_intentional_keep_budget_text)
        write_field("shell_intentional_keep_status", shell_intentional_keep_status)
        write_field("shell_intentional_keep_budget_status", shell_intentional_keep_status)
        write_field("shell_budget_profile_required", "true" if strict_budget_required else "false")
        write_field("shell_budget_profile_complete", "true" if shell_budget_profile_complete else "false")
        if shell_phase:
            write_field("shell_prune_phase", shell_phase)
        rt._write_shell_prune_report(contract_result=shell_migration)  # type: ignore[attr-defined]

        failures: list[str] = []
        error_report_path = rt._error_report_path()  # type: ignore[attr-defined]
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
        rt._persist_events_snapshot()  # type: ignore[attr-defined]
        if json_output:
            print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    def readiness_gates(self) -> dict[str, bool]:
        rt = self.runtime
        parity_manifest_complete = rt._parity_manifest_is_complete()  # type: ignore[attr-defined]
        partial_commands = list(rt.PARTIAL_COMMANDS)  # type: ignore[attr-defined]
        synthetic_state = False
        runtime_truth = True
        state = rt._try_load_existing_state()  # type: ignore[attr-defined]
        failing_services: list[str] = []
        requirement_issues: list[dict[str, object]] = []
        if state is not None:
            synthetic_state = rt._state_has_synthetic_services(state)  # type: ignore[attr-defined]
            failing_services = rt._reconcile_state_truth(state)  # type: ignore[attr-defined]
            requirement_issues = rt._requirement_truth_issues(state)  # type: ignore[attr-defined]
            rt._emit(  # type: ignore[attr-defined]
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
            rt._emit(  # type: ignore[attr-defined]
                "cutover.gate.fail_reason",
                gate="command_parity",
                reason="parity_manifest_incomplete",
                reason_code=GateFailureReason.PARITY_MANIFEST_INCOMPLETE.value,
            )
        if partial_commands:
            rt._emit(  # type: ignore[attr-defined]
                "cutover.gate.fail_reason",
                gate="command_parity",
                reason="partial_commands_present",
                reason_code=GateFailureReason.PARTIAL_COMMANDS_PRESENT.value,
                partial_commands=partial_commands,
            )
        if synthetic_state:
            rt._emit(  # type: ignore[attr-defined]
                "synthetic.execution.blocked",
                command="doctor",
                reason_code="synthetic_state_detected",
            )
            rt._emit(  # type: ignore[attr-defined]
                "cutover.gate.fail_reason",
                gate="command_parity",
                reason="synthetic_state_detected",
            )
        lifecycle = hasattr(rt.process_runner, "terminate")  # Protocol method always exists
        if state is not None:
            lifecycle = lifecycle and runtime_truth
        (
            shell_budget,
            shell_partial_keep_budget,
            shell_intentional_keep_budget,
            shell_phase,
        ) = self.shell_prune_budget_profile()
        shell_budget_profile_complete = self.is_shell_budget_profile_complete(
            shell_budget=shell_budget,
            shell_partial_keep_budget=shell_partial_keep_budget,
            shell_intentional_keep_budget=shell_intentional_keep_budget,
        )
        shipability_result = rt._evaluate_shipability(  # type: ignore[attr-defined]
            shell_budget=shell_budget,
            shell_partial_keep_budget=shell_partial_keep_budget,
            shell_intentional_keep_budget=shell_intentional_keep_budget,
            shell_phase=shell_phase,
            require_shell_budget_complete=rt.config.runtime_truth_mode == "strict",  # type: ignore[attr-defined]
        )
        shipability = shipability_result.passed
        if rt.config.runtime_truth_mode == "strict" and not shell_budget_profile_complete:  # type: ignore[attr-defined]
            shipability = False
            rt._emit(  # type: ignore[attr-defined]
                "cutover.gate.fail_reason",
                gate="shipability",
                reason="shell_budget_profile_incomplete",
                reason_code=GateFailureReason.SHELL_MIGRATION_FAILED.value,
            )
        if rt.config.runtime_truth_mode == "strict" and shell_budget is None:  # type: ignore[attr-defined]
            shipability = False
            rt._emit(  # type: ignore[attr-defined]
                "cutover.gate.fail_reason",
                gate="shipability",
                reason="shell_budget_undefined",
                reason_code=GateFailureReason.SHELL_UNMIGRATED_EXCEEDED.value,
            )
        if rt.config.runtime_truth_mode == "strict" and shell_partial_keep_budget is None:  # type: ignore[attr-defined]
            shipability = False
            rt._emit(  # type: ignore[attr-defined]
                "cutover.gate.fail_reason",
                gate="shipability",
                reason="shell_partial_keep_budget_undefined",
                reason_code=GateFailureReason.SHELL_PARTIAL_KEEP_EXCEEDED.value,
            )
        if rt.config.runtime_truth_mode == "strict" and shell_intentional_keep_budget is None:  # type: ignore[attr-defined]
            shipability = False
            rt._emit(  # type: ignore[attr-defined]
                "cutover.gate.fail_reason",
                gate="shipability",
                reason="shell_intentional_keep_budget_undefined",
                reason_code=GateFailureReason.SHELL_INTENTIONAL_KEEP_EXCEEDED.value,
            )
        if not runtime_truth:
            runtime_reason = "service_or_requirement_truth_failed"
            rt._emit(  # type: ignore[attr-defined]
                "cutover.gate.fail_reason",
                gate="runtime_truth",
                reason=runtime_reason,
                reason_code=GateFailureReason.RUNTIME_TRUTH_FAILED.value,
                failing_services=failing_services,
                failing_requirements=requirement_issues,
            )
        if not lifecycle:
            rt._emit(  # type: ignore[attr-defined]
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
            rt._emit(  # type: ignore[attr-defined]
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
        rt._emit(  # type: ignore[attr-defined]
            "cutover.gate.evaluate",
            command_parity=command_parity,
            runtime_truth=runtime_truth,
            lifecycle=lifecycle,
            shipability=shipability,
            synthetic_state=synthetic_state,
            parity_manifest_complete=parity_manifest_complete,
            partial_commands=len(partial_commands),
            state_compat_mode=rt.state_repository.compat_mode,  # type: ignore[attr-defined]
            shell_budget_profile_required=rt.config.runtime_truth_mode == "strict",  # type: ignore[attr-defined]
            shell_budget_profile_complete=shell_budget_profile_complete,
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

    def shell_prune_max_unmigrated_budget(self) -> int | None:
        rt = self.runtime
        raw = rt.env.get("ENVCTL_SHELL_PRUNE_MAX_UNMIGRATED") or rt.config.raw.get("ENVCTL_SHELL_PRUNE_MAX_UNMIGRATED")  # type: ignore[attr-defined]
        return self._parse_nonnegative_budget(raw)

    def shell_prune_max_partial_keep_budget(self) -> int | None:
        rt = self.runtime
        raw = rt.env.get("ENVCTL_SHELL_PRUNE_MAX_PARTIAL_KEEP") or rt.config.raw.get("ENVCTL_SHELL_PRUNE_MAX_PARTIAL_KEEP")  # type: ignore[attr-defined]
        return self._parse_nonnegative_budget(raw)

    def shell_prune_max_intentional_keep_budget(self) -> int | None:
        rt = self.runtime
        raw = rt.env.get("ENVCTL_SHELL_PRUNE_MAX_INTENTIONAL_KEEP") or rt.config.raw.get("ENVCTL_SHELL_PRUNE_MAX_INTENTIONAL_KEEP")  # type: ignore[attr-defined]
        return self._parse_nonnegative_budget(raw)

    @staticmethod
    def _parse_nonnegative_budget(raw: object) -> int | None:
        if raw is None or str(raw).strip() == "":
            return None
        try:
            value = int(str(raw).strip())
        except ValueError:
            return None
        return max(0, value)

    def shell_prune_phase(self) -> str | None:
        rt = self.runtime
        raw = rt.env.get("ENVCTL_SHELL_PRUNE_PHASE") or rt.config.raw.get("ENVCTL_SHELL_PRUNE_PHASE")  # type: ignore[attr-defined]
        if raw is None:
            return None
        text = str(raw).strip()
        return text or None

    def shell_prune_budget_profile(self) -> tuple[int | None, int | None, int | None, str | None]:
        rt = self.runtime
        shell_budget = self.shell_prune_max_unmigrated_budget()
        shell_partial_keep_budget = self.shell_prune_max_partial_keep_budget()
        shell_intentional_keep_budget = self.shell_prune_max_intentional_keep_budget()
        shell_phase = self.shell_prune_phase()

        strict_mode = rt.config.runtime_truth_mode == "strict"  # type: ignore[attr-defined]
        all_budgets_omitted = (
            shell_budget is None
            and shell_partial_keep_budget is None
            and shell_intentional_keep_budget is None
        )
        if all_budgets_omitted:
            shell_budget = 0
            shell_partial_keep_budget = 0
            shell_intentional_keep_budget = 0
        elif not strict_mode:
            if shell_budget is None:
                shell_budget = 0
            if shell_partial_keep_budget is None:
                shell_partial_keep_budget = 0
            if shell_intentional_keep_budget is None:
                shell_intentional_keep_budget = 0
        if shell_phase is None:
            shell_phase = "cutover"
        return shell_budget, shell_partial_keep_budget, shell_intentional_keep_budget, shell_phase

    def shell_prune_budget_values_omitted(self) -> bool:
        return (
            self.shell_prune_max_unmigrated_budget() is None
            and self.shell_prune_max_partial_keep_budget() is None
            and self.shell_prune_max_intentional_keep_budget() is None
        )

    def is_shell_budget_profile_complete(
        self,
        *,
        shell_budget: int | None,
        shell_partial_keep_budget: int | None,
        shell_intentional_keep_budget: int | None,
    ) -> bool:
        rt = self.runtime
        if shell_budget is None or shell_partial_keep_budget is None or shell_intentional_keep_budget is None:
            return False
        if rt.config.runtime_truth_mode == "strict" and self.shell_prune_budget_values_omitted():  # type: ignore[attr-defined]
            return False
        return True

    def enforce_runtime_shell_budget_profile(self, *, scope: str, strict_required: bool | None = None) -> bool:
        rt = self.runtime
        if strict_required is None:
            strict_required = rt.config.runtime_truth_mode == "strict"  # type: ignore[attr-defined]
        (
            shell_budget,
            shell_partial_keep_budget,
            shell_intentional_keep_budget,
            _shell_phase,
        ) = self.shell_prune_budget_profile()
        shell_budget_profile_complete = self.is_shell_budget_profile_complete(
            shell_budget=shell_budget,
            shell_partial_keep_budget=shell_partial_keep_budget,
            shell_intentional_keep_budget=shell_intentional_keep_budget,
        )
        shipability = (not strict_required) or shell_budget_profile_complete
        if strict_required and not shell_budget_profile_complete:
            rt._emit(  # type: ignore[attr-defined]
                "cutover.gate.fail_reason",
                gate="shipability",
                reason="shell_budget_profile_incomplete",
                scope=scope,
            )
        if strict_required and shell_budget is None:
            rt._emit(  # type: ignore[attr-defined]
                "cutover.gate.fail_reason",
                gate="shipability",
                reason="shell_budget_undefined",
                scope=scope,
            )
        if strict_required and shell_partial_keep_budget is None:
            rt._emit(  # type: ignore[attr-defined]
                "cutover.gate.fail_reason",
                gate="shipability",
                reason="shell_partial_keep_budget_undefined",
                scope=scope,
            )
        if strict_required and shell_intentional_keep_budget is None:
            rt._emit(  # type: ignore[attr-defined]
                "cutover.gate.fail_reason",
                gate="shipability",
                reason="shell_intentional_keep_budget_undefined",
                scope=scope,
            )
        rt._emit(  # type: ignore[attr-defined]
            "cutover.gate.evaluate",
            scope=scope,
            shipability=shipability,
            shell_budget_profile_required=bool(strict_required),
            shell_budget_profile_complete=shell_budget_profile_complete,
        )
        return shipability
