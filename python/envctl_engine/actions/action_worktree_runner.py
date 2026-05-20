from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
from typing import Any, Callable

from envctl_engine.actions.actions_worktree import delete_worktree_path
from envctl_engine.planning import discover_tree_projects
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.launcher_support import main_repo_root_for_linked_worktree
from envctl_engine.ui.spinner import spinner, use_spinner_policy
from envctl_engine.ui.spinner_service import emit_spinner_policy, resolve_spinner_policy


def run_self_destruct_worktree_action(orchestrator: Any, route: Route) -> int:
    targets, error = orchestrator.resolve_targets(route, trees_only=True)
    if error is not None:
        print(error)
        return 1
    if len(targets) != 1:
        print("self-destruct-worktree requires exactly one current worktree target.")
        return 1
    target = targets[0]
    target_root = Path(str(getattr(target, "root"))).resolve()
    target_name = str(getattr(target, "name", target_root.name))
    cwd = Path.cwd().resolve()
    if target_root != cwd:
        print("self-destruct-worktree must be launched from the worktree root.")
        return 1

    warnings = orchestrator.runtime._blast_worktree_before_delete(  # type: ignore[attr-defined]
        project_name=target_name,
        project_root=target_root,
        source_command="self-destruct-worktree",
    )
    for warning in warnings:
        print(f"Warning: {warning}")

    repo_root = main_repo_root_for_worktree(
        target_root,
        trees_dir_name=getattr(orchestrator.runtime.raw_runtime.config, "trees_dir_name", "trees"),
        process_runner=orchestrator.runtime.raw_runtime.process_runner,
    )
    if repo_root is None:
        print("Could not determine main repo root for current worktree.")
        return 1
    trees_root = orchestrator.runtime._trees_root_for_worktree(target_root)  # type: ignore[attr-defined]
    if not spawn_self_destruct_helper(
        repo_root=repo_root,
        trees_root=trees_root,
        worktree_root=target_root,
        process_runner=orchestrator.runtime.raw_runtime.process_runner,
    ):
        print("Failed to launch detached worktree self-destruct helper.")
        return 1

    print(f"Self-destruct launched for {target_name}. This worktree will be removed after envctl exits.")
    return 0


def resolve_current_worktree_target(
    runtime: Any,
    *,
    require_configured_main_root: bool = False,
) -> object | None:
    invocation_cwd = str(runtime.env.get("ENVCTL_INVOCATION_CWD") or "").strip()
    cwd = Path(invocation_cwd).expanduser().resolve() if invocation_cwd else Path.cwd().resolve()
    configured_root = getattr(runtime.raw_runtime.config, "base_dir", None)
    configured_root_path = Path(str(configured_root)).expanduser().resolve() if configured_root is not None else None
    if require_configured_main_root and configured_root_path == cwd:
        return None
    trees_dir_name = str(getattr(runtime.raw_runtime.config, "trees_dir_name", "trees"))
    if require_configured_main_root:
        if configured_root_path is None:
            return None
        repo_root = repo_root_from_worktree_layout(cwd, trees_dir_name)
        if repo_root is None:
            repo_root = main_repo_root_for_linked_worktree(cwd)
        if repo_root is None or repo_root.resolve() != configured_root_path:
            return None
    else:
        repo_root = main_repo_root_for_worktree(
            cwd,
            trees_dir_name=trees_dir_name,
            process_runner=runtime.raw_runtime.process_runner,
        )
        if repo_root is None:
            return None
    candidates = [
        SimpleNamespace(name=name, root=root)
        for name, root in discover_tree_projects(repo_root, trees_dir_name)
    ]
    matches = [candidate for candidate in candidates if Path(str(getattr(candidate, "root"))).resolve() == cwd]
    if len(matches) != 1:
        return None
    return matches[0]


