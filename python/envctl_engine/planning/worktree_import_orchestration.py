from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree, PlanWorktreeSyncResult
from envctl_engine.planning.worktree_code_intelligence import prepare_worktree_code_intelligence
from envctl_engine.planning.worktree_git_hooks import worktree_git_hooks_disabled
from envctl_engine.planning.worktree_import_commands import (
    ImportedBranchRef,
    build_fetch_remote_branch_command,
    build_import_worktree_add_command,
    build_update_imported_worktree_command,
    imported_branch_slug,
    normalize_import_branch_ref,
)
from envctl_engine.planning.worktree_provenance import WORKTREE_PROVENANCE_PATH, WORKTREE_PROVENANCE_SCHEMA_VERSION
from envctl_engine.planning.worktree_shared_artifacts import link_repo_local_shared_artifacts


def import_remote_branch_worktree(self: Any, *, branch_input: str) -> PlanWorktreeSyncResult:
    try:
        branch_ref = normalize_import_branch_ref(branch_input)
    except ValueError as exc:
        return PlanWorktreeSyncResult(raw_projects=[], error=str(exc))

    repo_root = Path(self.config.base_dir)
    worktree_name = imported_branch_slug(branch_ref.branch)
    target = (
        repo_root
        / str(getattr(self.config, "trees_dir_name", "trees")).strip().rstrip("/")
        / "imported"
        / worktree_name
    ).resolve()
    env = self._command_env(port=0)
    _emit(
        self,
        "planning.import.normalized",
        branch=branch_ref.branch,
        local_branch=branch_ref.branch,
        remote=branch_ref.remote,
        remote_ref=branch_ref.remote_ref,
        worktree_root=str(target),
    )

    _emit_import_event(
        self,
        "planning.import.fetch.start",
        branch_ref=branch_ref,
        target=target,
    )
    fetch_result = _run(
        self,
        build_fetch_remote_branch_command(repo_root=repo_root, branch_ref=branch_ref),
        cwd=repo_root,
        env=env,
        timeout=120.0,
    )
    fetch_returncode = _returncode(fetch_result)
    _emit_import_event(
        self,
        "planning.import.fetch.result",
        branch_ref=branch_ref,
        target=target,
        action="fetch",
        returncode=fetch_returncode,
        **_failure_payload(fetch_returncode, "fetch_failed"),
    )
    if fetch_returncode != 0:
        return _error_result(
            branch_ref=branch_ref,
            target=target,
            action="fetch",
            result=fetch_result,
            failure_reason="fetch_failed",
            fallback=f"remote branch not found or fetch failed: {branch_ref.remote_ref}",
        )

    action = "reused" if target.is_dir() else "created"
    if target.is_dir():
        _emit_import_event(
            self,
            "planning.import.worktree.reuse",
            branch_ref=branch_ref,
            target=target,
            action=action,
        )
        current_branch = _git_output(self, ["git", "-C", str(target), "branch", "--show-current"], cwd=target, env=env)
        if current_branch != branch_ref.branch:
            actual_branch = current_branch or "<unknown>"
            _emit_import_event(
                self,
                "planning.import.worktree.branch_mismatch",
                branch_ref=branch_ref,
                target=target,
                action="reuse",
                failure_reason="wrong_branch",
                actual_branch=actual_branch,
                expected_branch=branch_ref.branch,
                target_path=str(target),
            )
            return PlanWorktreeSyncResult(
                raw_projects=[],
                error=(
                    "Import reuse failed: imported worktree target already exists on the wrong branch. "
                    f"actual_branch={actual_branch} expected_branch={branch_ref.branch} target={target}"
                ),
            )
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        _emit_import_event(
            self,
            "planning.import.worktree.create.start",
            branch_ref=branch_ref,
            target=target,
            action=action,
        )
        add_result = _run(
            self,
            build_import_worktree_add_command(
                repo_root=repo_root,
                target=target,
                branch_ref=branch_ref,
                git_hooks_disabled=worktree_git_hooks_disabled(self),
                local_branch_exists=_local_branch_exists(self, branch_ref.branch, cwd=repo_root, env=env),
            ),
            cwd=repo_root,
            env=env,
            timeout=120.0,
        )
        add_returncode = _returncode(add_result)
        add_failure_reason = _worktree_add_failure_reason(add_result) if add_returncode != 0 else None
        _emit_import_event(
            self,
            "planning.import.worktree.create.result",
            branch_ref=branch_ref,
            target=target,
            action=action,
            returncode=add_returncode,
            **_failure_payload(add_returncode, add_failure_reason),
        )
        if add_returncode != 0:
            assert add_failure_reason is not None
            return _error_result(
                branch_ref=branch_ref,
                target=target,
                action="worktree_add",
                result=add_result,
                failure_reason=add_failure_reason,
                fallback=_worktree_add_failure_summary(branch_ref, add_failure_reason),
            )

    _emit_import_event(
        self,
        "planning.import.update.start",
        branch_ref=branch_ref,
        target=target,
        action=action,
    )
    update_result = _run(
        self,
        build_update_imported_worktree_command(worktree_root=target, branch_ref=branch_ref),
        cwd=target,
        env=env,
        timeout=120.0,
    )
    update_returncode = _returncode(update_result)
    _emit_import_event(
        self,
        "planning.import.update.result",
        branch_ref=branch_ref,
        target=target,
        action=action,
        returncode=update_returncode,
        **_failure_payload(update_returncode, "ff_only_update_failed"),
    )
    if update_returncode != 0:
        return _error_result(
            branch_ref=branch_ref,
            target=target,
            action="ff_only_update",
            result=update_result,
            failure_reason="ff_only_update_failed",
            fallback=f"imported worktree could not fast-forward to {branch_ref.remote_ref}",
        )

    link_repo_local_shared_artifacts(repo_root=repo_root, target=target)
    prepare_worktree_code_intelligence(
        self,
        target=target,
        trees_root_for_worktree=lambda _self, worktree: worktree.parent.parent,
    )
    provenance_path = _write_import_provenance(self, target=target, branch_ref=branch_ref)
    if provenance_path is not None:
        _emit_import_event(
            self,
            "planning.import.provenance.write",
            branch_ref=branch_ref,
            target=target,
            action=action,
            provenance_path=str(provenance_path),
        )
    _emit(
        self,
        "planning.import.ready",
        branch=branch_ref.branch,
        local_branch=branch_ref.branch,
        remote=branch_ref.remote,
        remote_ref=branch_ref.remote_ref,
        worktree_root=str(target),
        action=action,
    )
    print(
        "Imported remote branch "
        f"{branch_ref.remote_ref} -> {target} "
        f"(local branch: {branch_ref.branch}, action: {action})"
    )

    created = CreatedPlanWorktree(name=worktree_name, root=target.resolve(), plan_file="")
    return PlanWorktreeSyncResult(raw_projects=[(created.name, created.root)], created_worktrees=(created,))


