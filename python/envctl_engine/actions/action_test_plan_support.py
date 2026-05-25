from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, ClassVar, Mapping

from envctl_engine.actions.action_command_support import service_types_from_route_services
from envctl_engine.actions.action_failed_rerun_support import build_failed_test_execution_specs_from_state
from envctl_engine.actions.action_target_support import action_target_identities, action_target_names
from envctl_engine.actions.action_test_service_support import additional_service_test_execution_specs
from envctl_engine.actions.action_test_support import TestExecutionSpec, TestTargetContext, build_test_execution_specs
from envctl_engine.actions.action_test_support import is_backend_only_selection
from envctl_engine.actions.test_plan_action import run_test_plan_action
from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.parsing import parse_bool, parse_int


def run_test_plan_action_for_targets(orchestrator: object, route: Route, targets: list[object]) -> int:
    json_output = bool(route.flags.get("json"))
    dry_run = bool(route.flags.get("dry_run"))
    runtime = getattr(orchestrator, "runtime")
    for identity in action_target_identities(targets):
        context = type(
            "TestPlanActionContext",
            (),
            {
                "repo_root": runtime.config.base_dir,
                "project_root": identity.root.resolve(),
                "project_name": identity.name,
            },
        )()
        code = run_test_plan_action(context, json_output=json_output, dry_run=dry_run)
        if code != 0:
            return code
    return 0


def build_test_execution_specs_for_orchestrator(
    orchestrator: object,
    *,
    route: Route,
    targets: list[object],
    target_contexts: list[TestTargetContext],
    include_backend: bool,
    include_frontend: bool,
    run_all: bool,
    untested: bool,
) -> list[TestExecutionSpec]:
    runtime = getattr(orchestrator, "runtime")
    return build_test_execution_specs_for_route(
        route=route,
        targets=targets,
        target_contexts=target_contexts,
        include_backend=include_backend,
        include_frontend=include_frontend,
        run_all=run_all,
        untested=untested,
        env=runtime.env,
        config=runtime.config,
        action_replacements_builder=orchestrator.action_replacements,
        split_command=lambda command_raw, replacements: runtime.split_command(command_raw, replacements=replacements),
        failed_spec_builder=lambda **kwargs: build_failed_test_execution_specs_for_orchestrator(
            orchestrator,
            **kwargs,
        ),
        additional_service_spec_builder=lambda **kwargs: additional_service_test_execution_specs_for_orchestrator(
            orchestrator,
            **kwargs,
        ),
        is_legacy_tree_test_script=is_legacy_tree_test_script,
    )


def additional_service_test_execution_specs_for_orchestrator(
    orchestrator: object,
    *,
    route: Route,
    targets: list[object],
    target_contexts: list[TestTargetContext],
) -> list[TestExecutionSpec]:
    runtime = getattr(orchestrator, "runtime")
    return additional_service_test_execution_specs(
        route=route,
        targets=targets,
        target_contexts=target_contexts,
        config=runtime.config,
        split_command=lambda raw_command, replacements: runtime.split_command(
            raw_command,
            replacements=replacements,
        ),
        action_replacements_builder=orchestrator.action_replacements,
    )


def build_failed_test_execution_specs_for_orchestrator(
    orchestrator: object,
    *,
    route: Route,
    target_contexts: list[TestTargetContext],
) -> list[TestExecutionSpec]:
    runtime = getattr(orchestrator, "runtime")
    shared_raw = _first_non_empty(
        runtime.env.get("ENVCTL_ACTION_TEST_CMD"),
        runtime.config.raw.get("ENVCTL_ACTION_TEST_CMD", ""),
    )
    backend_raw = _first_non_empty(
        runtime.env.get("ENVCTL_BACKEND_TEST_CMD"),
        runtime.config.raw.get("ENVCTL_BACKEND_TEST_CMD", ""),
    )
    frontend_raw = _first_non_empty(
        runtime.env.get("ENVCTL_FRONTEND_TEST_CMD"),
        runtime.config.raw.get("ENVCTL_FRONTEND_TEST_CMD", ""),
    )
    state = runtime.load_existing_state(mode=route.mode)
    return build_failed_test_execution_specs_from_state(
        state=state,
        target_contexts=target_contexts,
        repo_root=runtime.config.base_dir,
        shared_raw_command=shared_raw,
        backend_raw_command=backend_raw,
        frontend_raw_command=frontend_raw,
        emit_status=orchestrator._emit_status,
    )