def main_repo_root_for_worktree(
    worktree_root: Path,
    *,
    trees_dir_name: str | None = None,
    process_runner: Any,
) -> Path | None:
    normalized_trees_dir = str(trees_dir_name or "trees").strip().rstrip("/")
    repo_root_from_layout = repo_root_from_worktree_layout(worktree_root, normalized_trees_dir)
    if repo_root_from_layout is not None:
        return repo_root_from_layout

    completed = process_runner.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=worktree_root,
        timeout=10.0,
    )
    if getattr(completed, "returncode", 1) != 0:
        return None
    top_level = Path(str(getattr(completed, "stdout", "") or "").strip()).resolve()

    common = process_runner.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=worktree_root,
        timeout=10.0,
    )
    if getattr(common, "returncode", 1) != 0:
        return top_level
    common_dir_raw = str(getattr(common, "stdout", "") or "").strip()
    if not common_dir_raw:
        return top_level
    common_dir_path = Path(common_dir_raw)
    common_dir = (
        (worktree_root / common_dir_path).resolve()
        if not common_dir_path.is_absolute()
        else common_dir_path.resolve()
    )
    if common_dir.name == ".git":
        return common_dir.parent
    if common_dir.name == "worktrees" and common_dir.parent.name == ".git":
        return common_dir.parent.parent
    if common_dir.parent.name == "worktrees" and common_dir.parent.parent.name == ".git":
        return common_dir.parent.parent.parent
    return top_level


def repo_root_from_worktree_layout(worktree_root: Path, trees_dir_name: str) -> Path | None:
    normalized = str(trees_dir_name).strip().rstrip("/")
    if not normalized:
        return None

    resolved_target = worktree_root.resolve()
    nested_suffix = Path(normalized)
    flat_prefix = f"{nested_suffix.name}-"

    ancestors = [resolved_target, *resolved_target.parents]
    for candidate_repo_root in ancestors:
        nested_root = candidate_repo_root / nested_suffix
        if nested_root == resolved_target or nested_root in resolved_target.parents:
            return candidate_repo_root

        flat_parent = nested_root.parent
        if flat_parent == resolved_target or flat_parent not in ancestors:
            continue
        current = resolved_target
        while current != flat_parent and flat_parent in current.parents:
            if current.parent == flat_parent and current.name.startswith(flat_prefix):
                return candidate_repo_root
            current = current.parent
    return None


