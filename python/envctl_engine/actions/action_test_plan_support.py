from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, ClassVar, Mapping, cast

from envctl_engine.actions.action_command_support import service_types_from_route_services
from envctl_engine.actions.action_failed_rerun_support import build_failed_test_execution_specs_from_state
from envctl_engine.actions.action_target_support import action_target_identities, action_target_names
from envctl_engine.actions.action_test_service_support import additional_service_test_execution_specs
from envctl_engine.actions.action_test_support import TestExecutionSpec, TestTargetContext, build_test_execution_specs
from envctl_engine.actions.action_test_support import is_backend_only_selection
from envctl_engine.actions.test_plan_action import run_test_plan_action
from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.parsing import parse_bool, parse_int


@dataclass(frozen=True, slots=True)
class RuntimeSplitCommandAdapter:
    runtime: Any

    def __call__(self, command_raw: str, replacements: Mapping[str, str]) -> list[str]:
        return self.runtime.split_command(command_raw, replacements=replacements)


@dataclass(frozen=True, slots=True)
class OrchestratorTestPlanDependencies:
    orchestrator: object

    @property
    def runtime(self) -> Any:
        return getattr(self.orchestrator, "runtime")

    @property
    def split_command(self) -> RuntimeSplitCommandAdapter:
        return RuntimeSplitCommandAdapter(self.runtime)

    def action_replacements(self, *args: object, **kwargs: object) -> dict[str, str]:
        builder = cast(Callable[..., dict[str, str]], getattr(self.orchestrator, "action_replacements"))
        return builder(*args, **kwargs)

    def failed_specs(self, *, route: Route, target_contexts: list[TestTargetContext]) -> list[TestExecutionSpec]:
        return build_failed_test_execution_specs_for_orchestrator(
            self.orchestrator,
            route=route,
            target_contexts=target_contexts,
        )

    def additional_service_specs(
        self,
        *,
        route: Route,
        targets: list[object],
        target_contexts: list[TestTargetContext],
    ) -> list[TestExecutionSpec]:
        return additional_service_test_execution_specs_for_orchestrator(
            self.orchestrator,
            route=route,
            targets=targets,
            target_contexts=target_contexts,
        )


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
    dependencies = OrchestratorTestPlanDependencies(orchestrator)
    runtime = dependencies.runtime
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
        action_replacements_builder=dependencies.action_replacements,
        split_command=dependencies.split_command,
        failed_spec_builder=dependencies.failed_specs,
        additional_service_spec_builder=dependencies.additional_service_specs,
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
    split_command = RuntimeSplitCommandAdapter(runtime)
    return additional_service_test_execution_specs(
        route=route,
        targets=targets,
        target_contexts=target_contexts,
        config=runtime.config,
        split_command=split_command,
        action_replacements_builder=cast(Callable[..., dict[str, str]], getattr(orchestrator, "action_replacements")),
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
        emit_status=cast(Callable[[str], None], getattr(orchestrator, "_emit_status")),
    )


@dataclass(frozen=True, slots=True)
class TestExecutionPlanRequest:
    route: Route
    targets: list[object]
    target_contexts: list[TestTargetContext]
    include_backend: bool
    include_frontend: bool
    run_all: bool
    untested: bool


@dataclass(frozen=True, slots=True)
class TestExecutionPlanConfiguration:
    env: Mapping[str, str]
    config: object


@dataclass(frozen=True, slots=True)
class TestExecutionPlanDependencies:
    action_replacements_builder: Callable[..., dict[str, str]]
    split_command: Callable[[str, Mapping[str, str]], list[str]]
    failed_spec_builder: Callable[..., list[TestExecutionSpec]]
    additional_service_spec_builder: Callable[..., list[TestExecutionSpec]]
    is_legacy_tree_test_script: Callable[[list[str]], bool]


@dataclass(frozen=True, slots=True)
class TestExecutionPlanner:
    __test__: ClassVar[bool] = False

    request: TestExecutionPlanRequest
    configuration: TestExecutionPlanConfiguration
    dependencies: TestExecutionPlanDependencies

    def build(self) -> list[TestExecutionSpec]:
        if bool(self.request.route.flags.get("failed")):
            return self.dependencies.failed_spec_builder(
                route=self.request.route,
                target_contexts=self.request.target_contexts,
            )
        service_specs = self.dependencies.additional_service_spec_builder(
            route=self.request.route,
            targets=self.request.targets,
            target_contexts=self.request.target_contexts,
        )
        if service_specs:
            return service_specs
        return build_test_execution_specs(
            shared_raw_command=self._configured_command("ENVCTL_ACTION_TEST_CMD"),
            backend_raw_command=self._configured_command("ENVCTL_BACKEND_TEST_CMD"),
            frontend_raw_command=self._configured_command("ENVCTL_FRONTEND_TEST_CMD"),
            target_contexts=self.request.target_contexts,
            repo_root=Path(getattr(self.configuration.config, "base_dir")),
            include_backend=self.request.include_backend,
            include_frontend=self.request.include_frontend,
            frontend_test_path=self._frontend_test_path(),
            run_all=self.request.run_all,
            untested=self.request.untested,
            split_command=self._split_command_for_test_support,
            replacements_for_target=self._replacements_for_target,
            is_legacy_tree_test_script=self.dependencies.is_legacy_tree_test_script,
        )

    def _configured_command(self, key: str) -> str | None:
        return _first_non_empty(
            self.configuration.env.get(key),
            getattr(self.configuration.config, "raw", {}).get(key, ""),
        )

    def _frontend_test_path(self) -> str | None:
        return _first_non_empty(
            getattr(self.configuration.config, "frontend_test_path", ""),
            self.configuration.env.get("ENVCTL_FRONTEND_TEST_PATH"),
            getattr(self.configuration.config, "raw", {}).get("ENVCTL_FRONTEND_TEST_PATH", ""),
        )

    def _replacements_for_target(self, target: object | None) -> dict[str, str]:
        return self.dependencies.action_replacements_builder(self.request.targets, target=target)

    def _split_command_for_test_support(self, command_raw: str, replacements: Mapping[str, str]) -> list[str]:
        return self.dependencies.split_command(command_raw, dict(replacements))


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
        request=TestExecutionPlanRequest(
            route=route,
            targets=targets,
            target_contexts=target_contexts,
            include_backend=include_backend,
            include_frontend=include_frontend,
            run_all=run_all,
            untested=untested,
        ),
        configuration=TestExecutionPlanConfiguration(env=env, config=config),
        dependencies=TestExecutionPlanDependencies(
            action_replacements_builder=action_replacements_builder,
            split_command=split_command,
            failed_spec_builder=failed_spec_builder,
            additional_service_spec_builder=additional_service_spec_builder,
            is_legacy_tree_test_script=is_legacy_tree_test_script,
        ),
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