@dataclass(frozen=True, slots=True)
class TestExecutionPlanner:
    __test__: ClassVar[bool] = False

    route: Route
    targets: list[object]
    target_contexts: list[TestTargetContext]
    include_backend: bool
    include_frontend: bool
    run_all: bool
    untested: bool
    env: Mapping[str, str]
    config: object
    action_replacements_builder: Callable[..., dict[str, str]]
    split_command: Callable[[str, Mapping[str, str]], list[str]]
    failed_spec_builder: Callable[..., list[TestExecutionSpec]]
    additional_service_spec_builder: Callable[..., list[TestExecutionSpec]]
    is_legacy_tree_test_script: Callable[[list[str]], bool]

    def build(self) -> list[TestExecutionSpec]:
        if bool(self.route.flags.get("failed")):
            return self.failed_spec_builder(route=self.route, target_contexts=self.target_contexts)
        service_specs = self.additional_service_spec_builder(
            route=self.route,
            targets=self.targets,
            target_contexts=self.target_contexts,
        )
        if service_specs:
            return service_specs
        return build_test_execution_specs(
            shared_raw_command=self._configured_command("ENVCTL_ACTION_TEST_CMD"),
            backend_raw_command=self._configured_command("ENVCTL_BACKEND_TEST_CMD"),
            frontend_raw_command=self._configured_command("ENVCTL_FRONTEND_TEST_CMD"),
            target_contexts=self.target_contexts,
            repo_root=Path(getattr(self.config, "base_dir")),
            include_backend=self.include_backend,
            include_frontend=self.include_frontend,
            frontend_test_path=self._frontend_test_path(),
            run_all=self.run_all,
            untested=self.untested,
            split_command=lambda command_raw, replacements: self.split_command(command_raw, dict(replacements)),
            replacements_for_target=self._replacements_for_target,
            is_legacy_tree_test_script=self.is_legacy_tree_test_script,
        )

    def _configured_command(self, key: str) -> str | None:
        return _first_non_empty(
            self.env.get(key),
            getattr(self.config, "raw", {}).get(key, ""),
        )

    def _frontend_test_path(self) -> str | None:
        return _first_non_empty(
            getattr(self.config, "frontend_test_path", ""),
            self.env.get("ENVCTL_FRONTEND_TEST_PATH"),
            getattr(self.config, "raw", {}).get("ENVCTL_FRONTEND_TEST_PATH", ""),
        )

    def _replacements_for_target(self, target: object | None) -> dict[str, str]:
        return self.action_replacements_builder(self.targets, target=target)


def build_test_execution_specs_for_route(
    *,
    route: Route,
    targets: list[object],
    target_contexts: list[TestTargetContext],
    include_backend: bool,
    include_frontend: bool,
    run_all: bool,
    untested: bool,
    env: Mapping[str, str],
    config: object,
    action_replacements_builder: Callable[..., dict[str, str]],
    split_command: Callable[[str, Mapping[str, str]], list[str]],
    failed_spec_builder: Callable[..., list[TestExecutionSpec]],
    additional_service_spec_builder: Callable[..., list[TestExecutionSpec]],
    is_legacy_tree_test_script: Callable[[list[str]], bool],
) -> list[TestExecutionSpec]:
    return TestExecutionPlanner(
        route=route,
        targets=targets,
        target_contexts=target_contexts,
        include_backend=include_backend,
        include_frontend=include_frontend,
        run_all=run_all,
        untested=untested,
        env=env,
        config=config,
        action_replacements_builder=action_replacements_builder,
        split_command=split_command,
        failed_spec_builder=failed_spec_builder,
        additional_service_spec_builder=additional_service_spec_builder,
        is_legacy_tree_test_script=is_legacy_tree_test_script,
    ).build()


def _first_non_empty(*values: object) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def select_test_services(
    route: Route,
    backend_flag: object,
    frontend_flag: object,
) -> tuple[bool, bool]:
    return is_backend_only_selection(
        backend_flag,
        frontend_flag,
        service_types_from_route_services(route),
    )


def is_legacy_tree_test_script(command: list[str]) -> bool:
    return len(command) >= 2 and command[0] == "bash" and command[1].endswith("test-all-trees.sh")


def command_start_status(command_name: str, targets: list[object]) -> str:
    target_names = action_target_names(targets)
    if not target_names:
        return f"Running {command_name}..."
    if len(target_names) == 1:
        return f"Running {command_name} for {target_names[0]}..."
    return f"Running {command_name} for {len(target_names)} targets..."


def render_test_scope_status(project_names: list[str], *, run_all: bool, untested: bool, failed: bool) -> str:
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


def render_test_execution_status(command: list[str], *, args: list[str], source: str, cwd: Path) -> str:
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
    if is_legacy_tree_test_script(command):
        projects_arg = next((value for value in args if value.startswith("projects=")), "")
        if projects_arg:
            selected = projects_arg.split("=", 1)[1]
            count = len([name for name in selected.split(",") if name])
            return f"Running tree test matrix for {count} selected project(s)..."
        if "untested=true" in args:
            return "Running tree test matrix for untested projects..."
        return "Running tree test matrix for all projects..."
    return "Executing detected test command..."


def parallel_tests_enabled(
    route: Route,
    *,
    specs: list[TestExecutionSpec],
    env: Mapping[str, str],
    config_raw: Mapping[str, object],
) -> bool:
    if len(specs) <= 1:
        return False
    if any(is_legacy_tree_test_script(spec.spec.command) for spec in specs):
        return False
    forced = route.flags.get("test_parallel")
    if isinstance(forced, bool):
        return forced
    configured = env.get("ENVCTL_ACTION_TEST_PARALLEL") or config_raw.get("ENVCTL_ACTION_TEST_PARALLEL")
    return parse_bool(configured, True)


def parallel_test_worker_count(
    route: Route,
    *,
    specs: list[TestExecutionSpec],
    env: Mapping[str, str],
    config_raw: Mapping[str, object],
) -> int:
    total = max(len(specs), 1)
    configured_values: list[object] = [
        route.flags.get("test_parallel_max"),
        env.get("ENVCTL_ACTION_TEST_PARALLEL_MAX"),
        config_raw.get("ENVCTL_ACTION_TEST_PARALLEL_MAX"),
    ]
    limit = 4
    for raw in configured_values:
        parsed = parse_int(raw, 0)
        if parsed > 0:
            limit = parsed
            break
    return max(1, min(total, limit))


def suite_spinner_policy_enabled(policy: object, *, env: Mapping[str, str]) -> tuple[bool, str]:
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
    return True, "enabled"
