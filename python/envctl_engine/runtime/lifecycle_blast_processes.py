from __future__ import annotations

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
