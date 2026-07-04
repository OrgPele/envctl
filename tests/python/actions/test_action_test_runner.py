from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from envctl_engine.actions import action_test_runner
from envctl_engine.actions.action_test_runner import run_test_action
from envctl_engine.runtime.command_router import parse_route


class _Orchestrator:
    def __init__(self) -> None:
        self.runtime = SimpleNamespace(env={}, config=SimpleNamespace(base_dir=Path("/repo"), raw={}))
        self.statuses: list[str] = []
        self.overviews: list[object] = []
        self.ship_calls: list[tuple[object, list[object]]] = []
        self.ship_code = 0

    def _test_suite_spinner_policy_enabled(self) -> bool:
        return False

    def _persist_test_summary_artifacts(self, **_kwargs: object) -> dict[str, object]:
        return {}

    def _print_test_suite_overview(self, outcomes: object, *, summary_metadata: object) -> None:
        self.overviews.append((outcomes, summary_metadata))

    def _emit_status(self, message: str) -> None:
        self.statuses.append(message)

    def run_ship_action(self, route, targets: list[object]) -> int:  # noqa: ANN001
        self.ship_calls.append((route, targets))
        return self.ship_code


def _run(orchestrator: _Orchestrator, route, targets: list[object]) -> int:  # noqa: ANN001
    return run_test_action(
        orchestrator,
        route,
        targets,
        rich_progress_available=lambda: (False, ""),
        suite_spinner_group_cls=object,
        test_runner_cls=object,
        futures_module=SimpleNamespace(),
        resolve_spinner_policy=lambda _env: SimpleNamespace(),
    )


class ActionTestRunnerShipOnPassTests(unittest.TestCase):
    def test_ship_on_pass_rejects_blank_message_before_planning_tests(self) -> None:
        orchestrator = _Orchestrator()
        route = parse_route(["test", "--ship-on-pass="], env={})

        with patch.object(
            action_test_runner,
            "build_test_action_execution_plan",
            side_effect=AssertionError("test plan should not build"),
        ):
            code = _run(orchestrator, route, [SimpleNamespace(name="api", root=Path("/repo/trees/api/1"))])

        self.assertEqual(code, 1)

    def test_ship_on_pass_does_not_ship_when_tests_fail(self) -> None:
        orchestrator = _Orchestrator()
        route = parse_route(["test", "--ship-on-pass", "Ship focused fix"], env={})
        targets = [SimpleNamespace(name="api", root=Path("/repo/trees/api/1"))]
        suite_result = SimpleNamespace(
            failures=["boom"],
            outcomes=[{"index": 1, "returncode": 1, "project_name": "api", "suite": "backend", "failure_summary": "boom"}],
        )

        with (
            patch.object(
                action_test_runner,
                "build_test_action_execution_plan",
                return_value=SimpleNamespace(execution_specs=[object()], interactive_command=False),
            ),
            patch.object(action_test_runner, "resolve_suite_spinner_decision", return_value=SimpleNamespace(use_suite_spinner_group=False, reason="test")),
            patch.object(action_test_runner, "emit_suite_spinner_decision"),
            patch.object(action_test_runner, "emit_test_execution_mode"),
            patch.object(action_test_runner, "execute_test_suites", return_value=suite_result),
        ):
            code = _run(orchestrator, route, targets)

        self.assertEqual(code, 1)
        self.assertEqual(orchestrator.ship_calls, [])

    def test_ship_on_pass_ships_after_test_success(self) -> None:
        orchestrator = _Orchestrator()
        route = parse_route(["test", "--pr-base", "release", "--ship-on-pass", "Ship focused fix"], env={})
        targets = [SimpleNamespace(name="api", root=Path("/repo/trees/api/1"))]
        suite_result = SimpleNamespace(
            failures=[],
            outcomes=[{"index": 1, "returncode": 0, "project_name": "api", "suite": "backend"}],
        )

        with (
            patch.object(
                action_test_runner,
                "build_test_action_execution_plan",
                return_value=SimpleNamespace(execution_specs=[object()], interactive_command=False),
            ),
            patch.object(action_test_runner, "resolve_suite_spinner_decision", return_value=SimpleNamespace(use_suite_spinner_group=False, reason="test")),
            patch.object(action_test_runner, "emit_suite_spinner_decision"),
            patch.object(action_test_runner, "emit_test_execution_mode"),
            patch.object(action_test_runner, "execute_test_suites", return_value=suite_result),
        ):
            code = _run(orchestrator, route, targets)

        self.assertEqual(code, 0)
        self.assertEqual(len(orchestrator.ship_calls), 1)
        ship_route, ship_targets = orchestrator.ship_calls[0]
        self.assertEqual(ship_route.command, "ship")
        self.assertEqual(ship_route.projects, ["api"])
        self.assertEqual(ship_route.flags["commit_message"], "Ship focused fix")
        self.assertEqual(ship_route.flags["pr_base"], "release")
        self.assertNotIn("ship_on_pass", ship_route.flags)
        self.assertEqual(ship_targets, targets)

    def test_ship_on_pass_ships_only_targets_with_executed_successful_suites(self) -> None:
        orchestrator = _Orchestrator()
        route = parse_route(["test", "--all", "--ship-on-pass", "Ship focused fix"], env={})
        api = SimpleNamespace(name="api", root=Path("/repo/trees/api/1"))
        web = SimpleNamespace(name="web", root=Path("/repo/trees/web/1"))
        suite_result = SimpleNamespace(
            failures=[],
            outcomes=[{"index": 1, "returncode": 0, "project_name": "api", "suite": "backend"}],
        )

        with (
            patch.object(
                action_test_runner,
                "build_test_action_execution_plan",
                return_value=SimpleNamespace(execution_specs=[object()], interactive_command=False),
            ),
            patch.object(action_test_runner, "resolve_suite_spinner_decision", return_value=SimpleNamespace(use_suite_spinner_group=False, reason="test")),
            patch.object(action_test_runner, "emit_suite_spinner_decision"),
            patch.object(action_test_runner, "emit_test_execution_mode"),
            patch.object(action_test_runner, "execute_test_suites", return_value=suite_result),
        ):
            code = _run(orchestrator, route, [api, web])

        self.assertEqual(code, 0)
        ship_route, ship_targets = orchestrator.ship_calls[0]
        self.assertEqual(ship_route.projects, ["api"])
        self.assertEqual(ship_targets, [api])


if __name__ == "__main__":
    unittest.main()
