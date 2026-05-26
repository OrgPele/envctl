from __future__ import annotations

import os
from typing import Any, cast

BLAST_ALL_PROCESS_PATTERNS: tuple[str, ...] = (
    "envctl_engine\\.cli.*--plan",
    "envctl_engine\\.cli.*--tree",
    "envctl_engine\\.cli.*--trees",
    "envctl_engine\\.cli.*--resume",
    "envctl_engine\\.cli.*--restart",
    "lib/engine/main\\.sh.*--plan",
    "lib/engine/main\\.sh.*--tree",
    "lib/engine/main\\.sh.*--trees",
    "lib/engine/main\\.sh.*--resume",
    "lib/engine/main\\.sh.*--restart",
    "vite",
    "uvicorn.*app\\.main",
    "gunicorn",
    "npm\\s+run\\s+dev",
    "pnpm\\s+dev",
    "bun\\s+run\\s+dev",
    "yarn\\s+dev",
    "next\\s+dev",
    "celery",
)


def process_tree_kill_order_from_ps(stdout: str, *, root_pid: int) -> list[int]:
    if root_pid <= 0:
        return []

    children_by_parent: dict[int, set[int]] = {}
    for line in stdout.splitlines():
        parts = line.strip().split()
        if len(parts) != 2:
            continue
        if not (parts[0].isdigit() and parts[1].isdigit()):
            continue
        pid = int(parts[0])
        ppid = int(parts[1])
        children_by_parent.setdefault(ppid, set()).add(pid)

    discovered: list[tuple[int, int]] = []
    seen: set[int] = set()
    stack: list[tuple[int, int]] = [(root_pid, 0)]
    while stack:
        current, depth = stack.pop()
        if current <= 0 or current in seen:
            continue
        seen.add(current)
        discovered.append((current, depth))
        for child in sorted(children_by_parent.get(current, set()), reverse=True):
            stack.append((child, depth + 1))

    if root_pid not in seen:
        discovered.append((root_pid, 0))

    discovered.sort(key=lambda item: (-item[1], -item[0]))
    return [pid for pid, _depth in discovered]


def is_orchestrator_process(command_text: str) -> bool:
    lowered = command_text.lower()
    orchestrator_tokens = (
        "envctl_engine.runtime.cli",
        "/bin/envctl",
        " bin/envctl",
    )
    return any(token in lowered for token in orchestrator_tokens)


def looks_like_docker_process(command_text: str) -> bool:
    lowered = (command_text or "").lower()
    docker_markers = ("com.docker", "docker desktop", "vpnkit", "dockerd", "containerd")
    return any(marker in lowered for marker in docker_markers)


class BlastProcessCleanupSupport:
    runtime: Any = cast(Any, None)

    @staticmethod
    def blast_all_process_patterns() -> tuple[str, ...]:
        return BLAST_ALL_PROCESS_PATTERNS

    def blast_all_kill_orchestrator_processes(self) -> None:
        owner = cast(Any, self)
        code, stdout, _stderr = owner.run_best_effort_command(
            ["ps", "-axo", "pid=,command="],
            timeout=5.0,
        )
        if code != 0 or not stdout.strip():
            return

        current_pid = os.getpid()
        parent_pid = os.getppid()
        for line in stdout.splitlines():
            text = line.strip()
            if not text:
                continue
            parts = text.split(None, 1)
            if len(parts) != 2 or not parts[0].isdigit():
                continue
            pid = int(parts[0])
            command = parts[1]
            if pid <= 0 or pid in {current_pid, parent_pid}:
                continue
            if not self.blast_all_is_orchestrator_process(command):
                continue
            lowered = command.lower()
            if " blast-all" in lowered or "--blast-all" in lowered:
                continue
            preview = self.runtime._truncate_text(command, 100)  # type: ignore[attr-defined]
            print(f"  Killing orchestrator PID {pid}: {preview}")
            self.blast_all_kill_pid_tree(pid, skip_pids={current_pid, parent_pid})

    def blast_all_kill_pid_tree(self, root_pid: int, *, skip_pids: set[int] | None = None) -> None:
        if root_pid <= 0:
            return
        owner = cast(Any, self)
        skip = set(skip_pids or set())
        for pid in self.blast_all_process_tree_kill_order(root_pid):
            if pid in skip or pid <= 0:
                continue
            owner.run_best_effort_command(["kill", "-9", str(pid)], timeout=2.0)

    def blast_all_process_tree_kill_order(self, root_pid: int) -> list[int]:
        if root_pid <= 0:
            return []

        owner = cast(Any, self)
        code, stdout, _stderr = owner.run_best_effort_command(
            ["ps", "-axo", "pid=,ppid="],
            timeout=5.0,
        )
        if code != 0 or not stdout.strip():
            return [root_pid]

        return process_tree_kill_order_from_ps(stdout, root_pid=root_pid)

    @staticmethod
    def blast_all_is_orchestrator_process(command_text: str) -> bool:
        return is_orchestrator_process(command_text)

    @staticmethod
    def looks_like_docker_process(command_text: str) -> bool:
        return looks_like_docker_process(command_text)
