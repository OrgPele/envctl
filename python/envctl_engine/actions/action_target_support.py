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


@dataclass(frozen=True)
class ActionTargetIdentity:
    name: str
    root: Path
    target_obj: object


def action_target_identity(target: object, *, fallback_name_from_root: bool = False) -> ActionTargetIdentity | None:
    root_raw = str(getattr(target, "root", "") or "").strip()
    if not root_raw:
        return None
    root = Path(root_raw)
    name = action_target_name(target)
    if not name and fallback_name_from_root:
        name = root.name
    if not name:
        return None
    return ActionTargetIdentity(name=name, root=root, target_obj=target)


def action_target_identities(
    targets: Sequence[object], *, fallback_name_from_root: bool = False
) -> list[ActionTargetIdentity]:
    identities: list[ActionTargetIdentity] = []
    for target in targets:
        identity = action_target_identity(target, fallback_name_from_root=fallback_name_from_root)
        if identity is not None:
            identities.append(identity)
    return identities


def action_target_name(target: object) -> str:
    return str(getattr(target, "name", "") or "").strip()


def action_target_names(targets: Sequence[object]) -> list[str]:
    return [name for target in targets if (name := action_target_name(target))]


def action_target_names_with_roots(targets: Sequence[object]) -> list[str]:
    return [identity.name for identity in action_target_identities(targets)]


