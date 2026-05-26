from __future__ import annotations

import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path

from envctl_engine.debug.debug_bundle_selector_diagnostics import analyze_selector_diagnostics
from envctl_engine.debug.debug_bundle_startup_diagnostics import analyze_startup_diagnostics
from envctl_engine.debug.debug_bundle_support import count_jsonl_bytes, read_jsonl


def summarize_debug_bundle(bundle_path: Path) -> dict[str, object]:
    if not bundle_path.is_file():
        raise FileNotFoundError(f"Bundle not found: {bundle_path}")
    summary: dict[str, object] = {
        "bundle": str(bundle_path),
        "session_id": "unknown",
        "events": 0,
        "anomalies": 0,
        "probable_root_causes": [],
        "next_data_needed": [],
        "spinner_disabled_reasons": [],
        "missing_spinner_lifecycle_transition": "",
        "suite_spinner_group_disabled_reasons": [],
        "startup_breakdown": {},
        "slowest_components": [],
        "resume_skip_reasons": {},
        "requirements_stage_hotspots": [],
        "service_bootstrap_hotspots": [],
        "service_attach_hotspots": [],
        "launch_intent_counts": {},
        "tracked_controller_input_owners": [],
        "launch_policy_violations": [],
    }
    with tarfile.open(bundle_path, "r:gz") as tar:
        names = set(tar.getnames())
        if "events.debug.jsonl" in names:
            member = tar.extractfile("events.debug.jsonl")
            if member is not None:
                summary["events"] = count_jsonl_bytes(member.read())
        if "anomalies.jsonl" in names:
            member = tar.extractfile("anomalies.jsonl")
            if member is not None:
                summary["anomalies"] = count_jsonl_bytes(member.read())
        if "diagnostics.json" in names:
            member = tar.extractfile("diagnostics.json")
            if member is not None:
                payload = json.loads(member.read().decode("utf-8"))
                if isinstance(payload, dict):
                    summary["probable_root_causes"] = payload.get("probable_root_causes", [])
                    summary["next_data_needed"] = payload.get("next_data_needed", [])
                    summary["spinner_disabled_reasons"] = payload.get("spinner_disabled_reasons", [])
                    summary["missing_spinner_lifecycle_transition"] = payload.get(
                        "missing_spinner_lifecycle_transition",
                        "",
                    )
                    summary["suite_spinner_group_disabled_reasons"] = payload.get(
                        "suite_spinner_group_disabled_reasons",
                        [],
                    )
                    summary["startup_breakdown"] = payload.get("startup_breakdown", {})
                    summary["slowest_components"] = payload.get("slowest_components", [])
                    summary["resume_skip_reasons"] = payload.get("resume_skip_reasons", {})
                    summary["requirements_stage_hotspots"] = payload.get("requirements_stage_hotspots", [])
                    summary["service_bootstrap_hotspots"] = payload.get("service_bootstrap_hotspots", [])
                    summary["service_attach_hotspots"] = payload.get("service_attach_hotspots", [])
                    summary["launch_intent_counts"] = payload.get("launch_intent_counts", {})
                    summary["tracked_controller_input_owners"] = payload.get("tracked_controller_input_owners", [])
                    summary["launch_policy_violations"] = payload.get("launch_policy_violations", [])
        if "manifest.json" in names:
            member = tar.extractfile("manifest.json")
            if member is not None:
                payload = json.loads(member.read().decode("utf-8"))
                if isinstance(payload, dict):
                    session_id = payload.get("session_id")
                    if isinstance(session_id, str):
                        normalized = session_id.strip()
                        if normalized:
                            summary["session_id"] = normalized
    return summary


