from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree, PlanWorktreeSyncResult


def create_single_worktree(
    *,
    feature: str,
    iteration: str,
    preferred_tree_root_for_feature: Callable[[str], Path],
    command_env: Callable[..., Mapping[str, str]],
    run_worktree_add: Callable[..., Any],
    recover_partial_worktree_creation: Callable[..., bool],
    link_repo_local_shared_artifacts: Callable[..., None],
    prepare_worktree_code_intelligence: Callable[..., None],
    write_worktree_provenance: Callable[..., None],
    worktree_add_failure: Callable[..., str | None],
) -> str | None:
    feature_root = preferred_tree_root_for_feature(feature)
    feature_root.mkdir(parents=True, exist_ok=True)
    target = feature_root / iteration
    result = run_worktree_add(
        feature=feature,
        iteration=iteration,
        target=target,
        env=command_env(port=0),
    )
    if getattr(result, "returncode", 1) != 0:
        if recover_partial_worktree_creation(feature=feature, iteration=iteration, target=target, result=result):
            link_repo_local_shared_artifacts(target=target)
            prepare_worktree_code_intelligence(target=target)
            write_worktree_provenance(target=target)
            return None
        error = worktree_add_failure(feature=feature, iteration=iteration, target=target, result=result)
        if error:
            return error
    else:
        link_repo_local_shared_artifacts(target=target)
        prepare_worktree_code_intelligence(target=target)
        write_worktree_provenance(target=target)
    return None


def create_feature_worktrees(
    *,
    feature: str,
    count: int,
    plan_file: str,
    create_feature_worktrees_result: Callable[..., PlanWorktreeSyncResult],
) -> str | None:
    return create_feature_worktrees_result(feature=feature, count=count, plan_file=plan_file).error


def create_feature_worktrees_result(
    *,
    feature: str,
    count: int,
    plan_file: str,
    preferred_tree_root_for_feature: Callable[[str], Path],
    planning_root: Callable[[], Path],
    command_env: Callable[..., Mapping[str, str]],
    run_worktree_add: Callable[..., Any],
    recover_partial_worktree_creation: Callable[..., bool],
    write_worktree_provenance: Callable[..., None],
    prepare_worktree_code_intelligence: Callable[..., None],
    worktree_add_failure: Callable[..., str | None],
    seed_main_task_from_plan: Callable[..., None],
    next_available_iteration: Callable[[set[int]], int],
    worktree_project_name: Callable[..., str],
    env: Mapping[str, str],
    config_raw: Mapping[str, str],
    created_for_fresh_ai_launch: bool = False,
    launch_transport: str = "",
) -> PlanWorktreeSyncResult:
    if count <= 0:
        return PlanWorktreeSyncResult(raw_projects=[])
    feature_root = preferred_tree_root_for_feature(feature)
    feature_root.mkdir(parents=True, exist_ok=True)
    existing_iters = {int(path.name) for path in feature_root.iterdir() if path.is_dir() and path.name.isdigit()}
    plan_path = planning_root() / plan_file
    setup_env = command_env(port=0, extra={"PLAN_FILE": str(plan_path)})
    created_worktrees: list[CreatedPlanWorktree] = []
    cli_sequence = _plan_agent_cli_sequence(env=env, config_raw=config_raw, count=count)

    for index in range(count):
        iteration = next_available_iteration(existing_iters)
        target = feature_root / str(iteration)
        result = run_worktree_add(feature=feature, iteration=str(iteration), target=target, env=setup_env)
        if getattr(result, "returncode", 1) != 0:
            if recover_partial_worktree_creation(
                feature=feature,
                iteration=str(iteration),
                target=target,
                result=result,
            ):
                write_worktree_provenance(
                    target=target,
                    plan_file=plan_file,
                    created_for_fresh_ai_launch=created_for_fresh_ai_launch,
                    launch_transport=launch_transport,
                )
                prepare_worktree_code_intelligence(target=target)
            else:
                error = worktree_add_failure(
                    feature=feature,
                    iteration=str(iteration),
                    target=target,
                    result=result,
                )
                if error:
                    return PlanWorktreeSyncResult(
                        raw_projects=[],
                        created_worktrees=tuple(created_worktrees),
                        error=error,
                    )
        else:
            write_worktree_provenance(
                target=target,
                plan_file=plan_file,
                created_for_fresh_ai_launch=created_for_fresh_ai_launch,
                launch_transport=launch_transport,
            )
            prepare_worktree_code_intelligence(target=target)
        seed_main_task_from_plan(target=target, plan_path=plan_path)
        worktree_cli = cli_sequence[index] if index < len(cli_sequence) else ""
        created_worktrees.append(
            CreatedPlanWorktree(
                name=worktree_project_name(feature=feature, iteration=iteration),
                root=target.resolve(),
                plan_file=plan_file,
                cli=worktree_cli,
            )
        )
        existing_iters.add(iteration)
    return PlanWorktreeSyncResult(raw_projects=[], created_worktrees=tuple(created_worktrees))


def _plan_agent_cli_sequence(*, env: Mapping[str, str], config_raw: Mapping[str, str], count: int) -> list[str]:
    requested_cli = str(env.get("ENVCTL_PLAN_AGENT_CLI") or config_raw.get("ENVCTL_PLAN_AGENT_CLI") or "").strip()
    if requested_cli.lower() == "both" and count == 2:
        return ["codex", "opencode"]
    return [""] * count