def spawn_self_destruct_helper(
    *,
    repo_root: Path,
    trees_root: Path,
    worktree_root: Path,
    process_runner: Any,
    parent_pid: int | None = None,
) -> bool:
    helper_dir = Path(tempfile.mkdtemp(prefix="envctl-self-destruct-", dir=str(repo_root)))
    helper_script = helper_dir / "self_destruct.py"
    helper_script.write_text(
        """
from __future__ import annotations
import shutil
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
    completed = process_runner.start_background(
        [
            "python3",
            str(helper_script),
            str(repo_root),
            str(trees_root),
            str(worktree_root),
            str(parent_pid if parent_pid is not None else os.getpid()),
        ],
        cwd=repo_root,
        stdout_path=helper_dir / "self_destruct.log",
        stderr_path=helper_dir / "self_destruct.log",
    )
    return getattr(completed, "pid", 0) > 0


def run_delete_worktree_action(orchestrator: Any, route: Route) -> int:
    rt = orchestrator.runtime
    command_name = route.command if route.command in {"delete-worktree", "blast-worktree"} else "delete-worktree"
    interactive_command = bool(route.flags.get("interactive_command"))
    if bool(route.flags.get("all")) and not bool(route.flags.get("yes")):
        print(f"{command_name} --all requires --yes")
        return 1

    targets, error = orchestrator.resolve_targets(route, trees_only=True)
    if error is not None:
        print(error)
        return 1

    rt._emit("action.command.start", command=route.command, mode=route.mode)  # type: ignore[attr-defined]
    orchestrator._emit_status(orchestrator._command_start_status(command_name, targets))
    spinner_policy = resolve_spinner_policy(getattr(rt, "env", {}))
    op_id = f"action.{command_name}"
    emit_spinner_policy(
        getattr(rt, "_emit", None),
        spinner_policy,
        context={"component": "action.command", "command": route.command, "op_id": op_id},
    )

    dry_run = bool(route.flags.get("dry_run"))
    failures = 0
    total = max(len(targets), 1)
    spinner_message = (
        "Blasting selected worktrees..." if command_name == "blast-worktree" else "Deleting selected worktrees..."
    )
    with (
        use_spinner_policy(spinner_policy),
        spinner(
            spinner_message,
            enabled=spinner_policy.enabled,
            start_immediately=False,
        ) as active_spinner,
    ):
        if spinner_policy.enabled:
            active_spinner.start()
            rt._emit(  # type: ignore[attr-defined]
                "ui.spinner.lifecycle",
                component="action.command",
                command=route.command,
                op_id=op_id,
                state="start",
                message=spinner_message,
            )
        for index, target in enumerate(targets, start=1):
            target_root = Path(str(getattr(target, "root")))
            target_name = str(getattr(target, "name", target_root.name))
            progress = f"Deleting worktree {target_name} ({index}/{total})..."
            orchestrator._emit_status(progress)
            if spinner_policy.enabled:
                active_spinner.update(progress)
                rt._emit(  # type: ignore[attr-defined]
                    "ui.spinner.lifecycle",
                    component="action.command",
                    command=route.command,
                    op_id=op_id,
                    state="update",
                    message=progress,
                )
            _run_cleanup(
                runtime=rt,
                command_name=command_name,
                interactive_command=interactive_command,
                dry_run=dry_run,
                target_name=target_name,
                target_root=target_root,
                emit_status=orchestrator._emit_status,
            )
            result = delete_worktree_path(
                repo_root=rt.config.base_dir,  # type: ignore[attr-defined]
                trees_root=rt._trees_root_for_worktree(target_root),  # type: ignore[attr-defined]
                worktree_root=target_root,
                process_runner=rt.process_runner,  # type: ignore[attr-defined]
                dry_run=dry_run,
            )
            if not interactive_command:
                print(result.message)
            if not result.success:
                orchestrator._emit_status(f"{command_name} failed for {target_name}")
                failures += 1
            else:
                orchestrator._emit_status(f"{command_name} succeeded for {target_name}")
        if spinner_policy.enabled:
            if failures == 0:
                active_spinner.succeed(f"{command_name} completed")
                rt._emit(  # type: ignore[attr-defined]
                    "ui.spinner.lifecycle",
                    component="action.command",
                    command=route.command,
                    op_id=op_id,
                    state="success",
                    message=f"{command_name} completed",
                )
            else:
                active_spinner.fail(f"{command_name} failed")
                rt._emit(  # type: ignore[attr-defined]
                    "ui.spinner.lifecycle",
                    component="action.command",
                    command=route.command,
                    op_id=op_id,
                    state="fail",
                    message=f"{command_name} failed",
                )
            rt._emit(  # type: ignore[attr-defined]
                "ui.spinner.lifecycle",
                component="action.command",
                command=route.command,
                op_id=op_id,
                state="stop",
            )
    return 0 if failures == 0 else 1


def _run_cleanup(
    *,
    runtime: Any,
    command_name: str,
    interactive_command: bool,
    dry_run: bool,
    target_name: str,
    target_root: Path,
    emit_status: Callable[[str], None],
) -> None:
    if dry_run:
        return
    blast_cleanup = getattr(runtime, "_blast_worktree_before_delete", None)
    if not callable(blast_cleanup):
        return
    cleanup_warnings = blast_cleanup(
        project_name=target_name,
        project_root=target_root,
        source_command=command_name,
    )
    for warning in cleanup_warnings:
        emit_status(warning)
        if not interactive_command:
            print(f"Warning: {warning}")
