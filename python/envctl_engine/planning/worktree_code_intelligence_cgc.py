from __future__ import annotations

from pathlib import Path
from typing import Any

from envctl_engine.planning.worktree_code_intelligence_config import (
    source_cgc_context,
    worktree_cgc_database,
)
from envctl_engine.planning.worktree_code_intelligence_models import (
    WORKTREE_CGC_INDEX_MODE_AUTO,
    WORKTREE_CGC_INDEX_MODE_ENABLED,
)
from envctl_engine.runtime.runtime_context import resolve_process_runtime


def short_command_output(value: object, *, limit: int = 500) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def cgc_context_already_exists(result: object) -> bool:
    combined = f"{getattr(result, 'stdout', '')}\n{getattr(result, 'stderr', '')}".lower()
    return "already exists" in combined or "already exist" in combined


def reuse_or_index_worktree_with_cgc(runtime: Any, *, target: Path, context: str) -> dict[str, object]:
    process_runtime = resolve_process_runtime(runtime)
    source_context = source_cgc_context(runtime)
    metadata: dict[str, object] = {
        "cgc_index_mode": WORKTREE_CGC_INDEX_MODE_AUTO,
        "cgc_index_requested": False,
        "cgc_available": False,
        "cgc_context_managed": False,
        "cgc_context_created": False,
        "cgc_context_already_exists": False,
        "cgc_context_returncode": None,
        "cgc_index_succeeded": False,
        "cgc_index_returncode": None,
        "cgc_commands": [],
        "cgc_source_context": source_context,
        "cgc_active_context": source_context,
    }
    if not getattr(runtime, "_command_exists", lambda _name: False)("cgc"):
        metadata["cgc_active_context"] = context
        metadata["cgc_index_skipped_reason"] = "cgc_not_available"
        return metadata
    metadata["cgc_available"] = True
    commands = metadata["cgc_commands"]
    assert isinstance(commands, list)
    list_command = ["cgc", "list", "--context", source_context]
    try:
        result = process_runtime.run(
            list_command,
            cwd=runtime.config.base_dir,
            env=runtime._command_env(port=0),
            timeout=30.0,
        )
    except OSError as exc:
        commands.append({"command": list_command, "error": str(exc)})
        runtime._emit(
            "setup.worktree.code_intelligence.cgc_reuse",
            target=str(target.resolve()),
            source_context=source_context,
            success=False,
            error=str(exc),
        )
        indexed = index_worktree_with_cgc(runtime, target=target, context=context)
        indexed["cgc_index_mode"] = WORKTREE_CGC_INDEX_MODE_AUTO
        indexed["cgc_source_context"] = source_context
        indexed_commands = indexed.get("cgc_commands")
        if isinstance(indexed_commands, list):
            indexed_commands.insert(0, commands[0])
        return indexed
    returncode = getattr(result, "returncode", 1)
    raw_stdout = str(getattr(result, "stdout", "") or "")
    raw_stderr = str(getattr(result, "stderr", "") or "")
    stdout = short_command_output(raw_stdout)
    stderr = short_command_output(raw_stderr)
    source_root = str(runtime.config.base_dir.resolve())
    source_matches = returncode == 0 and source_root in f"{raw_stdout}\n{raw_stderr}"
    commands.append(
        {
            "command": list_command,
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
        }
    )
    runtime._emit(
        "setup.worktree.code_intelligence.cgc_reuse",
        target=str(target.resolve()),
        source_context=source_context,
        source_root=source_root,
        success=source_matches,
        returncode=returncode,
    )
    if source_matches:
        metadata["cgc_index_skipped_reason"] = "source_context_reused"
        return metadata
    indexed = index_worktree_with_cgc(runtime, target=target, context=context)
    indexed["cgc_index_mode"] = WORKTREE_CGC_INDEX_MODE_AUTO
    indexed["cgc_source_context"] = source_context
    indexed["cgc_reuse_returncode"] = returncode
    indexed["cgc_reuse_stdout"] = stdout
    indexed["cgc_reuse_stderr"] = stderr
    indexed_commands = indexed.get("cgc_commands")
    if isinstance(indexed_commands, list):
        indexed_commands.insert(0, commands[0])
    return indexed


