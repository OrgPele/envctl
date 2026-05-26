from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Any, Callable

from envctl_engine.actions.action_target_support import action_target_identity
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.runtime_context import resolve_process_runtime


def run_self_destruct_worktree_action(
    orchestrator: Any,
    route: Route,
    *,
    current_cwd: Callable[[], Path] = Path.cwd,
) -> int:
    targets, error = orchestrator.resolve_targets(route, trees_only=True)
    if error is not None:
        print(error)
        return 1
    if len(targets) != 1:
        print("self-destruct-worktree requires exactly one current worktree target.")
        return 1
    identity = action_target_identity(targets[0], fallback_name_from_root=True)
    if identity is None:
        print("self-destruct-worktree requires a valid current worktree target.")
        return 1
    target_root = identity.root.resolve()
    target_name = identity.name
    cwd = current_cwd().resolve()
    if target_root != cwd:
        print("self-destruct-worktree must be launched from the worktree root.")
        return 1

    warnings = orchestrator.runtime._blast_worktree_before_delete(
        project_name=target_name,
        project_root=target_root,
        source_command="self-destruct-worktree",
    )
    for warning in warnings:
        print(f"Warning: {warning}")

    repo_root = orchestrator._main_repo_root_for_worktree(target_root)
    if repo_root is None:
        print("Could not determine main repo root for current worktree.")
        return 1
    trees_root = orchestrator.runtime._trees_root_for_worktree(target_root)
    if not orchestrator._spawn_self_destruct_helper(
        repo_root=repo_root,
        trees_root=trees_root,
        worktree_root=target_root,
    ):
        print("Failed to launch detached worktree self-destruct helper.")
        return 1

    print(f"Self-destruct launched for {target_name}. This worktree will be removed after envctl exits.")
    return 0


def spawn_self_destruct_helper(*, runtime: Any, repo_root: Path, trees_root: Path, worktree_root: Path) -> bool:
    raw_runtime = getattr(runtime, "raw_runtime", runtime)
    process_runtime = resolve_process_runtime(raw_runtime)
    helper_dir = Path(tempfile.mkdtemp(prefix="envctl-self-destruct-", dir=str(repo_root)))
    helper_script = helper_dir / "self_destruct.py"
    helper_script.write_text(
        """
from __future__ import annotations
import subprocess
import sys
import time
from pathlib import Path

repo_root = Path(sys.argv[1]).resolve()
trees_root = Path(sys.argv[2]).resolve()
worktree_root = Path(sys.argv[3]).resolve()
parent_pid = int(sys.argv[4])

for _ in range(200):
    try:
        subprocess.run(
            ["kill", "-0", str(parent_pid)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.1)
    except Exception:
        break

result = subprocess.run(
    ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(worktree_root)],
    capture_output=True,
    text=True,
    timeout=30.0,
)
if result.returncode != 0:
    sys.exit(result.returncode)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    completed = process_runtime.start_background(  # type: ignore[attr-defined]
        [
            "python3",
            str(helper_script),
            str(repo_root),
            str(trees_root),
            str(worktree_root),
            str(os.getpid()),
        ],
        cwd=repo_root,
        stdout_path=helper_dir / "self_destruct.log",
        stderr_path=helper_dir / "self_destruct.log",
    )
    return getattr(completed, "pid", 0) > 0
