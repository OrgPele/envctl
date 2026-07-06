from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from envctl_engine.runtime.runtime_context import resolve_process_runtime


CODEGRAPH_DIR = ".codegraph"
CODEGRAPH_DB = "codegraph.db"


def short_command_output(value: object, *, limit: int = 500) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def index_worktree_with_codegraph(runtime: Any, *, target: Path, mode: str) -> dict[str, object]:
    metadata: dict[str, object] = {
        "codegraph_index_mode": mode,
        "codegraph_index_requested": True,
        "codegraph_available": False,
        "codegraph_source_index_succeeded": False,
        "codegraph_source_index_returncode": None,
        "codegraph_copied_from_source": False,
        "codegraph_copy_succeeded": False,
        "codegraph_index_succeeded": False,
        "codegraph_index_returncode": None,
        "codegraph_commands": [],
    }
    if not getattr(runtime, "_command_exists", lambda _name: False)("codegraph"):
        metadata["codegraph_index_skipped_reason"] = "codegraph_not_available"
        return metadata
    metadata["codegraph_available"] = True
    source_root = runtime.config.base_dir.resolve()
    target_root = target.resolve()
    source_indexed = _sync_or_init_source_codegraph(runtime, source_root=source_root, metadata=metadata)
    if source_indexed and _copy_codegraph_index(source_root / CODEGRAPH_DIR, target_root / CODEGRAPH_DIR, metadata):
        target_command = ["codegraph", "sync", str(target_root)]
    else:
        target_command = ["codegraph", "init", str(target_root)]
    result = _run_codegraph_command(
        runtime,
        command=target_command,
        cwd=target_root,
        timeout=600.0,
        phase="target",
        metadata=metadata,
        emit_event="setup.worktree.code_intelligence.codegraph_index",
        emit_payload={"target": str(target_root)},
    )
    returncode = result.get("returncode")
    metadata["codegraph_index_returncode"] = returncode
    metadata["codegraph_index_succeeded"] = returncode == 0 and (target_root / CODEGRAPH_DIR / CODEGRAPH_DB).is_file()
    if returncode != 0 and target_command[1] == "sync":
        fallback = ["codegraph", "index", str(target_root), "--quiet"]
        fallback_result = _run_codegraph_command(
            runtime,
            command=fallback,
            cwd=target_root,
            timeout=600.0,
            phase="target_fallback",
            metadata=metadata,
            emit_event="setup.worktree.code_intelligence.codegraph_index",
            emit_payload={"target": str(target_root), "fallback": True},
        )
        fallback_returncode = fallback_result.get("returncode")
        metadata["codegraph_index_returncode"] = fallback_returncode
        metadata["codegraph_index_succeeded"] = fallback_returncode == 0 and (
            target_root / CODEGRAPH_DIR / CODEGRAPH_DB
        ).is_file()
    if not metadata["codegraph_index_succeeded"]:
        metadata["codegraph_index_skipped_reason"] = "index_failed"
    return metadata


def disabled_codegraph_metadata() -> dict[str, object]:
    return {
        "codegraph_index_mode": "disabled",
        "codegraph_index_requested": False,
        "codegraph_available": None,
        "codegraph_source_index_succeeded": False,
        "codegraph_source_index_returncode": None,
        "codegraph_copied_from_source": False,
        "codegraph_copy_succeeded": False,
        "codegraph_index_succeeded": False,
        "codegraph_index_returncode": None,
        "codegraph_commands": [],
        "codegraph_index_skipped_reason": "disabled",
    }


def _sync_or_init_source_codegraph(runtime: Any, *, source_root: Path, metadata: dict[str, object]) -> bool:
    source_dir = source_root / CODEGRAPH_DIR
    source_command = (
        ["codegraph", "sync", str(source_root)]
        if (source_dir / CODEGRAPH_DB).is_file()
        else ["codegraph", "init", str(source_root)]
    )
    result = _run_codegraph_command(
        runtime,
        command=source_command,
        cwd=source_root,
        timeout=600.0,
        phase="source",
        metadata=metadata,
        emit_event="setup.worktree.code_intelligence.codegraph_source",
        emit_payload={"source": str(source_root)},
    )
    returncode = result.get("returncode")
    metadata["codegraph_source_index_returncode"] = returncode
    metadata["codegraph_source_index_succeeded"] = returncode == 0 and (source_dir / CODEGRAPH_DB).is_file()
    return bool(metadata["codegraph_source_index_succeeded"])


def _copy_codegraph_index(source: Path, target: Path, metadata: dict[str, object]) -> bool:
    metadata["codegraph_copied_from_source"] = False
    metadata["codegraph_copy_succeeded"] = False
    if not (source / CODEGRAPH_DB).is_file():
        metadata["codegraph_copy_error"] = "source_index_missing"
        return False
    try:
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target, ignore=_ignored_codegraph_files)
    except OSError as exc:
        metadata["codegraph_copy_error"] = str(exc)
        return False
    metadata["codegraph_copied_from_source"] = True
    metadata["codegraph_copy_succeeded"] = (target / CODEGRAPH_DB).is_file()
    if not metadata["codegraph_copy_succeeded"]:
        metadata["codegraph_copy_error"] = "target_index_missing"
    return bool(metadata["codegraph_copy_succeeded"])


def _ignored_codegraph_files(_directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name.endswith((".sock", ".tmp", ".lock")) or name in {"daemon.pid", "daemon.log"}:
            ignored.add(name)
    return ignored


def _run_codegraph_command(
    runtime: Any,
    *,
    command: list[str],
    cwd: Path,
    timeout: float,
    phase: str,
    metadata: dict[str, object],
    emit_event: str,
    emit_payload: dict[str, object],
) -> dict[str, object]:
    process_runtime = resolve_process_runtime(runtime)
    commands = metadata["codegraph_commands"]
    assert isinstance(commands, list)
    try:
        result = process_runtime.run(
            command,
            cwd=cwd,
            env=runtime._command_env(port=0),
            timeout=timeout,
        )
    except OSError as exc:
        entry = {"phase": phase, "command": command, "error": str(exc)}
        commands.append(entry)
        runtime._emit(emit_event, command=command, success=False, error=str(exc), **emit_payload)
        return entry
    returncode = getattr(result, "returncode", 1)
    entry = {
        "phase": phase,
        "command": command,
        "returncode": returncode,
        "stdout": short_command_output(getattr(result, "stdout", "")),
        "stderr": short_command_output(getattr(result, "stderr", "")),
    }
    commands.append(entry)
    runtime._emit(
        emit_event,
        command=command,
        returncode=returncode,
        success=returncode == 0,
        **emit_payload,
    )
    return entry


__all__ = tuple(name for name in globals() if not name.startswith("__"))
