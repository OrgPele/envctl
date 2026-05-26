from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree, PlanSelectionResult
from envctl_engine.planning.worktree_import_commands import (
    ImportedBranchRef,
    WorktreeImportError,
    branch_exists_command,
    build_existing_branch_worktree_add_command,
    build_import_fetch_command,
    build_import_update_command,
    build_import_worktree_add_command,
    current_branch_command,
    find_worktree_for_branch,
    normalize_import_branch_ref,
    run_import_command,
    set_import_branch_upstream_command,
    worktree_list_command,
)
from envctl_engine.planning.worktree_provenance import WORKTREE_PROVENANCE_PATH, WORKTREE_PROVENANCE_SCHEMA_VERSION


def select_import_project(runtime: Any, route: object, project_contexts: list[Any]) -> list[Any]:
    del project_contexts
    branch_arg = _import_branch_arg(route)
    try:
        result = import_remote_branch_worktree(runtime, branch_arg)
    except (ValueError, WorktreeImportError) as exc:
        raise RuntimeError(str(exc)) from exc

    print(
        "Imported remote branch "
        f"{result.ref.remote_ref} -> {result.ref.local_branch} at {result.worktree.root}"
        f" ({result.action})."
    )
    planning_orchestrator = getattr(runtime, "planning_worktree_orchestrator", None)
    if planning_orchestrator is not None:
        planning_orchestrator._last_plan_selection_result = PlanSelectionResult(
            raw_projects=[(result.worktree.name, result.worktree.root)],
            selected_contexts=[],
            created_worktrees=(result.worktree,),
        )
    return runtime._contexts_from_raw_projects([(result.worktree.name, result.worktree.root)])


class ImportWorktreeResult:
    def __init__(self, *, ref: ImportedBranchRef, worktree: CreatedPlanWorktree, action: str) -> None:
        self.ref = ref
        self.worktree = worktree
        self.action = action


def import_remote_branch_worktree(runtime: Any, raw_branch: str) -> ImportWorktreeResult:
    ref = normalize_import_branch_ref(raw_branch)
    repo_root = runtime.config.base_dir
    target = repo_root / runtime.config.trees_dir_name / "imported" / ref.slug
    env = runtime._command_env(port=0)
    emit = getattr(runtime, "_emit", None)

    _emit(emit, "worktree.import.normalized", branch=ref.branch, remote=ref.remote, remote_ref=ref.remote_ref)
    fetch = run_import_command(
        build_import_fetch_command(repo_root=repo_root, ref=ref),
        cwd=repo_root,
        env=env,
        run=runtime.process_runner.run,
        timeout=120.0,
    )
    _emit_result(emit, "worktree.import.fetch", ref=ref, result=fetch)
    _ensure_ok(fetch, f"Remote branch not found or fetch failed: {ref.remote_ref}")

    existing_worktree = _existing_worktree_for_branch(runtime, ref=ref, repo_root=repo_root, env=env)
    if existing_worktree is not None:
        target = existing_worktree
        action = "reused"
    elif target.exists():
        _verify_target_branch(runtime, target=target, ref=ref, env=env)
        action = "reused"
    else:
        action = "created"
        _create_import_worktree(runtime, repo_root=repo_root, target=target, ref=ref, env=env, emit=emit)

    update = run_import_command(
        build_import_update_command(worktree_root=target, ref=ref),
        cwd=target,
        env=env,
        run=runtime.process_runner.run,
        timeout=120.0,
    )
    _emit_result(emit, "worktree.import.update", ref=ref, result=update, worktree_root=str(target))
    _ensure_ok(update, f"Imported worktree is dirty or diverged; ff-only update failed for {ref.remote_ref}.")

    runtime._link_repo_local_shared_artifacts(target=target)
    runtime._prepare_worktree_code_intelligence(target=target)
    _write_import_provenance(runtime, target=target, ref=ref)
    worktree = CreatedPlanWorktree(name=ref.project_name, root=target.resolve(), plan_file="")
    _emit(
        emit,
        "worktree.import.finish",
        branch=ref.branch,
        remote=ref.remote,
        remote_ref=ref.remote_ref,
        local_branch=ref.local_branch,
        worktree_root=str(target),
        action=action,
    )
    return ImportWorktreeResult(ref=ref, worktree=worktree, action=action)


def _import_branch_arg(route: object) -> str:
    passthrough = list(getattr(route, "passthrough_args", []) or [])
    if not passthrough:
        raise RuntimeError("Missing branch for --import.")
    return str(passthrough[0])


