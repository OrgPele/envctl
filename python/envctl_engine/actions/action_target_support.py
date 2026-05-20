from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping, Sequence


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


def resolve_action_targets(
    *,
    command: str,
    mode: str,
    trees_only: bool,
    projects: Sequence[str],
    passthrough_args: Sequence[str],
    flags: Mapping[str, object],
    discover_projects: Callable[[str], list[object]],
    selectors_from_passthrough: Callable[[Sequence[str]], set[str]],
    projects_for_services: Callable[[list[str]], list[str]],
    current_worktree_target: Callable[..., object | None],
    interactive_selection_allowed: Callable[[], bool],
    select_project_targets: Callable[..., object],
    no_target_selected_message: Callable[[], str],
) -> tuple[list[object], str | None]:
    if trees_only and command == "self-destruct-worktree":
        current = current_worktree_target(require_configured_main_root=False)
        if current is not None:
            return [current], None
        return [], "self-destruct-worktree must be run from inside a discovered worktree."
    if not trees_only and mode == "main" and command in {"commit", "pr", "test"}:
        current = current_worktree_target(require_configured_main_root=True)
        if current is not None:
            return [current], None
    if trees_only:
        candidates = discover_projects("trees")
    else:
        candidates = discover_projects(mode)
        if not candidates and mode == "main":
            candidates = discover_projects("trees")

    run_all = bool(flags.get("all"))
    untested_selected = bool(flags.get("untested"))
    project_selectors = {name.lower() for name in projects}
    project_selectors.update(selectors_from_passthrough(passthrough_args))

    services = flags.get("services")
    if isinstance(services, list):
        for project in projects_for_services(services):
            project_selectors.add(project.lower())

    if run_all:
        if not candidates:
            return [], "No projects discovered for selected mode."
        return candidates, None

    if not project_selectors and not run_all:
        if len(candidates) == 1:
            return candidates, None
        if interactive_selection_allowed():
            selection = select_project_targets(
                prompt=f"Select {command} target",
                projects=candidates,
                allow_all=True,
                allow_untested=command == "test",
                multi=True,
            )
            if bool(getattr(selection, "cancelled", False)):
                return [], no_target_selected_message()
            route_view = SimpleNamespace(command=command, projects=list(projects), flags=dict(flags))
            apply_to_route = getattr(selection, "apply_to_route", None)
            if callable(apply_to_route):
                apply_to_route(route_view)
                if isinstance(projects, list):
                    projects[:] = list(route_view.projects)
                if isinstance(flags, dict):
                    flags.clear()
                    flags.update(route_view.flags)
            run_all = bool(route_view.flags.get("all"))
            project_selectors = {name.lower() for name in route_view.projects}
            untested_selected = bool(route_view.flags.get("untested"))
        else:
            return [], no_target_selected_message()

    if not project_selectors and not run_all and not untested_selected:
        return [], no_target_selected_message()
    if run_all:
        if not candidates:
            return [], "No projects discovered for selected mode."
        return candidates, None
    selected = [
        candidate
        for candidate in candidates
        if str(getattr(candidate, "name", "")).lower() in project_selectors
    ]
    if not selected:
        if command == "test" and untested_selected:
            return [], None
        requested = ", ".join(sorted(project_selectors))
        return [], f"No matching targets found for: {requested}"
    return selected, None


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
