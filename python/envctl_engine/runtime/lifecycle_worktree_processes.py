from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast


def blast_tree_listener_ports(runtime: Any, *, project_name: str, ports: set[int], warnings: list[str]) -> None:
    if not ports:
        return
    orchestrator = getattr(runtime, "lifecycle_cleanup_orchestrator", None)
    run_best_effort = getattr(orchestrator, "run_best_effort_command", None)
    looks_like_docker = getattr(orchestrator, "looks_like_docker_process", None)
    process_command = getattr(runtime, "_blast_all_process_command", None)
    kill_pid_tree = getattr(runtime, "_blast_all_kill_pid_tree", None)
    if not callable(run_best_effort) or not callable(process_command) or not callable(kill_pid_tree):
        return

    seen_pids: set[int] = set()
    for port in sorted(ports):
        code, stdout, _stderr = cast(
            tuple[int, str, str],
            run_best_effort(["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], timeout=2.0),
        )
        if code not in {0, 1} or not stdout.strip():
            continue
        for raw_pid in stdout.splitlines():
            raw_pid = raw_pid.strip()
            if not raw_pid.isdigit():
                continue
            pid = int(raw_pid)
            if pid <= 0 or pid in seen_pids:
                continue
            seen_pids.add(pid)
            command_text = str(process_command(pid) or "")
            if callable(looks_like_docker) and looks_like_docker(command_text):
                runtime._emit(
                    "cleanup.worktree.port.skip",
                    project=project_name,
                    pid=pid,
                    port=port,
                    reason="docker_managed",
                )
                continue
            runtime._emit(
                "cleanup.worktree.port.kill",
                project=project_name,
                pid=pid,
                port=port,
            )
            try:
                kill_pid_tree(pid)
            except Exception as exc:  # noqa: BLE001
                warning = f"listener cleanup failed for {project_name} (pid {pid}, port {port}): {exc}"
                warnings.append(warning)
                runtime._emit(
                    "cleanup.worktree.warning",
                    project=project_name,
                    pid=pid,
                    port=port,
                    warning=warning,
                )


def blast_tree_cwd_processes(runtime: Any, *, project_name: str, project_root: Path, warnings: list[str]) -> None:
    kill_pid_tree = getattr(runtime, "_blast_all_kill_pid_tree", None)
    process_command = getattr(runtime, "_blast_all_process_command", None)
    looks_like_docker = getattr(runtime, "_looks_like_docker_process", None)
    if not callable(kill_pid_tree):
        return

    resolved_root = project_root.resolve()
    seen_pids: set[int] = set()
    skip_pids = {os.getpid(), os.getppid()}
    proc_root = Path("/proc")
    try:
        proc_dirs = list(proc_root.iterdir())
    except FileNotFoundError:
        return

    for proc_dir in proc_dirs:
        raw_pid = proc_dir.name.strip()
        if not raw_pid.isdigit():
            continue
        pid = int(raw_pid)
        if pid <= 0 or pid in skip_pids or pid in seen_pids:
            continue

        try:
            cwd_path = (proc_dir / "cwd").resolve()
        except OSError:
            continue
        if cwd_path != resolved_root and resolved_root not in cwd_path.parents:
            continue

        command_text = ""
        if callable(process_command):
            try:
                command_text = str(process_command(pid) or "")
            except Exception:
                command_text = ""
        if callable(looks_like_docker) and looks_like_docker(command_text):
            runtime._emit(
                "cleanup.worktree.cwd.skip",
                project=project_name,
                pid=pid,
                reason="docker_managed",
            )
            continue

        seen_pids.add(pid)
        runtime._emit(
            "cleanup.worktree.cwd.kill",
            project=project_name,
            pid=pid,
            cwd=str(cwd_path),
        )
        try:
            kill_pid_tree(pid, skip_pids=skip_pids)
        except Exception as exc:  # noqa: BLE001
            warning = f"cwd cleanup failed for {project_name} (pid {pid}): {exc}"
            warnings.append(warning)
            runtime._emit(
                "cleanup.worktree.warning",
                project=project_name,
                pid=pid,
                cwd=str(cwd_path),
                warning=warning,
            )
