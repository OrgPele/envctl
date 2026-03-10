from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from typing import Any

from envctl_engine.debug.debug_bundle import pack_debug_bundle
from envctl_engine.debug.debug_utils import debug_env_value
from envctl_engine.shared.parsing import parse_bool, parse_float


def debug_pack(runtime: Any, route: Any) -> int:
    scope_id_value = route.flags.get("scope_id")
    explicit_scope = isinstance(scope_id_value, str) and bool(scope_id_value.strip())
    scope_id = scope_id_value if isinstance(scope_id_value, str) else runtime.config.runtime_scope_id
    runtime_scope_dir = runtime.runtime_root
    if isinstance(scope_id, str) and scope_id and scope_id != runtime.config.runtime_scope_id:
        runtime_scope_dir = runtime.config.runtime_dir / "python-engine" / scope_id

    session_id_value = route.flags.get("session_id")
    session_id = session_id_value if isinstance(session_id_value, str) else None
    run_id_value = route.flags.get("run_id")
    run_id = run_id_value if isinstance(run_id_value, str) else None
    explicit_run_id = run_id if isinstance(run_id, str) and run_id.strip() else None
    if explicit_run_id is not None:
        scope_run_id = runtime._scope_latest_run_id(runtime_scope_dir)
        if isinstance(scope_run_id, str) and scope_run_id and scope_run_id != explicit_run_id:
            print(
                f"Note: using explicit run_id={explicit_run_id}; "
                f"current scope run_id={scope_run_id}."
            )
    if session_id is None and run_id is None:
        latest_state = runtime.state_repository.load_latest(mode=None, strict_mode_match=False)
        if latest_state is not None and isinstance(latest_state.run_id, str) and latest_state.run_id:
            run_id = latest_state.run_id
    if session_id is None and run_id is None and not explicit_scope:
        local_session = runtime._latest_scope_session_id(runtime_scope_dir)
        if local_session is not None:
            session_id = local_session
        else:
            fallback = runtime._latest_debug_scope_session()
            if fallback is not None:
                scope_id, runtime_scope_dir, session_id = fallback
    output_dir_value = route.flags.get("output_dir")
    output_dir_raw = output_dir_value if isinstance(output_dir_value, str) else None
    output_dir = Path(output_dir_raw).expanduser() if output_dir_raw else None

    strict = parse_bool(debug_env_value(runtime.env, "ENVCTL_DEBUG_UI_BUNDLE_STRICT"), True)
    include_doctor = bool(route.flags.get("debug_ui_include_doctor"))
    timeout_raw = route.flags.get("timeout")
    timeout = parse_float(str(timeout_raw) if timeout_raw is not None else None, 5.0)
    doctor_text = runtime._debug_doctor_snapshot_text() if include_doctor else None

    try:
        bundle_path = pack_debug_bundle(
            runtime_scope_dir=runtime_scope_dir,
            session_id=session_id,
            run_id=run_id,
            scope_id=scope_id if isinstance(scope_id, str) and scope_id else runtime.config.runtime_scope_id,
            output_dir=output_dir,
            strict=strict,
            include_doctor=include_doctor,
            doctor_text=doctor_text,
            timeout=timeout,
        )
    except (OSError, RuntimeError, TimeoutError, FileNotFoundError) as exc:
        print(str(exc))
        return 1

    print(str(bundle_path))
    runtime._last_debug_bundle_path = str(bundle_path)
    try:
        latest = runtime_scope_dir / "debug" / "latest_bundle"
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text(str(bundle_path), encoding="utf-8")
    except OSError:
        pass
    return 0


def scope_latest_run_id(scope_dir: Path) -> str | None:
    state_path = scope_dir / "run_state.json"
    if not state_path.is_file():
        return None
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = payload.get("run_id")
    if isinstance(value, str):
        normalized = value.strip()
        if normalized:
            return normalized
    return None


def latest_scope_session_id(scope_dir: Path) -> str | None:
    debug_dir = scope_dir / "debug"
    if not debug_dir.is_dir():
        return None
    latest = debug_dir / "latest"
    if latest.is_file():
        try:
            latest_session = latest.read_text(encoding="utf-8").strip()
        except OSError:
            latest_session = ""
        if latest_session and (debug_dir / latest_session).is_dir():
            return latest_session
    sessions = [entry for entry in debug_dir.iterdir() if entry.is_dir() and entry.name.startswith("session-")]
    if not sessions:
        return None
    sessions.sort(key=lambda entry: entry.stat().st_mtime, reverse=True)
    return sessions[0].name


def latest_debug_scope_session(runtime: Any) -> tuple[str, Path, str] | None:
    root = runtime.config.runtime_dir / "python-engine"
    if not root.is_dir():
        return None
    selected: tuple[float, str, Path, str] | None = None
    for scope_dir in root.iterdir():
        if not scope_dir.is_dir():
            continue
        debug_dir = scope_dir / "debug"
        session_id = latest_scope_session_id(scope_dir)
        if session_id is None:
            continue
        session_dir = debug_dir / session_id
        try:
            stamp = session_dir.stat().st_mtime
        except OSError:
            continue
        candidate = (stamp, scope_dir.name, scope_dir, session_id)
        if selected is None or stamp > selected[0]:
            selected = candidate
    if selected is None:
        return None
    _, scope_id, scope_dir, session_id = selected
    return scope_id, scope_dir, session_id


