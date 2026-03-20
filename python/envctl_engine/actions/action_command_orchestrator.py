from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import hashlib
import concurrent.futures
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable, Mapping, cast

from envctl_engine.actions.actions_analysis import default_review_command, default_migrate_command
from envctl_engine.actions.actions_git import default_commit_command, default_pr_command
from envctl_engine.actions.action_command_support import (
    build_action_env,
    build_action_extra_env,
    build_action_replacements,
    service_types_from_route_services,
)
from envctl_engine.actions.action_target_support import (
    ActionCommandResolution,
    ActionTargetContext,
    execute_targeted_action,
)
from envctl_engine.actions.action_test_support import (
    FailedTestManifest,
    TestExecutionSpec as _TestExecutionSpec,
    build_failed_test_execution_specs,
    frontend_failed_files_from_failed_tests,
    sanitize_failed_test_identifiers,
    TestSuiteSpinnerGroup as _TestSuiteSpinnerGroup,
    TestTargetContext,
    build_test_execution_specs,
    build_test_target_contexts,
    is_backend_only_selection,
    load_failed_test_manifest,
    rich_progress_available as _rich_progress_available,
)
from envctl_engine.actions.action_test_runner import run_test_action as run_test_action_impl
from envctl_engine.actions.action_worktree_runner import run_delete_worktree_action as run_delete_worktree_action_impl
from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.parsing import parse_bool, parse_int
from envctl_engine.startup.service_bootstrap_domain import (
    _resolve_backend_env_contract,
)
from envctl_engine.state.models import PortPlan, RequirementsResult
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.test_output.failure_summary import extract_failure_summary_excerpt, summary_excerpt_from_entry
from envctl_engine.test_output.test_runner import TestRunner
from envctl_engine.test_output.parser_base import strip_ansi
from envctl_engine.test_output.symbols import format_duration
from envctl_engine.ui.color_policy import colors_enabled
from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI  # noqa: F401
from envctl_engine.ui.path_links import render_path_for_terminal
from envctl_engine.ui.selection_support import interactive_selection_allowed, no_target_selected_message
from envctl_engine.ui.selection_types import TargetSelection
from envctl_engine.ui.spinner import spinner, use_spinner_policy
from envctl_engine.ui.spinner_service import emit_spinner_policy, resolve_spinner_policy


def _stdout_is_live_terminal() -> bool:
    streams = [getattr(sys, "stdout", None), getattr(sys, "__stdout__", None)]
    for stream in streams:
        if stream is None:
            continue
        try:
            if bool(getattr(stream, "isatty", lambda: False)()):
                return True
        except Exception:
            continue
    return False


@dataclass(frozen=True)
class _MigrateProjectContext:
    name: str
    root: Path
    ports: dict[str, PortPlan]


class ActionRuntimeFacade:
    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    def _resolve_callable(self, *names: str) -> Callable[..., object]:
        for name in names:
            candidate = getattr(self._runtime, name, None)
            if callable(candidate):
                return cast(Callable[..., object], candidate)
        joined = ", ".join(names)
        raise AttributeError(f"{type(self._runtime).__name__} is missing required action collaborator ({joined})")

    @property
    def env(self) -> Mapping[str, str]:
        return cast(Mapping[str, str], getattr(self._runtime, "env", {}))

    @property
    def config(self) -> Any:
        return getattr(self._runtime, "config", None)

    @property
    def process_runner(self) -> Any:
        return getattr(self._runtime, "process_runner", None)

    @property
    def state_repository(self) -> Any:
        return getattr(self._runtime, "state_repository", None)

    def discover_projects(self, *, mode: str) -> list[object]:
        discover = self._resolve_callable("discover_projects", "_discover_projects")
        return cast(list[object], discover(mode=mode))

    def selectors_from_passthrough(self, passthrough_args: list[str]) -> set[str]:
        selectors = self._resolve_callable("selectors_from_passthrough", "_selectors_from_passthrough")
        return cast(set[str], selectors(passthrough_args))

    def load_existing_state(self, *, mode: str) -> object | None:
        load_state = getattr(self._runtime, "load_existing_state", None)
        if callable(load_state):
            return load_state(mode=mode)
        legacy = self._resolve_callable("_try_load_existing_state")
        return legacy(mode=mode)

    def project_name_from_service(self, service_name: str) -> str:
        project_name = self._resolve_callable("project_name_from_service", "_project_name_from_service")
        return str(project_name(service_name))

    def select_project_targets(self, **kwargs: object) -> object:
        select = self._resolve_callable("select_project_targets", "_select_project_targets")
        return select(**kwargs)

    def unsupported_command(self, command: str) -> int:
        unsupported = self._resolve_callable("unsupported_command", "_unsupported_command")
        return int(unsupported(command))

    def emit(self, event: str, **payload: object) -> None:
        emitter = getattr(self._runtime, "_emit", None)
        if callable(emitter):
            emitter(event, **payload)
            return
        emitter = getattr(self._runtime, "emit", None)
        if callable(emitter):
            emitter(event, **payload)

    def _emit(self, event: str, **payload: object) -> None:
        self.emit(event, **payload)

    def split_command(self, raw: str, *, replacements: Mapping[str, str]) -> list[str]:
        splitter = self._resolve_callable("split_command", "_split_command")
        return cast(list[str], splitter(raw, replacements=replacements))

    def _trees_root_for_worktree(self, worktree_root: Path) -> Path:
        resolver = self._resolve_callable("trees_root_for_worktree", "_trees_root_for_worktree")
        return cast(Path, resolver(worktree_root))

    def _blast_worktree_before_delete(
        self,
        *,
        project_name: str,
        project_root: Path,
        source_command: str,
    ) -> list[str]:
        cleanup = getattr(self._runtime, "_blast_worktree_before_delete", None)
        if callable(cleanup):
            return cast(
                list[str],
                cleanup(
                    project_name=project_name,
                    project_root=project_root,
                    source_command=source_command,
                ),
            )
        cleanup = getattr(self._runtime, "blast_worktree_before_delete", None)
        if callable(cleanup):
            return cast(
                list[str],
                cleanup(
                    project_name=project_name,
                    project_root=project_root,
                    source_command=source_command,
                ),
            )
        return []

    @property
    def raw_runtime(self) -> Any:
        return self._runtime