def _write_import_provenance(self: Any, *, target: Path, branch_ref: ImportedBranchRef) -> Path | None:
    if not target.is_dir():
        return None
    payload: dict[str, object] = {
        "schema_version": WORKTREE_PROVENANCE_SCHEMA_VERSION,
        "source_branch": branch_ref.branch,
        "source_ref": branch_ref.remote_ref,
        "resolution_reason": "remote_branch_import",
        "created_from_repo": str(Path(self.config.base_dir).resolve()),
        "recorded_at": datetime.now(tz=UTC).isoformat(),
        "imported_branch": branch_ref.branch,
        "import_remote": branch_ref.remote,
        "remote_ref": branch_ref.remote_ref,
    }
    path = target / WORKTREE_PROVENANCE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _local_branch_exists(self: Any, branch: str, *, cwd: Path, env: dict[str, str]) -> bool:
    result = _run(
        self,
        ["git", "-C", str(cwd), "rev-parse", "--verify", f"refs/heads/{branch}"],
        cwd=cwd,
        env=env,
        timeout=30.0,
    )
    return _returncode(result) == 0


def _git_output(self: Any, command: list[str], *, cwd: Path, env: dict[str, str]) -> str:
    result = _run(self, command, cwd=cwd, env=env, timeout=30.0)
    if _returncode(result) != 0:
        return ""
    return str(getattr(result, "stdout", "") or "").strip()


def _run(self: Any, command: list[str], *, cwd: Path, env: dict[str, str], timeout: float) -> object:
    try:
        return self.process_runner.run(command, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout)
    except TypeError:
        return self.process_runner.run(command, cwd=cwd, env=env, timeout=timeout)


def _returncode(result: object) -> int:
    return int(getattr(result, "returncode", 1))


def _failure_payload(returncode: int, failure_reason: str | None) -> dict[str, object]:
    if returncode == 0 or not failure_reason:
        return {}
    return {"failure_reason": failure_reason}


def _result_detail(result: object, fallback: str) -> str:
    stderr = str(getattr(result, "stderr", "") or "").strip()
    stdout = str(getattr(result, "stdout", "") or "").strip()
    return stderr or stdout or fallback


def _worktree_add_failure_reason(result: object) -> str:
    detail = _result_detail(result, "").lower()
    if "already used by worktree" in detail or "already checked out" in detail:
        return "local_branch_checked_out_elsewhere"
    return "worktree_add_failed"


def _worktree_add_failure_summary(branch_ref: ImportedBranchRef, failure_reason: str) -> str:
    if failure_reason == "local_branch_checked_out_elsewhere":
        return (
            f"local branch {branch_ref.branch} is already checked out in another worktree; "
            f"free that worktree or use its existing checkout before importing {branch_ref.remote_ref}"
        )
    return f"failed to create imported worktree for {branch_ref.remote_ref}"


def _error_result(
    *,
    branch_ref: ImportedBranchRef,
    target: Path,
    action: str,
    result: object,
    failure_reason: str,
    fallback: str,
) -> PlanWorktreeSyncResult:
    detail = _result_detail(result, fallback)
    return PlanWorktreeSyncResult(
        raw_projects=[],
        error=(
            f"Import {action} failed: {fallback}. action={action} failure_reason={failure_reason} "
            f"branch={branch_ref.branch} remote={branch_ref.remote} remote_ref={branch_ref.remote_ref} "
            f"worktree={target}: {detail}"
        ),
    )


def _emit(self: Any, event: str, **payload: object) -> None:
    emit = getattr(self, "_emit", None)
    if callable(emit):
        emit(event, **payload)


def _emit_import_event(
    self: Any,
    event: str,
    *,
    branch_ref: ImportedBranchRef,
    target: Path,
    **payload: object,
) -> None:
    _emit(
        self,
        event,
        branch=branch_ref.branch,
        local_branch=branch_ref.branch,
        remote=branch_ref.remote,
        remote_ref=branch_ref.remote_ref,
        worktree_root=str(target),
        **payload,
    )
