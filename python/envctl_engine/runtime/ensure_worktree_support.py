from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from envctl_engine.actions.actions_worktree import delete_worktree_path


def run_ensure_worktree_command(runtime: Any, route: object) -> int:
    flags = getattr(route, "flags", {}) or {}
    passthrough_args = [str(token).strip() for token in (getattr(route, "passthrough_args", []) or []) if str(token).strip()]
    json_output = bool(flags.get("json"))
    dry_run = bool(flags.get("dry_run"))
    recreate_existing = bool(flags.get("setup_worktree_recreate"))

    if not getattr(runtime, "_command_exists", lambda _name: False)("git"):
        print("Missing required executables: git")
        return 1

    parsed, error = _parse_ensure_worktree_args(passthrough_args)
    if error is not None:
        return _print_ensure_worktree_failure(error=error, json_output=json_output)
    assert parsed is not None

    feature = parsed["feature"]
    iteration = parsed["iteration"]
    feature_root = runtime._preferred_tree_root_for_feature(feature)
    worktree_root = feature_root / iteration
    existed_before = worktree_root.exists()
    action = "recreate" if existed_before and recreate_existing else ("reuse" if existed_before else "create")

    if dry_run:
        return _print_ensure_worktree_success(
            feature=feature,
            iteration=iteration,
            worktree_root=worktree_root,
            branch_name=f"{feature}-{iteration}",
            action=action,
            existed_before=existed_before,
            created=not existed_before,
            dry_run=True,
            json_output=json_output,
        )

    if existed_before and recreate_existing:
        result = delete_worktree_path(
            repo_root=runtime.config.base_dir,
            trees_root=runtime._trees_root_for_worktree(worktree_root),
            worktree_root=worktree_root,
            process_runner=runtime.process_runner,
        )
        if not result.success:
            return _print_ensure_worktree_failure(error=result.message, json_output=json_output)

    if not worktree_root.exists():
        create_error = runtime._create_single_worktree(feature=feature, iteration=iteration)
        if create_error:
            return _print_ensure_worktree_failure(error=create_error, json_output=json_output)

    return _print_ensure_worktree_success(
        feature=feature,
        iteration=iteration,
        worktree_root=worktree_root,
        branch_name=f"{feature}-{iteration}",
        action=action,
        existed_before=existed_before,
        created=not existed_before or recreate_existing,
        dry_run=False,
        json_output=json_output,
    )


def _parse_ensure_worktree_args(args: list[str]) -> tuple[dict[str, str] | None, str | None]:
    if not args:
        return None, "ensure-worktree requires <feature> [iteration]"
    if len(args) > 2:
        return None, f"Unexpected extra arguments for ensure-worktree: {', '.join(args[2:])}"
    feature = args[0].strip()
    if not feature:
        return None, "ensure-worktree requires <feature> [iteration]"
    if "/" in feature or feature in {".", ".."}:
        return None, f"Invalid feature name for ensure-worktree: {feature}"
    iteration = args[1].strip() if len(args) == 2 else "1"
    if not iteration.isdigit() or int(iteration) < 1:
        return None, f"Invalid iteration for ensure-worktree {feature}: {iteration}"
    return {"feature": feature, "iteration": str(int(iteration))}, None


def _print_ensure_worktree_failure(*, error: str, json_output: bool) -> int:
    if json_output:
        print(
            json.dumps(
                {
                    "contract_version": "envctl.ensure_worktree.v1",
                    "surface": "ensure-worktree",
                    "ok": False,
                    "error": error,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(error)
    return 1


def _print_ensure_worktree_success(
    *,
    feature: str,
    iteration: str,
    worktree_root: Path,
    branch_name: str,
    action: str,
    existed_before: bool,
    created: bool,
    dry_run: bool,
    json_output: bool,
) -> int:
    payload = {
        "contract_version": "envctl.ensure_worktree.v1",
        "surface": "ensure-worktree",
        "ok": True,
        "feature": feature,
        "iteration": iteration,
        "project_name": f"{feature}-{iteration}",
        "branch_name": branch_name,
        "worktree_root": str(worktree_root.resolve()),
        "feature_root": str(worktree_root.parent.resolve()),
        "action": action,
        "existed_before": existed_before,
        "created": created,
        "runtime_started": False,
        "dry_run": dry_run,
    }
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{action}: {payload['project_name']} -> {payload['worktree_root']}")
    return 0
