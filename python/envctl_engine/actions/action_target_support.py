from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, cast

from envctl_engine.runtime.command_router import Route
from envctl_engine.ui.selection_types import TargetSelection


@dataclass(frozen=True)
class ActionCommandResolution:
    command: list[str] | None
    cwd: Path | None
    error: str | None = None


@dataclass(frozen=True)
class ActionTargetContext:
    name: str
    root: Path
    index: int
    total: int
    target_obj: object


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


def main_repo_root_for_worktree(
    worktree_root: Path,
    *,
    trees_dir_name: str,
    process_run: Callable[[list[str], Path], object],
) -> Path | None:
    repo_root_from_layout = repo_root_from_worktree_layout(worktree_root, trees_dir_name)
    if repo_root_from_layout is not None:
        return repo_root_from_layout

    completed = process_run(["git", "rev-parse", "--show-toplevel"], worktree_root)
    if getattr(completed, "returncode", 1) != 0:
        return None
    top_level = Path(str(getattr(completed, "stdout", "") or "").strip()).resolve()

    common = process_run(["git", "rev-parse", "--git-common-dir"], worktree_root)
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


def projects_for_services(
    service_targets: Sequence[object],
    *,
    load_existing_state: Callable[[str], object | None],
    project_name_from_service: Callable[[str], str],
) -> list[str]:
    normalized_targets = [
        str(target).strip().lower().removeprefix("service:")
        for target in service_targets
        if str(target).strip()
    ]
    if not normalized_targets:
        return []

    state = load_existing_state("trees") or load_existing_state("main")
    resolved: list[str] = []
    for target in normalized_targets:
        matched = False
        if state is not None:
            services = getattr(state, "services", {})
            for service_name, service in services.items():
                service_type = str(getattr(service, "type", "") or "").strip().lower()
                if str(service_name).lower() == target or service_type == target:
                    project = project_name_from_service(str(service_name))
                    if project:
                        resolved.append(project)
                        matched = True
        if matched:
            continue
        project = project_name_from_service(target)
        if project:
            resolved.append(project)

    deduped: list[str] = []
    seen: set[str] = set()
    for project in resolved:
        lowered = project.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(project)
    return deduped


def resolve_action_targets(
    *,
    route: Route,
    trees_only: bool,
    discover_projects: Callable[[str], list[object]],
    selectors_from_passthrough: Callable[[list[str]], set[str]],
    load_existing_state: Callable[[str], object | None],
    project_name_from_service: Callable[[str], str],
    select_project_targets: Callable[..., object],
    resolve_current_worktree_target: Callable[[bool], object | None],
    interactive_selection_allowed: Callable[[Route], bool],
    no_target_selected_message: Callable[[Route], str],
) -> tuple[list[object], str | None]:
    if trees_only and route.command == "self-destruct-worktree":
        current = resolve_current_worktree_target(False)
        if current is not None:
            return [current], None
        return [], "self-destruct-worktree must be run from inside a discovered worktree."
    if not trees_only and route.mode == "main" and route.command in {"commit", "pr", "test"}:
        current = resolve_current_worktree_target(True)
        if current is not None:
            return [current], None
    if trees_only:
        candidates = discover_projects("trees")
    else:
        candidates = discover_projects(route.mode)
        if not candidates and route.mode == "main":
            candidates = discover_projects("trees")

    run_all = bool(route.flags.get("all"))
    untested_selected = bool(route.flags.get("untested"))
    project_selectors = {name.lower() for name in route.projects}
    project_selectors.update(selectors_from_passthrough(route.passthrough_args))

    services = route.flags.get("services")
    if isinstance(services, list):
        for project in projects_for_services(
            services,
            load_existing_state=load_existing_state,
            project_name_from_service=project_name_from_service,
        ):
            project_selectors.add(project.lower())

    if run_all:
        if not candidates:
            return [], "No projects discovered for selected mode."
        return candidates, None

    if not project_selectors and not run_all:
        if len(candidates) == 1:
            return candidates, None
        if interactive_selection_allowed(route):
            selection = cast(
                TargetSelection,
                select_project_targets(
                    prompt=f"Select {route.command} target",
                    projects=candidates,
                    allow_all=True,
                    allow_untested=route.command == "test",
                    multi=True,
                ),
            )
            if selection.cancelled:
                return [], no_target_selected_message(route)
            selection.apply_to_route(route)
            run_all = bool(route.flags.get("all"))
            project_selectors = {name.lower() for name in route.projects}
            untested_selected = bool(route.flags.get("untested"))
        else:
            return [], no_target_selected_message(route)

    if not project_selectors and not run_all and not untested_selected:
        return [], no_target_selected_message(route)
    if run_all:
        if not candidates:
            return [], "No projects discovered for selected mode."
        return candidates, None
    selected = [candidate for candidate in candidates if str(getattr(candidate, "name")).lower() in project_selectors]
    if not selected:
        if route.command == "test" and untested_selected:
            return [], None
        requested = ", ".join(sorted(project_selectors))
        return [], f"No matching targets found for: {requested}"
    return selected, None


