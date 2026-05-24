from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from envctl_engine.actions.action_test_execution_support import (
    build_test_action_execution_plan,
    emit_test_execution_mode,
    resolve_suite_spinner_decision,
)
from envctl_engine.actions.action_test_support_models import TestExecutionSpec as ExecutionSpec
from envctl_engine.actions.action_test_support_models import TestTargetContext as TargetContext
from envctl_engine.actions.actions_test import TestCommandSpec as CommandSpec
from envctl_engine.runtime.command_router import parse_route


class _Runtime:
    def __init__(self) -> None:
        self.env: dict[str, str] = {}
        self.events: list[tuple[str, dict[str, object]]] = []

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append((event, payload))


class _PlanOrchestrator:
    def __init__(self) -> None:
        self.runtime = _Runtime()
        self.statuses: list[str] = []
        self.target_contexts = [
            TargetContext("api", Path("/repo/api"), object()),
            TargetContext("api-copy", Path("/repo/api"), object()),
        ]
        self.execution_specs = [
            ExecutionSpec(
                index=1,
                spec=CommandSpec(
                    command=["python", "-m", "pytest"],
                    cwd=Path("/repo/api"),
                    source="backend_pytest",
                ),
                args=[],
                resolved_source="backend_pytest",
                project_name="api",
                project_root=Path("/repo/api"),
            ),
            ExecutionSpec(
                index=2,
                spec=CommandSpec(
                    command=["npm", "run", "test"],
                    cwd=Path("/repo/web"),
                    source="frontend_package_test",
                ),
                args=[],
                resolved_source="frontend_package_test",
                project_name="web",
                project_root=Path("/repo/web"),
            ),
        ]

    def _emit_status(self, message: str) -> None:
        self.statuses.append(message)

    @staticmethod
    def _test_scope_status(project_names: list[str], *, run_all: bool, untested: bool, failed: bool) -> str:
        return f"scope:{project_names}:{run_all}:{untested}:{failed}"

    @staticmethod
    def _test_service_selection(route, backend_flag, frontend_flag):  # noqa: ANN001, ANN202
        return bool(backend_flag is not False), bool(frontend_flag is not False)

    def _test_target_contexts(self, _targets):  # noqa: ANN001, ANN202
        return self.target_contexts

    def _build_test_execution_specs(self, **_kwargs):  # noqa: ANN202
        return self.execution_specs

    @staticmethod
    def _test_parallel_enabled(_route, _execution_specs) -> bool:  # noqa: ANN001
        return True

    @staticmethod
    def _test_parallel_max_workers(_route, _execution_specs) -> int:  # noqa: ANN001
        return 2


class ActionTestExecutionSupportTests(unittest.TestCase):
    def test_build_test_action_execution_plan_dedupes_prereqs_and_emits_suite_plan(self) -> None:
        orchestrator = _PlanOrchestrator()
        route = parse_route(["test", "--failed", "--backend"], env={})
        targets = [SimpleNamespace(name="api"), SimpleNamespace(name="web")]
        prereq_roots: list[Path] = []

        with patch(
            "envctl_engine.actions.action_test_execution_support.ensure_repo_local_test_prereqs",
            side_effect=lambda root, emit_status: prereq_roots.append(Path(root)),
        ):
            plan = build_test_action_execution_plan(orchestrator, route, targets)

        self.assertTrue(plan.failed_only)
        self.assertTrue(plan.parallel)
        self.assertEqual(plan.parallel_workers, 2)
        self.assertEqual(plan.distinct_projects, {"api", "web"})
        self.assertEqual(prereq_roots, [Path("/repo/api")])
        self.assertEqual(orchestrator.statuses, ["scope:['api', 'web']:False:False:True"])
        self.assertEqual(
            orchestrator.runtime.events,
            [
                (
                    "test.suite.plan",
                    {
                        "suites": ["backend_pytest", "frontend_package_test"],
                        "total": 2,
                        "parallel": True,
                        "projects": ["api", "web"],
                    },
                )
            ],
        )

    def test_suite_spinner_decision_reports_exact_disable_reason(self) -> None:
        decision = resolve_suite_spinner_decision(
            interactive_command=True,
            spinner_policy=SimpleNamespace(backend="rich"),
            rich_progress_available_fn=lambda: (False, "missing"),
            suite_policy_enabled_fn=lambda _policy: (True, "enabled"),
        )

        self.assertFalse(decision.use_suite_spinner_group)
        self.assertEqual(decision.reason, "rich_progress_unavailable")
        self.assertEqual(decision.rich_progress_error, "missing")

        decision = resolve_suite_spinner_decision(
            interactive_command=True,
            spinner_policy=SimpleNamespace(backend="plain"),
            rich_progress_available_fn=lambda: (True, ""),
            suite_policy_enabled_fn=lambda _policy: (False, "spinner_backend_missing"),
        )
        self.assertFalse(decision.use_suite_spinner_group)
        self.assertEqual(decision.reason, "suite_spinner_policy_disabled:spinner_backend_missing")

    def test_emit_test_execution_mode_uses_plan_summary(self) -> None:
        runtime = _Runtime()
        plan = _PlanOrchestrator()
        with patch("envctl_engine.actions.action_test_execution_support.ensure_repo_local_test_prereqs"):
            execution_plan = build_test_action_execution_plan(plan, parse_route(["test"], env={}), [])

        emit_test_execution_mode(runtime, execution_plan, suite_spinner_group=True)

        self.assertEqual(runtime.events[-1][0], "test.execution.mode")
        self.assertEqual(runtime.events[-1][1]["mode"], "parallel")
        self.assertEqual(runtime.events[-1][1]["total"], 2)
        self.assertEqual(runtime.events[-1][1]["projects"], 2)
        self.assertTrue(runtime.events[-1][1]["suite_spinner_group"])


if __name__ == "__main__":
    unittest.main()