def _create_import_worktree(
    runtime: Any,
    *,
    repo_root: Path,
    target: Path,
    ref: ImportedBranchRef,
    env: dict[str, str],
    emit: Any,
) -> None:
    branch_exists = run_import_command(
        branch_exists_command(repo_root=repo_root, ref=ref),
        cwd=repo_root,
        env=env,
        run=runtime.process_runner.run,
        timeout=30.0,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    branch_already_exists = getattr(branch_exists, "returncode", 1) == 0
    if branch_already_exists:
        add_command = build_existing_branch_worktree_add_command(
            repo_root=repo_root,
            target=target,
            ref=ref,
            git_hooks_disabled=runtime._worktree_git_hooks_disabled(),
        )
    else:
        add_command = build_import_worktree_add_command(
            repo_root=repo_root,
            target=target,
            ref=ref,
            git_hooks_disabled=runtime._worktree_git_hooks_disabled(),
        )
    add = run_import_command(
        add_command,
        cwd=repo_root,
        env=env,
        run=runtime.process_runner.run,
        timeout=120.0,
    )
    _emit_result(emit, "worktree.import.worktree_add", ref=ref, result=add, worktree_root=str(target))
    _ensure_ok(add, f"Failed to create imported worktree for {ref.remote_ref}.")
    if branch_already_exists:
        upstream = run_import_command(
            set_import_branch_upstream_command(repo_root=repo_root, ref=ref),
            cwd=repo_root,
            env=env,
            run=runtime.process_runner.run,
            timeout=30.0,
        )
        _emit_result(emit, "worktree.import.upstream", ref=ref, result=upstream, worktree_root=str(target))
        _ensure_ok(upstream, f"Failed to set upstream for imported branch {ref.local_branch}.")


def _existing_worktree_for_branch(
    runtime: Any,
    *,
    ref: ImportedBranchRef,
    repo_root: Path,
    env: dict[str, str],
) -> Path | None:
    result = run_import_command(
        worktree_list_command(repo_root=repo_root),
        cwd=repo_root,
        env=env,
        run=runtime.process_runner.run,
        timeout=30.0,
    )
    if getattr(result, "returncode", 1) != 0:
        return None
    return find_worktree_for_branch(str(getattr(result, "stdout", "")), ref=ref)


def _verify_target_branch(runtime: Any, *, target: Path, ref: ImportedBranchRef, env: dict[str, str]) -> None:
    result = run_import_command(
        current_branch_command(worktree_root=target),
        cwd=target,
        env=env,
        run=runtime.process_runner.run,
        timeout=30.0,
    )
    branch = str(getattr(result, "stdout", "")).strip()
    if getattr(result, "returncode", 1) != 0 or branch != ref.local_branch:
        raise WorktreeImportError(
            f"Import target already exists but is not on {ref.local_branch}: {target}."
        )


def _write_import_provenance(runtime: Any, *, target: Path, ref: ImportedBranchRef) -> None:
    if not target.is_dir():
        return
    payload = {
        "schema_version": WORKTREE_PROVENANCE_SCHEMA_VERSION,
        "source_branch": ref.local_branch,
        "source_ref": ref.remote_ref,
        "resolution_reason": "remote_branch_import",
        "created_from_repo": str(runtime.config.base_dir.resolve()),
        "recorded_at": datetime.now(tz=UTC).isoformat(),
        "imported_branch": ref.branch,
        "import_remote": ref.remote,
        "remote_ref": ref.remote_ref,
        "local_branch": ref.local_branch,
    }
    path = target / WORKTREE_PROVENANCE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _ensure_ok(result: object, message: str) -> None:
    if getattr(result, "returncode", 1) == 0:
        return
    stderr = str(getattr(result, "stderr", "") or "").strip()
    raise WorktreeImportError(f"{message}{f' {stderr}' if stderr else ''}")


def _emit(emit: Any, event: str, **payload: object) -> None:
    if callable(emit):
        emit(event, **payload)


def _emit_result(emit: Any, event: str, *, ref: ImportedBranchRef, result: object, **payload: object) -> None:
    _emit(
        emit,
        event,
        branch=ref.branch,
        remote=ref.remote,
        remote_ref=ref.remote_ref,
        local_branch=ref.local_branch,
        returncode=getattr(result, "returncode", None),
        **payload,
    )
