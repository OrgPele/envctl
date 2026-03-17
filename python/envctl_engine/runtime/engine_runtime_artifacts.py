from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from envctl_engine.runtime.runtime_readiness import (
    GAP_REPORT_RELATIVE_PATH,
    build_runtime_readiness_report,
    evaluate_runtime_readiness,
)
from envctl_engine.state.runtime_map import build_runtime_map


def write_artifacts(runtime: Any, state: object, contexts: list[object], *, errors: list[str]) -> None:
    started = time.monotonic()
    cached = _cached_runtime_readiness_payload(runtime)
    paths = runtime.state_repository.save_run(
        state=state,
        contexts=list(contexts),
        errors=list(errors),
        events=list(runtime.events),
        emit=runtime._emit,
        runtime_map_builder=build_runtime_map,
        write_runtime_readiness_report=(
            (lambda run_dir: _write_cached_runtime_readiness_payload(runtime, run_dir=run_dir, cached=cached))
            if cached is not None
            else (lambda run_dir: _write_pending_runtime_readiness_payload(runtime, run_dir=run_dir))
        ),
    )
    runtime._emit(
        "artifacts.write",
        duration_ms=round((time.monotonic() - started) * 1000.0, 2),
        project_count=len(contexts),
        error_count=len(errors),
    )
    if cached is None and _runtime_readiness_async_enabled(runtime):
        _start_background_runtime_readiness_report(runtime, run_dir=paths.run_dir)
    elif cached is None and hasattr(paths, "run_dir"):
        write_runtime_readiness_report(runtime, run_dir=paths.run_dir)


def write_runtime_readiness_report(
    runtime: Any,
    *,
    run_dir: Path | None = None,
    readiness_result: object | None = None,
) -> None:
    started = time.monotonic()
    emit = getattr(runtime, "_emit", None)
    cached = _cached_runtime_readiness_payload(runtime)
    if readiness_result is None and cached is not None:
        _write_runtime_readiness_payload(runtime, report_text=cached, run_dir=run_dir)
        if callable(emit):
            emit(
                "artifacts.runtime_readiness_report",
                duration_ms=round((time.monotonic() - started) * 1000.0, 2),
                used_cached_contract=True,
                run_dir=str(run_dir) if run_dir is not None else None,
            )
        return

    readiness = readiness_result or evaluate_runtime_readiness(runtime.config.base_dir)
    report_payload = build_runtime_readiness_report(readiness)
    report_text = json.dumps(report_payload, indent=2, sort_keys=True)
    _write_runtime_readiness_payload(runtime, report_text=report_text, run_dir=run_dir)
    if callable(emit):
        emit(
            "artifacts.runtime_readiness_report",
            duration_ms=round((time.monotonic() - started) * 1000.0, 2),
            used_cached_contract=readiness_result is not None,
            run_dir=str(run_dir) if run_dir is not None else None,
        )


def _write_runtime_readiness_payload(
    runtime: Any,
    *,
    report_text: str,
    run_dir: Path | None,
) -> None:
    (runtime.runtime_root / "runtime_readiness_report.json").write_text(report_text, encoding="utf-8")
    runtime.runtime_legacy_root.mkdir(parents=True, exist_ok=True)
    (runtime.runtime_legacy_root / "runtime_readiness_report.json").write_text(report_text, encoding="utf-8")
    if run_dir is not None:
        (run_dir / "runtime_readiness_report.json").write_text(report_text, encoding="utf-8")


def _write_cached_runtime_readiness_payload(
    runtime: Any,
    *,
    run_dir: Path,
    cached: str,
) -> None:
    started = time.monotonic()
    _write_runtime_readiness_payload(runtime, report_text=cached, run_dir=run_dir)
    emit = getattr(runtime, "_emit", None)
    if callable(emit):
        emit(
            "artifacts.runtime_readiness_report",
            duration_ms=round((time.monotonic() - started) * 1000.0, 2),
            used_cached_contract=True,
            run_dir=str(run_dir),
        )


def _write_pending_runtime_readiness_payload(runtime: Any, *, run_dir: Path) -> None:
    report = {
        "passed": None,
        "pending": True,
        "gap_report": {
            "path": str(runtime.config.base_dir / GAP_REPORT_RELATIVE_PATH),
        },
        "summary": {
            "blocking_gap_count": None,
        },
        "errors": [],
        "warnings": [],
    }
    _write_runtime_readiness_payload(
        runtime,
        report_text=json.dumps(report, indent=2, sort_keys=True),
        run_dir=run_dir,
    )
    emit = getattr(runtime, "_emit", None)
    if callable(emit):
        emit("artifacts.runtime_readiness_report.pending", run_dir=str(run_dir))


def _start_background_runtime_readiness_report(runtime: Any, *, run_dir: Path) -> None:
    def _worker() -> None:
        try:
            write_runtime_readiness_report(runtime, run_dir=run_dir)
            emit = getattr(runtime, "_emit", None)
            if callable(emit):
                emit("artifacts.runtime_readiness_report.complete", run_dir=str(run_dir))
        except Exception as exc:  # pragma: no cover
            emit = getattr(runtime, "_emit", None)
            if callable(emit):
                emit(
                    "artifacts.runtime_readiness_report.error",
                    run_dir=str(run_dir),
                    error=str(exc),
                )

    thread = threading.Thread(
        target=_worker,
        name=f"envctl-runtime-readiness-{run_dir.name}",
        daemon=True,
    )
    thread.start()


def _cached_runtime_readiness_payload(runtime: Any) -> str | None:
    report_path = runtime.runtime_root / "runtime_readiness_report.json"
    gap_report_path = runtime.config.base_dir / GAP_REPORT_RELATIVE_PATH
    if not report_path.is_file() or not gap_report_path.is_file():
        return None
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        gap_payload = json.loads(gap_report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(report, dict) or not isinstance(gap_payload, dict):
        return None
    if bool(report.get("pending")):
        return None
    report_gap = report.get("gap_report", {})
    if not isinstance(report_gap, dict):
        return None
    if str(report_gap.get("path", "")).strip() != str(gap_report_path):
        return None
    if str(report_gap.get("generated_at", "")).strip() != str(gap_payload.get("generated_at", "")).strip():
        return None
    return json.dumps(report, indent=2, sort_keys=True)


def _runtime_readiness_async_enabled(runtime: Any) -> bool:
    env = getattr(runtime, "env", None)
    if not isinstance(env, dict):
        return False
    raw_value = env.get("ENVCTL_ASYNC_RUNTIME_READINESS_REPORT")
    if raw_value is None:
        return False
    raw = str(raw_value).strip().lower()
    return raw not in {"0", "false", "no", "off"}


def print_summary(_runtime: Any, state: object, contexts: list[object]) -> None:
    _ = state
    print("envctl Python engine run summary")
    for context in contexts:
        backend = context.ports["backend"].final
        frontend = context.ports["frontend"].final
        db = context.ports["db"].final
        redis = context.ports["redis"].final
        n8n = context.ports["n8n"].final
        print(f"- {context.name}: backend={backend} frontend={frontend} db={db} redis={redis} n8n={n8n}")
