from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
from typing import Any, Callable

from envctl_engine.actions.actions_worktree import delete_worktree_path
from envctl_engine.actions.action_target_support import action_target_identities, action_target_identity
from envctl_engine.planning import discover_tree_projects
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.launcher_support import main_repo_root_for_linked_worktree
from envctl_engine.runtime.runtime_context import resolve_process_runtime
from envctl_engine.ui.spinner import spinner, use_spinner_policy
from envctl_engine.ui.spinner_service import emit_spinner_policy, resolve_spinner_policy


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
    target_identities = action_target_identities(targets, fallback_name_from_root=True)
    total = max(len(target_identities), 1)
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
        for index, identity in enumerate(target_identities, start=1):
            target_root = identity.root
            target_name = identity.name
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


def run_self_destruct_worktree_action(orchestrator: Any, route: Route) -> int:
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
    cwd = Path.cwd().resolve()
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


def resolve_current_worktree_target(
    *,
    runtime: Any,
    require_configured_main_root: bool = False,
    current_cwd: Callable[[], Path] = Path.cwd,
    discover_tree_projects_fn: Callable[[Path, str], list[tuple[str, Path]]] = discover_tree_projects,
    main_repo_root_for_linked_worktree_fn: Callable[[Path], Path | None] = main_repo_root_for_linked_worktree,
    git_main_repo_root_for_worktree_fn: Callable[..., Path | None] | None = None,
) -> object | None:
    invocation_cwd = str(getattr(runtime, "env", {}).get("ENVCTL_INVOCATION_CWD") or "").strip()
    cwd = Path(invocation_cwd).expanduser().resolve() if invocation_cwd else current_cwd().resolve()
    raw_runtime = getattr(runtime, "raw_runtime", runtime)
    configured_root = getattr(getattr(raw_runtime, "config", None), "base_dir", None)
    configured_root_path = Path(str(configured_root)).expanduser().resolve() if configured_root is not None else None
    if require_configured_main_root and configured_root_path == cwd:
        return None
    trees_dir_name = str(getattr(getattr(raw_runtime, "config", None), "trees_dir_name", "trees"))
    if require_configured_main_root:
        if configured_root_path is None:
            return None
        repo_root = repo_root_from_worktree_layout(cwd, trees_dir_name)
        if repo_root is None:
            repo_root = main_repo_root_for_linked_worktree_fn(cwd)
        if repo_root is None or repo_root.resolve() != configured_root_path:
            return None
    else:
        resolver = git_main_repo_root_for_worktree_fn or main_repo_root_for_worktree
        repo_root = resolver(worktree_root=cwd, runtime=runtime, trees_dir_name=trees_dir_name)
        if repo_root is None:
            return None
    candidates = [
        SimpleNamespace(name=name, root=root)
        for name, root in discover_tree_projects_fn(repo_root, trees_dir_name)
    ]
    matches = [
        candidate
        for candidate in candidates
        if _path_is_at_or_under(cwd, Path(str(getattr(candidate, "root"))).resolve())
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def _path_is_at_or_under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def main_repo_root_for_worktree(*, worktree_root: Path, runtime: Any, trees_dir_name: str | None = None) -> Path | None:
    raw_runtime = getattr(runtime, "raw_runtime", runtime)
    configured_trees_dir = trees_dir_name or getattr(getattr(raw_runtime, "config", None), "trees_dir_name", "trees")
    normalized_trees_dir = str(configured_trees_dir).strip().rstrip("/")
    repo_root_from_layout = repo_root_from_worktree_layout(worktree_root, normalized_trees_dir)
    if repo_root_from_layout is not None:
        return repo_root_from_layout

    process_runtime = resolve_process_runtime(raw_runtime)
    completed = process_runtime.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=worktree_root,
        timeout=10.0,
    )
    if getattr(completed, "returncode", 1) != 0:
        return None
    top_level = Path(str(getattr(completed, "stdout", "") or "").strip()).resolve()

    common = process_runtime.run(
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


def spawn_self_destruct_helper(*, runtime: Any, repo_root: Path, trees_root: Path, worktree_root: Path) -> bool:
    raw_runtime = getattr(runtime, "raw_runtime", runtime)
    process_runtime = resolve_process_runtime(raw_runtime)
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
