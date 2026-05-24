from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from envctl_engine.planning import planning_existing_counts
from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.parsing import parse_bool


def route_requests_fresh_ai_worktree(route: Route) -> bool:
    flags = getattr(route, "flags", {}) or {}
    if not bool(flags.get("new_session")):
        return False
    if bool(flags.get("dry_run")):
        return False
    return bool(flags.get("cmux") or flags.get("tmux") or flags.get("omx"))


def fresh_ai_launch_transport(route: Route) -> str:
    flags = getattr(route, "flags", {}) or {}
    if bool(flags.get("omx")):
        return "omx"
    if bool(flags.get("tmux")):
        return "tmux"
    if bool(flags.get("cmux")):
        return "cmux"
    return ""


def adjust_plan_counts_for_fresh_ai_launch(
    *,
    raw_projects: list[tuple[str, Path]],
    plan_counts: OrderedDict[str, int],
    route: Route,
) -> OrderedDict[str, int]:
    if not route_requests_fresh_ai_worktree(route):
        return plan_counts
    existing_counts = planning_existing_counts(projects=raw_projects, planning_files=list(plan_counts.keys()))
    adjusted: OrderedDict[str, int] = OrderedDict()
    for plan_file, requested_count in plan_counts.items():
        adjusted[plan_file] = int(requested_count) + int(existing_counts.get(plan_file, 0))
    return adjusted


def planning_keep_plan_enabled(
    *,
    route: Route,
    env: Mapping[str, str],
    config_raw: Mapping[str, Any],
) -> bool:
    if bool(route.flags.get("keep_plan")):
        return True
    raw = env.get("PLANNING_KEEP_PLAN") or config_raw.get("PLANNING_KEEP_PLAN")
    return parse_bool(raw, False)
