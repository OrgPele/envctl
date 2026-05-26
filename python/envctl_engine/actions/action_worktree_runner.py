from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, cast

import envctl_engine.actions.action_worktree_self_destruct as _self_destruct
import envctl_engine.actions.action_worktree_target_resolution as _target_resolution
from envctl_engine.actions.actions_worktree import delete_worktree_path
from envctl_engine.actions.action_target_support import action_target_identities
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.runtime_context import resolve_process_runtime
from envctl_engine.ui.spinner import spinner, use_spinner_policy
from envctl_engine.ui.spinner_service import emit_spinner_policy, resolve_spinner_policy

CurrentWorktreeTargetResolver = _target_resolution.CurrentWorktreeTargetResolver
main_repo_root_for_worktree = _target_resolution.main_repo_root_for_worktree
repo_root_from_worktree_layout = _target_resolution.repo_root_from_worktree_layout
resolve_current_worktree_target = _target_resolution.resolve_current_worktree_target
spawn_self_destruct_helper = _self_destruct.spawn_self_destruct_helper


@dataclass(slots=True)
class ActionWorktreeDeleteRunner:
    orchestrator: Any
    route: Route

    @property
    def runtime(self) -> Any:
        return self.orchestrator.runtime

    @property
    def command_name(self) -> str:
        return self.route.command if self.route.command in {"delete-worktree", "blast-worktree"} else "delete-worktree"

    def execute(self) -> int:
        if bool(self.route.flags.get("all")) and not bool(self.route.flags.get("yes")):
            print(f"{self.command_name} --all requires --yes")
            return 1

        targets, error = self.orchestrator.resolve_targets(self.route, trees_only=True)
        if error is not None:
            print(error)
            return 1

        self.runtime._emit("action.command.start", command=self.route.command, mode=self.route.mode)  # type: ignore[attr-defined]
        self.orchestrator._emit_status(self.orchestrator._command_start_status(self.command_name, targets))
        spinner_policy = resolve_spinner_policy(getattr(self.runtime, "env", {}))
        op_id = f"action.{self.command_name}"
        emit_spinner_policy(
            getattr(self.runtime, "_emit", None),
            spinner_policy,
            context={"component": "action.command", "command": self.route.command, "op_id": op_id},
        )

        dry_run = bool(self.route.flags.get("dry_run"))
        failures = 0
        target_identities = action_target_identities(targets, fallback_name_from_root=True)
        total = max(len(target_identities), 1)
        spinner_message = (
            "Blasting selected worktrees..."
            if self.command_name == "blast-worktree"
            else "Deleting selected worktrees..."
        )
        with (
            use_spinner_policy(spinner_policy),
            spinner(
                spinner_message,
                enabled=spinner_policy.enabled,
                start_immediately=False,
            ) as active_spinner,
        ):
            self._start_spinner(active_spinner, spinner_policy=spinner_policy, op_id=op_id, message=spinner_message)
            for index, identity in enumerate(target_identities, start=1):
                failures += self._delete_one(
                    identity=identity,
                    index=index,
                    total=total,
                    dry_run=dry_run,
                    active_spinner=active_spinner,
                    spinner_policy=spinner_policy,
                    op_id=op_id,
                )
            self._finish_spinner(active_spinner, spinner_policy=spinner_policy, op_id=op_id, failures=failures)
        return 0 if failures == 0 else 1

    def _delete_one(
        self,
        *,
        identity: Any,
        index: int,
        total: int,
        dry_run: bool,
        active_spinner: Any,
        spinner_policy: object,
        op_id: str,
    ) -> int:
        target_root = identity.root
        target_name = identity.name
        progress = f"Deleting worktree {target_name} ({index}/{total})..."
        self.orchestrator._emit_status(progress)
        self._update_spinner(active_spinner, spinner_policy=spinner_policy, op_id=op_id, message=progress)
        _run_cleanup(
            runtime=self.runtime,
            command_name=self.command_name,
            interactive_command=bool(self.route.flags.get("interactive_command")),
            dry_run=dry_run,
            target_name=target_name,
            target_root=target_root,
            emit_status=self.orchestrator._emit_status,
        )
        result = delete_worktree_path(
            repo_root=self.runtime.config.base_dir,  # type: ignore[attr-defined]
            trees_root=self.runtime._trees_root_for_worktree(target_root),  # type: ignore[attr-defined]
            worktree_root=target_root,
            process_runner=resolve_process_runtime(getattr(self.runtime, "raw_runtime", self.runtime)),
            dry_run=dry_run,
        )
        if not bool(self.route.flags.get("interactive_command")):
            print(result.message)
        if result.success:
            self.orchestrator._emit_status(f"{self.command_name} succeeded for {target_name}")
            return 0
        self.orchestrator._emit_status(f"{self.command_name} failed for {target_name}")
        return 1

    def _start_spinner(self, active_spinner: Any, *, spinner_policy: object, op_id: str, message: str) -> None:
        if not bool(getattr(spinner_policy, "enabled", False)):
            return
        active_spinner.start()
        self._emit_spinner_lifecycle(op_id=op_id, state="start", message=message)

    def _update_spinner(self, active_spinner: Any, *, spinner_policy: object, op_id: str, message: str) -> None:
        if not bool(getattr(spinner_policy, "enabled", False)):
            return
        active_spinner.update(message)
        self._emit_spinner_lifecycle(op_id=op_id, state="update", message=message)

    def _finish_spinner(self, active_spinner: Any, *, spinner_policy: object, op_id: str, failures: int) -> None:
        if not bool(getattr(spinner_policy, "enabled", False)):
            return
        if failures == 0:
            active_spinner.succeed(f"{self.command_name} completed")
            self._emit_spinner_lifecycle(op_id=op_id, state="success", message=f"{self.command_name} completed")
        else:
            active_spinner.fail(f"{self.command_name} failed")
            self._emit_spinner_lifecycle(op_id=op_id, state="fail", message=f"{self.command_name} failed")
        self._emit_spinner_lifecycle(op_id=op_id, state="stop")

    def _emit_spinner_lifecycle(self, *, op_id: str, state: str, message: str | None = None) -> None:
        payload: dict[str, object] = {
            "component": "action.command",
            "command": self.route.command,
            "op_id": op_id,
            "state": state,
        }
        if message is not None:
            payload["message"] = message
        self.runtime._emit("ui.spinner.lifecycle", **payload)  # type: ignore[attr-defined]


def run_delete_worktree_action(orchestrator: Any, route: Route) -> int:
    return ActionWorktreeDeleteRunner(orchestrator=orchestrator, route=route).execute()


def run_self_destruct_worktree_action(orchestrator: Any, route: Route) -> int:
    return _self_destruct.run_self_destruct_worktree_action(orchestrator, route, current_cwd=Path.cwd)


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
    cleanup_warnings = cast(
        list[str],
        blast_cleanup(
            project_name=target_name,
            project_root=target_root,
            source_command=command_name,
        ),
    )
    for warning in cleanup_warnings:
        emit_status(warning)
        if not interactive_command:
            print(f"Warning: {warning}")
