from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.shell.shell_prune import LEDGER_RELATIVE_PATH, evaluate_shell_prune_contract
from envctl_engine.shared.parsing import parse_bool


def write_artifacts(runtime: Any, state: object, contexts: list[object], *, errors: list[str]) -> None:
    started = time.monotonic()
    cached = _cached_shell_prune_payload(runtime)
    paths = runtime.state_repository.save_run(
        state=state,
        contexts=list(contexts),
        errors=list(errors),
        events=list(runtime.events),
        emit=runtime._emit,
        runtime_map_builder=build_runtime_map,
        write_shell_prune_report=(
            (lambda run_dir: _write_cached_shell_prune_payload(runtime, run_dir=run_dir, cached=cached))
            if cached is not None
            else (lambda run_dir: _write_pending_shell_prune_payload(runtime, run_dir=run_dir))
        ),
    )
    runtime._emit(
        "artifacts.write",
        duration_ms=round((time.monotonic() - started) * 1000.0, 2),
        project_count=len(contexts),
        error_count=len(errors),
    )
    if cached is None and _shell_prune_async_enabled(runtime):
        _start_background_shell_prune_report(runtime, run_dir=paths.run_dir)
    elif cached is None and hasattr(paths, "run_dir"):
        write_shell_prune_report(runtime, run_dir=paths.run_dir)


def write_shell_prune_report(
    runtime: Any,
    *,
    run_dir: Path | None = None,
    contract_result: object | None = None,
) -> None:
    started = time.monotonic()
    emit = getattr(runtime, "_emit", None)
    cached = _cached_shell_prune_payload(runtime)
    if contract_result is None and cached is not None:
        shell_snapshot_text, shell_report_text = cached
        _write_shell_prune_payload(runtime, shell_snapshot_text=shell_snapshot_text, shell_report_text=shell_report_text, run_dir=run_dir)
        if callable(emit):
            emit(
                "artifacts.shell_prune_report",
                duration_ms=round((time.monotonic() - started) * 1000.0, 2),
                used_cached_contract=True,
                run_dir=str(run_dir) if run_dir is not None else None,
            )
        return
    (
        shell_budget,
        shell_partial_keep_budget,
        shell_intentional_keep_budget,
        shell_phase,
    ) = runtime._shell_prune_budget_profile()
    shell_migration = contract_result or evaluate_shell_prune_contract(
        runtime.config.base_dir,
        enforce_manifest_coverage=True,
        max_unmigrated=shell_budget,
        max_partial_keep=shell_partial_keep_budget,
        max_intentional_keep=shell_intentional_keep_budget,
        phase=shell_phase,
    )
    shell_snapshot = {
        "ledger_path": str(shell_migration.ledger_path),
        "ledger_generated_at": shell_migration.ledger_generated_at,
        "ledger_hash": shell_migration.ledger_hash,
        "status_counts": shell_migration.status_counts,
        "partial_keep_covered_count": shell_migration.partial_keep_covered_count,
        "partial_keep_uncovered_count": shell_migration.partial_keep_uncovered_count,
        "partial_keep_budget_actual": shell_migration.partial_keep_budget_actual,
        "partial_keep_budget_basis": shell_migration.partial_keep_budget_basis,
        "intentional_keep_budget_actual": shell_migration.intentional_keep_budget_actual,
    }
    shell_report = {
        "passed": shell_migration.passed,
        "errors": shell_migration.errors,
        "warnings": shell_migration.warnings,
        "missing_python_complete_commands": shell_migration.missing_python_complete_commands,
        "snapshot": shell_snapshot,
    }
    shell_snapshot_text = json.dumps(shell_snapshot, indent=2, sort_keys=True)
    shell_report_text = json.dumps(shell_report, indent=2, sort_keys=True)
    _write_shell_prune_payload(runtime, shell_snapshot_text=shell_snapshot_text, shell_report_text=shell_report_text, run_dir=run_dir)
    if callable(emit):
        emit(
            "artifacts.shell_prune_report",
            duration_ms=round((time.monotonic() - started) * 1000.0, 2),
            used_cached_contract=contract_result is not None,
            run_dir=str(run_dir) if run_dir is not None else None,
        )


def _write_shell_prune_payload(
    runtime: Any,
    *,
    shell_snapshot_text: str,
    shell_report_text: str,
    run_dir: Path | None,
) -> None:
    (runtime.runtime_root / "shell_ownership_snapshot.json").write_text(shell_snapshot_text, encoding="utf-8")
    (runtime.runtime_root / "shell_prune_report.json").write_text(shell_report_text, encoding="utf-8")
    runtime.runtime_legacy_root.mkdir(parents=True, exist_ok=True)
    (runtime.runtime_legacy_root / "shell_ownership_snapshot.json").write_text(shell_snapshot_text, encoding="utf-8")
    (runtime.runtime_legacy_root / "shell_prune_report.json").write_text(shell_report_text, encoding="utf-8")
    if run_dir is not None:
        (run_dir / "shell_prune_report.json").write_text(shell_report_text, encoding="utf-8")


