from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.actions.action_command_orchestrator import ActionCommandOrchestrator
from envctl_engine.runtime.command_router import Route
from envctl_engine.ui.spinner_service import SpinnerPolicy


class _RuntimeStub:
    def __init__(self) -> None:
        self.env: dict[str, str] = {}
        self.config = SimpleNamespace(base_dir=Path("/tmp"), raw={})
        self.events: list[dict[str, object]] = []

    def _emit(self, event: str, **payload: object) -> None:
        entry = {"event": event}
        entry.update(payload)
        self.events.append(entry)

    def _discover_projects(self, *, mode: str):  # noqa: ANN001
        _ = mode
        return [SimpleNamespace(name="Main", root=Path("/tmp/main"))]

    @staticmethod
    def _selectors_from_passthrough(_args):  # noqa: ANN001
        return set()

    def _try_load_existing_state(self, *args, **kwargs):  # noqa: ANN001, ARG002
        return None

    @staticmethod
    def _project_name_from_service(_name: str) -> str:
        return ""

    @staticmethod
    def _unsupported_command(_command: str) -> int:
        return 1


class ActionSpinnerIntegrationTests(unittest.TestCase):
    def test_action_execute_emits_spinner_policy_and_success_lifecycle(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = ActionCommandOrchestrator(runtime)
        route = Route(command="test", mode="main", flags={"all": True})
        spinner_calls: list[tuple[str, bool]] = []

        @contextmanager
        def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
            _ = start_immediately
            spinner_calls.append((message, enabled))

            class _SpinnerStub:
                def start(self) -> None:
                    return None

                def update(self, _message: str) -> None:
                    return None

                def succeed(self, _message: str) -> None:
                    return None

                def fail(self, _message: str) -> None:
                    return None

            yield _SpinnerStub()

        with (
            patch.object(orchestrator, "resolve_targets", return_value=([SimpleNamespace(name="Main")], None)),
            patch.object(orchestrator, "run_test_action", return_value=0),
            patch("envctl_engine.actions.action_command_orchestrator.spinner", side_effect=fake_spinner),
            patch(
                "envctl_engine.actions.action_command_orchestrator.resolve_spinner_policy",
                return_value=SpinnerPolicy(
                    mode="auto",
                    enabled=True,
                    reason="",
                    backend="rich",
                    min_ms=0,
                    verbose_events=False,
                ),
            ),
        ):
            code = orchestrator.execute(route)

        self.assertEqual(code, 0)
        self.assertEqual(spinner_calls, [("Running test for Main...", True)])
        self.assertTrue(any(item.get("event") == "ui.spinner.policy" for item in runtime.events))
        lifecycle = [item for item in runtime.events if item.get("event") == "ui.spinner.lifecycle"]
        self.assertTrue(any(item.get("state") == "start" for item in lifecycle))
        self.assertTrue(any(item.get("state") == "success" for item in lifecycle))
        self.assertTrue(any(item.get("state") == "stop" for item in lifecycle))

    def test_action_execute_emits_spinner_fail_lifecycle_on_failure(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = ActionCommandOrchestrator(runtime)
        route = Route(command="test", mode="main", flags={"all": True})

        @contextmanager
        def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
            _ = message, enabled, start_immediately

            class _SpinnerStub:
                def start(self) -> None:
                    return None

                def update(self, _message: str) -> None:
                    return None

                def succeed(self, _message: str) -> None:
                    return None

                def fail(self, _message: str) -> None:
                    return None

            yield _SpinnerStub()

        with (
            patch.object(orchestrator, "resolve_targets", return_value=([SimpleNamespace(name="Main")], None)),
            patch.object(orchestrator, "run_test_action", return_value=1),
            patch("envctl_engine.actions.action_command_orchestrator.spinner", side_effect=fake_spinner),
            patch(
                "envctl_engine.actions.action_command_orchestrator.resolve_spinner_policy",
                return_value=SpinnerPolicy(
                    mode="auto",
                    enabled=True,
                    reason="",
                    backend="rich",
                    min_ms=0,
                    verbose_events=False,
                ),
            ),
        ):
            code = orchestrator.execute(route)

        self.assertEqual(code, 1)
        lifecycle = [item for item in runtime.events if item.get("event") == "ui.spinner.lifecycle"]
        self.assertTrue(any(item.get("state") == "fail" for item in lifecycle))

    def test_action_execute_updates_spinner_from_later_status_events(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = ActionCommandOrchestrator(runtime)
        route = Route(command="migrate", mode="main", flags={"all": True})
        spinner_calls: list[tuple[str, str, bool] | tuple[str, str]] = []

        class _SpinnerStub:
            def start(self) -> None:
                spinner_calls.append(("spin-start", ""))

            def update(self, message: str) -> None:
                spinner_calls.append(("update", message))

            def succeed(self, message: str) -> None:
                spinner_calls.append(("succeed", message))

            def fail(self, message: str) -> None:
                spinner_calls.append(("fail", message))

        @contextmanager
        def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
            _ = start_immediately
            spinner_calls.append(("start", message, enabled))
            yield _SpinnerStub()

        def fake_run(_route: Route, _targets: list[object]) -> int:
            orchestrator._emit_status("Running migrate for Main (1/1)...")
            orchestrator._emit_status("migrate succeeded for Main")
            return 0

        with (
            patch.object(orchestrator, "resolve_targets", return_value=([SimpleNamespace(name="Main")], None)),
            patch.object(orchestrator, "run_migrate_action", side_effect=fake_run),
            patch("envctl_engine.actions.action_command_orchestrator.spinner", side_effect=fake_spinner),
            patch(
                "envctl_engine.actions.action_command_orchestrator.resolve_spinner_policy",
                return_value=SpinnerPolicy(
                    mode="auto",
                    enabled=True,
                    reason="",
                    backend="rich",
                    min_ms=0,
                    verbose_events=False,
                ),
            ),
        ):
            code = orchestrator.execute(route)

        self.assertEqual(code, 0)
        self.assertIn(("start", "Running migrate for Main...", True), spinner_calls)
        self.assertIn(("spin-start", ""), spinner_calls)
        self.assertIn(("update", "Running migrate for Main (1/1)..."), spinner_calls)
        self.assertIn(("update", "migrate succeeded for Main"), spinner_calls)
        self.assertIn(("succeed", "migrate completed"), spinner_calls)

    def test_action_execute_suppresses_nested_spinner_for_interactive_commands(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = ActionCommandOrchestrator(runtime)
        route = Route(command="commit", mode="main", flags={"all": True, "interactive_command": True})
        spinner_calls: list[tuple[str, bool]] = []

        @contextmanager
        def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
            _ = start_immediately
            spinner_calls.append((message, enabled))

            class _SpinnerStub:
                def start(self) -> None:
                    return None

                def update(self, _message: str) -> None:
                    return None

                def succeed(self, _message: str) -> None:
                    return None

                def fail(self, _message: str) -> None:
                    return None

            yield _SpinnerStub()

        with (
            patch.object(orchestrator, "resolve_targets", return_value=([SimpleNamespace(name="Main")], None)),
            patch.object(orchestrator, "run_commit_action", return_value=0),
            patch("envctl_engine.actions.action_command_orchestrator.spinner", side_effect=fake_spinner),
            patch(
                "envctl_engine.actions.action_command_orchestrator.resolve_spinner_policy",
                return_value=SpinnerPolicy(
                    mode="auto",
                    enabled=True,
                    reason="",
                    backend="rich",
                    min_ms=0,
                    verbose_events=False,
                ),
            ),
        ):
            code = orchestrator.execute(route)

        self.assertEqual(code, 0)
        self.assertEqual(spinner_calls, [("Running commit for Main...", False)])
        self.assertTrue(
            any(
                item.get("event") == "ui.spinner.disabled"
                and item.get("reason") == "interactive_command_spinner_suppressed"
                for item in runtime.events
            )
        )

    def test_action_execute_disables_migrate_spinner_for_interactive_commands(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = ActionCommandOrchestrator(runtime)
        route = Route(command="migrate", mode="main", flags={"all": True, "interactive_command": True})
        spinner_calls: list[tuple[str, bool]] = []

        @contextmanager
        def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
            _ = start_immediately
            spinner_calls.append((message, enabled))

            class _SpinnerStub:
                def start(self) -> None:
                    return None

                def update(self, _message: str) -> None:
                    return None

                def succeed(self, _message: str) -> None:
                    return None

                def fail(self, _message: str) -> None:
                    return None

            yield _SpinnerStub()

        with (
            patch.object(orchestrator, "resolve_targets", return_value=([SimpleNamespace(name="Main")], None)),
            patch.object(orchestrator, "run_migrate_action", return_value=0),
            patch("envctl_engine.actions.action_command_orchestrator.spinner", side_effect=fake_spinner),
            patch(
                "envctl_engine.actions.action_command_orchestrator.resolve_spinner_policy",
                return_value=SpinnerPolicy(
                    mode="auto",
                    enabled=True,
                    reason="",
                    backend="rich",
                    min_ms=0,
                    verbose_events=False,
                ),
            ),
        ):
            code = orchestrator.execute(route)

        self.assertEqual(code, 0)
        self.assertEqual(spinner_calls, [("Running migrate for Main...", False)])


if __name__ == "__main__":
    unittest.main()
