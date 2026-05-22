from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import concurrent.futures
import os
from pathlib import Path
import tempfile
import re
import sys
from types import SimpleNamespace
from typing import Any, Callable, Mapping, cast

from envctl_engine.actions.actions_analysis import default_review_command
from envctl_engine.actions.actions_git import default_commit_command, default_pr_command
from envctl_engine.actions.action_command_support import service_types_from_route_services
from envctl_engine.actions.action_migrate_support import (
    MigrateResultRecord as _MigrateResultRecord,
    is_migrate_env_source_hint as is_migrate_env_source_hint_impl,
    migrate_env_source_hint_lines as migrate_env_source_hint_lines_impl,
    migrate_failure_hint_lines as migrate_failure_hint_lines_impl,
    migrate_result_record as migrate_result_record_impl,
    migrate_result_records as migrate_result_records_impl,
    print_compact_migrate_failure_logs as print_compact_migrate_failure_logs_impl,
    print_migrate_failure_logs as print_migrate_failure_logs_impl,
    print_migrate_result_records as print_migrate_result_records_impl,
    print_migrate_result_summary as print_migrate_result_summary_impl,
    record_index as record_index_impl,
    render_migrate_project_name as render_migrate_project_name_impl,
    render_migrate_symbol as render_migrate_symbol_impl,
    shared_migrate_hint_lines as shared_migrate_hint_lines_impl,
    shared_report_parent as shared_report_parent_impl,
    visible_migrate_hint_lines as visible_migrate_hint_lines_impl,
)
from envctl_engine.actions.action_migrate_execution_support import (
    run_migrate_action as run_migrate_action_impl,
)
from envctl_engine.actions.action_failed_rerun_support import (
    build_failed_test_execution_specs_from_state as build_failed_test_execution_specs_from_state_impl,
    summary_indicates_extraction_failure as summary_indicates_extraction_failure_impl,
)
from envctl_engine.actions.action_target_support import (
    ActionTargetContext,
    execute_targeted_action,
    projects_for_services as projects_for_services_impl,
    resolve_action_targets as resolve_action_targets_impl,
)
from envctl_engine.actions.action_test_summary_support import (
    collect_failed_test_manifest_entries as collect_failed_test_manifest_entries_impl,
    collect_failed_tests as collect_failed_tests_impl,
    collect_generic_suite_failures as collect_generic_suite_failures_impl,
    collect_suite_failure_contexts as collect_suite_failure_contexts_impl,
    default_git_state_components as git_state_components_impl,
    resolve_failed_test_error as resolve_failed_test_error_impl,
    short_failed_summary_path as short_failed_summary_path_impl,
    suite_display_name as suite_display_name_impl,
    write_failed_tests_summary as write_failed_tests_summary_impl,
)
from envctl_engine.actions.action_test_service_support import (
    additional_service_test_execution_specs as additional_service_test_execution_specs_impl,
)
from envctl_engine.actions.project_action_report_support import (
    first_output_line as first_output_line_impl,
    persist_project_action_result as persist_project_action_result_impl,
    project_action_success_status as project_action_success_status_impl,
    review_success_artifact_paths as review_success_artifact_paths_impl,
    write_project_action_failure_report as write_project_action_failure_report_impl,
)
from envctl_engine.actions.project_action_env_support import (
    action_env as action_env_impl,
    action_extra_env as action_extra_env_impl,
    action_replacements as action_replacements_impl,
    migrate_action_env as migrate_action_env_impl,
    test_action_extra_env as test_action_extra_env_impl,
)
from envctl_engine.actions.project_action_execution_support import (
    run_project_action as run_project_action_impl,
)
from envctl_engine.actions.action_test_support import (
    TestExecutionSpec as _TestExecutionSpec,
    TestSuiteSpinnerGroup as _TestSuiteSpinnerGroup,
    TestTargetContext,
    build_test_execution_specs,
    build_test_target_contexts,
    is_backend_only_selection,
    rich_progress_available as _rich_progress_available,
)
from envctl_engine.actions.action_test_runner import run_test_action as run_test_action_impl
from envctl_engine.actions.action_worktree_runner import (
    run_delete_worktree_action as run_delete_worktree_action_impl,
    run_self_destruct_worktree_action as run_self_destruct_worktree_action_impl,
)
from envctl_engine.planning import discover_tree_projects
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.launcher_support import main_repo_root_for_linked_worktree
from envctl_engine.shared.parsing import parse_bool, parse_int
from envctl_engine.startup.service_bootstrap_domain import (
    _resolve_backend_env_contract,
)
from envctl_engine.state.models import PortPlan, RequirementsResult
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.test_output.test_runner import TestRunner
from envctl_engine.test_output.parser_base import strip_ansi
from envctl_engine.test_output.symbols import format_duration
from envctl_engine.ui.color_policy import colors_enabled
from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI  # noqa: F401
from envctl_engine.ui.path_links import render_path_for_terminal
from envctl_engine.ui.selection_support import interactive_selection_allowed, no_target_selected_message
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
        self._deferred_post_action_output: Callable[[], None] | None = None

    @staticmethod
    def _short_failed_summary_path(*, run_dir: Path, project_name: str) -> Path:
        return short_failed_summary_path_impl(run_dir=run_dir, project_name=project_name)

    def execute(self, route: Route) -> int:
        rt = self.runtime
        if route.command == "self-destruct-worktree":
            code = self.run_self_destruct_worktree_action(route)
            rt.emit("action.command.finish", command=route.command, code=code)
            return code
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

        self._deferred_post_action_output = None
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
        deferred_output = self._deferred_post_action_output
        self._deferred_post_action_output = None
        if deferred_output is not None:
            deferred_output()
        rt.emit("action.command.finish", command=route.command, code=code)
        return code

    def resolve_targets(self, route: Route, *, trees_only: bool) -> tuple[list[object], str | None]:
        return resolve_action_targets_impl(
            runtime=self.runtime,
            route=route,
            trees_only=trees_only,
            resolve_current_worktree_target=self._resolve_current_worktree_target,
            interactive_selection_allowed=self._interactive_selection_allowed,
            no_target_selected_message=self._no_target_selected_message,
        )

    def run_self_destruct_worktree_action(self, route: Route) -> int:
        return run_self_destruct_worktree_action_impl(self, route)

    def _resolve_current_worktree_target(self, *, require_configured_main_root: bool = False) -> object | None:
        invocation_cwd = str(self.runtime.env.get("ENVCTL_INVOCATION_CWD") or "").strip()
        cwd = Path(invocation_cwd).expanduser().resolve() if invocation_cwd else Path.cwd().resolve()
        configured_root = getattr(self.runtime.raw_runtime.config, "base_dir", None)
        configured_root_path = (
            Path(str(configured_root)).expanduser().resolve()
            if configured_root is not None
            else None
        )
        if require_configured_main_root and configured_root_path == cwd:
            return None
        trees_dir_name = str(getattr(self.runtime.raw_runtime.config, "trees_dir_name", "trees"))
        if require_configured_main_root:
            if configured_root_path is None:
                return None
            repo_root = self._repo_root_from_worktree_layout(cwd, trees_dir_name)
            if repo_root is None:
                repo_root = main_repo_root_for_linked_worktree(cwd)
            if repo_root is None or repo_root.resolve() != configured_root_path:
                return None
        else:
            repo_root = self._main_repo_root_for_worktree(cwd, trees_dir_name=trees_dir_name)
            if repo_root is None:
                return None
        candidates = [
            SimpleNamespace(name=name, root=root)
            for name, root in discover_tree_projects(repo_root, trees_dir_name)
        ]
        matches = [candidate for candidate in candidates if Path(str(getattr(candidate, "root"))).resolve() == cwd]
        if len(matches) != 1:
            return None
        return matches[0]

    def _main_repo_root_for_worktree(self, worktree_root: Path, *, trees_dir_name: str | None = None) -> Path | None:
        configured_trees_dir = trees_dir_name or getattr(self.runtime.raw_runtime.config, "trees_dir_name", "trees")
        normalized_trees_dir = str(configured_trees_dir).strip().rstrip("/")
        repo_root_from_layout = self._repo_root_from_worktree_layout(worktree_root, normalized_trees_dir)
        if repo_root_from_layout is not None:
            return repo_root_from_layout

        completed = self.runtime.raw_runtime.process_runner.run(  # type: ignore[attr-defined]
            ["git", "rev-parse", "--show-toplevel"],
            cwd=worktree_root,
            timeout=10.0,
        )
        if getattr(completed, "returncode", 1) != 0:
            return None
        top_level = Path(str(getattr(completed, "stdout", "") or "").strip()).resolve()

        common = self.runtime.raw_runtime.process_runner.run(  # type: ignore[attr-defined]
            ["git", "rev-parse", "--git-common-dir"],
            cwd=worktree_root,
            timeout=10.0,
        )
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
        return top_level

    @staticmethod
    def _repo_root_from_worktree_layout(worktree_root: Path, trees_dir_name: str) -> Path | None:
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

    def _spawn_self_destruct_helper(self, *, repo_root: Path, trees_root: Path, worktree_root: Path) -> bool:
        rt = self.runtime.raw_runtime
        helper_dir = Path(tempfile.mkdtemp(prefix="envctl-self-destruct-", dir=str(repo_root)))
        helper_script = helper_dir / "self_destruct.py"
        helper_script.write_text(
            """
from __future__ import annotations
import shutil
import subprocess
import sys
import time
from pathlib import Path

repo_root = Path(sys.argv[1]).resolve()
trees_root = Path(sys.argv[2]).resolve()
worktree_root = Path(sys.argv[3]).resolve()
parent_pid = int(sys.argv[4])

for _ in range(200):
    try:
        subprocess.run(
            ["kill", "-0", str(parent_pid)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.1)
    except Exception:
        break

result = subprocess.run(
    ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(worktree_root)],
    capture_output=True,
    text=True,
    timeout=30.0,
)
if result.returncode != 0:
    sys.exit(result.returncode)
""".strip()
            + "\n",
            encoding="utf-8",
        )
        completed = rt.process_runner.start_background(  # type: ignore[attr-defined]
            [
                "python3",
                str(helper_script),
                str(repo_root),
                str(trees_root),
                str(worktree_root),
                str(os.getpid()),
            ],
            cwd=repo_root,
            stdout_path=helper_dir / "self_destruct.log",
            stderr_path=helper_dir / "self_destruct.log",
        )
        return getattr(completed, "pid", 0) > 0

    def _interactive_selection_allowed(self, route: Route) -> bool:
        return interactive_selection_allowed(self.runtime.raw_runtime, route, allow_dashboard_override=True)

    def projects_for_services(self, service_targets: list[object]) -> list[str]:
        return projects_for_services_impl(self.runtime, service_targets)

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
        interactive_command = bool(route.flags.get("interactive_command"))
        return run_migrate_action_impl(
            runtime=self.runtime,
            route=route,
            targets=targets,
            extra_env=self.action_extra_env(route),
            action_replacements_builder=self.action_replacements,
            migrate_action_env_builder=self.migrate_action_env,
            success_handler=self._project_action_success_handler("migrate", route.mode, interactive_command),
            failure_handler=self._project_action_failure_handler("migrate", route.mode),
            emit_status=self._emit_status,
            failure_summary_lines=self._project_action_failure_summary_lines,
            failure_headline=self._migrate_failure_headline,
            print_result_summary=self._print_migrate_result_summary,
            set_deferred_output=lambda callback: setattr(self, "_deferred_post_action_output", callback),
            execute_targeted_action_fn=execute_targeted_action,
            migrate_env_contracts=self._migrate_env_contracts,
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
        service_specs = self._additional_service_test_execution_specs(
            route=route,
            targets=targets,
            target_contexts=target_contexts,
        )
        if service_specs:
            return service_specs
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

    def _additional_service_test_execution_specs(
        self,
        *,
        route: Route,
        targets: list[object],
        target_contexts: list[TestTargetContext],
    ) -> list["_TestExecutionSpec"]:
        rt = self.runtime
        return additional_service_test_execution_specs_impl(
            route=route,
            targets=targets,
            target_contexts=target_contexts,
            config=rt.config,
            split_command=lambda raw_command, replacements: rt.split_command(
                raw_command,
                replacements=replacements,
            ),
            action_replacements_builder=self.action_replacements,
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
        return build_failed_test_execution_specs_from_state_impl(
            state=state,
            target_contexts=target_contexts,
            repo_root=rt.config.base_dir,  # type: ignore[attr-defined]
            shared_raw_command=shared_raw,
            backend_raw_command=backend_raw,
            frontend_raw_command=frontend_raw,
            emit_status=self._emit_status,
        )

    @staticmethod
    def _summary_indicates_extraction_failure(entry: Mapping[str, object]) -> bool:
        return summary_indicates_extraction_failure_impl(entry)

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
        interactive_command = bool(route.flags.get("interactive_command"))
        return run_project_action_impl(
            runtime=rt,
            route=route,
            targets=targets,
            command_name=command_name,
            env_key=env_key,
            default_command=default_command,
            default_cwd=default_cwd,
            default_append_project_path=default_append_project_path,
            extra_env=extra_env,
            action_replacements_builder=self.action_replacements,
            action_env_builder=self.action_env,
            emit_status=self._emit_status,
            success_handler=self._project_action_success_handler(command_name, route.mode, interactive_command),
            failure_handler=self._project_action_failure_handler(command_name, route.mode),
            stdout_is_live_terminal=_stdout_is_live_terminal,
            execute_targeted_action_fn=execute_targeted_action,
        )

    def action_replacements(
        self,
        targets: list[object],
        *,
        target: object | None,
    ) -> dict[str, str]:
        return action_replacements_impl(
            runtime=self.runtime,
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
        return action_env_impl(
            runtime=self.runtime,
            command_name=command_name,
            targets=targets,
            route=route,
            target=target,
            extra=extra,
        )

    def test_action_extra_env(
        self,
        *,
        route: Route | None,
        target: object | None,
        suite_source: str,
    ) -> dict[str, str]:
        return test_action_extra_env_impl(
            runtime=self.runtime,
            route=route,
            target=target,
            suite_source=suite_source,
            project_context_builder=self._migrate_project_context,
        )

    @staticmethod
    def action_extra_env(route: Route) -> dict[str, str]:
        return action_extra_env_impl(route)

    def migrate_action_env(
        self,
        *,
        targets: list[object],
        route: Route | None,
        target: object | None,
        extra: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        return migrate_action_env_impl(
            runtime=self.runtime,
            targets=targets,
            route=route,
            target=target,
            extra=extra,
            migrate_env_contracts=self._migrate_env_contracts,
            base_env_builder=self.action_env,
            backend_cwd=self._migrate_backend_cwd,
            requirements_for_target=self._migrate_requirements_for_target,
            project_context_builder=self._migrate_project_context,
            contract_context_builder=lambda project_name, target_root: _MigrateProjectContext(
                name=project_name,
                root=target_root,
                ports={},
            ),
            resolve_backend_env_contract=_resolve_backend_env_contract,
        )

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
        persist_project_action_result_impl(
            runtime=self.runtime,
            command_name=command_name,
            mode=mode,
            project_name=project_name,
            status=status,
            error_output=error_output,
            migrate_env_contracts=self._migrate_env_contracts,
            failure_summary_lines=self._project_action_failure_summary_lines,
            failure_headline=self._migrate_failure_headline,
            runtime_map_builder=build_runtime_map,
            extra_entry=extra_entry,
        )

    def _print_migrate_result_summary(
        self,
        *,
        mode: str,
        project_names: list[str],
        fallback_entries: Mapping[str, Mapping[str, object]] | None = None,
    ) -> None:
        print_migrate_result_summary_impl(
            runtime=self.runtime,
            mode=mode,
            project_names=project_names,
            fallback_entries=fallback_entries,
            failure_headline=ActionCommandOrchestrator._migrate_failure_headline,
        )

    def _migrate_result_records(
        self,
        *,
        mode: str,
        project_names: list[str],
        fallback_entries: Mapping[str, Mapping[str, object]] | None = None,
    ) -> list[_MigrateResultRecord]:
        return migrate_result_records_impl(
            runtime=self.runtime,
            mode=mode,
            project_names=project_names,
            fallback_entries=fallback_entries,
            failure_headline=ActionCommandOrchestrator._migrate_failure_headline,
        )

    @staticmethod
    def _migrate_result_record(
        *,
        project_name: str,
        action_entry: Mapping[str, object] | None,
    ) -> _MigrateResultRecord | None:
        return migrate_result_record_impl(
            project_name=project_name,
            action_entry=action_entry,
            failure_headline=ActionCommandOrchestrator._migrate_failure_headline,
        )

    @staticmethod
    def _print_migrate_result_records(
        *,
        records: list[_MigrateResultRecord],
        env: Mapping[str, str],
        interactive_tty: bool | None = None,
    ) -> None:
        print_migrate_result_records_impl(records=records, env=env, interactive_tty=interactive_tty)

    @staticmethod
    def _shared_migrate_hint_lines(records: list[_MigrateResultRecord]) -> tuple[str, ...]:
        return shared_migrate_hint_lines_impl(records)

    @staticmethod
    def _visible_migrate_hint_lines(hint_lines: tuple[str, ...]) -> tuple[str, ...]:
        return visible_migrate_hint_lines_impl(hint_lines)

    @staticmethod
    def _is_migrate_env_source_hint(hint_line: str) -> bool:
        return is_migrate_env_source_hint_impl(hint_line)

    @staticmethod
    def _print_migrate_failure_logs(
        records: list[_MigrateResultRecord],
        *,
        env: Mapping[str, str],
        interactive_tty: bool | None,
        compact: bool,
        use_color: bool,
        ordered_records: list[_MigrateResultRecord],
    ) -> None:
        print_migrate_failure_logs_impl(
            records,
            env=env,
            interactive_tty=interactive_tty,
            compact=compact,
            use_color=use_color,
            ordered_records=ordered_records,
        )

    @staticmethod
    def _print_compact_migrate_failure_logs(
        records: list[_MigrateResultRecord],
        *,
        env: Mapping[str, str],
        interactive_tty: bool | None,
        use_color: bool,
        ordered_records: list[_MigrateResultRecord],
    ) -> None:
        print_compact_migrate_failure_logs_impl(
            records,
            env=env,
            interactive_tty=interactive_tty,
            use_color=use_color,
            ordered_records=ordered_records,
        )

    @staticmethod
    def _shared_report_parent(records: list[_MigrateResultRecord]) -> str:
        return shared_report_parent_impl(records)

    @staticmethod
    def _record_index(records: list[_MigrateResultRecord], project_name: str) -> int:
        return record_index_impl(records, project_name)

    @staticmethod
    def _render_migrate_symbol(symbol: str, *, status: str, use_color: bool) -> str:
        return render_migrate_symbol_impl(symbol, status=status, use_color=use_color)

    @staticmethod
    def _render_migrate_project_name(project_name: str, *, index: int, use_color: bool) -> str:
        return render_migrate_project_name_impl(project_name, index=index, use_color=use_color)

    @staticmethod
    def _review_success_artifact_paths(*, stdout: object, stderr: object) -> dict[str, object]:
        return review_success_artifact_paths_impl(stdout=stdout, stderr=stderr)

    def _write_project_action_failure_report(
        self,
        *,
        run_id: str,
        project_name: str,
        command_name: str,
        output: str,
    ) -> Path:
        return write_project_action_failure_report_impl(
            self.runtime,
            run_id=run_id,
            project_name=project_name,
            command_name=command_name,
            output=output,
        )

    def _clear_dashboard_pr_cache(self) -> None:
        runtime_raw = self.runtime.raw_runtime
        cache = getattr(runtime_raw, "_dashboard_pr_url_cache", None)
        if isinstance(cache, dict):
            cache.clear()

    @staticmethod
    def _first_output_line(output: object) -> str:
        return first_output_line_impl(output)

    @classmethod
    def _project_action_success_status(cls, *, command_name: str, completed: Any) -> str:
        return project_action_success_status_impl(command_name=command_name, completed=completed)

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
        return write_failed_tests_summary_impl(
            run_dir=run_dir,
            project_name=project_name,
            project_root=project_root,
            outcomes=outcomes,
            previous_entry=previous_entry,
            short_failed_summary_path=ActionCommandOrchestrator._short_failed_summary_path,
            format_summary_error_lines=ActionCommandOrchestrator._format_summary_error_lines,
            git_state_components=ActionCommandOrchestrator._git_state_components,
        )

    def _collect_failed_tests(
        self,
        outcomes: list[dict[str, object]],
        *,
        project_name: str | None = None,
    ) -> list[tuple[str, str, str]]:
        return collect_failed_tests_impl(outcomes, project_name=project_name)

    def _collect_failed_test_manifest_entries(
        self,
        outcomes: list[dict[str, object]],
        *,
        project_name: str | None = None,
    ) -> list[dict[str, object]]:
        return collect_failed_test_manifest_entries_impl(outcomes, project_name=project_name)

    def _collect_generic_suite_failures(
        self,
        outcomes: list[dict[str, object]],
        *,
        project_name: str | None = None,
    ) -> list[tuple[str, str]]:
        return collect_generic_suite_failures_impl(outcomes, project_name=project_name)

    def _collect_suite_failure_contexts(
        self,
        outcomes: list[dict[str, object]],
        *,
        project_name: str | None = None,
    ) -> list[tuple[str, str]]:
        return collect_suite_failure_contexts_impl(outcomes, project_name=project_name)

    @staticmethod
    def _resolve_failed_test_error(error_details: dict[str, object], test_name: str) -> str:
        return resolve_failed_test_error_impl(error_details, test_name)

    @staticmethod
    def _git_state_components(project_root: Path) -> tuple[str, str, int]:
        return git_state_components_impl(project_root)

    @staticmethod
    def _suite_display_name(source: str, *, failed_only: bool = False) -> str:
        return suite_display_name_impl(source, failed_only=failed_only)

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
        return migrate_failure_hint_lines_impl(error_output)

    @staticmethod
    def _migrate_env_source_hint_lines(migrate_env_metadata: Mapping[str, object] | None) -> list[str]:
        return migrate_env_source_hint_lines_impl(migrate_env_metadata)

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
                    summary_env = dict(getattr(self.runtime, "env", {}))
                    hyperlink_mode = str(summary_env.get("ENVCTL_UI_HYPERLINK_MODE", "")).strip().lower()
                    if hyperlink_mode not in {"off", "false", "no", "0"}:
                        summary_env["ENVCTL_UI_HYPERLINK_MODE"] = "on"
                    rendered_path = render_path_for_terminal(
                        summary_path, env=summary_env, stream=sys.stdout
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
        repo_root = Path(rt.config.base_dir)  # type: ignore[attr-defined]
        run_repo_root_raw = str(getattr(rt, "env", {}).get("RUN_REPO_ROOT", "")).strip()  # type: ignore[attr-defined]
        if run_repo_root_raw:
            candidate = Path(run_repo_root_raw).expanduser()
            if candidate.exists():
                repo_root = candidate.resolve()
        return build_test_target_contexts(targets, repo_root=repo_root)