def debug_doctor_snapshot_text(runtime: Any) -> str:
    stream = io.StringIO()
    with redirect_stdout(stream):
        runtime.doctor_orchestrator.execute()
    payload = stream.getvalue()
    if payload.strip():
        return payload
    return "doctor snapshot unavailable\n"


def debug_last(runtime: Any, route: object) -> int:
    _ = route
    if runtime._last_debug_bundle_path:
        print(runtime._last_debug_bundle_path)
        return 0
    latest = runtime.runtime_root / "debug" / "latest_bundle"
    if latest.is_file():
        payload = latest.read_text(encoding="utf-8").strip()
        if payload:
            print(payload)
            return 0
    print("No debug bundle has been created yet.")
    return 1


def debug_report(runtime: Any, route: object) -> int:
    from envctl_engine.debug.debug_bundle import summarize_debug_bundle

    if runtime._debug_pack(route) != 0:
        return 1
    bundle_path = runtime._last_debug_bundle_path
    if not bundle_path:
        latest = runtime.runtime_root / "debug" / "latest_bundle"
        if latest.is_file():
            bundle_path = latest.read_text(encoding="utf-8").strip()
    if not bundle_path:
        print("Debug report unavailable: missing bundle path.")
        return 1
    try:
        summary = summarize_debug_bundle(Path(bundle_path))
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc))
        return 1
    print(f"bundle: {bundle_path}")
    session_id_value = summary.get("session_id")
    session_id = session_id_value if isinstance(session_id_value, str) else ""
    session_id = session_id.strip() or "unknown"
    print(f"session_id: {session_id}")
    print(f"events: {summary.get('events', 0)} anomalies: {summary.get('anomalies', 0)}")
    probable = summary.get("probable_root_causes", [])
    if isinstance(probable, list) and probable:
        print("probable_root_causes:")
        for item in probable[:5]:
            print(f"- {item}")
    else:
        print("probable_root_causes: none")
    next_data = summary.get("next_data_needed", [])
    if isinstance(next_data, list) and next_data:
        print("next_data_needed:")
        for item in next_data[:5]:
            print(f"- {item}")
    startup_breakdown = summary.get("startup_breakdown", {})
    if isinstance(startup_breakdown, dict) and startup_breakdown:
        measured = float(startup_breakdown.get("measured_window_ms", 0.0) or 0.0)
        known = float(startup_breakdown.get("known_total_ms", 0.0) or 0.0)
        unknown = float(startup_breakdown.get("unknown_ms", 0.0) or 0.0)
        ratio = float(startup_breakdown.get("unknown_ratio", 0.0) or 0.0)
        print("startup_breakdown:")
        print(
            "- "
            f"execution_mode={startup_breakdown.get('execution_mode', 'unknown')} "
            f"workers={startup_breakdown.get('workers', 0)} "
            f"measured_window_ms={measured:.2f} "
            f"known_total_ms={known:.2f} "
            f"unknown_ms={unknown:.2f} "
            f"unknown_ratio={ratio:.4f}"
        )
        print(
            "- "
            f"requirements_total_ms={float(startup_breakdown.get('requirements_total_ms', 0.0) or 0.0):.2f} "
            f"service_total_ms={float(startup_breakdown.get('service_total_ms', 0.0) or 0.0):.2f} "
            f"resume_restore_total_ms={float(startup_breakdown.get('resume_restore_total_ms', 0.0) or 0.0):.2f}"
        )
    slowest_components = summary.get("slowest_components", [])
    if isinstance(slowest_components, list) and slowest_components:
        print("slowest_components:")
        for item in slowest_components[:5]:
            if not isinstance(item, dict):
                continue
            print(
                "- "
                f"kind={item.get('kind', 'unknown')} "
                f"project={item.get('project', 'unknown')} "
                f"name={item.get('name', 'unknown')} "
                f"duration_ms={float(item.get('duration_ms', 0.0) or 0.0):.2f} "
                f"success={bool(item.get('success', False))}"
            )
    resume_skip_reasons = summary.get("resume_skip_reasons", {})
    if isinstance(resume_skip_reasons, dict) and resume_skip_reasons:
        print("resume_skip_reasons:")
        for reason, count in sorted(resume_skip_reasons.items()):
            print(f"- {reason}: {count}")
    requirements_stage_hotspots = summary.get("requirements_stage_hotspots", [])
    if isinstance(requirements_stage_hotspots, list) and requirements_stage_hotspots:
        print("requirements_stage_hotspots:")
        for item in requirements_stage_hotspots[:5]:
            if not isinstance(item, dict):
                continue
            print(f"- stage={item.get('stage', 'unknown')} total_ms={float(item.get('total_ms', 0.0) or 0.0):.2f}")
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
                details = f"reason={reason} backend={backend} rich_progress_supported={rich_supported} python={python_exe}"
                if rich_error:
                    details += f" rich_progress_error={rich_error}"
                print(f"- {details}")
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
    missing_lifecycle = summary.get("missing_spinner_lifecycle_transition", "")
    if isinstance(missing_lifecycle, str) and missing_lifecycle.strip():
        print(f"missing_spinner_lifecycle_transition: {missing_lifecycle}")
    return 0