def build_action_target_contexts(targets: Sequence[object]) -> list[ActionTargetContext]:
    identities = action_target_identities(targets)
    total = len(identities)
    return [
        ActionTargetContext(
            name=identity.name,
            root=identity.root,
            index=index,
            total=total,
            target_obj=identity.target_obj,
        )
        for index, identity in enumerate(identities, start=1)
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


def _normalized_service_targets(service_targets: list[object]) -> list[str]:
    normalized: list[str] = []
    for target in service_targets:
        value = str(target).strip().lower().removeprefix("service:")
        if value:
            normalized.append(value)
    return normalized


def _projects_by_service_selector(runtime: Any, state: object | None) -> dict[str, list[str]]:
    projects_by_selector: dict[str, list[str]] = {}
    services = getattr(state, "services", {}) if state is not None else {}
    for service_name, service in services.items():
        project = runtime.project_name_from_service(service_name)
        if not project:
            continue
        service_type = str(getattr(service, "type", "") or "").strip().lower()
        selectors = {service_name.lower(), service_type} - {""}
        for selector in selectors:
            projects_by_selector.setdefault(selector, []).append(project)
    return projects_by_selector


def _deduplicate_project_names(projects: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for project in projects:
        lowered = project.lower()
        if lowered not in seen:
            seen.add(lowered)
            deduped.append(project)
    return deduped


def projects_for_services(runtime: Any, service_targets: list[object]) -> list[str]:
    projects, _unresolved = _resolve_projects_for_services(runtime, service_targets)
    return projects


def _resolve_projects_for_services(
    runtime: Any,
    service_targets: list[object],
) -> tuple[list[str], tuple[str, ...]]:
    normalized_targets = _normalized_service_targets(service_targets)
    if not normalized_targets:
        return [], ()

    state = runtime.load_existing_state(mode="trees") or runtime.load_existing_state(mode="main")
    projects_by_selector = _projects_by_service_selector(runtime, state)
    resolved: list[str] = []
    unresolved: list[str] = []
    for target in normalized_targets:
        matched_projects = projects_by_selector.get(target, [])
        if matched_projects:
            resolved.extend(matched_projects)
        elif project := runtime.project_name_from_service(target):
            resolved.append(project)
        else:
            unresolved.append(target)
    return _deduplicate_project_names(resolved), tuple(unresolved)


def _is_configured_test_service_selector(runtime: Any, route: Route, selector: str) -> bool:
    if route.command not in {"test", "test-focused"}:
        return False
    if selector in {"backend", "frontend"}:
        return True
    config = getattr(runtime, "config", None)
    app_service_by_name = getattr(config, "app_service_by_name", None)
    return callable(app_service_by_name) and app_service_by_name(selector) is not None


def _discover_action_candidates(runtime: Any, route: Route, *, trees_only: bool) -> list[object]:
    mode = "trees" if trees_only else route.mode
    candidates = list(runtime.discover_projects(mode=mode))
    if not candidates and not trees_only and route.mode == "main":
        return list(runtime.discover_projects(mode="trees"))
    return candidates


def _all_action_candidates(candidates: list[object]) -> tuple[list[object], str | None]:
    if not candidates:
        return [], "No projects discovered for selected mode."
    return candidates, None


@dataclass(frozen=True)
class _ActionTargetRequest:
    run_all: bool
    untested_selected: bool
    project_selectors: frozenset[str]
    explicit_targeting: bool
    unresolved_service_selectors: tuple[str, ...]


@dataclass
class _ActionTargetResolver:
    runtime: Any
    route: Route
    trees_only: bool
    resolve_current_worktree_target: Callable[..., object | None]
    interactive_selection_allowed: Callable[[Route], bool]
    no_target_selected_message: Callable[[Route], str]

    def resolve(self) -> tuple[list[object], str | None]:
        request = self._request_from_route()
        if current_result := self._current_worktree_result(request):
            return current_result
        candidates = _discover_action_candidates(self.runtime, self.route, trees_only=self.trees_only)
        if request.run_all:
            return _all_action_candidates(candidates)
        if request.project_selectors:
            return self._match_request(candidates, request)
        return self._resolve_without_project_selectors(candidates, request)

    def _resolve_without_project_selectors(
        self,
        candidates: list[object],
        request: _ActionTargetRequest,
    ) -> tuple[list[object], str | None]:
        if len(candidates) == 1 and not request.explicit_targeting:
            return candidates, None
        if not candidates and not request.explicit_targeting:
            return _all_action_candidates(candidates)
        if request.explicit_targeting:
            return self._match_request(candidates, request)
        interactive_request, error = self._request_from_interactive_selection(candidates)
        if error is not None:
            return [], error
        return self._match_request(candidates, interactive_request)

    def _current_worktree_result(
        self,
        request: _ActionTargetRequest,
    ) -> tuple[list[object], str | None] | None:
        if self.trees_only and self.route.command == "self-destruct-worktree":
            current = self.resolve_current_worktree_target()
            if current is not None:
                return [current], None
            return [], "self-destruct-worktree must be run from inside a discovered worktree."
        current_worktree_commands = {"commit", "pr", "ship", "test", "test-focused"}
        if self.trees_only or self.route.command not in current_worktree_commands or request.explicit_targeting:
            return None
        current = self.resolve_current_worktree_target(
            require_configured_main_root=self.route.mode == "main",
            require_configured_root_match=True,
        )
        if current is not None:
            return [current], None
        if self._execution_root_differs_from_configured_root():
            return [], self.no_target_selected_message(self.route)
        return None

    def _execution_root_differs_from_configured_root(self) -> bool:
        raw_runtime = getattr(self.runtime, "raw_runtime", self.runtime)
        config = getattr(raw_runtime, "config", None)
        base_dir = getattr(config, "base_dir", None)
        execution_root = getattr(config, "execution_root", None)
        if base_dir is None or execution_root is None:
            return False
        try:
            return Path(str(base_dir)).expanduser().resolve() != Path(str(execution_root)).expanduser().resolve()
        except OSError:
            return True

    def _request_from_route(self) -> _ActionTargetRequest:
        project_selectors = {name.lower() for name in self.route.projects}
        project_selectors.update(self.runtime.selectors_from_passthrough(self.route.passthrough_args))
        services = self.route.flags.get("services")
        unresolved_service_selectors: tuple[str, ...] = ()
        if isinstance(services, list):
            project_target_services = _normalized_service_targets(services)
            if self.route.command in {"test", "test-focused"}:
                project_target_services = [
                    selector for selector in project_target_services if selector not in {"backend", "frontend"}
                ]
            service_projects, unresolved_service_selectors = _resolve_projects_for_services(
                self.runtime,
                project_target_services,
            )
            unresolved_service_selectors = tuple(
                selector
                for selector in unresolved_service_selectors
                if not _is_configured_test_service_selector(self.runtime, self.route, selector)
            )
            project_selectors.update(project.lower() for project in service_projects)
        run_all = bool(self.route.flags.get("all"))
        untested_selected = bool(self.route.flags.get("untested"))
        return _ActionTargetRequest(
            run_all=run_all,
            untested_selected=untested_selected,
            project_selectors=frozenset(project_selectors),
            explicit_targeting=bool(
                project_selectors or unresolved_service_selectors or run_all or untested_selected
            ),
            unresolved_service_selectors=unresolved_service_selectors,
        )

    def _request_from_interactive_selection(
        self,
        candidates: list[object],
    ) -> tuple[_ActionTargetRequest, str | None]:
        if not self.interactive_selection_allowed(self.route):
            return self._request_from_route(), self.no_target_selected_message(self.route)
        selection = cast(
            TargetSelection,
            self.runtime.select_project_targets(
                prompt=f"Select {self.route.command} target",
                projects=candidates,
                allow_all=True,
                allow_untested=self.route.command == "test",
                multi=True,
            ),
        )
        if selection.cancelled:
            return self._request_from_route(), self.no_target_selected_message(self.route)
        selection.apply_to_route(self.route)
        return self._request_from_route(), None

    def _match_request(
        self,
        candidates: list[object],
        request: _ActionTargetRequest,
    ) -> tuple[list[object], str | None]:
        if request.run_all:
            return _all_action_candidates(candidates)
        if request.unresolved_service_selectors:
            requested = ", ".join(request.unresolved_service_selectors)
            return [], f"No matching targets found for: {requested}"
        if not request.project_selectors:
            return self._empty_request_result(request)
        selected = [
            candidate
            for candidate in candidates
            if candidate.name.lower() in request.project_selectors
        ]
        selected_names = {candidate.name.lower() for candidate in selected}
        missing_selectors = request.project_selectors - selected_names
        if missing_selectors:
            requested = ", ".join(sorted(missing_selectors))
            return [], f"No matching targets found for: {requested}"
        return selected, None

    def _empty_request_result(self, request: _ActionTargetRequest) -> tuple[list[object], str | None]:
        if self.route.command == "test" and request.untested_selected:
            return [], None
        return [], self.no_target_selected_message(self.route)


def resolve_action_targets(
    *,
    runtime: Any,
    route: Route,
    trees_only: bool,
    resolve_current_worktree_target: Callable[..., object | None],
    interactive_selection_allowed: Callable[[Route], bool],
    no_target_selected_message: Callable[[Route], str],
) -> tuple[list[object], str | None]:
    return _ActionTargetResolver(
        runtime=runtime,
        route=route,
        trees_only=trees_only,
        resolve_current_worktree_target=resolve_current_worktree_target,
        interactive_selection_allowed=interactive_selection_allowed,
        no_target_selected_message=no_target_selected_message,
    ).resolve()


def _exception_message(exc: Exception) -> str:
    detail = str(exc).strip()
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


def _completed_process_error(completed: Any) -> str | None:
    if completed.returncode == 0:
        return None
    stdout = str(getattr(completed, "stdout", "") or "").strip()
    stderr = str(getattr(completed, "stderr", "") or "").strip()
    if stderr and stdout and stderr != stdout:
        return f"{stderr}\n\nstdout:\n{stdout}"
    return stderr or stdout or f"exit:{completed.returncode}"


def _run_action_target(
    context: ActionTargetContext,
    *,
    resolve_command: Callable[[ActionTargetContext], ActionCommandResolution],
    build_env: Callable[[ActionTargetContext], Mapping[str, str]],
    process_run: Callable[[list[str], Path, Mapping[str, str]], Any],
) -> tuple[Any | None, str | None]:
    try:
        resolution = resolve_command(context)
        if resolution.command is None or resolution.cwd is None:
            return None, resolution.error or "no command resolved"
        completed = process_run(resolution.command, resolution.cwd, build_env(context))
        return completed, _completed_process_error(completed)
    except Exception as exc:  # Keep independent targets running after one operational failure.
        return None, _exception_message(exc)


def _report_action_failure(
    context: ActionTargetContext,
    error: str,
    *,
    command_name: str,
    interactive_command: bool,
    should_print: bool,
    emit_status: Callable[[str], None],
    printer: Callable[[str], None],
    on_failure: Callable[[ActionTargetContext, str], None] | None,
    failure_status_formatter: Callable[[ActionTargetContext, str], str] | None,
) -> None:
    if on_failure is not None:
        on_failure(context, error)
    if should_print:
        printer(f"{command_name} action failed for {context.name}: {error}")
    if interactive_command:
        status = (
            failure_status_formatter(context, error)
            if failure_status_formatter is not None
            else f"{command_name} failed for {context.name}: {error}"
        )
        emit_status(status)


def _report_action_success(
    context: ActionTargetContext,
    completed: Any,
    *,
    command_name: str,
    interactive_command: bool,
    emit_success_output: bool,
    print_noninteractive_successes: bool,
    emit_status: Callable[[str], None],
    printer: Callable[[str], None],
    on_success: Callable[[ActionTargetContext, Any], None] | None,
    success_print_formatter: Callable[[ActionTargetContext, Any], str] | None,
    success_status_formatter: Callable[[ActionTargetContext, Any], str] | None,
) -> None:
    if emit_success_output:
        emit_action_output(completed.stdout, emit_status=emit_status, printer=printer)
    if on_success is not None:
        on_success(context, completed)
    if not interactive_command and print_noninteractive_successes:
        message = (
            success_print_formatter(context, completed)
            if success_print_formatter is not None
            else f"{command_name} action succeeded for {context.name}."
        )
        if message:
            printer(message)
    status = (
        success_status_formatter(context, completed)
        if success_status_formatter is not None
        else f"{command_name} succeeded for {context.name}"
    )
    if status:
        emit_status(status)


def _prepare_action_contexts(
    targets: Sequence[object],
    *,
    command_name: str,
    emit_status: Callable[[str], None],
    printer: Callable[[str], None],
) -> tuple[list[ActionTargetContext], int]:
    contexts = build_action_target_contexts(targets)
    invalid_target_count = len(targets) - len(contexts)
    if invalid_target_count:
        message = (
            f"{command_name} action skipped {invalid_target_count} invalid target(s) "
            "without both a name and root."
        )
        printer(message)
        emit_status(message)
    elif not contexts:
        message = f"{command_name} action failed: no targets were provided."
        printer(message)
        emit_status(message)
    return contexts, invalid_target_count


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
    success_print_formatter: Callable[[ActionTargetContext, Any], str] | None = None,
    success_status_formatter: Callable[[ActionTargetContext, Any], str] | None = None,
    print_noninteractive_failures: bool = True,
    print_noninteractive_successes: bool = True,
) -> int:
    contexts, failures = _prepare_action_contexts(
        targets,
        command_name=command_name,
        emit_status=emit_status,
        printer=printer,
    )
    if not contexts:
        return 1

    should_print_failure = (not interactive_command and print_noninteractive_failures) or (
        interactive_command and interactive_print_failures
    )
    for context in contexts:
        emit_status(f"Running {command_name} for {context.name} ({context.index}/{context.total})...")
        completed, error = _run_action_target(
            context,
            resolve_command=resolve_command,
            build_env=build_env,
            process_run=process_run,
        )
        if error is not None:
            _report_action_failure(
                context,
                error,
                command_name=command_name,
                interactive_command=interactive_command,
                should_print=should_print_failure,
                emit_status=emit_status,
                printer=printer,
                on_failure=on_failure,
                failure_status_formatter=failure_status_formatter,
            )
            failures += 1
            continue
        assert completed is not None
        _report_action_success(
            context,
            completed,
            command_name=command_name,
            interactive_command=interactive_command,
            emit_success_output=emit_success_output,
            print_noninteractive_successes=print_noninteractive_successes,
            emit_status=emit_status,
            printer=printer,
            on_success=on_success,
            success_print_formatter=success_print_formatter,
            success_status_formatter=success_status_formatter,
        )

    return 0 if failures == 0 else 1
