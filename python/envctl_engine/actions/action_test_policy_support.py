from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Mapping

from envctl_engine.actions.action_test_command_support import is_legacy_tree_test_script
from envctl_engine.actions.action_test_support_models import TestExecutionSpec
from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.parsing import parse_bool, parse_int


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


__all__ = [
    "TestExecutionPolicy",
    "parallel_test_worker_count",
    "parallel_tests_enabled",
    "suite_spinner_policy_enabled",
]