def _write_cached_shell_prune_payload(
    runtime: Any,
    *,
    run_dir: Path,
    cached: tuple[str, str],
) -> None:
    started = time.monotonic()
    shell_snapshot_text, shell_report_text = cached
    _write_shell_prune_payload(
        runtime,
        shell_snapshot_text=shell_snapshot_text,
        shell_report_text=shell_report_text,
        run_dir=run_dir,
    )
    emit = getattr(runtime, "_emit", None)
    if callable(emit):
        emit(
            "artifacts.shell_prune_report",
            duration_ms=round((time.monotonic() - started) * 1000.0, 2),
            used_cached_contract=True,
            run_dir=str(run_dir),
        )


def _write_pending_shell_prune_payload(runtime: Any, *, run_dir: Path) -> None:
    ledger_path = runtime.config.base_dir / LEDGER_RELATIVE_PATH
    snapshot = {
        "pending": True,
        "ledger_path": str(ledger_path),
    }
    report = {
        "passed": None,
        "pending": True,
        "errors": [],
        "warnings": [],
        "missing_python_complete_commands": [],
        "snapshot": snapshot,
    }
    _write_shell_prune_payload(
        runtime,
        shell_snapshot_text=json.dumps(snapshot, indent=2, sort_keys=True),
        shell_report_text=json.dumps(report, indent=2, sort_keys=True),
        run_dir=run_dir,
    )
    emit = getattr(runtime, "_emit", None)
    if callable(emit):
        emit("artifacts.shell_prune_report.pending", run_dir=str(run_dir))


def _start_background_shell_prune_report(runtime: Any, *, run_dir: Path) -> None:
    def _worker() -> None:
        try:
            write_shell_prune_report(runtime, run_dir=run_dir)
            emit = getattr(runtime, "_emit", None)
            if callable(emit):
                emit("artifacts.shell_prune_report.complete", run_dir=str(run_dir))
        except Exception as exc:  # pragma: no cover - defensive background failure path
            emit = getattr(runtime, "_emit", None)
            if callable(emit):
                emit(
                    "artifacts.shell_prune_report.error",
                    run_dir=str(run_dir),
                    error=str(exc),
                )

    thread = threading.Thread(
        target=_worker,
        name=f"envctl-shell-prune-{run_dir.name}",
        daemon=True,
    )
    thread.start()


def _cached_shell_prune_payload(runtime: Any) -> tuple[str, str] | None:
    config = getattr(runtime, "config", None)
    runtime_root = getattr(runtime, "runtime_root", None)
    if config is None or runtime_root is None or not hasattr(config, "base_dir"):
        return None
    ledger_path = runtime.config.base_dir / LEDGER_RELATIVE_PATH
    snapshot_path = runtime.runtime_root / "shell_ownership_snapshot.json"
    report_path = runtime.runtime_root / "shell_prune_report.json"
    if not ledger_path.is_file() or not snapshot_path.is_file() or not report_path.is_file():
        return None
    try:
        ledger_text = ledger_path.read_text(encoding="utf-8")
        ledger_hash = hashlib.sha256(ledger_text.encode("utf-8")).hexdigest()
        snapshot_text = snapshot_path.read_text(encoding="utf-8")
        report_text = report_path.read_text(encoding="utf-8")
        snapshot = json.loads(snapshot_text)
        report = json.loads(report_text)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(snapshot, dict) or not isinstance(report, dict):
        return None
    if bool(snapshot.get("pending")) or bool(report.get("pending")):
        return None
    if str(snapshot.get("ledger_hash", "")).strip() != ledger_hash:
        return None
    if str(snapshot.get("ledger_path", "")).strip() != str(ledger_path):
        return None
    if "passed" not in report or "snapshot" not in report:
        return None
    return snapshot_text, report_text


def _shell_prune_async_enabled(runtime: Any) -> bool:
    env = getattr(runtime, "env", None)
    if not isinstance(env, Mapping) or not env:
        return False
    return parse_bool(env.get("ENVCTL_ASYNC_SHELL_PRUNE_REPORT"), True)


def print_summary(_runtime: Any, state: object, contexts: list[object]) -> None:
    _ = state
    print("envctl Python engine run summary")
    for context in contexts:
        backend = context.ports["backend"].final
        frontend = context.ports["frontend"].final
        db = context.ports["db"].final
        redis = context.ports["redis"].final
        n8n = context.ports["n8n"].final
        print(
            f"- {context.name}: backend={backend} frontend={frontend} db={db} redis={redis} n8n={n8n}"
        )