def write_diagnostics(staging_dir: Path) -> None:
    issues: list[dict[str, object]] = []
    probable: list[str] = []
    next_data_needed: list[str] = []
    anomalies = read_jsonl(staging_dir / "anomalies.jsonl")
    timeline = read_jsonl(staging_dir / "timeline.jsonl")
    anomaly_event_names = sorted(
        {str(item.get("event", "")).strip() for item in anomalies if str(item.get("event", "")).strip()}
    )

    repeated = any(str(item.get("event", "")).endswith("input_repeated_burst") for item in anomalies)
    empty_submit = any(str(item.get("event", "")).endswith("empty_submit_with_bytes") for item in anomalies)
    state_changed_without_lifecycle = any(
        str(item.get("event", "")).endswith("state_changed_without_lifecycle_event") for item in anomalies
    )
    spinner_without_command_activity = any(
        str(item.get("event", "")).strip() == "ui.anomaly.spinner_without_command_activity" for item in timeline
    )
    spinner_fail = any(
        (
            str(item.get("event", "")) == "ui.spinner.state"
            and str(item.get("spinner_state", "")).strip().lower() == "fail"
        )
        or (
            str(item.get("event", "")) == "ui.spinner.lifecycle"
            and str(item.get("state", "")).strip().lower() == "fail"
        )
        for item in timeline
    )
    spinner_disabled_reasons = sorted(
        {
            str(item.get("reason", "")).strip()
            for item in timeline
            if (
                (
                    str(item.get("event", "")) == "ui.spinner.disabled"
                    or (str(item.get("event", "")) == "ui.spinner.policy" and not bool(item.get("enabled", True)))
                )
                and str(item.get("reason", "")).strip()
            )
        }
    )
    spinner_disabled_actionable_reasons = [
        reason for reason in spinner_disabled_reasons if reason != "input_phase_guard"
    ]
    suite_spinner_group_disabled_reasons = sorted(
        {
            str(item.get("reason", "")).strip()
            for item in timeline
            if (
                str(item.get("event", "")) == "test.suite_spinner_group.policy"
                and not bool(item.get("enabled", False))
                and str(item.get("reason", "")).strip()
            )
        }
    )
    suite_spinner_runtime = [
        {
            "reason": str(item.get("reason", "")),
            "backend": str(item.get("backend", "")),
            "python_executable": str(item.get("python_executable", "")),
            "rich_progress_supported": bool(item.get("rich_progress_supported", False)),
            "rich_progress_error": str(item.get("rich_progress_error", "")),
        }
        for item in timeline
        if str(item.get("event", "")) == "test.suite_spinner_group.policy"
    ]
    lifecycle_states = [
        str(item.get("state", "")).strip().lower()
        for item in timeline
        if str(item.get("event", "")) == "ui.spinner.lifecycle"
    ]
    missing_spinner_lifecycle_transition = ""
    if "start" in lifecycle_states and not any(state in {"success", "fail"} for state in lifecycle_states):
        missing_spinner_lifecycle_transition = "missing_terminal_state"
    elif any(state in {"success", "fail"} for state in lifecycle_states) and "stop" not in lifecycle_states:
        missing_spinner_lifecycle_transition = "missing_stop"

    selector_diagnostics = analyze_selector_diagnostics(timeline)

    startup_diagnostics = analyze_startup_diagnostics(timeline)

    if repeated:
        issues.append({"code": "input_repeated_burst", "confidence": 0.9})
        probable.append("Input backend likely duplicated buffered characters (burst typing replay).")
    if empty_submit:
        issues.append({"code": "empty_submit_with_bytes", "confidence": 0.8})
        probable.append("TTY newline delivered without parseable command token.")
    if state_changed_without_lifecycle:
        issues.append({"code": "state_changed_without_lifecycle_event", "confidence": 0.75})
        probable.append(
            "Run state fingerprint changed without a matching lifecycle event; inspect service truth reconciliation transitions."
        )
    if spinner_without_command_activity:
        issues.append({"code": "spinner_without_command_activity", "confidence": 0.7})
        probable.append(
            "Spinner policy was enabled for command dispatch but no spinner-starting activity events were observed."
        )
    if spinner_fail:
        issues.append({"code": "spinner_fail", "confidence": 0.6})
        probable.append("Command lifecycle failed while spinner was active; inspect action.command.finish events.")
    if spinner_disabled_actionable_reasons:
        issues.append({"code": "spinner_disabled", "confidence": 0.7})
        probable.append("Spinner disabled by policy; inspect spinner_disabled_reasons for visibility root cause.")
    if suite_spinner_group_disabled_reasons:
        issues.append({"code": "suite_spinner_group_disabled", "confidence": 0.8})
        probable.append("Per-suite test spinner group disabled; inspect suite_spinner_group_disabled_reasons.")
    if missing_spinner_lifecycle_transition:
        issues.append({"code": "spinner_lifecycle_incomplete", "confidence": 0.7})
        probable.append("Spinner lifecycle is incomplete; expected terminal transitions are missing.")
    if selector_diagnostics.inactive_tokens:
        issues.append({"code": "selector_input_inactive", "confidence": 0.9})
        probable.append(
            "Selector entered but no key/mouse/focus events were observed; input/focus pipeline likely stalled."
        )
    if selector_diagnostics.low_throughput:
        issues.append({"code": "selector_input_low_throughput", "confidence": 0.85})
        probable.append(
            "Selector key throughput is abnormally low for observed selector duration; investigate terminal input pipeline."
        )
    if selector_diagnostics.mouse_double_toggle:
        issues.append({"code": "selector_mouse_double_toggle", "confidence": 0.75})
        probable.append("Selector click handling may be double-dispatching toggles in a short debounce window.")
    if selector_diagnostics.blocked_then_cancel:
        issues.append({"code": "selector_blocked_submit_then_cancel", "confidence": 0.7})
        probable.append("Selector submit was blocked and then cancelled, indicating unstable focus/selection handoff.")
    if selector_diagnostics.key_pipeline_gaps:
        issues.append({"code": "selector_key_pipeline_gap", "confidence": 0.95})
        probable.append("Selector key events are dropping between parser ingress and app-level handling.")
    if selector_diagnostics.read_pipeline_gaps:
        issues.append({"code": "selector_read_pipeline_gap", "confidence": 0.9})
        probable.append("Raw selector input bytes suggest additional key sequences dropped before parser key events.")
    if selector_diagnostics.driver_focus_loss:
        issues.append({"code": "selector_driver_focus_loss", "confidence": 0.9})
        probable.append(
            "Terminal focus-out events occurred during selector input without corresponding focus-in recovery."
        )
    if selector_diagnostics.idle_after_activity:
        issues.append({"code": "selector_input_stalled_after_activity", "confidence": 0.9})
        probable.append(
            "Selector accepted initial navigation keys but then went idle; inspect selector key driver snapshots and focus events."
        )
    if (
        startup_diagnostics.known_total_ms > 0
        and startup_diagnostics.requirements_total_ms / max(startup_diagnostics.known_total_ms, 1.0) >= 0.7
    ):
        issues.append({"code": "startup_requirements_dominant", "confidence": 0.9})
        probable.append(
            "Startup latency is dominated by requirement lifecycle timing rather than application service attach timing."
        )
    if startup_diagnostics.resume_skip_reasons:
        issues.append({"code": "startup_auto_resume_skipped", "confidence": 0.85})
        probable.append(
            "Auto-resume was skipped for at least one startup path; inspect resume_skip_reasons and selected/state project sets."
        )
    if startup_diagnostics.requirements_stage_hotspots:
        top_stage = str(startup_diagnostics.requirements_stage_hotspots[0].get("stage", "")).strip().lower()
        if top_stage in {"listener_wait", "probe", "restart", "recreate"}:
            issues.append({"code": "requirements_stage_hotspot", "confidence": 0.8})
            probable.append(
                "Requirement adapter timing is concentrated in listener/probe/retry stages; inspect requirements_stage_hotspots."
            )
    if not anomalies:
        next_data_needed.append("No anomalies captured; rerun with ENVCTL_DEBUG_UI_MODE=deep.")
    if startup_diagnostics.requirements_total_ms > 0 and not startup_diagnostics.has_adapter_stage_detail:
        next_data_needed.append("Requirement stage-level traces missing; rerun with ENVCTL_DEBUG_REQUIREMENTS_TRACE=1.")
    if startup_diagnostics.requirements_total_ms > 0 and not startup_diagnostics.has_command_timing_detail:
        next_data_needed.append(
            "Docker command timing traces missing; rerun with ENVCTL_DEBUG_DOCKER_COMMAND_TIMING=1."
        )
    launch_intent_counts: dict[str, int] = {}
    tracked_controller_input_owners: list[dict[str, object]] = []
    launch_policy_violations: list[dict[str, object]] = []
    for item in timeline:
        if str(item.get("event", "")).strip() != "process.launch":
            continue
        launch_intent = str(item.get("launch_intent", "")).strip() or "unknown"
        launch_intent_counts[launch_intent] = launch_intent_counts.get(launch_intent, 0) + 1
        controller_input_owner_allowed = bool(item.get("controller_input_owner_allowed", False))
        stdin_policy = str(item.get("stdin_policy", "")).strip().lower() or "unknown"
        if controller_input_owner_allowed:
            tracked_controller_input_owners.append(
                {
                    "launch_intent": launch_intent,
                    "pid": item.get("pid"),
                    "stdin_policy": stdin_policy,
                    "cwd": str(item.get("cwd", "")).strip(),
                }
            )
        if launch_intent in {"background_service", "probe"} and (
            controller_input_owner_allowed or stdin_policy != "devnull"
        ):
            launch_policy_violations.append(
                {
                    "launch_intent": launch_intent,
                    "pid": item.get("pid"),
                    "stdin_policy": stdin_policy,
                    "controller_input_owner_allowed": controller_input_owner_allowed,
                }
            )
    input_backends = {
        str(item.get("backend", "")).strip()
        for item in timeline
        if str(item.get("event", "")) in {"ui.input.backend", "ui.input.read.begin"}
        and str(item.get("backend", "")).strip()
    }
    tty_transition_observed = any(str(item.get("event", "")) == "ui.tty.transition" for item in timeline)
    tty_transition_required = "fallback" in input_backends
    if tty_transition_required and not tty_transition_observed:
        next_data_needed.append("TTY transition events missing; verify terminal_session debug wiring.")
    if launch_policy_violations:
        issues.append({"code": "launch_policy_input_owner_violation", "confidence": 0.98})
        probable.append(
            "A non-interactive child launch inherited controller input; inspect launch_policy_violations and tracked_controller_input_owners."
        )

    payload = {
        "issues": issues,
        "probable_root_causes": probable,
        "next_data_needed": next_data_needed,
        "spinner_disabled_reasons": spinner_disabled_actionable_reasons,
        "spinner_disabled_reasons_raw": spinner_disabled_reasons,
        "missing_spinner_lifecycle_transition": missing_spinner_lifecycle_transition,
        "suite_spinner_group_disabled_reasons": suite_spinner_group_disabled_reasons,
        "suite_spinner_group_runtime": suite_spinner_runtime[:3],
        "selector_inactive_tokens": selector_diagnostics.inactive_tokens[:10],
        "selector_low_throughput": selector_diagnostics.low_throughput[:10],
        "selector_mouse_double_toggle": selector_diagnostics.mouse_double_toggle,
        "selector_blocked_submit_then_cancel": selector_diagnostics.blocked_then_cancel,
        "selector_key_pipeline_gaps": selector_diagnostics.key_pipeline_gaps[:10],
        "selector_read_pipeline_gaps": selector_diagnostics.read_pipeline_gaps[:10],
        "selector_driver_focus_loss": selector_diagnostics.driver_focus_loss[:10],
        "selector_idle_after_activity": selector_diagnostics.idle_after_activity[:10],
        "anomaly_event_names": anomaly_event_names[:20],
        "startup_breakdown": startup_diagnostics.startup_breakdown,
        "slowest_components": startup_diagnostics.slowest_components[:20],
        "resume_skip_reasons": dict(sorted(startup_diagnostics.resume_skip_reasons.items(), key=lambda item: item[0])),
        "requirements_stage_hotspots": startup_diagnostics.requirements_stage_hotspots[:20],
        "service_bootstrap_hotspots": startup_diagnostics.service_bootstrap_hotspots[:20],
        "service_attach_hotspots": startup_diagnostics.service_attach_hotspots[:20],
        "launch_intent_counts": dict(sorted(launch_intent_counts.items(), key=lambda item: item[0])),
        "tracked_controller_input_owners": tracked_controller_input_owners[:20],
        "launch_policy_violations": launch_policy_violations[:20],
        "generated_at": datetime.now(tz=UTC).isoformat(),
    }
    (staging_dir / "diagnostics.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