def index_worktree_with_cgc(runtime: Any, *, target: Path, context: str) -> dict[str, object]:
    process_runtime = resolve_process_runtime(runtime)
    database = worktree_cgc_database(runtime)
    metadata: dict[str, object] = {
        "cgc_index_mode": WORKTREE_CGC_INDEX_MODE_ENABLED,
        "cgc_index_requested": True,
        "cgc_available": False,
        "cgc_context_managed": False,
        "cgc_context_created": False,
        "cgc_context_already_exists": False,
        "cgc_context_returncode": None,
        "cgc_index_succeeded": False,
        "cgc_index_returncode": None,
        "cgc_commands": [],
    }
    if not getattr(runtime, "_command_exists", lambda _name: False)("cgc"):
        return metadata
    metadata["cgc_available"] = True
    context_command = ["cgc", "context", "create", context]
    if database:
        context_command.extend(["--database", database])
    commands = metadata["cgc_commands"]
    assert isinstance(commands, list)
    try:
        context_result = process_runtime.run(
            context_command,
            cwd=target,
            env=runtime._command_env(port=0),
            timeout=600.0,
        )
    except OSError as exc:
        runtime._emit(
            "setup.worktree.code_intelligence.cgc_context",
            target=str(target.resolve()),
            context=context,
            database=database,
            success=False,
            error=str(exc),
        )
        commands.append({"command": context_command, "error": str(exc)})
        return metadata
    context_returncode = getattr(context_result, "returncode", 1)
    already_exists = context_returncode != 0 and cgc_context_already_exists(context_result)
    context_success = context_returncode == 0 or already_exists
    metadata["cgc_context_returncode"] = context_returncode
    metadata["cgc_context_created"] = context_returncode == 0
    metadata["cgc_context_already_exists"] = already_exists
    metadata["cgc_context_managed"] = context_success
    commands.append(
        {
            "command": context_command,
            "returncode": context_returncode,
            "stdout": short_command_output(getattr(context_result, "stdout", "")),
            "stderr": short_command_output(getattr(context_result, "stderr", "")),
        }
    )
    context_payload: dict[str, object] = {
        "target": str(target.resolve()),
        "context": context,
        "database": database,
        "created": context_returncode == 0,
        "already_exists": already_exists,
        "success": context_success,
        "returncode": context_returncode,
    }
    if not context_success:
        context_payload["stdout"] = short_command_output(getattr(context_result, "stdout", ""))
        context_payload["stderr"] = short_command_output(getattr(context_result, "stderr", ""))
    runtime._emit("setup.worktree.code_intelligence.cgc_context", **context_payload)
    if not context_success:
        return metadata

    index_command = ["cgc", "index", str(target), "--context", context]
    try:
        result = process_runtime.run(
            index_command,
            cwd=target,
            env=runtime._command_env(port=0),
            timeout=600.0,
        )
    except OSError as exc:
        runtime._emit(
            "setup.worktree.code_intelligence.cgc_index",
            target=str(target.resolve()),
            context=context,
            command=index_command,
            success=False,
            error=str(exc),
        )
        commands.append({"command": index_command, "error": str(exc)})
        return metadata
    returncode = getattr(result, "returncode", 1)
    metadata["cgc_index_returncode"] = returncode
    metadata["cgc_index_succeeded"] = returncode == 0
    commands.append(
        {
            "command": index_command,
            "returncode": returncode,
            "stdout": short_command_output(getattr(result, "stdout", "")),
            "stderr": short_command_output(getattr(result, "stderr", "")),
        }
    )
    index_payload: dict[str, object] = {
        "target": str(target.resolve()),
        "context": context,
        "command": index_command,
        "returncode": returncode,
        "success": returncode == 0,
    }
    if returncode != 0:
        index_payload["stdout"] = short_command_output(getattr(result, "stdout", ""))
        index_payload["stderr"] = short_command_output(getattr(result, "stderr", ""))
    runtime._emit(
        "setup.worktree.code_intelligence.cgc_index",
        **index_payload,
    )
    return metadata