def build_action_target_contexts(targets: Sequence[object]) -> list[ActionTargetContext]:
    total = max(len(targets), 1)
    return [
        ActionTargetContext(
            name=str(getattr(target, "name")),
            root=Path(str(getattr(target, "root"))),
            index=index,
            total=total,
            target_obj=target,
        )
        for index, target in enumerate(targets, start=1)
    ]


def emit_action_output(
    output: str | None,
    *,
    emit_status: Callable[[str], None],
    printer: Callable[[str], None] = print,
) -> bool:
    lines: list[str] = []
    for raw in str(output or "").splitlines():
        text = raw.strip()
        if text:
            lines.append(text)
    if not lines:
        return False
    for line in lines:
        printer(line)
        emit_status(line)
    return True


def execute_targeted_action(
    *,
    targets: Sequence[object],
    command_name: str,
    interactive_command: bool,
    resolve_command: Callable[[ActionTargetContext], ActionCommandResolution],
    build_env: Callable[[ActionTargetContext], Mapping[str, str]],
    process_run: Callable[[list[str], Path, Mapping[str, str]], Any],
    emit_status: Callable[[str], None],
    printer: Callable[[str], None] = print,
    interactive_print_failures: bool = True,
    emit_success_output: bool = True,
    on_success: Callable[[ActionTargetContext, Any], None] | None = None,
    on_failure: Callable[[ActionTargetContext, str], None] | None = None,
    failure_status_formatter: Callable[[ActionTargetContext, str], str] | None = None,
    print_noninteractive_failures: bool = True,
    print_noninteractive_successes: bool = True,
) -> int:
    def should_print_failure() -> bool:
        return (not interactive_command and print_noninteractive_failures) or (
            interactive_command and interactive_print_failures
        )

    failures = 0
    for context in build_action_target_contexts(targets):
        emit_status(f"Running {command_name} for {context.name} ({context.index}/{context.total})...")
        resolution = resolve_command(context)
        if resolution.command is None or resolution.cwd is None:
            raw_error = resolution.error or "no command resolved"
            message = f"{command_name} action failed for {context.name}: {raw_error}"
            if on_failure is not None:
                on_failure(context, raw_error)
            if should_print_failure():
                printer(message)
            if interactive_command:
                if failure_status_formatter is not None:
                    emit_status(failure_status_formatter(context, raw_error))
                else:
                    emit_status(f"{command_name} failed for {context.name}: {raw_error}")
            failures += 1
            continue

        completed = process_run(resolution.command, resolution.cwd, build_env(context))
        if completed.returncode != 0:
            stdout = str(getattr(completed, "stdout", "") or "").strip()
            stderr = str(getattr(completed, "stderr", "") or "").strip()
            if stderr and stdout and stderr != stdout:
                error = f"{stderr}\n\nstdout:\n{stdout}"
            else:
                error = stderr or stdout or f"exit:{completed.returncode}"
            message = f"{command_name} action failed for {context.name}: {error}"
            if on_failure is not None:
                on_failure(context, error)
            if should_print_failure():
                printer(message)
            if interactive_command:
                if failure_status_formatter is not None:
                    emit_status(failure_status_formatter(context, error))
                else:
                    emit_status(f"{command_name} failed for {context.name}: {error}")
            failures += 1
            continue

        if emit_success_output:
            emit_action_output(completed.stdout, emit_status=emit_status, printer=printer)
        if on_success is not None:
            on_success(context, completed)
        if not interactive_command and print_noninteractive_successes:
            printer(f"{command_name} action succeeded for {context.name}.")
        emit_status(f"{command_name} succeeded for {context.name}")

    return 0 if failures == 0 else 1
