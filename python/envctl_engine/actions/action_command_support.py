from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from envctl_engine.actions.action_utils import envctl_python_root
from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.parsing import parse_bool


def build_action_replacements(
    *,
    repo_root: Path,
    targets: list[object],
    target: object | None,
) -> dict[str, str]:
    project_names = [str(getattr(ctx, "name")) for ctx in targets if hasattr(ctx, "name")]
    replacements = {
        "repo_root": str(repo_root),
        "projects_csv": ",".join(project_names),
    }
    if target is not None:
        replacements["project"] = str(getattr(target, "name"))
        replacements["project_root"] = str(getattr(target, "root"))
    return replacements


def service_types_from_route_services(route: Route) -> set[str]:
    services = route.flags.get("services")
    if not isinstance(services, list):
        return set()
    selected: set[str] = set()
    for item in services:
        normalized = str(item).strip().lower()
        if not normalized:
            continue
        if normalized.endswith(" backend") or normalized == "backend":
            selected.add("backend")
        elif normalized.endswith(" frontend") or normalized == "frontend":
            selected.add("frontend")
    return selected


def build_action_extra_env(route: Route) -> dict[str, str]:
    extra: dict[str, str] = {}
    if isinstance(route.flags.get("pr_base"), str):
        extra["ENVCTL_PR_BASE"] = str(route.flags["pr_base"])
    if isinstance(route.flags.get("pr_body"), str):
        extra["ENVCTL_PR_BODY"] = str(route.flags["pr_body"])
    if isinstance(route.flags.get("commit_message"), str):
        extra["ENVCTL_COMMIT_MESSAGE"] = str(route.flags["commit_message"])
    if isinstance(route.flags.get("commit_message_file"), str):
        extra["ENVCTL_COMMIT_MESSAGE_FILE"] = str(route.flags["commit_message_file"])
    if isinstance(route.flags.get("analyze_mode"), str):
        extra["ENVCTL_ANALYZE_MODE"] = str(route.flags["analyze_mode"])
    service_types = service_types_from_route_services(route)
    if service_types == {"backend"}:
        extra["ENVCTL_ANALYZE_SCOPE"] = "backend"
    elif service_types == {"frontend"}:
        extra["ENVCTL_ANALYZE_SCOPE"] = "frontend"
    return extra


def build_action_env(
    *,
    process_env: Mapping[str, str],
    runtime_env: Mapping[str, str],
    repo_root: Path,
    runtime_root: Path | None,
    run_id: str | None,
    tree_diffs_root: Path | None,
    command_name: str,
    targets: list[object],
    route: Route | None,
    target: object | None,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = dict(process_env)
    env.update(runtime_env)
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("GH_PROMPT_DISABLED", "1")
    env.setdefault("GCM_INTERACTIVE", "Never")
    python_path = str(envctl_python_root())
    existing_path = env.get("PYTHONPATH")
    if existing_path:
        paths = existing_path.split(os.pathsep)
        if python_path not in paths:
            env["PYTHONPATH"] = os.pathsep.join([python_path, *paths])
    else:
        env["PYTHONPATH"] = python_path
    env["ENVCTL_ACTION_COMMAND"] = command_name
    env["ENVCTL_ACTION_PROJECTS"] = ",".join(
        str(getattr(context, "name")) for context in targets if hasattr(context, "name")
    )
    env["ENVCTL_ACTION_REPO_ROOT"] = str(repo_root)
    if runtime_root is not None:
        env["ENVCTL_ACTION_RUNTIME_ROOT"] = str(runtime_root)
    if run_id:
        env["ENVCTL_ACTION_RUN_ID"] = run_id
    if tree_diffs_root is not None:
        env["ENVCTL_ACTION_TREE_DIFFS_ROOT"] = str(tree_diffs_root)
    if target is not None:
        env["ENVCTL_ACTION_PROJECT"] = str(getattr(target, "name"))
        env["ENVCTL_ACTION_PROJECT_ROOT"] = str(getattr(target, "root"))
    if route is not None:
        batch_requested = bool(route.flags.get("batch")) or parse_bool(env.get("BATCH"), False)
        interactive_action = bool(route.flags.get("interactive_command")) or not batch_requested
        env["ENVCTL_ACTION_INTERACTIVE"] = "1" if interactive_action else "0"
    if extra:
        env.update(extra)
    return env
