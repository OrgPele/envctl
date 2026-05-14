from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree, PlanAgentLaunchConfig, _OmxSpawnProcessRecord


def _spawn_omx_session_for_worktree(
    runtime: Any,
    *,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
) -> str | None:
    from envctl_engine.planning.plan_agent import launch as _launch

    omx_root = _launch._omx_runtime_root_for_worktree(runtime, worktree)
    try:
        omx_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return str(exc)
    _launch._cleanup_stale_omx_tmux_locks(runtime, worktree_root=worktree.root, omx_root=omx_root)
    cli_command = shlex.split(launch_config.cli_command) if str(launch_config.cli_command).strip() else []
    wants_bypass = any(token == _launch._CODEX_BYPASS_FLAGS for token in cli_command[1:])
    command = ["omx", "--tmux"]
    if wants_bypass:
        command.append("--madmax")
    popen_command = ["script", "-qfc", shlex.join(command), "/dev/null"]
    env = _launch._omx_launch_env(runtime)
    env["OMX_ROOT"] = str(omx_root)
    env["OMX_LAUNCH_POLICY"] = "detached-tmux"
    if launch_config.omx_workflow == "team":
        env["OMX_TEAM_WORKER_LAUNCH_ARGS"] = _launch._CODEX_BYPASS_FLAGS
    runtime._emit(
        "planning.agent_launch.omx_state_root_selected",
        worktree=worktree.name,
        omx_root=str(omx_root),
        transport="omx",
    )
    started_at = _launch._utc_timestamp_from_epoch()
    try:
        process = subprocess.Popen(
            popen_command,
            cwd=str(Path(worktree.root).resolve()),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except OSError as exc:
        return str(exc)
    spawn_payload = _launch._omx_spawn_metadata_payload(
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
        if _launch._read_omx_session_id(runtime, worktree):
            return None
        try:
            stdout, stderr = process.communicate(timeout=0.5)
        except TypeError:
            stdout, stderr = process.communicate()
        except Exception:
            stdout, stderr = "", ""
        error = _launch._omx_spawn_failure_text(returncode=getattr(process, "returncode", None), stdout=stdout, stderr=stderr)
        runtime._emit(
            "planning.agent_launch.omx_spawn.failed",
            **spawn_payload,
            returncode=getattr(process, "returncode", None),
            error=error,
            stdout_excerpt=_launch._bounded_process_output_excerpt(stdout),
            stderr_excerpt=_launch._bounded_process_output_excerpt(stderr),
        )
        return error
    process_stdout = getattr(process, "stdout", None)
    if process_stdout is not None:
        process_stdout.close()
    process_stderr = getattr(process, "stderr", None)
    if process_stderr is not None:
        process_stderr.close()
    _launch._retain_omx_spawn_process(
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