class ActionCommandOrchestrator:
    def __init__(self, runtime: Any) -> None:
        self.runtime = ActionRuntimeFacade(runtime)
        self._migrate_env_contracts: dict[str, dict[str, object]] = {}

    @staticmethod
    def _short_failed_summary_path(*, run_dir: Path, project_name: str) -> Path:
        digest = hashlib.sha1(project_name.encode("utf-8")).hexdigest()[:10]
        run_root = run_dir.parent.parent
        return run_root / f"ft_{digest}.txt"

    def execute(self, route: Route) -> int:
        rt = self.runtime
        if route.command in {"delete-worktree", "blast-worktree"}:
            code = self.run_delete_worktree_action(route)
            rt.emit("action.command.finish", command=route.command, code=code)
            return code

        targets, error = self.resolve_targets(route, trees_only=False)
        if error is not None:
            print(error)
            rt.emit("action.command.finish", command=route.command, code=1, error=error)
            return 1

        handler_map: dict[str, Callable[[Route, list[object]], int]] = {
            "test": self.run_test_action,
            "pr": self.run_pr_action,
            "commit": self.run_commit_action,
            "review": self.run_review_action,
            "migrate": self.run_migrate_action,
        }
        handler = handler_map.get(route.command)
        if handler is None:
            return rt.unsupported_command(route.command)

        spinner_policy = resolve_spinner_policy(getattr(rt, "env", {}))
        op_id = f"action.{route.command}"
        start_status = self._command_start_status(route.command, targets)
        suppress_action_spinner = bool(route.flags.get("interactive_command"))
        action_spinner_enabled = spinner_policy.enabled and not suppress_action_spinner
        emit_spinner_policy(
            getattr(rt.raw_runtime, "_emit", None),
            spinner_policy,
            context={"component": "action.command", "command": route.command, "op_id": op_id},
        )
        if suppress_action_spinner:
            rt.emit(
                "ui.spinner.disabled",
                component="action.command",
                command=route.command,
                op_id=op_id,
                reason="interactive_command_spinner_suppressed",
            )

        rt.emit("action.command.start", command=route.command, mode=route.mode)
        self._emit_status(start_status)
        with (
            use_spinner_policy(spinner_policy),
            spinner(
                start_status,
                enabled=action_spinner_enabled,
                start_immediately=False,
            ) as active_spinner,
        ):
            if action_spinner_enabled:
                active_spinner.start()
                rt.emit(
                    "ui.spinner.lifecycle",
                    component="action.command",
                    command=route.command,
                    op_id=op_id,
                    state="start",
                    message=start_status,
                )
            restore_spinner_bridge = self._noop_restore
            if action_spinner_enabled:
                restore_spinner_bridge = self._install_action_spinner_status_bridge(
                    command=route.command,
                    op_id=op_id,
                    active_spinner=active_spinner,
                )
            try:
                try:
                    code = handler(route, targets)
                finally:
                    restore_spinner_bridge()
            except KeyboardInterrupt:
                if action_spinner_enabled:
                    interrupted = f"{route.command} interrupted"
                    active_spinner.fail(interrupted)
                    rt.emit(
                        "ui.spinner.lifecycle",
                        component="action.command",
                        command=route.command,
                        op_id=op_id,
                        state="fail",
                        message=interrupted,
                    )
                    rt.emit(
                        "ui.spinner.lifecycle",
                        component="action.command",
                        command=route.command,
                        op_id=op_id,
                        state="stop",
                    )
                rt.emit("action.command.finish", command=route.command, code=2)
                raise
            if action_spinner_enabled:
                if code == 0:
                    completion = f"{route.command} completed"
                    active_spinner.succeed(completion)
                    rt.emit(
                        "ui.spinner.lifecycle",
                        component="action.command",
                        command=route.command,
                        op_id=op_id,
                        state="success",
                        message=completion,
                    )
                else:
                    failure = f"{route.command} failed"
                    active_spinner.fail(failure)
                    rt.emit(
                        "ui.spinner.lifecycle",
                        component="action.command",
                        command=route.command,
                        op_id=op_id,
                        state="fail",
                        message=failure,
                    )
                rt.emit(
                    "ui.spinner.lifecycle",
                    component="action.command",
                    command=route.command,
                    op_id=op_id,
                    state="stop",
                )
        rt.emit("action.command.finish", command=route.command, code=code)
        return code

    def resolve_targets(self, route: Route, *, trees_only: bool) -> tuple[list[object], str | None]:
        rt = self.runtime
        if trees_only:
            candidates = rt.discover_projects(mode="trees")
        else:
            candidates = rt.discover_projects(mode=route.mode)
            if not candidates and route.mode == "main":
                candidates = rt.discover_projects(mode="trees")

        run_all = bool(route.flags.get("all"))
        untested_selected = bool(route.flags.get("untested"))
        project_selectors = {name.lower() for name in route.projects}
        project_selectors.update(rt.selectors_from_passthrough(route.passthrough_args))

        services = route.flags.get("services")
        if isinstance(services, list):
            for project in self.projects_for_services(services):
                project_selectors.add(project.lower())

        if run_all:
            if not candidates:
                return [], "No projects discovered for selected mode."
            return candidates, None

        if not project_selectors and not run_all:
            if len(candidates) == 1:
                return candidates, None
            if self._interactive_selection_allowed(route):
                selection = cast(
                    TargetSelection,
                    rt.select_project_targets(
                        prompt=f"Select {route.command} target",
                        projects=candidates,
                        allow_all=True,
                        allow_untested=route.command == "test",
                        multi=True,
                    ),
                )
                if selection.cancelled:
                    return [], self._no_target_selected_message(route)
                selection.apply_to_route(route)
                run_all = bool(route.flags.get("all"))
                project_selectors = {name.lower() for name in route.projects}
                untested_selected = bool(route.flags.get("untested"))
            else:
                return [], self._no_target_selected_message(route)

        if not project_selectors and not run_all and not untested_selected:
            return [], self._no_target_selected_message(route)
        if run_all:
            if not candidates:
                return [], "No projects discovered for selected mode."
            return candidates, None
        selected = [candidate for candidate in candidates if candidate.name.lower() in project_selectors]
        if not selected:
            if route.command == "test" and untested_selected:
                return [], None
            requested = ", ".join(sorted(project_selectors))
            return [], f"No matching targets found for: {requested}"
        return selected, None

    def _interactive_selection_allowed(self, route: Route) -> bool:
        return interactive_selection_allowed(self.runtime.raw_runtime, route, allow_dashboard_override=True)

    def projects_for_services(self, service_targets: list[object]) -> list[str]:
        rt = self.runtime
        normalized_targets = [str(target).strip().lower() for target in service_targets if str(target).strip()]
        if not normalized_targets:
            return []

        state = rt.load_existing_state(mode="trees") or rt.load_existing_state(mode="main")
        resolved: list[str] = []
        for target in normalized_targets:
            matched = False
            if state is not None:
                for service_name in state.services:
                    if service_name.lower() == target:
                        project = rt.project_name_from_service(service_name)
                        if project:
                            resolved.append(project)
                            matched = True
            if matched:
                continue
            project = rt.project_name_from_service(target)
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

    def run_test_action(self, route: Route, targets: list[object]) -> int:
        return run_test_action_impl(
            self,
            route,
            targets,
            rich_progress_available=_rich_progress_available,
            suite_spinner_group_cls=_TestSuiteSpinnerGroup,
            test_runner_cls=TestRunner,
            futures_module=concurrent.futures,
            resolve_spinner_policy=resolve_spinner_policy,
        )

    def run_pr_action(self, route: Route, targets: list[object]) -> int:
        rt = self.runtime
        return self.run_project_action(
            route,
            targets,
            command_name="pr",
            env_key="ENVCTL_ACTION_PR_CMD",
            default_command=default_pr_command(rt.config.base_dir),  # type: ignore[attr-defined]
            default_cwd=rt.config.base_dir,  # type: ignore[attr-defined]
            default_append_project_path=False,
            extra_env=self.action_extra_env(route),
        )

    def run_commit_action(self, route: Route, targets: list[object]) -> int:
        rt = self.runtime
        return self.run_project_action(
            route,
            targets,
            command_name="commit",
            env_key="ENVCTL_ACTION_COMMIT_CMD",
            default_command=default_commit_command(rt.config.base_dir),  # type: ignore[attr-defined]
            default_cwd=rt.config.base_dir,  # type: ignore[attr-defined]
            default_append_project_path=False,
            extra_env=self.action_extra_env(route),
        )

    def run_review_action(self, route: Route, targets: list[object]) -> int:
        rt = self.runtime
        return self.run_project_action(
            route,
            targets,
            command_name="review",
            env_key="ENVCTL_ACTION_ANALYZE_CMD",
            default_command=default_review_command(rt.config.base_dir),  # type: ignore[attr-defined]
            default_cwd=rt.config.base_dir,  # type: ignore[attr-defined]
            default_append_project_path=False,
            extra_env=self.action_extra_env(route),
        )

    def run_migrate_action(self, route: Route, targets: list[object]) -> int:
        rt = self.runtime
        raw = rt.env.get("ENVCTL_ACTION_MIGRATE_CMD")  # type: ignore[attr-defined]
        interactive_command = bool(route.flags.get("interactive_command"))
        extra_env = self.action_extra_env(route)

        def resolve_command(context: object) -> ActionCommandResolution:
            target = getattr(context, "target_obj")
            target_root = Path(str(getattr(context, "root")))
            if raw is not None:
                replacements = self.action_replacements(targets, target=target)
                try:
                    command = rt.split_command(raw, replacements=replacements)
                except RuntimeError as exc:
                    return ActionCommandResolution(command=None, cwd=None, error=str(exc))
                return ActionCommandResolution(command=command, cwd=target_root)
            resolution = default_migrate_command(target_root)
            return ActionCommandResolution(
                command=resolution.command,
                cwd=resolution.cwd,
                error=resolution.error,
            )

        return execute_targeted_action(
            targets=targets,
            command_name="migrate",
            interactive_command=interactive_command,
            resolve_command=resolve_command,
            build_env=lambda context: self.migrate_action_env(
                targets=targets,
                route=route,
                target=getattr(context, "target_obj"),
                extra=extra_env,
            ),
            process_run=lambda command, cwd, env: rt.process_runner.run(  # type: ignore[attr-defined]
                command,
                cwd=cwd,
                env=dict(env),
                timeout=300.0,
            ),
            emit_status=self._emit_status,
            interactive_print_failures=False,
            on_success=self._project_action_success_handler("migrate", route.mode, interactive_command),
            on_failure=self._project_action_failure_handler("migrate", route.mode),
            failure_status_formatter=lambda context, error: (
                f"migrate failed for {context.name}: {self._migrate_failure_headline(error)}"
            ),
        )

    def _no_target_selected_message(self, route: Route) -> str:
        interactive_allowed = self._interactive_selection_allowed(route)
        return no_target_selected_message(route.command, route=route, interactive_allowed=interactive_allowed)

    @staticmethod
    def _service_types_from_route_services(route: Route) -> set[str]:
        return service_types_from_route_services(route)

    def _test_service_selection(
        self,
        route: Route,
        backend_flag: object,
        frontend_flag: object,
    ) -> tuple[bool, bool]:
        return is_backend_only_selection(
            backend_flag,
            frontend_flag,
            self._service_types_from_route_services(route),
        )

    def _build_test_execution_specs(
        self,
        *,
        route: Route,
        targets: list[object],
        target_contexts: list[TestTargetContext],
        include_backend: bool,
        include_frontend: bool,
        run_all: bool,
        untested: bool,
    ) -> list["_TestExecutionSpec"]:
        rt = self.runtime
        if bool(route.flags.get("failed")):
            return self._build_failed_test_execution_specs(
                route=route,
                target_contexts=target_contexts,
            )
        shared_raw = (
            str(
                rt.env.get("ENVCTL_ACTION_TEST_CMD")  # type: ignore[attr-defined]
                or rt.config.raw.get("ENVCTL_ACTION_TEST_CMD", "")  # type: ignore[attr-defined]
            ).strip()
            or None
        )
        backend_raw = (
            str(
                rt.env.get("ENVCTL_BACKEND_TEST_CMD")  # type: ignore[attr-defined]
                or rt.config.raw.get("ENVCTL_BACKEND_TEST_CMD", "")  # type: ignore[attr-defined]
            ).strip()
            or None
        )
        frontend_raw = (
            str(
                rt.env.get("ENVCTL_FRONTEND_TEST_CMD")  # type: ignore[attr-defined]
                or rt.config.raw.get("ENVCTL_FRONTEND_TEST_CMD", "")  # type: ignore[attr-defined]
            ).strip()
            or None
        )
        return build_test_execution_specs(
            shared_raw_command=shared_raw,
            backend_raw_command=backend_raw,
            frontend_raw_command=frontend_raw,
            target_contexts=target_contexts,
            repo_root=rt.config.base_dir,  # type: ignore[attr-defined]
            include_backend=include_backend,
            include_frontend=include_frontend,
            frontend_test_path=(
                getattr(rt.config, "frontend_test_path", "")
                or rt.env.get("ENVCTL_FRONTEND_TEST_PATH")  # type: ignore[attr-defined]
                or rt.config.raw.get("ENVCTL_FRONTEND_TEST_PATH", "")  # type: ignore[attr-defined]
            ),
            run_all=run_all,
            untested=untested,
            split_command=lambda command_raw, replacements: rt.split_command(
                command_raw,
                replacements=dict(replacements),
            ),
            replacements_for_target=lambda target: self.action_replacements(targets, target=target),
            is_legacy_tree_test_script=self._is_legacy_tree_test_script,
        )

    def _build_failed_test_execution_specs(
        self,
        *,
        route: Route,
        target_contexts: list[TestTargetContext],
    ) -> list["_TestExecutionSpec"]:
        rt = self.runtime
        shared_raw = (
            str(
                rt.env.get("ENVCTL_ACTION_TEST_CMD")  # type: ignore[attr-defined]
                or rt.config.raw.get("ENVCTL_ACTION_TEST_CMD", "")  # type: ignore[attr-defined]
            ).strip()
            or None
        )
        backend_raw = (
            str(
                rt.env.get("ENVCTL_BACKEND_TEST_CMD")  # type: ignore[attr-defined]
                or rt.config.raw.get("ENVCTL_BACKEND_TEST_CMD", "")  # type: ignore[attr-defined]
            ).strip()
            or None
        )
        frontend_raw = (
            str(
                rt.env.get("ENVCTL_FRONTEND_TEST_CMD")  # type: ignore[attr-defined]
                or rt.config.raw.get("ENVCTL_FRONTEND_TEST_CMD", "")  # type: ignore[attr-defined]
            ).strip()
            or None
        )
        state = rt.load_existing_state(mode=route.mode)
        if state is None:
            raise RuntimeError("No saved failed-test data is available yet. Run the full test suite first.")
        summaries_raw = getattr(state, "metadata", {}).get("project_test_summaries")
        summaries = summaries_raw if isinstance(summaries_raw, dict) else {}
        manifests_by_project: dict[str, FailedTestManifest] = {}
        invalid_selector_counts: dict[str, int] = {}
        non_rerunnable_projects: list[str] = []
        extraction_failed_projects: list[str] = []
        for target in target_contexts:
            entry = summaries.get(target.project_name)
            if not isinstance(entry, dict):
                continue
            manifest_path_raw = str(entry.get("manifest_path", "") or "").strip()
            if not manifest_path_raw:
                if str(entry.get("status", "") or "").strip().lower() == "failed":
                    non_rerunnable_projects.append(target.project_name)
                    if self._summary_indicates_extraction_failure(entry):
                        extraction_failed_projects.append(target.project_name)
                continue
            manifest = load_failed_test_manifest(Path(manifest_path_raw))
            if manifest is None:
                if str(entry.get("status", "") or "").strip().lower() == "failed":
                    non_rerunnable_projects.append(target.project_name)
                    if self._summary_indicates_extraction_failure(entry):
                        extraction_failed_projects.append(target.project_name)
                continue
            if not manifest.entries:
                if str(entry.get("status", "") or "").strip().lower() == "failed":
                    non_rerunnable_projects.append(target.project_name)
                    if self._summary_indicates_extraction_failure(entry):
                        extraction_failed_projects.append(target.project_name)
                continue
            invalid_count = sum(item.invalid_failed_tests for item in manifest.entries)
            if invalid_count > 0:
                invalid_selector_counts[target.project_name] = invalid_count
            manifests_by_project[target.project_name] = manifest
        for project_name, invalid_count in sorted(invalid_selector_counts.items()):
            noun = "selector" if invalid_count == 1 else "selectors"
            message = (
                f"Skipping {invalid_count} invalid saved pytest {noun} for {project_name}; "
                "rerunning the remaining failed tests."
            )
            self._emit_status(message)
            print(message)
        if non_rerunnable_projects:
            projects = ", ".join(sorted(non_rerunnable_projects))
            if extraction_failed_projects and sorted(extraction_failed_projects) == sorted(non_rerunnable_projects):
                print(f"No rerunnable failed tests were extracted for: {projects}")
            else:
                print(f"No rerunnable failed tests remain for: {projects}")
        if not manifests_by_project:
            if extraction_failed_projects and sorted(extraction_failed_projects) == sorted(non_rerunnable_projects):
                raise RuntimeError(
                    "No rerunnable failed tests were found for the selected target(s). "
                    "The last full run failed before envctl could derive rerunnable test selectors. "
                    "See the saved failure summary."
                )
            if non_rerunnable_projects:
                raise RuntimeError(
                    "No rerunnable failed tests were found for the selected target(s). "
                    "Saved failures could not be converted into rerunnable selectors. Run the full suite first."
                )
            raise RuntimeError("No saved failed tests were found for the selected target(s). Run the full suite first.")
        execution_specs = build_failed_test_execution_specs(
            target_contexts=target_contexts,
            repo_root=rt.config.base_dir,  # type: ignore[attr-defined]
            manifests_by_project=manifests_by_project,
            shared_raw_command=shared_raw,
            backend_raw_command=backend_raw,
            frontend_raw_command=frontend_raw,
        )
        if execution_specs:
            return execution_specs
        if manifests_by_project:
            projects = ", ".join(sorted(manifests_by_project))
            print(f"No rerunnable failed tests remain for: {projects}")
        if non_rerunnable_projects:
            raise RuntimeError(
                "No rerunnable failed tests were found for the selected target(s). "
                "Saved failures could not be converted into rerunnable selectors. See the saved failure summary."
            )
        raise RuntimeError("No rerunnable failed tests were found for the selected target(s).")

    @staticmethod
    def _summary_indicates_extraction_failure(entry: Mapping[str, object]) -> bool:
        for key in ("short_summary_path", "summary_path"):
            raw = str(entry.get(key, "") or "").strip()
            if not raw:
                continue
            path = Path(raw).expanduser()
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "suite failed before envctl could extract failed tests" in text:
                return True
        return False

    def run_project_action(
        self,
        route: Route,
        targets: list[object],
        *,
        command_name: str,
        env_key: str,
        default_command: list[str] | None,
        default_cwd: Path,
        default_append_project_path: bool,
        extra_env: Mapping[str, str],
    ) -> int:
        rt = self.runtime
        raw = rt.env.get(env_key)  # type: ignore[attr-defined]
        interactive_command = bool(route.flags.get("interactive_command"))
        command_extra_env = dict(extra_env)
        stream_review_output = bool(
            command_name == "review"
            and not interactive_command
            and _stdout_is_live_terminal()
            and hasattr(rt.process_runner, "run_streaming")  # type: ignore[attr-defined]
        )
        if stream_review_output:
            command_extra_env["ENVCTL_ACTION_FORCE_RICH"] = "1"
        if raw is None and default_command is None:
            print(f"No {command_name} command configured. Set {env_key} or add repo utility script.")
            return 1

        def resolve_command(context: object) -> ActionCommandResolution:
            target = getattr(context, "target_obj")
            target_root = Path(str(getattr(context, "root")))
            if raw is not None:
                replacements = self.action_replacements(targets, target=target)
                try:
                    command = rt.split_command(raw, replacements=replacements)
                except RuntimeError as exc:
                    return ActionCommandResolution(command=None, cwd=None, error=str(exc))
                return ActionCommandResolution(command=command, cwd=target_root)

            command: list[str] = []
            replacements = self.action_replacements(targets, target=target)
            for token in list(default_command or []):
                value = str(token)
                for key, replacement in replacements.items():
                    value = value.replace(f"{{{key}}}", replacement)
                command.append(value)
            if default_append_project_path:
                command.append(str(target_root))
            return ActionCommandResolution(command=command, cwd=default_cwd)

        return execute_targeted_action(
            targets=targets,
            command_name=command_name,
            interactive_command=interactive_command,
            resolve_command=resolve_command,
            build_env=lambda context: self.action_env(
                command_name,
                targets,
                route=route,
                target=getattr(context, "target_obj"),
                extra=command_extra_env,
            ),
            process_run=lambda command, cwd, env: (
                subprocess.CompletedProcess(
                    args=command,
                    returncode=(
                        completed := rt.process_runner.run_streaming(  # type: ignore[attr-defined]
                            command,
                            cwd=cwd,
                            env=dict(env),
                            timeout=300.0,
                            show_spinner=False,
                            echo_output=True,
                        )
                    ).returncode,
                    stdout="" if completed.returncode == 0 else str(completed.stdout or ""),
                    stderr=str(getattr(completed, "stderr", "") or ""),
                )
                if stream_review_output
                else rt.process_runner.run(  # type: ignore[attr-defined]
                    command,
                    cwd=cwd,
                    env=dict(env),
                    timeout=300.0,
                )
            ),
            emit_status=self._emit_status,
            interactive_print_failures=(not interactive_command) or command_name in {"pr", "review"},
            emit_success_output=not stream_review_output,
            on_success=self._project_action_success_handler(command_name, route.mode, interactive_command),
            on_failure=self._project_action_failure_handler(command_name, route.mode),
        )

    def action_replacements(
        self,
        targets: list[object],
        *,
        target: object | None,
    ) -> dict[str, str]:
        rt = self.runtime
        return build_action_replacements(
            repo_root=rt.config.base_dir,  # type: ignore[attr-defined]
            targets=targets,
            target=target,
        )

    def action_env(
        self,
        command_name: str,
        targets: list[object],
        *,
        route: Route | None = None,
        target: object | None,
        extra: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        rt = self.runtime
        route_mode = getattr(route, "mode", None)
        state = rt.load_existing_state(mode=route_mode) if isinstance(route_mode, str) else None
        run_id = getattr(state, "run_id", None)
        tree_diffs_root = rt.state_repository.tree_diffs_dir_path(run_id)  # type: ignore[attr-defined]
        return build_action_env(
            process_env=os.environ,
            runtime_env=rt.env,  # type: ignore[arg-type,attr-defined]
            repo_root=rt.config.base_dir,  # type: ignore[attr-defined]
            runtime_root=rt.state_repository.runtime_root,  # type: ignore[attr-defined]
            run_id=run_id,
            tree_diffs_root=tree_diffs_root,
            command_name=command_name,
            targets=targets,
            route=route,
            target=target,
            extra=extra,
        )

    @staticmethod
    def action_extra_env(route: Route) -> dict[str, str]:
        return build_action_extra_env(route)

    def migrate_action_env(
        self,
        *,
        targets: list[object],
        route: Route | None,
        target: object | None,
        extra: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        env = self.action_env(
            "migrate",
            targets,
            route=route,
            target=target,
            extra=extra,
        )
        if target is None:
            return env

        project_name = str(getattr(target, "name", "")).strip()
        target_root = Path(str(getattr(target, "root")))
        backend_cwd = self._migrate_backend_cwd(target_root)

        runtime_raw = self.runtime.raw_runtime
        context = _MigrateProjectContext(name=project_name, root=target_root, ports={})

        projected_env: dict[str, str] = {}
        requirements = self._migrate_requirements_for_target(route=route, project_name=project_name)
        if requirements is not None:
            project_context = self._migrate_project_context(
                project_name=project_name,
                project_root=target_root,
                requirements=requirements,
            )
            projector = getattr(runtime_raw, "_project_service_env_internal", None)
            if callable(projector):
                projected_candidate = projector(project_context, requirements=requirements, route=route)
                if isinstance(projected_candidate, dict):
                    projected_env = {
                        str(key): str(value)
                        for key, value in projected_candidate.items()
                        if isinstance(key, str) and isinstance(value, str)
                    }

        contract = _resolve_backend_env_contract(
            runtime_raw,
            context=context,
            backend_cwd=backend_cwd,
            base_env=env,
            projected_env=projected_env,
        )
        self._migrate_env_contracts[project_name] = {
            "env_file_path": str(contract.env_file_path) if contract.env_file_path is not None else None,
            "env_file_source": contract.env_file_source,
            "override_requested": contract.override_requested,
            "override_resolution": contract.override_resolution,
            "override_authoritative": contract.override_authoritative,
            "scrubbed_keys": list(contract.scrubbed_keys),
            "projected_keys": list(contract.projected_keys),
        }
        return contract.env

    def run_delete_worktree_action(self, route: Route) -> int:
        return run_delete_worktree_action_impl(self, route)

    def _emit_status(self, message: str) -> None:
        rt = self.runtime
        text = str(message).strip()
        if not text:
            return
        rt.emit("ui.status", message=text)

    def _install_action_spinner_status_bridge(
        self,
        *,
        command: str,
        op_id: str,
        active_spinner: Any,
    ) -> Callable[[], None]:
        rt = self.runtime.raw_runtime

        def update_spinner(message: object) -> None:
            text = str(message).strip()
            if not text:
                return
            active_spinner.update(text)
            self.runtime.emit(
                "ui.spinner.lifecycle",
                component="action.command",
                command=command,
                op_id=op_id,
                state="update",
                message=text,
            )

        add_listener = getattr(rt, "add_emit_listener", None)
        if callable(add_listener):

            def listener(event_name: str, payload: Mapping[str, object]) -> None:
                if event_name != "ui.status":
                    return
                update_spinner(payload.get("message", ""))

            remove = add_listener(listener)
            if callable(remove):
                return remove
            return self._noop_restore

        emit = getattr(rt, "_emit", None)
        if not callable(emit):
            return self._noop_restore

        def bridged_emit(event_name: str, **payload: object) -> None:
            emit(event_name, **payload)
            if event_name == "ui.status":
                update_spinner(payload.get("message", ""))

        try:
            setattr(rt, "_emit", bridged_emit)
        except Exception:
            return self._noop_restore

        def restore() -> None:
            try:
                setattr(rt, "_emit", emit)
            except Exception:
                return

        return restore

    def _project_action_success_handler(
        self,
        command_name: str,
        mode: str,
        interactive_command: bool,
    ) -> Callable[[ActionTargetContext, Any], None] | None:
        def handle_success(context: ActionTargetContext, completed: Any) -> None:
            self._clear_dashboard_pr_cache()
            status = self._project_action_success_status(command_name=command_name, completed=completed)
            extra_entry: dict[str, object] | None = None
            if command_name == "review" and status == "success":
                extra_entry = self._review_success_artifact_paths(
                    stdout=getattr(completed, "stdout", ""),
                    stderr=getattr(completed, "stderr", ""),
                )
            self._persist_project_action_result(
                command_name=command_name,
                mode=mode,
                project_name=context.name,
                status=status,
                error_output="",
                extra_entry=extra_entry,
            )
            if command_name != "pr" or not interactive_command or status != "success":
                return
            url = self._first_output_line(getattr(completed, "stdout", ""))
            if url:
                self._emit_status(f"PR created: {url}")

        return handle_success

    def _project_action_failure_handler(
        self,
        command_name: str,
        mode: str,
    ) -> Callable[[ActionTargetContext, str], None]:
        def handle_failure(context: ActionTargetContext, error_output: str) -> None:
            self._persist_project_action_result(
                command_name=command_name,
                mode=mode,
                project_name=context.name,
                status="failed",
                error_output=error_output,
            )

        return handle_failure

    def _persist_project_action_result(
        self,
        *,
        command_name: str,
        mode: str,
        project_name: str,
        status: str,
        error_output: str,
        extra_entry: Mapping[str, object] | None = None,
    ) -> None:
        rt = self.runtime
        state = rt.load_existing_state(mode=mode)
        if state is None:
            return
        metadata_raw = state.metadata.get("project_action_reports")
        metadata = dict(metadata_raw) if isinstance(metadata_raw, dict) else {}
        project_raw = metadata.get(project_name)
        project_metadata = dict(project_raw) if isinstance(project_raw, dict) else {}
        entry: dict[str, object] = {
            "status": status,
            "updated_at": datetime.now(tz=UTC).isoformat(),
        }
        migrate_env_metadata = (
            dict(self._migrate_env_contracts.get(project_name, {})) if command_name == "migrate" else None
        )
        if migrate_env_metadata:
            entry["backend_env"] = migrate_env_metadata
        if isinstance(extra_entry, Mapping):
            entry.update({str(key): value for key, value in extra_entry.items()})
        if status == "failed":
            clean_output = strip_ansi(str(error_output or "")).strip()
            summary_lines = self._project_action_failure_summary_lines(
                command_name=command_name,
                error_output=clean_output,
                migrate_env_metadata=migrate_env_metadata,
            )
            summary_text = "\n".join(summary_lines).strip() or "Command failed."
            report_path = self._write_project_action_failure_report(
                run_id=state.run_id,
                project_name=project_name,
                command_name=command_name,
                output=clean_output,
            )
            if command_name == "migrate":
                headline = self._migrate_failure_headline(clean_output)
                if headline:
                    entry["headline"] = headline
            entry["summary"] = summary_text
            entry["report_path"] = str(report_path)
        project_metadata[command_name] = entry
        metadata[project_name] = project_metadata
        state.metadata["project_action_reports"] = metadata
        rt.state_repository.save_resume_state(
            state=state,
            emit=rt.emit,
            runtime_map_builder=build_runtime_map,
        )

    @staticmethod
    def _review_success_artifact_paths(*, stdout: object, stderr: object) -> dict[str, object]:
        cleaned = strip_ansi("\n".join(part for part in [str(stdout or ""), str(stderr or "")] if str(part or "").strip()))
        lines = [line.rstrip() for line in cleaned.splitlines()]
        label_map = {
            "output directory": "output_dir",
            "summary file": "summary_path",
            "full review bundle": "bundle_path",
        }
        parsed: dict[str, object] = {}
        for index, raw_line in enumerate(lines):
            label = raw_line.strip().lower()
            key = label_map.get(label)
            if not key:
                continue
            for follow_line in lines[index + 1 :]:
                candidate = follow_line.strip()
                if not candidate:
                    continue
                parsed[key] = candidate
                break
        return parsed

    def _write_project_action_failure_report(
        self,
        *,
        run_id: str,
        project_name: str,
        command_name: str,
        output: str,
    ) -> Path:
        results_root = self.runtime.state_repository.run_dir_path(run_id)
        results_root.mkdir(parents=True, exist_ok=True)
        safe_project = project_name.replace(" ", "_")
        report_path = results_root / f"{safe_project}_{command_name}.txt"
        report_path.write_text((output or "Command failed.").rstrip() + "\n", encoding="utf-8")
        return report_path

    def _clear_dashboard_pr_cache(self) -> None:
        runtime_raw = self.runtime.raw_runtime
        cache = getattr(runtime_raw, "_dashboard_pr_url_cache", None)
        if isinstance(cache, dict):
            cache.clear()

    @staticmethod
    def _first_output_line(output: object) -> str:
        for raw in str(output or "").splitlines():
            text = raw.strip()
            if text:
                return text
        return ""

    @classmethod
    def _project_action_success_status(cls, *, command_name: str, completed: Any) -> str:
        if command_name != "pr":
            return "success"
        output = strip_ansi(str(getattr(completed, "stdout", "") or ""))
        first_line = cls._first_output_line(output)
        if first_line.startswith("Skipping ") and "detached HEAD" in output:
            return "skipped"
        return "success"

    def _colors_enabled(self) -> bool:
        rt_env = getattr(self.runtime, "env", {})
        interactive_tty = False
        can_interactive_tty = getattr(self.runtime.raw_runtime, "_can_interactive_tty", None)
        if callable(can_interactive_tty):
            try:
                interactive_tty = bool(can_interactive_tty())
            except Exception:
                interactive_tty = False
        return colors_enabled(rt_env, stream=sys.stdout, interactive_tty=interactive_tty)

    def _colorize(self, text: str, *, fg: str | None = None, bold: bool = False, dim: bool = False) -> str:
        if not self._colors_enabled():
            return text
        palette = {
            "red": "31",
            "green": "32",
            "yellow": "33",
            "blue": "34",
            "magenta": "35",
            "cyan": "36",
            "gray": "90",
        }
        codes: list[str] = []
        if bold:
            codes.append("1")
        if dim:
            codes.append("2")
        if fg is not None:
            code = palette.get(str(fg).strip().lower())
            if code is not None:
                codes.append(code)
        if not codes:
            return text
        return f"\033[{';'.join(codes)}m{text}\033[0m"

    @staticmethod
    def _command_start_status(command_name: str, targets: list[object]) -> str:
        target_names = [str(getattr(target, "name", "")).strip() for target in targets]
        target_names = [name for name in target_names if name]
        if not target_names:
            return f"Running {command_name}..."
        if len(target_names) == 1:
            return f"Running {command_name} for {target_names[0]}..."
        return f"Running {command_name} for {len(target_names)} targets..."

    @staticmethod
    def _test_scope_status(project_names: list[str], *, run_all: bool, untested: bool, failed: bool) -> str:
        if run_all:
            return "Running tests for all discovered projects..."
        if failed:
            if len(project_names) == 1:
                return f"Rerunning failed tests for {project_names[0]}..."
            if project_names:
                return f"Rerunning failed tests for {len(project_names)} selected projects..."
            return "Rerunning failed tests..."
        if untested and not project_names:
            return "Running tests for untested projects..."
        if len(project_names) == 1:
            return f"Running tests for {project_names[0]}..."
        if project_names:
            return f"Running tests for {len(project_names)} selected projects..."
        return "Running tests..."

    @staticmethod
    def _test_execution_status(command: list[str], *, args: list[str], source: str, cwd: Path) -> str:
        if source == "configured":
            snippet = " ".join(command[:3]).strip()
            if snippet:
                return f"Executing configured test command: {snippet}..."
            return "Executing configured test command..."

        if len(command) >= 3 and command[1] == "-m" and command[2] == "pytest":
            if len(command) > 3 and all("test" in str(part) or "::" in str(part) for part in command[3:]):
                return f"Rerunning failed pytest cases ({len(command) - 3})..."
            target = command[3] if len(command) > 3 else "tests"
            return f"Running pytest suite at {target}..."
        if len(command) >= 4 and command[1] == "-m" and command[2] == "unittest" and command[3] == "discover":
            return "Running unittest discovery (test_*.py)..."
        if len(command) >= 4 and command[1] == "-m" and command[2] == "unittest":
            return f"Rerunning failed unittest cases ({len(command) - 3})..."
        if len(command) >= 3 and command[1] == "run" and command[2] == "test":
            manager = command[0]
            if "--" in command:
                try:
                    file_count = max(0, len(command) - command.index("--") - 1)
                except ValueError:
                    file_count = 0
                if file_count > 0:
                    return f"Rerunning failed {manager} test files ({file_count}) in {cwd}..."
            return f"Running {manager} test script in {cwd}..."
        if len(command) >= 2 and command[0] == "bash" and command[1].endswith("test-all-trees.sh"):
            projects_arg = next((value for value in args if value.startswith("projects=")), "")
            if projects_arg:
                selected = projects_arg.split("=", 1)[1]
                count = len([name for name in selected.split(",") if name])
                return f"Running tree test matrix for {count} selected project(s)..."
            if "untested=true" in args:
                return "Running tree test matrix for untested projects..."
            return "Running tree test matrix for all projects..."
        return "Executing detected test command..."

    def _test_parallel_enabled(self, route: Route, specs: list["_TestExecutionSpec"]) -> bool:
        rt = self.runtime
        if len(specs) <= 1:
            return False
        if any(self._is_legacy_tree_test_script(spec.spec.command) for spec in specs):
            return False
        forced = route.flags.get("test_parallel")
        if isinstance(forced, bool):
            return forced
        configured = rt.env.get("ENVCTL_ACTION_TEST_PARALLEL") or rt.config.raw.get("ENVCTL_ACTION_TEST_PARALLEL")  # type: ignore[attr-defined]
        return parse_bool(configured, True)

    def _test_parallel_max_workers(self, route: Route, specs: list["_TestExecutionSpec"]) -> int:
        rt = self.runtime
        total = max(len(specs), 1)
        configured_values: list[object] = [
            route.flags.get("test_parallel_max"),
            rt.env.get("ENVCTL_ACTION_TEST_PARALLEL_MAX"),  # type: ignore[attr-defined]
            rt.config.raw.get("ENVCTL_ACTION_TEST_PARALLEL_MAX"),  # type: ignore[attr-defined]
        ]
        limit = 4
        for raw in configured_values:
            parsed = parse_int(raw, 0)
            if parsed > 0:
                limit = parsed
                break
        return max(1, min(total, limit))

    def _test_suite_spinner_policy_enabled(self, policy: Any) -> tuple[bool, str]:
        rt = self.runtime
        env = getattr(rt, "env", {})
        mode = str(env.get("ENVCTL_UI_SPINNER_MODE", "")).strip().lower()
        if mode == "off":
            return False, "spinner_mode_off"
        if not parse_bool(env.get("ENVCTL_UI_SPINNER"), True):
            return False, "spinner_env_off"
        if not parse_bool(env.get("ENVCTL_UI_RICH"), True):
            return False, "rich_env_off"
        reason = str(getattr(policy, "reason", "")).strip().lower()
        if reason == "spinner_backend_missing":
            return False, "spinner_backend_missing"
        if reason == "ci_mode":
            return False, "ci_mode"
        # Intentionally ignore policy reason=non_tty for test suite rows in
        # interactive dashboard mode; nested launcher/PTY stacks can report
        # non-tty here while rich rendering still works.
        return True, "enabled"

    def _persist_test_summary_artifacts(
        self,
        *,
        route: Route,
        targets: list[object],
        outcomes: list[dict[str, object]],
    ) -> dict[str, dict[str, object]]:
        if not targets:
            return {}

        rt = self.runtime
        project_roots: dict[str, Path] = {}
        for target in targets:
            name = str(getattr(target, "name", "")).strip()
            root_raw = str(getattr(target, "root", "")).strip()
            if not name or not root_raw:
                continue
            project_roots[name] = Path(root_raw)
        if not project_roots:
            for outcome in outcomes:
                name = str(outcome.get("project_name", "")).strip()
                root_raw = str(outcome.get("project_root", "")).strip()
                if not name or not root_raw:
                    continue
                project_roots[name] = Path(root_raw)
        if not project_roots:
            return {}

        state = rt.load_existing_state(mode=route.mode)
        if state is None:
            return {}

        run_dir = self._new_test_results_run_dir(state.run_id)  # type: ignore[attr-defined]
        existing = state.metadata.get("project_test_summaries")
        metadata = dict(existing) if isinstance(existing, dict) else {}
        summaries: dict[str, dict[str, object]] = {}
        for project_name, project_root in project_roots.items():
            summaries[project_name] = self._write_failed_tests_summary(
                run_dir=run_dir,
                project_name=project_name,
                project_root=project_root,
                outcomes=outcomes,
                previous_entry=metadata.get(project_name) if isinstance(metadata.get(project_name), dict) else None,
            )

        metadata.update(summaries)
        state.metadata["project_test_summaries"] = metadata
        state.metadata["project_test_results_root"] = str(run_dir)
        state.metadata["project_test_results_updated_at"] = datetime.now(tz=UTC).isoformat()

        rt.state_repository.save_resume_state(
            state=state,
            emit=rt.emit,
            runtime_map_builder=build_runtime_map,
        )
        rt.emit(
            "test.summary.persisted",
            mode=route.mode,
            projects=sorted(summaries),
            run_dir=str(run_dir),
        )
        return summaries

    def _new_test_results_run_dir(self, run_id: str) -> Path:
        results_root = self.runtime.state_repository.test_results_dir_path(run_id)
        results_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(tz=UTC).strftime("run_%Y%m%d_%H%M%S")
        candidate = results_root / stamp
        if not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        suffix = 1
        while True:
            suffixed = results_root / f"{stamp}_{suffix}"
            if not suffixed.exists():
                suffixed.mkdir(parents=True, exist_ok=True)
                return suffixed
            suffix += 1

    def _write_failed_tests_summary(
        self,
        *,
        run_dir: Path,
        project_name: str,
        project_root: Path,
        outcomes: list[dict[str, object]],
        previous_entry: dict[str, object] | None = None,
    ) -> dict[str, object]:
        safe_project = project_name.replace(" ", "_")
        output_dir = run_dir / safe_project
        output_dir.mkdir(parents=True, exist_ok=True)
        summary_path = output_dir / "failed_tests_summary.txt"
        short_summary_path = self._short_failed_summary_path(run_dir=run_dir, project_name=project_name)
        state_path = output_dir / "test_state.txt"
        manifest_path = output_dir / "failed_tests_manifest.json"

        failures = self._collect_failed_tests(outcomes, project_name=project_name)
        generic_suite_failures = self._collect_generic_suite_failures(outcomes, project_name=project_name)
        suite_failure_contexts = self._collect_suite_failure_contexts(outcomes, project_name=project_name)
        manifest_entries = self._collect_failed_test_manifest_entries(outcomes, project_name=project_name)
        failed_only = any(
            bool(item.get("failed_only", False))
            for item in outcomes
            if str(item.get("project_name", "")).strip() == project_name
        )
        generated_at = datetime.now().astimezone()
        lines = [
            "# envctl Failed Test Summary",
            f"# Generated at: {generated_at.strftime('%a %b %d %H:%M:%S %Z %Y')}",
            "",
        ]
        if failures:
            for suite_name, failed_test, error_text in failures:
                clean_suite_name = strip_ansi(str(suite_name)).strip()
                clean_failed_test = strip_ansi(str(failed_test)).strip()
                lines.append(f"[{clean_suite_name}]")
                lines.append(f"- {clean_failed_test}")
                if error_text:
                    for detail in self._format_summary_error_lines(str(error_text)):
                        lines.append(f"    {detail}")
                lines.append("")
            for suite_name, context_text in suite_failure_contexts:
                clean_suite_name = strip_ansi(str(suite_name)).strip()
                lines.append(f"[{clean_suite_name}]")
                lines.append("suite context:")
                for detail in self._format_summary_error_lines(str(context_text)):
                    lines.append(f"    {detail}")
                lines.append("")
        elif generic_suite_failures:
            for suite_name, summary in generic_suite_failures:
                clean_suite_name = strip_ansi(str(suite_name)).strip()
                lines.append(f"[{clean_suite_name}]")
                lines.append("- suite failed before envctl could extract failed tests")
                for detail in self._format_summary_error_lines(str(summary)):
                    lines.append(f"    {detail}")
                lines.append("")
        else:
            lines.append("No failed tests.")
            lines.append("")
        summary_text = "\n".join(lines)
        summary_path.write_text(summary_text, encoding="utf-8")
        short_summary_path.write_text(summary_text, encoding="utf-8")

        head, status_hash, status_lines = self._git_state_components(project_root)
        state_path.write_text(
            f"state|{project_name}|{project_root}|{head}|{status_hash}|{status_lines}\n",
            encoding="utf-8",
        )
        manifest_payload = {
            "generated_at": generated_at.isoformat(),
            "project_name": project_name,
            "project_root": str(project_root),
            "git_state": {
                "head": head,
                "status_hash": status_hash,
                "status_lines": status_lines,
            },
            "entries": manifest_entries,
        }
        manifest_path.write_text(json.dumps(manifest_payload, indent=2, sort_keys=True), encoding="utf-8")

        preserve_previous = (
            failed_only
            and not failures
            and bool(generic_suite_failures)
            and not manifest_entries
            and previous_entry is not None
        )
        if preserve_previous:
            previous_manifest_path_raw = str(previous_entry.get("manifest_path", "") or "").strip()
            previous_manifest = (
                load_failed_test_manifest(Path(previous_manifest_path_raw)) if previous_manifest_path_raw else None
            )
            if previous_manifest is not None and previous_manifest.entries:
                preserved = dict(previous_entry)
                preserved["status"] = "failed"
                preserved["updated_at"] = generated_at.isoformat()
                preserved["preserved_after_failed_only_extraction_failure"] = True
                return preserved

        return {
            "summary_path": str(summary_path),
            "short_summary_path": str(short_summary_path),
            "state_path": str(state_path),
            "manifest_path": str(manifest_path),
            "status": "failed" if failures or generic_suite_failures else "passed",
            "failed_tests": len(failures),
            "failed_manifest_entries": len(manifest_entries),
            "summary_excerpt": extract_failure_summary_excerpt(summary_text, max_lines=3),
            "updated_at": generated_at.isoformat(),
        }

    def _collect_failed_tests(
        self,
        outcomes: list[dict[str, object]],
        *,
        project_name: str | None = None,
    ) -> list[tuple[str, str, str]]:
        collected: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str]] = set()
        ordered = sorted(outcomes, key=lambda value: int(value.get("index", 0)))
        for item in ordered:
            if project_name is not None:
                item_project_name = str(item.get("project_name", "")).strip()
                if item_project_name != project_name:
                    continue
            source = str(item.get("suite", "suite"))
            parsed = item.get("parsed")
            failed_tests = list(getattr(parsed, "failed_tests", []) or []) if parsed is not None else []
            error_details = dict(getattr(parsed, "error_details", {}) or {}) if parsed is not None else {}
            suite_name = self._suite_display_name(source, failed_only=bool(item.get("failed_only", False)))
            for failed_test in failed_tests:
                test_name = str(failed_test).strip()
                if not test_name:
                    continue
                dedupe_key = (suite_name, test_name)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                error_text = self._resolve_failed_test_error(error_details, test_name)
                collected.append((suite_name, test_name, error_text))
        return collected

    def _collect_failed_test_manifest_entries(
        self,
        outcomes: list[dict[str, object]],
        *,
        project_name: str | None = None,
    ) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        ordered = sorted(outcomes, key=lambda value: int(value.get("index", 0)))
        for item in ordered:
            if project_name is not None:
                item_project_name = str(item.get("project_name", "")).strip()
                if item_project_name != project_name:
                    continue
            source = str(item.get("suite", "")).strip()
            if not source:
                continue
            parsed = item.get("parsed")
            raw_failed_tests = (
                [
                    str(failed_test).strip()
                    for failed_test in list(getattr(parsed, "failed_tests", []) or [])
                    if str(failed_test).strip()
                ]
                if parsed is not None
                else []
            )
            failed_tests, invalid_failed_tests = sanitize_failed_test_identifiers(
                source=source,
                failed_tests=raw_failed_tests,
            )
            failed_files = (
                frontend_failed_files_from_failed_tests(failed_tests)
                if source in {"frontend_package_test", "package_test"}
                else []
            )
            if not failed_tests and not failed_files:
                continue
            entries.append(
                {
                    "suite": self._suite_display_name(source, failed_only=bool(item.get("failed_only", False))),
                    "source": source,
                    "failed_tests": list(failed_tests),
                    "failed_files": failed_files,
                    "invalid_failed_tests": invalid_failed_tests,
                }
            )
        return entries

    def _collect_generic_suite_failures(
        self,
        outcomes: list[dict[str, object]],
        *,
        project_name: str | None = None,
    ) -> list[tuple[str, str]]:
        collected: list[tuple[str, str]] = []
        ordered = sorted(outcomes, key=lambda value: int(value.get("index", 0)))
        for item in ordered:
            if project_name is not None:
                item_project_name = str(item.get("project_name", "")).strip()
                if item_project_name != project_name:
                    continue
            if int(item.get("returncode", 0) or 0) == 0:
                continue
            parsed = item.get("parsed")
            failed_tests = list(getattr(parsed, "failed_tests", []) or []) if parsed is not None else []
            if failed_tests:
                continue
            summary = str(item.get("failure_details", "") or item.get("failure_summary", "") or "").strip()
            if not summary:
                summary = "Test command failed before envctl could extract failed tests."
            suite_name = self._suite_display_name(
                str(item.get("suite", "suite")),
                failed_only=bool(item.get("failed_only", False)),
            )
            collected.append((suite_name, summary))
        return collected

    def _collect_suite_failure_contexts(
        self,
        outcomes: list[dict[str, object]],
        *,
        project_name: str | None = None,
    ) -> list[tuple[str, str]]:
        collected: list[tuple[str, str]] = []
        ordered = sorted(outcomes, key=lambda value: int(value.get("index", 0)))
        for item in ordered:
            if project_name is not None:
                item_project_name = str(item.get("project_name", "")).strip()
                if item_project_name != project_name:
                    continue
            if int(item.get("returncode", 0) or 0) == 0:
                continue
            parsed = item.get("parsed")
            failed_tests = list(getattr(parsed, "failed_tests", []) or []) if parsed is not None else []
            if not failed_tests:
                continue
            context_text = str(item.get("failure_details", "") or "").strip()
            if not context_text:
                continue
            suite_name = self._suite_display_name(
                str(item.get("suite", "suite")),
                failed_only=bool(item.get("failed_only", False)),
            )
            collected.append((suite_name, context_text))
        return collected

    @staticmethod
    def _resolve_failed_test_error(error_details: dict[str, object], test_name: str) -> str:
        direct = error_details.get(test_name)
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        if "::" in test_name:
            file_key = test_name.split("::", 1)[0]
            file_error = error_details.get(file_key)
            if isinstance(file_error, str) and file_error.strip():
                return file_error.strip()
        return ""

    @staticmethod
    def _git_state_components(project_root: Path) -> tuple[str, str, int]:
        head = ""
        status = ""
        try:
            head_proc = subprocess.run(
                ["git", "-C", str(project_root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            )
            if head_proc.returncode == 0:
                head = (head_proc.stdout or "").strip()
            status_proc = subprocess.run(
                ["git", "-C", str(project_root), "status", "--porcelain=1"],
                capture_output=True,
                text=True,
                check=False,
            )
            if status_proc.returncode == 0:
                status = status_proc.stdout or ""
        except Exception:
            head = ""
            status = ""
        status_hash = hashlib.sha1(status.encode("utf-8")).hexdigest()
        status_lines = len([line for line in status.splitlines() if line.strip()])
        return head, status_hash, status_lines

    @staticmethod
    def _suite_display_name(source: str, *, failed_only: bool = False) -> str:
        if source == "backend_pytest":
            return "Backend (pytest, failed only)" if failed_only else "Backend (pytest)"
        if source == "configured_backend":
            return "Backend (failed only)" if failed_only else "Backend"
        if source == "frontend_package_test":
            return "Frontend (package test, failed only)" if failed_only else "Frontend (package test)"
        if source == "configured_frontend":
            return "Frontend (failed only)" if failed_only else "Frontend"
        if source == "root_unittest":
            return "Repository tests (unittest, failed only)" if failed_only else "Repository tests (unittest)"
        if source == "package_test":
            return "Repository package test (failed only)" if failed_only else "Repository package test"
        if source == "configured":
            return "Test command (failed only)" if failed_only else "Test command"
        return source.replace("_", " ")

    def _project_action_failure_summary_lines(
        self,
        *,
        command_name: str,
        error_output: str,
        migrate_env_metadata: Mapping[str, object] | None = None,
    ) -> list[str]:
        lines = self._format_summary_error_lines(error_output)
        if command_name != "migrate":
            return lines
        headline = self._migrate_failure_headline_from_lines(lines)
        hint_lines = self._migrate_failure_hint_lines(error_output)
        env_lines = self._migrate_env_source_hint_lines(migrate_env_metadata)
        merged: list[str] = []
        if headline:
            merged.append(headline)
        seen = set(merged)
        for line in lines:
            if line in seen:
                continue
            merged.append(line)
            seen.add(line)
        for hint in [*hint_lines, *env_lines]:
            if hint in seen:
                continue
            merged.append(hint)
            seen.add(hint)
        return merged

    @staticmethod
    def _migrate_failure_headline(error_output: str) -> str:
        lines = ActionCommandOrchestrator._format_summary_error_lines(error_output)
        headline = ActionCommandOrchestrator._migrate_failure_headline_from_lines(lines)
        return headline or "Command failed."

    @staticmethod
    def _migrate_failure_headline_from_lines(lines: list[str]) -> str:
        if not lines:
            return ""
        has_exception = any(ActionCommandOrchestrator._is_exception_start(line) for line in lines)
        for line in lines:
            if ActionCommandOrchestrator._is_exception_start(line):
                return line
        for line in lines:
            if line == "Traceback (most recent call last):":
                continue
            if has_exception and line.startswith('File "'):
                continue
            if ActionCommandOrchestrator._is_captured_output_header(line):
                continue
            if ActionCommandOrchestrator._is_exception_context_marker(line):
                continue
            return line
        return lines[0]

    @staticmethod
    def _migrate_failure_hint_lines(error_output: str) -> list[str]:
        cleaned = strip_ansi(error_output)
        normalized = cleaned.replace("\\", "/").lower()
        if "alembic/env.py" not in normalized:
            return []
        if "validationerror" not in normalized and "field required" not in normalized and "type=missing" not in normalized:
            return []

        missing_vars = [
            name
            for name in ("DATABASE_URL", "REDIS_URL", "DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME")
            if re.search(rf"(?m)^{re.escape(name)}\s*$", cleaned)
        ]
        if not missing_vars:
            return []
        joined_vars = ", ".join(missing_vars)
        return [
            f"hint: migrate failed before Alembic reached revisions because required env vars were missing ({joined_vars}).",
            "hint: envctl migrate loads backend env from backend/.env by default.",
            "hint: BACKEND_ENV_FILE_OVERRIDE or MAIN_ENV_FILE_PATH can redirect the env file.",
            "hint: APP_ENV_FILE is exported when an env file is found, and running projects reuse current dependency URLs when available.",
        ]

    @staticmethod
    def _migrate_env_source_hint_lines(migrate_env_metadata: Mapping[str, object] | None) -> list[str]:
        if not isinstance(migrate_env_metadata, Mapping):
            return []
        source = str(migrate_env_metadata.get("env_file_source", "")).strip()
        if not source:
            return []
        parts = [f"hint: backend env source: {source}"]
        env_file_path_raw = migrate_env_metadata.get("env_file_path")
        env_file_path = str(env_file_path_raw).strip() if isinstance(env_file_path_raw, str) else ""
        if env_file_path:
            parts.append(env_file_path)
        if bool(migrate_env_metadata.get("override_requested")):
            resolution = str(migrate_env_metadata.get("override_resolution", "")).strip()
            if resolution:
                parts.append(f"override_resolution={resolution}")
        return [" | ".join(parts)]

    def _migrate_requirements_for_target(
        self,
        *,
        route: Route | None,
        project_name: str,
    ) -> RequirementsResult | None:
        route_mode = getattr(route, "mode", None)
        state = self.runtime.load_existing_state(mode=route_mode) if isinstance(route_mode, str) else None
        if state is None:
            return None
        requirements_map = getattr(state, "requirements", None)
        if not isinstance(requirements_map, dict):
            return None
        candidate = requirements_map.get(project_name)
        if isinstance(candidate, RequirementsResult):
            return candidate
        normalized_name = project_name.strip().lower()
        for key, value in requirements_map.items():
            if str(key).strip().lower() == normalized_name and isinstance(value, RequirementsResult):
                return value
        return None

    @staticmethod
    def _migrate_backend_cwd(target_root: Path) -> Path:
        backend_dir = target_root / "backend"
        if backend_dir.is_dir():
            return backend_dir
        return target_root

    @staticmethod
    def _migrate_project_context(
        *,
        project_name: str,
        project_root: Path,
        requirements: RequirementsResult,
    ) -> _MigrateProjectContext:
        ports: dict[str, PortPlan] = {}
        for component_name, port_key in (
            ("postgres", "db"),
            ("redis", "redis"),
            ("n8n", "n8n"),
            ("supabase", "db"),
        ):
            if port_key in ports:
                continue
            component = requirements.component(component_name)
            port = ActionCommandOrchestrator._migrate_component_port(component)
            if port <= 0:
                continue
            ports[port_key] = PortPlan(
                project=project_name,
                requested=port,
                assigned=port,
                final=port,
                source="requirements_state",
            )
        return _MigrateProjectContext(name=project_name, root=project_root, ports=ports)

    @staticmethod
    def _migrate_component_port(component: Mapping[str, object]) -> int:
        for key in ("final", "requested", "assigned"):
            raw = component.get(key)
            try:
                value = int(raw)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
        return 0

    @staticmethod
    def _format_summary_error_lines(error_text: str) -> list[str]:
        cleaned = strip_ansi(error_text)
        lines: list[str] = []
        for raw_line in cleaned.splitlines():
            compact = ActionCommandOrchestrator._compact_summary_line(raw_line)
            if compact:
                lines.append(compact)
        if not lines:
            return []

        max_lines = 60
        if len(lines) <= max_lines:
            return lines
        structured = ActionCommandOrchestrator._structured_summary_lines(lines)
        if not structured:
            structured = lines[:]
        merged = structured[:]
        seen = set(merged)
        for line in lines:
            if len(merged) >= max_lines:
                break
            if line in seen:
                continue
            merged.append(line)
            seen.add(line)
        if len(lines) > len(merged):
            merged.append(f"... ({len(lines) - len(merged)} more lines omitted)")
        return merged[: max_lines + 1]

    @staticmethod
    def _compact_summary_line(line: str) -> str:
        stripped = line.strip()
        if not stripped:
            return ""
        if re.fullmatch(r"[-=]{6,}", stripped):
            return ""
        if ActionCommandOrchestrator._looks_like_terminal_chrome(stripped):
            return ""
        stripped = re.sub(r"( not found in )(['\"]).*", r"\1<omitted output>", stripped)
        stripped = re.sub(r"( not found: )(['\"]).*", r"\1<omitted output>", stripped)
        stripped = re.sub(r"(result(?:ed)? in )(['\"]).*", r"\1<omitted output>", stripped, flags=re.IGNORECASE)
        if len(stripped) > 220:
            stripped = f"{stripped[:217].rstrip()}..."
        return stripped

    @staticmethod
    def _structured_summary_lines(lines: list[str]) -> list[str]:
        assembled: list[str] = []
        seen: set[str] = set()

        def append_block(block: list[str], *, allow_gap: bool = False) -> None:
            nonlocal assembled
            block = [line for line in block if line]
            if not block:
                return
            if allow_gap and assembled and assembled[-1] != "...":
                assembled.append("...")
            for line in block:
                if line in seen:
                    continue
                assembled.append(line)
                seen.add(line)

        traceback_header = next((line for line in lines if line.startswith("Traceback (most recent call last):")), "")
        if traceback_header:
            append_block([traceback_header])

        for block in ActionCommandOrchestrator._user_code_frame_blocks(lines):
            append_block(block, allow_gap=bool(assembled))

        context_markers = ActionCommandOrchestrator._exception_context_markers(lines)
        if context_markers:
            append_block(context_markers, allow_gap=bool(assembled))

        exception_body = ActionCommandOrchestrator._exception_body_block(lines)
        if exception_body:
            append_block(exception_body, allow_gap=bool(assembled))

        captured_blocks = ActionCommandOrchestrator._captured_output_blocks(lines)
        for block in captured_blocks:
            append_block(block, allow_gap=bool(assembled))

        max_lines = 24
        if assembled:
            return assembled[:max_lines]
        return []

    @staticmethod
    def _user_code_frame_blocks(lines: list[str]) -> list[list[str]]:
        blocks: list[list[str]] = []
        file_indexes = [index for index, line in enumerate(lines) if line.startswith('File "')]
        for index in file_indexes:
            if not ActionCommandOrchestrator._is_user_code_frame(lines[index]):
                continue
            block = [lines[index]]
            cursor = index + 1
            while cursor < len(lines):
                line = lines[cursor]
                if line.startswith('File "') or ActionCommandOrchestrator._is_captured_output_header(line):
                    break
                if ActionCommandOrchestrator._is_exception_start(line):
                    break
                block.append(line)
                cursor += 1
            blocks.append(block[:3])
        return blocks

    @staticmethod
    def _exception_body_block(lines: list[str]) -> list[str]:
        start = -1
        for index in range(len(lines) - 1, -1, -1):
            if ActionCommandOrchestrator._is_exception_start(lines[index]):
                start = index
                break
        if start < 0:
            return []
        block = [lines[start]]
        cursor = start + 1
        while cursor < len(lines):
            line = lines[cursor]
            if line.startswith('File "') or ActionCommandOrchestrator._is_captured_output_header(line):
                break
            block.append(line)
            cursor += 1
        return block[:5]

    @staticmethod
    def _captured_output_blocks(lines: list[str]) -> list[list[str]]:
        blocks: list[list[str]] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            if not ActionCommandOrchestrator._is_captured_output_header(line):
                index += 1
                continue
            block = [line]
            cursor = index + 1
            while cursor < len(lines):
                candidate = lines[cursor]
                if ActionCommandOrchestrator._is_captured_output_header(candidate):
                    break
                if candidate.startswith('File "') and ActionCommandOrchestrator._is_user_code_frame(candidate):
                    break
                if candidate == "Traceback (most recent call last):":
                    break
                if ActionCommandOrchestrator._is_exception_context_marker(candidate):
                    break
                block.append(candidate)
                cursor += 1
            blocks.append(block[:5])
            index = cursor
        return blocks

    @staticmethod
    def _exception_context_markers(lines: list[str]) -> list[str]:
        return [line for line in lines if ActionCommandOrchestrator._is_exception_context_marker(line)][:3]

    @staticmethod
    def _is_user_code_frame(line: str) -> bool:
        match = re.match(r'^File "([^"]+)"', line)
        if match is None:
            return False
        path = match.group(1)
        stdlib_markers = (
            "/Cellar/python@",
            "/Frameworks/Python.framework/",
            "/lib/python",
            "/site-packages/",
            "/asyncio/",
            "/unittest/",
        )
        return not any(marker in path for marker in stdlib_markers)

    @staticmethod
    def _is_exception_start(line: str) -> bool:
        return bool(
            re.match(
                r"^(?:AssertionError|[A-Za-z_][\w.]*(?:Error|Exception|Failure|Exit|Interrupt|Warning))(?:\b|:)",
                line,
            )
        )

    @staticmethod
    def _is_exception_context_marker(line: str) -> bool:
        lowered = line.strip().lower()
        return (
            "during handling of the above exception" in lowered or "the above exception was the direct cause" in lowered
        )

    @staticmethod
    def _is_captured_output_header(line: str) -> bool:
        lowered = line.strip().lower()
        return (
            lowered.startswith("captured stdout")
            or lowered.startswith("captured stderr")
            or lowered.startswith("captured log")
            or lowered in {"stdout:", "stderr:"}
        )

    @staticmethod
    def _looks_like_terminal_chrome(line: str) -> bool:
        if "RESULT_SERVICES=" in line or "Run tests for" in line or "Filter targets..." in line:
            return True
        box_chars = "╭╮╰╯│▊▎▔▁▄▅▇"
        box_count = sum(1 for char in line if char in box_chars)
        if box_count >= 4:
            return True
        if len(line) >= 40 and sum(1 for char in line if char == " ") > len(line) * 0.55 and box_count >= 1:
            return True
        return False

    @staticmethod
    def _noop_restore() -> None:
        return None

    def _print_test_suite_overview(
        self,
        outcomes: list[dict[str, object]],
        *,
        summary_metadata: dict[str, dict[str, object]] | None = None,
    ) -> None:
        if not outcomes:
            return
        print("")
        print(self._colorize("======================================================================", fg="cyan"))
        print(self._colorize("Test Suite Summary", fg="cyan", bold=True))
        print(self._colorize("======================================================================", fg="cyan"))
        project_labels = {
            str(item.get("project_name", "")).strip() for item in outcomes if str(item.get("project_name", "")).strip()
        }
        multi_project = len(project_labels) > 1
        total_passed = 0
        total_failed = 0
        total_skipped = 0
        total_known = 0
        total_duration = 0.0
        grouped_outcomes: dict[str, list[dict[str, object]]] = {}
        for item in sorted(
            outcomes,
            key=lambda value: (
                str(value.get("project_name", "")).lower(),
                int(value.get("index", 0)),
            ),
        ):
            project_name = str(item.get("project_name", "")).strip() or "Main"
            grouped_outcomes.setdefault(project_name, []).append(item)

        for project_name, project_items in grouped_outcomes.items():
            if multi_project:
                print(self._colorize(project_name, fg="blue", bold=True))
            for item in project_items:
                source = str(item.get("suite", "suite"))
                label = self._suite_display_name(source, failed_only=bool(item.get("failed_only", False)))
                label_rendered = self._colorize(label, fg="cyan", bold=True)
                if multi_project:
                    label_rendered = f"  {label_rendered}"
                returncode = int(item.get("returncode", 1))
                parsed = item.get("parsed")
                parsed_total = int(getattr(parsed, "total", 0) or 0) if parsed is not None else 0
                counts_detected = bool(getattr(parsed, "counts_detected", False)) if parsed is not None else False
                passed = int(getattr(parsed, "passed", 0) or 0) if parsed is not None else 0
                failed = int(getattr(parsed, "failed", 0) or 0) if parsed is not None else 0
                skipped = int(getattr(parsed, "skipped", 0) or 0) if parsed is not None else 0
                duration_ms = float(item.get("duration_ms", 0.0) or 0.0)
                duration_text = format_duration(max(duration_ms / 1000.0, 0.0))

                icon = (
                    self._colorize("✓", fg="green", bold=True)
                    if returncode == 0
                    else self._colorize("✗", fg="red", bold=True)
                )
                if counts_detected:
                    total_passed += passed
                    total_failed += failed
                    total_skipped += skipped
                    total_known += parsed_total
                    total_duration += max(duration_ms / 1000.0, 0.0)
                    passed_text = self._colorize(f"{passed} passed", fg="green")
                    failed_text = self._colorize(f"{failed} failed", fg="red")
                    skipped_text = self._colorize(f"{skipped} skipped", fg="yellow")
                    print(
                        f"{icon} {label_rendered}: {passed_text}, {failed_text}, {skipped_text}"
                        f" (total {parsed_total}, duration {duration_text})"
                    )
                else:
                    total_duration += max(duration_ms / 1000.0, 0.0)
                    if returncode == 0:
                        print(
                            f"{icon} {label_rendered}: "
                            f"{self._colorize('completed', fg='green', bold=True)} "
                            f"(no parsed test counts, duration {duration_text})"
                        )
                    else:
                        print(
                            f"{icon} {label_rendered}: "
                            f"{self._colorize('failed', fg='red', bold=True)} "
                            f"(no parsed test counts, duration {duration_text})"
                        )
            summary_entry = summary_metadata.get(project_name) if isinstance(summary_metadata, dict) else None
            if isinstance(summary_entry, dict) and str(summary_entry.get("status", "")).strip().lower() == "failed":
                summary_path = str(
                    summary_entry.get("short_summary_path") or summary_entry.get("summary_path") or ""
                ).strip()
                if summary_path:
                    prefix = "  " if multi_project else ""
                    label = self._colorize("failure summary:", fg="gray")
                    print(f"{prefix}{label}")
                    rendered_path = render_path_for_terminal(
                        summary_path, env=getattr(self.runtime, "env", {}), stream=sys.stdout
                    )
                    print(f"{prefix}{rendered_path}")
            if multi_project:
                print("")

        if total_known > 0:
            overall_prefix = self._colorize("Overall:", fg="cyan", bold=True)
            overall_passed = self._colorize(f"{total_passed} passed", fg="green")
            overall_failed = self._colorize(f"{total_failed} failed", fg="red")
            overall_skipped = self._colorize(f"{total_skipped} skipped", fg="yellow")
            print(
                f"{overall_prefix} {overall_passed}, {overall_failed}, {overall_skipped}"
                f" (total {total_known}, duration {format_duration(total_duration)})"
            )
        print(self._colorize("======================================================================", fg="cyan"))

    @staticmethod
    def _is_legacy_tree_test_script(command: list[str]) -> bool:
        return len(command) >= 2 and command[0] == "bash" and command[1].endswith("test-all-trees.sh")

    def _test_target_contexts(self, targets: list[object]) -> list[TestTargetContext]:
        rt = self.runtime
        return build_test_target_contexts(targets, repo_root=rt.config.base_dir)  # type: ignore[attr-defined]
