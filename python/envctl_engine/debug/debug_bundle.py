from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from envctl_engine.debug.debug_bundle_diagnostics import summarize_debug_bundle, write_diagnostics
from envctl_engine.debug.debug_bundle_support import (
    copy_debug_session_files,
    create_tarball,
    ensure_summary,
    resolve_session_id,
    sanitize_runtime_event,
    write_bundle_contract,
    write_command_index,
    write_manifest,
    write_redacted_runtime_events,
    write_timeline,
)
from envctl_engine.debug.debug_utils import file_lock


def pack_debug_bundle(
    *,
    runtime_scope_dir: Path,
    session_id: str | None,
    run_id: str | None,
    scope_id: str,
    output_dir: Path | None,
    strict: bool,
    include_doctor: bool,
    doctor_text: str | None = None,
    timeout: float,
) -> Path:
    debug_root = runtime_scope_dir / "debug"
    resolved_session_id = resolve_session_id(debug_root, session_id=session_id, run_id=run_id)
    session_dir = debug_root / resolved_session_id
    if not session_dir.is_dir():
        raise FileNotFoundError(f"Debug session not found: {resolved_session_id}")

    output_root = output_dir or session_dir
    output_root.mkdir(parents=True, exist_ok=True)
    bundle_name = f"envctl-debug-bundle-{resolved_session_id}.tar.gz"
    bundle_path = output_root / bundle_name
    staging_dir = output_root / f".debug-pack-{resolved_session_id}-{uuid.uuid4().hex[:6]}"

    with file_lock(debug_root / "debug.lock", timeout=timeout):
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=True)
        copy_debug_session_files(
            session_dir,
            staging_dir,
            strict=strict,
            include_doctor=include_doctor,
            doctor_text=doctor_text,
        )
        write_redacted_runtime_events(
            runtime_scope_dir=runtime_scope_dir,
            output_path=staging_dir / "events.runtime.redacted.jsonl",
            salt=resolved_session_id,
        )
        write_timeline(staging_dir)
        write_command_index(staging_dir)
        write_diagnostics(staging_dir)
        write_bundle_contract(staging_dir, strict=strict)
        ensure_summary(staging_dir)
        write_manifest(staging_dir, scope_id=scope_id, strict=strict, session_id=resolved_session_id)
        create_tarball(bundle_path, staging_dir)
        shutil.rmtree(staging_dir, ignore_errors=True)
    try:
        latest = runtime_scope_dir / "debug" / "latest_bundle"
        latest.write_text(str(bundle_path), encoding="utf-8")
    except OSError:
        pass
    return bundle_path
