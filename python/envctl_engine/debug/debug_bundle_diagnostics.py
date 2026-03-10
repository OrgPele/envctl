from __future__ import annotations

import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

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
        {
            str(item.get("event", "")).strip()
            for item in anomalies
            if str(item.get("event", "")).strip()
        }
    )

    repeated = any(str(item.get("event", "")).endswith("input_repeated_burst") for item in anomalies)
    empty_submit = any(str(item.get("event", "")).endswith("empty_submit_with_bytes") for item in anomalies)
    state_changed_without_lifecycle = any(
        str(item.get("event", "")).endswith("state_changed_without_lifecycle_event")
        for item in anomalies
    )
    spinner_without_command_activity = any(
        str(item.get("event", "")).strip() == "ui.anomaly.spinner_without_command_activity"
        for item in timeline
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
                    or (
                        str(item.get("event", "")) == "ui.spinner.policy"
                        and not bool(item.get("enabled", True))
                    )
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

    def selector_token(item: Mapping[str, object]) -> str:
        selector_id = str(item.get("selector_id", "")).strip().lower()
        if selector_id:
            return f"id:{selector_id}"
        prompt = str(item.get("prompt", "")).strip().lower()
        if prompt:
            return f"prompt:{prompt}"
        return ""

    def _sum_counter_payload_local(value: object) -> int:
        if not isinstance(value, Mapping):
            return 0
        total = 0
        for raw_count in value.values():
            try:
                total += int(raw_count)
            except (TypeError, ValueError):
                continue
        return total

    selector_activity_events = {
        "ui.selector.key",
        "ui.selector.mouse",
        "ui.selector.focus",
        "ui.selector.submit",
    }
    latest_ts_mono = max(
        (int(item.get("ts_mono_ns")) for item in timeline if isinstance(item.get("ts_mono_ns"), int)),
        default=0,
    )
    selector_activity_counts: dict[str, int] = {}
    selector_key_counts: dict[str, int] = {}
    for item in timeline:
        event_name = str(item.get("event", "")).strip()
        if event_name not in selector_activity_events:
            continue
        token = selector_token(item)
        if not token:
            continue
        selector_activity_counts[token] = selector_activity_counts.get(token, 0) + 1
        if event_name == "ui.selector.key":
            selector_key_counts[token] = selector_key_counts.get(token, 0) + 1

    for item in timeline:
        if str(item.get("event", "")).strip() != "ui.selector.key.summary":
            continue
        token = selector_token(item)
        if not token:
            continue
        summary_total = _sum_counter_payload_local(item.get("handled_counts"))
        summary_total = max(summary_total, _sum_counter_payload_local(item.get("event_counts")))
        summary_total = max(summary_total, _sum_counter_payload_local(item.get("raw_counts")))
        if summary_total > selector_key_counts.get(token, 0):
            selector_key_counts[token] = summary_total

    for item in timeline:
        if str(item.get("event", "")).strip() != "ui.selector.key.snapshot":
            continue
        token = selector_token(item)
        if not token:
            continue
        snapshot_total = _sum_counter_payload_local(item.get("handled_counts"))
        snapshot_total = max(snapshot_total, _sum_counter_payload_local(item.get("event_counts")))
        snapshot_total = max(snapshot_total, _sum_counter_payload_local(item.get("raw_counts")))
        nav_total = int(item.get("nav_event_counter", 0)) if isinstance(item.get("nav_event_counter"), int) else 0
        snapshot_total = max(snapshot_total, nav_total)
        if snapshot_total > selector_key_counts.get(token, 0):
            selector_key_counts[token] = snapshot_total

    selector_inactive_tokens: list[str] = []
    selector_low_throughput: list[dict[str, object]] = []
    for item in timeline:
        if str(item.get("event", "")).strip() != "ui.selector.lifecycle":
            continue
        if str(item.get("phase", "")).strip().lower() != "enter":
            continue
        token = selector_token(item)
        if not token:
            continue
        interactions = int(selector_activity_counts.get(token, 0))
        if interactions > 0:
            continue
        enter_ts = int(item.get("ts_mono_ns")) if isinstance(item.get("ts_mono_ns"), int) else 0
        observed_window_ns = max(0, latest_ts_mono - enter_ts)
        if observed_window_ns < 1_000_000_000:
            continue
        selector_inactive_tokens.append(token)
        continue
    for item in timeline:
        if str(item.get("event", "")).strip() != "ui.selector.lifecycle":
            continue
        if str(item.get("phase", "")).strip().lower() != "enter":
            continue
        token = selector_token(item)
        if not token:
            continue
        enter_ts = int(item.get("ts_mono_ns")) if isinstance(item.get("ts_mono_ns"), int) else 0
        observed_window_ns = max(0, latest_ts_mono - enter_ts)
        if observed_window_ns < 2_000_000_000:
            continue
        key_total = int(selector_key_counts.get(token, 0))
        if key_total <= 1:
            selector_low_throughput.append(
                {
                    "selector": token,
                    "observed_window_ms": round(observed_window_ns / 1_000_000, 1),
                    "key_events": key_total,
                }
            )

    selector_mouse_double_toggle = False
    mouse_events = [
        item
        for item in timeline
        if str(item.get("event", "")).strip() == "ui.selector.mouse"
        and isinstance(item.get("ts_mono_ns"), int)
    ]
    mouse_events.sort(key=lambda item: int(item.get("ts_mono_ns", 0)))
    last_mouse_by_row: dict[tuple[str, str], int] = {}
    for item in mouse_events:
        token = selector_token(item)
        row_id = str(item.get("row_id", "")).strip()
        if not token or not row_id:
            continue
        ts = int(item.get("ts_mono_ns", 0))
        key = (token, row_id)
        previous = last_mouse_by_row.get(key)
        if previous is not None and 0 <= ts - previous <= 250_000_000:
            selector_mouse_double_toggle = True
            break
        last_mouse_by_row[key] = ts

    selector_blocked_then_cancel = False
    blocked_by_selector: set[str] = set()
    for item in timeline:
        if str(item.get("event", "")).strip() != "ui.selector.submit":
            continue
        token = selector_token(item)
        if not token:
            continue
        if bool(item.get("blocked", False)):
            blocked_by_selector.add(token)
            continue
        if bool(item.get("cancelled", False)) and token in blocked_by_selector:
            selector_blocked_then_cancel = True
            break

    def _sum_counter_payload(value: object) -> int:
        if not isinstance(value, Mapping):
            return 0
        total = 0
        for raw_count in value.values():
            try:
                total += int(raw_count)
            except (TypeError, ValueError):
                continue
        return total

    selector_driver_key_totals: dict[str, int] = {}
    selector_driver_key_names: dict[str, Mapping[str, object]] = {}
    selector_driver_non_key_names: dict[str, Mapping[str, object]] = {}
    selector_driver_non_key_totals: dict[str, int] = {}
    for item in timeline:
        if str(item.get("event", "")).strip() not in {"ui.selector.key.driver.summary", "ui.selector.key.driver.snapshot"}:
            continue
        token = selector_token(item)
        if not token:
            continue
        non_key = item.get("non_key_messages")
        if isinstance(non_key, Mapping):
            non_key_total = _sum_counter_payload_local(non_key)
            if non_key_total >= selector_driver_non_key_totals.get(token, -1):
                selector_driver_non_key_totals[token] = non_key_total
                selector_driver_non_key_names[token] = non_key
        key_total = int(item.get("key_events_total", 0)) if isinstance(item.get("key_events_total"), int) else 0
        if key_total <= selector_driver_key_totals.get(token, -1):
            continue
        selector_driver_key_totals[token] = key_total
        names = item.get("key_events_by_name")
        if isinstance(names, Mapping):
            selector_driver_key_names[token] = names

    selector_app_key_totals: dict[str, int] = {}
    for item in timeline:
        event_name = str(item.get("event", "")).strip()
        if event_name not in {"ui.selector.key.summary", "ui.selector.key.snapshot"}:
            continue
        token = selector_token(item)
        if not token:
            continue
        event_counts = _sum_counter_payload(item.get("event_counts"))
        handled_counts = _sum_counter_payload(item.get("handled_counts"))
        observed = max(event_counts, handled_counts)
        if observed <= selector_app_key_totals.get(token, -1):
            continue
        selector_app_key_totals[token] = observed

    selector_key_pipeline_gaps: list[dict[str, object]] = []
    for token, driver_total in selector_driver_key_totals.items():
        app_total = int(selector_app_key_totals.get(token, 0))
        if driver_total <= app_total:
            continue
        selector_key_pipeline_gaps.append(
            {
                "selector": token,
                "driver_key_events": driver_total,
                "app_key_events": app_total,
                "dropped_after_driver": driver_total - app_total,
                "driver_key_names": dict(selector_driver_key_names.get(token, {})),
            }
        )

    selector_read_pipeline_gaps: list[dict[str, object]] = []
    selector_driver_read_totals: dict[str, int] = {}
    selector_driver_escape_totals: dict[str, int] = {}
    for item in timeline:
        if str(item.get("event", "")).strip() not in {"ui.selector.key.driver.summary", "ui.selector.key.driver.snapshot"}:
            continue
        token = selector_token(item)
        if not token:
            continue
        read_bytes = int(item.get("read_bytes", 0)) if isinstance(item.get("read_bytes"), int) else 0
        if read_bytes <= selector_driver_read_totals.get(token, -1):
            continue
        selector_driver_read_totals[token] = read_bytes
        selector_driver_escape_totals[token] = (
            int(item.get("escape_bytes", 0)) if isinstance(item.get("escape_bytes"), int) else 0
        )
    for token, read_bytes in selector_driver_read_totals.items():
        non_key_total = int(selector_driver_non_key_totals.get(token, 0))
        if non_key_total > 0:
            continue
        escape_bytes = int(selector_driver_escape_totals.get(token, 0))
        if escape_bytes > 0:
            estimated_key_sequences = escape_bytes
            estimation_method = "escape_bytes"
        else:
            estimated_key_sequences = read_bytes // 3 if read_bytes > 0 else 0
            estimation_method = "read_bytes_div_3"
        driver_total = int(selector_driver_key_totals.get(token, 0))
        if estimated_key_sequences <= driver_total:
            continue
        selector_read_pipeline_gaps.append(
            {
                "selector": token,
                "read_bytes": read_bytes,
                "estimated_key_sequences": estimated_key_sequences,
                "driver_key_events": driver_total,
                "dropped_before_driver_parse": estimated_key_sequences - driver_total,
                "estimation_method": estimation_method,
                "non_key_messages": non_key_total,
            }
        )

    selector_driver_focus_loss: list[dict[str, object]] = []
    for token, names in selector_driver_non_key_names.items():
        app_blur = int(names.get("AppBlur", 0)) if isinstance(names.get("AppBlur"), int) else 0
        app_focus = int(names.get("AppFocus", 0)) if isinstance(names.get("AppFocus"), int) else 0
        if app_blur <= 0:
            continue
        if app_focus > 0:
            continue
        selector_driver_focus_loss.append(
            {
                "selector": token,
                "app_blur_events": app_blur,
                "app_focus_events": app_focus,
            }
        )

    selector_idle_after_activity: list[dict[str, object]] = []
    for item in timeline:
        if str(item.get("event", "")).strip() != "ui.selector.key.idle_after_activity":
            continue
        token = selector_token(item)
        if not token:
            continue
        idle_ms = int(item.get("idle_ms", 0)) if isinstance(item.get("idle_ms"), int) else 0
        nav_events = int(item.get("nav_event_counter", 0)) if isinstance(item.get("nav_event_counter"), int) else 0
        selector_idle_after_activity.append(
            {
                "selector": token,
                "idle_ms": idle_ms,
                "nav_event_counter": nav_events,
                "focused_widget_id": str(item.get("focused_widget_id", "")),
            }
        )

    startup_timeline = [
        item
        for item in timeline
        if str(item.get("source", "")).strip().lower() == "debug"
    ]

    startup_window_first: int | None = None
    startup_window_last: int | None = None
    startup_execution_mode = "unknown"
    startup_workers = 0
    startup_projects: list[str] = []
    requirements_total_ms = 0.0
    service_total_ms = 0.0
    resume_restore_total_ms = 0.0
    project_breakdown: dict[str, dict[str, object]] = {}
    slowest_components: list[dict[str, object]] = []
    resume_skip_reasons: dict[str, int] = {}
    requirements_stage_totals: dict[str, float] = {}
    service_bootstrap_totals: dict[str, float] = {}
    service_attach_totals: dict[str, float] = {}
    has_adapter_stage_detail = False
    has_command_timing_detail = False
    startup_events = {
        "startup.execution",
        "startup.phase",
        "resume.phase",
        "state.auto_resume",
        "state.auto_resume.skipped",
        "state.resume",
        "requirements.timing.component",
        "requirements.timing.summary",
        "service.timing.component",
        "service.timing.summary",
        "resume.restore.project_timing",
        "resume.restore.timing",
        "artifacts.write",
        "artifacts.runtime_readiness_report",
        "requirements.adapter",
        "requirements.adapter.stage",
        "requirements.adapter.command_timing",
        "service.bootstrap.phase",
        "service.attach.phase",
    }
    phase_totals: dict[str, float] = {}

    for item in startup_timeline:
        event_name = str(item.get("event", "")).strip()
        ts_value = item.get("ts_mono_ns")
        ts_mono_ns = int(ts_value) if isinstance(ts_value, int) else None
        if event_name in startup_events and ts_mono_ns is not None:
            startup_window_first = ts_mono_ns if startup_window_first is None else min(startup_window_first, ts_mono_ns)
            startup_window_last = ts_mono_ns if startup_window_last is None else max(startup_window_last, ts_mono_ns)

        if event_name == "startup.execution":
            startup_execution_mode = str(item.get("mode", "")).strip() or startup_execution_mode
            workers = item.get("workers")
            startup_workers = int(workers) if isinstance(workers, int) else startup_workers
            raw_projects = item.get("projects")
            if isinstance(raw_projects, list):
                startup_projects = [str(project).strip() for project in raw_projects if str(project).strip()]
            continue

        if event_name == "state.auto_resume.skipped":
            reason = str(item.get("reason", "")).strip() or "unknown"
            resume_skip_reasons[reason] = resume_skip_reasons.get(reason, 0) + 1
            continue

        if event_name == "requirements.timing.summary":
            project = str(item.get("project", "")).strip() or "unknown"
            duration_ms = float(item.get("duration_ms", 0.0) or 0.0)
            requirements_total_ms += duration_ms
            entry = project_breakdown.setdefault(
                project,
                {
                    "project": project,
                    "requirements_ms": 0.0,
                    "service_ms": 0.0,
                    "resume_restore_ms": 0.0,
                    "total_ms": 0.0,
                },
            )
            entry["requirements_ms"] = round(float(entry.get("requirements_ms", 0.0) or 0.0) + duration_ms, 2)
            continue

        if event_name in {"startup.phase", "resume.phase"}:
            phase = str(item.get("phase", "")).strip() or "unknown"
            duration_ms = round(float(item.get("duration_ms", 0.0) or 0.0), 2)
            phase_totals[phase] = round(phase_totals.get(phase, 0.0) + duration_ms, 2)
            slowest_components.append(
                {
                    "kind": "startup_phase" if event_name == "startup.phase" else "resume_phase",
                    "project": str(item.get("project", "")).strip() or "",
                    "name": phase,
                    "duration_ms": duration_ms,
                    "success": str(item.get("status", "ok")).strip().lower() not in {"error", "blocked", "degraded"},
                }
            )
            continue

        if event_name in {"artifacts.write", "artifacts.runtime_readiness_report"}:
            duration_ms = round(float(item.get("duration_ms", 0.0) or 0.0), 2)
            slowest_components.append(
                {
                    "kind": "artifacts",
                    "project": "",
                    "name": "write_total" if event_name == "artifacts.write" else "runtime_readiness_report",
                    "duration_ms": duration_ms,
                    "success": True,
                }
            )
            continue

        if event_name in {"service.bootstrap.phase", "service.attach.phase"}:
            phase = str(item.get("phase", "")).strip() or "unknown"
            component = str(item.get("component", "")).strip() or "unknown"
            project = str(item.get("project", "")).strip() or "unknown"
            duration_ms = round(float(item.get("duration_ms", 0.0) or 0.0), 2)
            key = f"{project}:{component}:{phase}"
            target_totals = service_bootstrap_totals if event_name == "service.bootstrap.phase" else service_attach_totals
            target_totals[key] = round(target_totals.get(key, 0.0) + duration_ms, 2)
            slowest_components.append(
                {
                    "kind": "service_bootstrap_phase" if event_name == "service.bootstrap.phase" else "service_attach_phase",
                    "project": project,
                    "name": f"{component}:{phase}",
                    "duration_ms": duration_ms,
                    "success": str(item.get("status", "ok")).strip().lower() not in {"error", "blocked", "degraded"},
                }
            )
            continue

        if event_name == "service.timing.summary":
            project = str(item.get("project", "")).strip() or "unknown"
            duration_ms = float(item.get("duration_ms", 0.0) or 0.0)
            service_total_ms += duration_ms
            entry = project_breakdown.setdefault(
                project,
                {
                    "project": project,
                    "requirements_ms": 0.0,
                    "service_ms": 0.0,
                    "resume_restore_ms": 0.0,
                    "total_ms": 0.0,
                },
            )
            entry["service_ms"] = round(float(entry.get("service_ms", 0.0) or 0.0) + duration_ms, 2)
            continue

        if event_name == "resume.restore.project_timing":
            project = str(item.get("project", "")).strip() or "unknown"
            duration_ms = float(item.get("total_ms", 0.0) or 0.0)
            resume_restore_total_ms += duration_ms
            entry = project_breakdown.setdefault(
                project,
                {
                    "project": project,
                    "requirements_ms": 0.0,
                    "service_ms": 0.0,
                    "resume_restore_ms": 0.0,
                    "total_ms": 0.0,
                },
            )
            entry["resume_restore_ms"] = round(float(entry.get("resume_restore_ms", 0.0) or 0.0) + duration_ms, 2)
            continue

        if event_name == "requirements.timing.component":
            slowest_components.append(
                {
                    "kind": "requirement",
                    "project": str(item.get("project", "")).strip() or "unknown",
                    "name": str(item.get("requirement", "")).strip() or "unknown",
                    "duration_ms": round(float(item.get("duration_ms", 0.0) or 0.0), 2),
                    "success": bool(item.get("success", False)),
                }
            )
            continue

        if event_name == "service.timing.component":
            slowest_components.append(
                {
                    "kind": "service",
                    "project": str(item.get("project", "")).strip() or "unknown",
                    "name": str(item.get("component", "")).strip() or "unknown",
                    "duration_ms": round(float(item.get("duration_ms", 0.0) or 0.0), 2),
                    "success": True,
                }
            )
            continue

        if event_name == "requirements.adapter.command_timing":
            has_command_timing_detail = True
            try:
                command_returncode = int(item.get("returncode", 1))
            except (TypeError, ValueError):
                command_returncode = 1
            slowest_components.append(
                {
                    "kind": "adapter_command",
                    "project": str(item.get("project", "")).strip() or "unknown",
                    "name": str(item.get("stage", "")).strip() or "command",
                    "duration_ms": round(float(item.get("duration_ms", 0.0) or 0.0), 2),
                    "success": command_returncode == 0,
                }
            )
            continue

        if event_name == "requirements.adapter.stage":
            has_adapter_stage_detail = True
            continue

        if event_name == "requirements.adapter":
            stage_map = item.get("stage_durations_ms")
            if not isinstance(stage_map, Mapping):
                continue
            for stage_name, raw_duration in stage_map.items():
                stage_key = str(stage_name).strip().lower()
                if not stage_key:
                    continue
                try:
                    duration = float(raw_duration)
                except (TypeError, ValueError):
                    continue
                requirements_stage_totals[stage_key] = round(requirements_stage_totals.get(stage_key, 0.0) + duration, 2)

    for entry in project_breakdown.values():
        requirements_ms = float(entry.get("requirements_ms", 0.0) or 0.0)
        service_ms = float(entry.get("service_ms", 0.0) or 0.0)
        resume_ms = float(entry.get("resume_restore_ms", 0.0) or 0.0)
        entry["total_ms"] = round(requirements_ms + service_ms + resume_ms, 2)

    if not slowest_components:
        for entry in project_breakdown.values():
            project = str(entry.get("project", "")).strip() or "unknown"
            requirements_ms = round(float(entry.get("requirements_ms", 0.0) or 0.0), 2)
            service_ms = round(float(entry.get("service_ms", 0.0) or 0.0), 2)
            resume_ms = round(float(entry.get("resume_restore_ms", 0.0) or 0.0), 2)
            if requirements_ms > 0:
                slowest_components.append(
                    {
                        "kind": "requirements_summary",
                        "project": project,
                        "name": "requirements_total",
                        "duration_ms": requirements_ms,
                        "success": True,
                    }
                )
            if service_ms > 0:
                slowest_components.append(
                    {
                        "kind": "service_summary",
                        "project": project,
                        "name": "service_total",
                        "duration_ms": service_ms,
                        "success": True,
                    }
                )
            if resume_ms > 0:
                slowest_components.append(
                    {
                        "kind": "resume_summary",
                        "project": project,
                        "name": "resume_restore_total",
                        "duration_ms": resume_ms,
                        "success": True,
                    }
                )

    project_rows = sorted(
        project_breakdown.values(),
        key=lambda row: float(row.get("total_ms", 0.0) or 0.0),
        reverse=True,
    )
    slowest_components.sort(key=lambda item: float(item.get("duration_ms", 0.0) or 0.0), reverse=True)
    requirements_stage_hotspots = [
        {"stage": stage, "total_ms": round(total, 2)}
        for stage, total in sorted(requirements_stage_totals.items(), key=lambda item: item[1], reverse=True)
    ]
    service_bootstrap_hotspots = [
        {"target": target, "total_ms": round(total, 2)}
        for target, total in sorted(service_bootstrap_totals.items(), key=lambda item: item[1], reverse=True)
    ]
    service_attach_hotspots = [
        {"target": target, "total_ms": round(total, 2)}
        for target, total in sorted(service_attach_totals.items(), key=lambda item: item[1], reverse=True)
    ]

    measured_window_ms = 0.0
    if startup_window_first is not None and startup_window_last is not None and startup_window_last >= startup_window_first:
        measured_window_ms = round((startup_window_last - startup_window_first) / 1_000_000.0, 2)
    known_total_ms = round(requirements_total_ms + service_total_ms + resume_restore_total_ms, 2)
    unknown_ms = round(max(0.0, measured_window_ms - known_total_ms), 2)
    unknown_ratio = round((unknown_ms / measured_window_ms), 4) if measured_window_ms > 0 else 0.0
    startup_breakdown = {
        "execution_mode": startup_execution_mode,
        "workers": startup_workers,
        "projects": startup_projects,
        "measured_window_ms": measured_window_ms,
        "known_total_ms": known_total_ms,
        "unknown_ms": unknown_ms,
        "unknown_ratio": unknown_ratio,
        "requirements_total_ms": round(requirements_total_ms, 2),
        "service_total_ms": round(service_total_ms, 2),
        "resume_restore_total_ms": round(resume_restore_total_ms, 2),
        "phase_breakdown": [
            {"phase": phase, "total_ms": round(total, 2)}
            for phase, total in sorted(phase_totals.items(), key=lambda item: item[1], reverse=True)
        ],
        "project_breakdown": project_rows[:20],
    }

    if repeated:
        issues.append({"code": "input_repeated_burst", "confidence": 0.9})
        probable.append("Input backend likely duplicated buffered characters (burst typing replay).")
    if empty_submit:
        issues.append({"code": "empty_submit_with_bytes", "confidence": 0.8})
        probable.append("TTY newline delivered without parseable command token.")
    if state_changed_without_lifecycle:
        issues.append({"code": "state_changed_without_lifecycle_event", "confidence": 0.75})
        probable.append("Run state fingerprint changed without a matching lifecycle event; inspect service truth reconciliation transitions.")
    if spinner_without_command_activity:
        issues.append({"code": "spinner_without_command_activity", "confidence": 0.7})
        probable.append("Spinner policy was enabled for command dispatch but no spinner-starting activity events were observed.")
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
    if selector_inactive_tokens:
        issues.append({"code": "selector_input_inactive", "confidence": 0.9})
        probable.append("Selector entered but no key/mouse/focus events were observed; input/focus pipeline likely stalled.")
    if selector_low_throughput:
        issues.append({"code": "selector_input_low_throughput", "confidence": 0.85})
        probable.append("Selector key throughput is abnormally low for observed selector duration; investigate terminal input pipeline.")
    if selector_mouse_double_toggle:
        issues.append({"code": "selector_mouse_double_toggle", "confidence": 0.75})
        probable.append("Selector click handling may be double-dispatching toggles in a short debounce window.")
    if selector_blocked_then_cancel:
        issues.append({"code": "selector_blocked_submit_then_cancel", "confidence": 0.7})
        probable.append("Selector submit was blocked and then cancelled, indicating unstable focus/selection handoff.")
    if selector_key_pipeline_gaps:
        issues.append({"code": "selector_key_pipeline_gap", "confidence": 0.95})
        probable.append("Selector key events are dropping between parser ingress and app-level handling.")
    if selector_read_pipeline_gaps:
        issues.append({"code": "selector_read_pipeline_gap", "confidence": 0.9})
        probable.append("Raw selector input bytes suggest additional key sequences dropped before parser key events.")
    if selector_driver_focus_loss:
        issues.append({"code": "selector_driver_focus_loss", "confidence": 0.9})
        probable.append("Terminal focus-out events occurred during selector input without corresponding focus-in recovery.")
    if selector_idle_after_activity:
        issues.append({"code": "selector_input_stalled_after_activity", "confidence": 0.9})
        probable.append("Selector accepted initial navigation keys but then went idle; inspect selector key driver snapshots and focus events.")
    if known_total_ms > 0 and requirements_total_ms / max(known_total_ms, 1.0) >= 0.7:
        issues.append({"code": "startup_requirements_dominant", "confidence": 0.9})
        probable.append("Startup latency is dominated by requirement lifecycle timing rather than application service attach timing.")
    if resume_skip_reasons:
        issues.append({"code": "startup_auto_resume_skipped", "confidence": 0.85})
        probable.append("Auto-resume was skipped for at least one startup path; inspect resume_skip_reasons and selected/state project sets.")
    if requirements_stage_hotspots:
        top_stage = str(requirements_stage_hotspots[0].get("stage", "")).strip().lower()
        if top_stage in {"listener_wait", "probe", "restart", "recreate"}:
            issues.append({"code": "requirements_stage_hotspot", "confidence": 0.8})
            probable.append("Requirement adapter timing is concentrated in listener/probe/retry stages; inspect requirements_stage_hotspots.")
    if not anomalies:
        next_data_needed.append("No anomalies captured; rerun with ENVCTL_DEBUG_UI_MODE=deep.")
    if requirements_total_ms > 0 and not has_adapter_stage_detail:
        next_data_needed.append("Requirement stage-level traces missing; rerun with ENVCTL_DEBUG_REQUIREMENTS_TRACE=1.")
    if requirements_total_ms > 0 and not has_command_timing_detail:
        next_data_needed.append("Docker command timing traces missing; rerun with ENVCTL_DEBUG_DOCKER_COMMAND_TIMING=1.")
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
        "selector_inactive_tokens": selector_inactive_tokens[:10],
        "selector_low_throughput": selector_low_throughput[:10],
        "selector_mouse_double_toggle": selector_mouse_double_toggle,
        "selector_blocked_submit_then_cancel": selector_blocked_then_cancel,
        "selector_key_pipeline_gaps": selector_key_pipeline_gaps[:10],
        "selector_read_pipeline_gaps": selector_read_pipeline_gaps[:10],
        "selector_driver_focus_loss": selector_driver_focus_loss[:10],
        "selector_idle_after_activity": selector_idle_after_activity[:10],
        "anomaly_event_names": anomaly_event_names[:20],
        "startup_breakdown": startup_breakdown,
        "slowest_components": slowest_components[:20],
        "resume_skip_reasons": dict(sorted(resume_skip_reasons.items(), key=lambda item: item[0])),
        "requirements_stage_hotspots": requirements_stage_hotspots[:20],
        "service_bootstrap_hotspots": service_bootstrap_hotspots[:20],
        "service_attach_hotspots": service_attach_hotspots[:20],
        "launch_intent_counts": dict(sorted(launch_intent_counts.items(), key=lambda item: item[0])),
        "tracked_controller_input_owners": tracked_controller_input_owners[:20],
        "launch_policy_violations": launch_policy_violations[:20],
        "generated_at": datetime.now(tz=UTC).isoformat(),
    }
    (staging_dir / "diagnostics.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
