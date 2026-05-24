from __future__ import annotations

import os
import re
import shlex
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.constants import (
    _CODEX_BYPASS_FLAGS,
    _OMX_SPAWN_OUTPUT_EXCERPT_CHARS,
)
from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    _OmxSpawnProcessRecord,
)


OmxRuntimeRootForWorktreeFn = Callable[..., Path]
CleanupStaleLocksFn = Callable[..., None]
OmxLaunchEnvFn = Callable[..., dict[str, str]]
UtcTimestampFromEpochFn = Callable[[], str]
ReadOmxSessionIdFn = Callable[..., str]
RetainOmxSpawnProcessFn = Callable[..., None]
PopenFactory = Callable[..., Any]


def deterministic_omx_root_for_worktree(worktree: CreatedPlanWorktree) -> Path:
    token = sanitize_omx_tmux_token(worktree.name)
    return Path(worktree.root).resolve() / ".envctl-state" / "omx" / token


def sanitize_omx_tmux_token(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")
    return cleaned or "unknown"


def utc_timestamp_from_epoch(value: float | None = None) -> str:
    timestamp = time.time() if value is None else value
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp))


def bounded_process_output_excerpt(value: object) -> str:
    return str(value or "")[:_OMX_SPAWN_OUTPUT_EXCERPT_CHARS]


def omx_spawn_metadata_payload(
    *,
    process: object,
    command: tuple[str, ...],
    popen_command: tuple[str, ...],
    worktree: CreatedPlanWorktree,
    omx_root: Path,
    started_at: str,
    madmax: bool,
) -> dict[str, object]:
    return {
        "pid": getattr(process, "pid", None),
        "command": list(command),
        "popen_command": list(popen_command),
        "worktree": worktree.name,
        "worktree_root": str(Path(worktree.root).resolve(strict=False)),
        "omx_root": str(Path(omx_root).resolve(strict=False)),
        "transport": "omx",
        "madmax": bool(madmax),
        "started_at": started_at,
        "phase": "spawn",
    }


def omx_spawn_failure_text(*, returncode: object, stdout: str, stderr: str) -> str:
    for stream in (stderr, stdout):
        lines = [line.strip() for line in str(stream or "").splitlines() if line.strip()]
        if lines:
            return lines[0]
    normalized_code = "" if returncode is None else str(returncode).strip()
    if normalized_code:
        return f"omx exited with status {normalized_code}"
    return "omx exited before creating a managed session"


def retained_omx_spawn_process(record: object) -> object:
    return getattr(record, "process", record)


def retained_omx_spawn_returncode(record: object) -> object:
    process = retained_omx_spawn_process(record)
    poll = getattr(process, "poll", None)
    try:
        return poll() if callable(poll) else getattr(process, "returncode", None)
    except Exception:
        return None


def retained_omx_spawn_event_payload(
    record: object,
    *,
    session_name: str,
    worktree: CreatedPlanWorktree | None,
    returncode: object,
) -> dict[str, object]:
    process = retained_omx_spawn_process(record)
    record_worktree_root = getattr(record, "worktree_root", None)
    if record_worktree_root is None and worktree is not None:
        record_worktree_root = worktree.root
    record_omx_root = getattr(record, "omx_root", None)
    if record_omx_root is None and worktree is not None:
        record_omx_root = deterministic_omx_root_for_worktree(worktree)
    command = getattr(record, "command", None) or getattr(process, "args", None) or ()
    popen_command = getattr(record, "popen_command", None) or getattr(process, "args", None) or ()
    payload: dict[str, object] = {
        "pid": getattr(process, "pid", None),
        "returncode": returncode,
        "session_name": session_name,
        "command": [str(part) for part in command],
        "popen_command": [str(part) for part in popen_command],
        "worktree": str(getattr(record, "worktree_name", "") or getattr(worktree, "name", "") or "") or None,
        "transport": "omx",
    }
    if record_worktree_root is not None:
        payload["worktree_root"] = str(Path(record_worktree_root).resolve(strict=False))
    if record_omx_root is not None:
        payload["omx_root"] = str(Path(record_omx_root).resolve(strict=False))
    if getattr(record, "started_at", ""):
        payload["started_at"] = str(getattr(record, "started_at"))
    if hasattr(record, "madmax"):
        payload["madmax"] = bool(getattr(record, "madmax"))
    return payload


