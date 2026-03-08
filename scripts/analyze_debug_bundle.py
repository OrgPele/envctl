#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tarfile
from pathlib import Path
import sys
from typing import IO

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.debug.debug_bundle import summarize_debug_bundle


def _count_jsonl(handle: IO[bytes]) -> int:
    data = handle.read()
    text = data.decode("utf-8")
    return sum(1 for line in text.splitlines() if line.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze envctl debug bundle")
    parser.add_argument("bundle", help="Path to envctl-debug-bundle.tar.gz")
    args = parser.parse_args()

    bundle_path = Path(args.bundle)
    if not bundle_path.is_file():
        raise SystemExit(f"Bundle not found: {bundle_path}")

    with tarfile.open(bundle_path, "r:gz") as tar:
        names = tar.getnames()
        print("Bundle contents:")
        for name in sorted(names):
            print(f"- {name}")
        if "events.debug.jsonl" in names:
            member = tar.extractfile("events.debug.jsonl")
            if member is not None:
                print(f"events.debug.jsonl: {_count_jsonl(member)} events")
        if "anomalies.jsonl" in names:
            member = tar.extractfile("anomalies.jsonl")
            if member is not None:
                print(f"anomalies.jsonl: {_count_jsonl(member)} anomalies")
        if "manifest.json" in names:
            member = tar.extractfile("manifest.json")
            if member is not None:
                payload = json.loads(member.read().decode("utf-8"))
                print(f"manifest.json: {payload.get('session_id', '')}")

    summary = summarize_debug_bundle(bundle_path)
    print("Summary:")
    print(f"- events: {summary.get('events', 0)}")
    print(f"- anomalies: {summary.get('anomalies', 0)}")
    probable = summary.get("probable_root_causes", [])
    if isinstance(probable, list) and probable:
        print("Probable root causes:")
        for item in probable[:5]:
            print(f"- {item}")
    next_data = summary.get("next_data_needed", [])
    if isinstance(next_data, list) and next_data:
        print("Next data needed:")
        for item in next_data[:5]:
            print(f"- {item}")
    spinner_reasons = summary.get("spinner_disabled_reasons", [])
    if isinstance(spinner_reasons, list) and spinner_reasons:
        print("spinner_disabled_reasons:")
        for item in spinner_reasons[:5]:
            print(f"- {item}")
    suite_spinner_reasons = summary.get("suite_spinner_group_disabled_reasons", [])
    if isinstance(suite_spinner_reasons, list) and suite_spinner_reasons:
        print("suite_spinner_group_disabled_reasons:")
        for item in suite_spinner_reasons[:5]:
            print(f"- {item}")
    suite_spinner_runtime = summary.get("suite_spinner_group_runtime", [])
    if isinstance(suite_spinner_runtime, list) and suite_spinner_runtime:
        print("suite_spinner_group_runtime:")
        for item in suite_spinner_runtime[:3]:
            if isinstance(item, dict):
                reason = str(item.get("reason", "")).strip() or "unknown"
                backend = str(item.get("backend", "")).strip() or "unknown"
                python_exe = str(item.get("python_executable", "")).strip() or "unknown"
                rich_supported = bool(item.get("rich_progress_supported", False))
                rich_error = str(item.get("rich_progress_error", "")).strip()
                line = f"reason={reason} backend={backend} rich_progress_supported={rich_supported} python={python_exe}"
                if rich_error:
                    line += f" rich_progress_error={rich_error}"
                print(f"- {line}")
    missing_lifecycle = summary.get("missing_spinner_lifecycle_transition", "")
    if isinstance(missing_lifecycle, str) and missing_lifecycle.strip():
        print(f"missing_spinner_lifecycle_transition: {missing_lifecycle}")

    startup_breakdown = summary.get("startup_breakdown", {})
    if isinstance(startup_breakdown, dict) and startup_breakdown:
        print("startup_breakdown:")
        measured = float(startup_breakdown.get("measured_window_ms", 0.0) or 0.0)
        known = float(startup_breakdown.get("known_total_ms", 0.0) or 0.0)
        unknown = float(startup_breakdown.get("unknown_ms", 0.0) or 0.0)
        ratio = float(startup_breakdown.get("unknown_ratio", 0.0) or 0.0)
        mode = str(startup_breakdown.get("execution_mode", "unknown"))
        workers = startup_breakdown.get("workers", 0)
        print(f"- execution_mode={mode} workers={workers}")
        print(f"- measured_window_ms={measured:.2f} known_total_ms={known:.2f} unknown_ms={unknown:.2f} unknown_ratio={ratio:.4f}")
        print(
            "- requirements_total_ms="
            f"{float(startup_breakdown.get('requirements_total_ms', 0.0) or 0.0):.2f} "
            "service_total_ms="
            f"{float(startup_breakdown.get('service_total_ms', 0.0) or 0.0):.2f} "
            "resume_restore_total_ms="
            f"{float(startup_breakdown.get('resume_restore_total_ms', 0.0) or 0.0):.2f}"
        )
        phase_breakdown = startup_breakdown.get("phase_breakdown", [])
        if isinstance(phase_breakdown, list) and phase_breakdown:
            print("phase_breakdown:")
            for item in phase_breakdown[:10]:
                if not isinstance(item, dict):
                    continue
                phase = str(item.get("phase", "unknown"))
                total_ms = float(item.get("total_ms", 0.0) or 0.0)
                print(f"- phase={phase} total_ms={total_ms:.2f}")

    slowest_components = summary.get("slowest_components", [])
    if isinstance(slowest_components, list) and slowest_components:
        print("slowest_components:")
        for item in slowest_components[:5]:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", "unknown"))
            project = str(item.get("project", "unknown"))
            name = str(item.get("name", "unknown"))
            duration = float(item.get("duration_ms", 0.0) or 0.0)
            success = bool(item.get("success", False))
            print(f"- kind={kind} project={project} name={name} duration_ms={duration:.2f} success={success}")

    skip_reasons = summary.get("resume_skip_reasons", {})
    if isinstance(skip_reasons, dict) and skip_reasons:
        print("resume_skip_reasons:")
        for reason, count in sorted(skip_reasons.items()):
            print(f"- {reason}: {count}")

    stage_hotspots = summary.get("requirements_stage_hotspots", [])
    if isinstance(stage_hotspots, list) and stage_hotspots:
        print("requirements_stage_hotspots:")
        for item in stage_hotspots[:5]:
            if not isinstance(item, dict):
                continue
            stage = str(item.get("stage", "unknown"))
            total_ms = float(item.get("total_ms", 0.0) or 0.0)
            print(f"- stage={stage} total_ms={total_ms:.2f}")
    bootstrap_hotspots = summary.get("service_bootstrap_hotspots", [])
    if isinstance(bootstrap_hotspots, list) and bootstrap_hotspots:
        print("service_bootstrap_hotspots:")
        for item in bootstrap_hotspots[:5]:
            if not isinstance(item, dict):
                continue
            target = str(item.get("target", "unknown"))
            total_ms = float(item.get("total_ms", 0.0) or 0.0)
            print(f"- target={target} total_ms={total_ms:.2f}")
    attach_hotspots = summary.get("service_attach_hotspots", [])
    if isinstance(attach_hotspots, list) and attach_hotspots:
        print("service_attach_hotspots:")
        for item in attach_hotspots[:5]:
            if not isinstance(item, dict):
                continue
            target = str(item.get("target", "unknown"))
            total_ms = float(item.get("total_ms", 0.0) or 0.0)
            print(f"- target={target} total_ms={total_ms:.2f}")
    launch_intent_counts = summary.get("launch_intent_counts", {})
    if isinstance(launch_intent_counts, dict) and launch_intent_counts:
        print("launch_intent_counts:")
        for intent, count in sorted(launch_intent_counts.items()):
            print(f"- {intent}: {count}")
    tracked_input_owners = summary.get("tracked_controller_input_owners", [])
    if isinstance(tracked_input_owners, list) and tracked_input_owners:
        print("tracked_controller_input_owners:")
        for item in tracked_input_owners[:5]:
            if not isinstance(item, dict):
                continue
            intent = str(item.get("launch_intent", "")).strip() or "unknown"
            pid = item.get("pid")
            stdin_policy = str(item.get("stdin_policy", "")).strip() or "unknown"
            print(f"- intent={intent} pid={pid} stdin_policy={stdin_policy}")
    launch_policy_violations = summary.get("launch_policy_violations", [])
    if isinstance(launch_policy_violations, list) and launch_policy_violations:
        print("launch_policy_violations:")
        for item in launch_policy_violations[:5]:
            if not isinstance(item, dict):
                continue
            intent = str(item.get("launch_intent", "")).strip() or "unknown"
            pid = item.get("pid")
            stdin_policy = str(item.get("stdin_policy", "")).strip() or "unknown"
            allowed = bool(item.get("controller_input_owner_allowed", False))
            print(f"- intent={intent} pid={pid} stdin_policy={stdin_policy} controller_input_owner_allowed={allowed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