@dataclass(frozen=True, slots=True)
class TestStatusRenderer:
    __test__: ClassVar[bool] = False

    def command_start_status(self, command_name: str, targets: list[object]) -> str:
        target_names = action_target_names(targets)
        if not target_names:
            return f"Running {command_name}..."
        if len(target_names) == 1:
            return f"Running {command_name} for {target_names[0]}..."
        return f"Running {command_name} for {len(target_names)} targets..."

    def scope_status(self, project_names: list[str], *, run_all: bool, untested: bool, failed: bool) -> str:
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

    def execution_status(self, command: list[str], *, args: list[str], source: str, cwd: Path) -> str:
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


@dataclass(frozen=True, slots=True)
class TestExecutionPolicy:
    __test__: ClassVar[bool] = False

    route: Route
    specs: list[TestExecutionSpec]
    env: Mapping[str, str]
    config_raw: Mapping[str, object]

    def parallel_enabled(self) -> bool:
        if len(self.specs) <= 1:
            return False
        if any(is_legacy_tree_test_script(spec.spec.command) for spec in self.specs):
            return False
        forced = self.route.flags.get("test_parallel")
        if isinstance(forced, bool):
            return forced
        configured = self.env.get("ENVCTL_ACTION_TEST_PARALLEL") or self.config_raw.get(
            "ENVCTL_ACTION_TEST_PARALLEL"
        )
        return parse_bool(configured, True)

    def parallel_worker_count(self) -> int:
        total = max(len(self.specs), 1)
        configured_values: list[object] = [
            self.route.flags.get("test_parallel_max"),
            self.env.get("ENVCTL_ACTION_TEST_PARALLEL_MAX"),
            self.config_raw.get("ENVCTL_ACTION_TEST_PARALLEL_MAX"),
        ]
        limit = 4
        for raw in configured_values:
            parsed = parse_int(raw, 0)
            if parsed > 0:
                limit = parsed
                break
        return max(1, min(total, limit))

    def suite_spinner_policy_enabled(self, policy: object) -> tuple[bool, str]:
        mode = str(self.env.get("ENVCTL_UI_SPINNER_MODE", "")).strip().lower()
        if mode == "off":
            return False, "spinner_mode_off"
        if not parse_bool(self.env.get("ENVCTL_UI_SPINNER"), True):
            return False, "spinner_env_off"
        if not parse_bool(self.env.get("ENVCTL_UI_RICH"), True):
            return False, "rich_env_off"
        reason = str(getattr(policy, "reason", "")).strip().lower()
        if reason == "spinner_backend_missing":
            return False, "spinner_backend_missing"
        if reason == "ci_mode":
            return False, "ci_mode"
        return True, "enabled"


def command_start_status(command_name: str, targets: list[object]) -> str:
    return TestStatusRenderer().command_start_status(command_name, targets)


def render_test_scope_status(project_names: list[str], *, run_all: bool, untested: bool, failed: bool) -> str:
    return TestStatusRenderer().scope_status(project_names, run_all=run_all, untested=untested, failed=failed)


def render_test_execution_status(command: list[str], *, args: list[str], source: str, cwd: Path) -> str:
    return TestStatusRenderer().execution_status(command, args=args, source=source, cwd=cwd)


def parallel_tests_enabled(
    route: Route,
    *,
    specs: list[TestExecutionSpec],
    env: Mapping[str, str],
    config_raw: Mapping[str, object],
) -> bool:
    return TestExecutionPolicy(route=route, specs=specs, env=env, config_raw=config_raw).parallel_enabled()


def parallel_test_worker_count(
    route: Route,
    *,
    specs: list[TestExecutionSpec],
    env: Mapping[str, str],
    config_raw: Mapping[str, object],
) -> int:
    return TestExecutionPolicy(route=route, specs=specs, env=env, config_raw=config_raw).parallel_worker_count()


def suite_spinner_policy_enabled(policy: object, *, env: Mapping[str, str]) -> tuple[bool, str]:
    execution_policy = TestExecutionPolicy(route=Route(command="", mode="main"), specs=[], env=env, config_raw={})
    return execution_policy.suite_spinner_policy_enabled(policy)