def omx_launch_env(runtime: Any) -> dict[str, str]:
    env = dict(os.environ)
    env.update(dict(getattr(runtime, "env", {})))
    home = str(env.get("HOME") or "").strip()
    if home and not str(env.get("CODEX_HOME") or "").strip():
        codex_home = Path(home).expanduser() / ".codex"
        if codex_home.exists():
            env["CODEX_HOME"] = str(codex_home)
    env.pop("TMUX", None)
    env.pop("TMUX_PANE", None)
    return env


def retain_omx_spawn_process(runtime: Any, record: object) -> None:
    retained = getattr(runtime, "_omx_spawn_processes", None)
    if not isinstance(retained, list):
        retained = []
        try:
            setattr(runtime, "_omx_spawn_processes", retained)
        except Exception:
            return
    retained[:] = [item for item in retained if retained_omx_spawn_returncode(item) is None]
    retained.append(record)


def spawn_omx_session_for_worktree(
    runtime: Any,
    *,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
    omx_runtime_root_for_worktree_fn: OmxRuntimeRootForWorktreeFn,
    cleanup_stale_locks_fn: CleanupStaleLocksFn,
    omx_launch_env_fn: OmxLaunchEnvFn,
    utc_timestamp_from_epoch_fn: UtcTimestampFromEpochFn,
    read_omx_session_id_fn: ReadOmxSessionIdFn,
    retain_omx_spawn_process_fn: RetainOmxSpawnProcessFn,
    popen_factory: PopenFactory,
) -> str | None:
    omx_root = omx_runtime_root_for_worktree_fn(runtime, worktree)
    try:
        omx_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return str(exc)
    cleanup_stale_locks_fn(runtime, worktree_root=worktree.root, omx_root=omx_root)
    cli_command = shlex.split(launch_config.cli_command) if str(launch_config.cli_command).strip() else []
    wants_bypass = any(token == _CODEX_BYPASS_FLAGS for token in cli_command[1:])
    command = ["omx", "--tmux"]
    if wants_bypass:
        command.append("--madmax")
    popen_command = ["script", "-qfc", shlex.join(command), "/dev/null"]
    env = omx_launch_env_fn(runtime)
    env["OMX_ROOT"] = str(omx_root)
    env["OMX_LAUNCH_POLICY"] = "detached-tmux"
    if launch_config.omx_workflow == "team":
        env["OMX_TEAM_WORKER_LAUNCH_ARGS"] = _CODEX_BYPASS_FLAGS
    runtime._emit(
        "planning.agent_launch.omx_state_root_selected",
        worktree=worktree.name,
        omx_root=str(omx_root),
        transport="omx",
    )
    started_at = utc_timestamp_from_epoch_fn()
    try:
        process = popen_factory(
            popen_command,
            cwd=str(Path(worktree.root).resolve()),
            env=env,
            stdin=-1,
            stdout=-1,
            stderr=-1,
            text=True,
            start_new_session=True,
        )
    except OSError as exc:
        return str(exc)
    spawn_payload = omx_spawn_metadata_payload(
        process=process,
        command=tuple(command),
        popen_command=tuple(popen_command),
        worktree=worktree,
        omx_root=omx_root,
        started_at=started_at,
        madmax=wants_bypass,
    )
    runtime._emit("planning.agent_launch.omx_spawn.started", **spawn_payload)
    if process.poll() is not None:
        if read_omx_session_id_fn(runtime, worktree):
            return None
        try:
            stdout, stderr = process.communicate(timeout=0.5)
        except TypeError:
            stdout, stderr = process.communicate()
        except Exception:
            stdout, stderr = "", ""
        error = omx_spawn_failure_text(
            returncode=getattr(process, "returncode", None),
            stdout=stdout,
            stderr=stderr,
        )
        runtime._emit(
            "planning.agent_launch.omx_spawn.failed",
            **spawn_payload,
            returncode=getattr(process, "returncode", None),
            error=error,
            stdout_excerpt=bounded_process_output_excerpt(stdout),
            stderr_excerpt=bounded_process_output_excerpt(stderr),
        )
        return error
    process_stdout = getattr(process, "stdout", None)
    if process_stdout is not None:
        process_stdout.close()
    process_stderr = getattr(process, "stderr", None)
    if process_stderr is not None:
        process_stderr.close()
    retain_omx_spawn_process_fn(
        runtime,
        _OmxSpawnProcessRecord(
            process=process,
            command=tuple(command),
            popen_command=tuple(popen_command),
            worktree_name=worktree.name,
            worktree_root=Path(worktree.root).resolve(strict=False),
            omx_root=Path(omx_root).resolve(strict=False),
            started_at=started_at,
            madmax=wants_bypass,
        ),
    )
    return None
