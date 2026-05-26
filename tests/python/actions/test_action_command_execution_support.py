from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
import unittest

from envctl_engine.actions.action_command_execution_support import execute_action_command


class _Spinner:
    def __init__(self) -> None:
        self.started = False
        self.successes: list[str] = []
        self.failures: list[str] = []

    def start(self) -> None:
        self.started = True

    def succeed(self, message: str) -> None:
        self.successes.append(message)

    def fail(self, message: str) -> None:
        self.failures.append(message)


class _Runtime:
    def __init__(self) -> None:
        self.env: dict[str, str] = {}
        self.raw_runtime = SimpleNamespace(_emit=lambda *_args, **_kwargs: None)
        self.events: list[dict[str, object]] = []

    def emit(self, event_name: str, **payload: object) -> None:
        self.events.append({"event": event_name, **payload})

    def unsupported_command(self, command: str) -> int:
        self.events.append({"event": "unsupported", "command": command})
        return 64


class _Orchestrator:
    def __init__(self) -> None:
        self.runtime = _Runtime()
        self._deferred_post_action_output = None
        self.statuses: list[str] = []
        self.restored = False
        self.spinner = _Spinner()

    def resolve_targets(self, _route, *, trees_only: bool) -> tuple[list[object], str | None]:
        return [SimpleNamespace(name="Main")], None

    def _command_start_status(self, command: str, targets: list[object]) -> str:
        return f"Running {command} for {len(targets)} targets..."

    def _emit_status(self, message: str) -> None:
        self.statuses.append(message)

    def _noop_restore(self) -> None:
        return None

    def _install_action_spinner_status_bridge(self, **_kwargs):
        def restore() -> None:
            self.restored = True

        return restore

    def run_test_action(self, _route, _targets: list[object]) -> int:
        return 0


class _DeferredOutputOrchestrator(_Orchestrator):
    def __init__(self) -> None:
        super().__init__()
        self.deferred_output_calls = 0

    def run_test_action(self, _route, _targets: list[object]) -> int:
        self._deferred_post_action_output = self._deferred_output
        return 0

    def _deferred_output(self) -> None:
        self.deferred_output_calls += 1


@contextmanager
def _policy_context(_policy):
    yield


class ActionCommandExecutionSupportTests(unittest.TestCase):
    def test_execute_action_command_emits_lifecycle_and_finish_events(self) -> None:
        orchestrator = _Orchestrator()
        route = SimpleNamespace(command="test", mode="main", flags={})
        policy = SimpleNamespace(enabled=True)

        @contextmanager
        def spinner_factory(_message: str, *, enabled: bool, start_immediately: bool):
            self.assertTrue(enabled)
            self.assertFalse(start_immediately)
            yield orchestrator.spinner

        code = execute_action_command(
            orchestrator,
            route,
            spinner_factory=spinner_factory,
            resolve_spinner_policy_fn=lambda _env: policy,
            emit_spinner_policy_fn=lambda emit, policy, context: orchestrator.runtime.emit(
                "policy", policy=policy, context=context
            ),
            use_spinner_policy_fn=_policy_context,
        )

        self.assertEqual(code, 0)
        self.assertEqual(orchestrator.statuses, ["Running test for 1 targets..."])
        self.assertTrue(orchestrator.spinner.started)
        self.assertEqual(orchestrator.spinner.successes, ["test completed"])
        self.assertTrue(orchestrator.restored)
        self.assertIn({"event": "action.command.finish", "command": "test", "code": 0}, orchestrator.runtime.events)
        self.assertIsNone(orchestrator._deferred_post_action_output)

    def test_execute_action_command_returns_target_resolution_error(self) -> None:
        orchestrator = _Orchestrator()
        orchestrator.resolve_targets = lambda _route, trees_only: ([], "No targets")  # type: ignore[assignment]
        route = SimpleNamespace(command="test", mode="main", flags={})

        code = execute_action_command(
            orchestrator,
            route,
            spinner_factory=lambda *_args, **_kwargs: None,
            resolve_spinner_policy_fn=lambda _env: SimpleNamespace(enabled=False),
            emit_spinner_policy_fn=lambda *_args, **_kwargs: None,
            use_spinner_policy_fn=_policy_context,
        )

        self.assertEqual(code, 1)
        self.assertIn(
            {"event": "action.command.finish", "command": "test", "code": 1, "error": "No targets"},
            orchestrator.runtime.events,
        )

    def test_execute_action_command_flushes_deferred_output_before_finish(self) -> None:
        orchestrator = _DeferredOutputOrchestrator()
        route = SimpleNamespace(command="test", mode="main", flags={})

        code = execute_action_command(
            orchestrator,
            route,
            spinner_factory=lambda *_args, **_kwargs: _policy_context(orchestrator.spinner),
            resolve_spinner_policy_fn=lambda _env: SimpleNamespace(enabled=False),
            emit_spinner_policy_fn=lambda *_args, **_kwargs: None,
            use_spinner_policy_fn=_policy_context,
        )

        self.assertEqual(code, 0)
        self.assertEqual(orchestrator.deferred_output_calls, 1)
        self.assertIsNone(orchestrator._deferred_post_action_output)
        self.assertEqual(orchestrator.runtime.events[-1], {"event": "action.command.finish", "command": "test", "code": 0})

    def test_execute_action_command_suppresses_finish_event_for_json_commands(self) -> None:
        orchestrator = _Orchestrator()
        route = SimpleNamespace(command="test", mode="main", flags={"json": True})

        code = execute_action_command(
            orchestrator,
            route,
            spinner_factory=lambda *_args, **_kwargs: _policy_context(orchestrator.spinner),
            resolve_spinner_policy_fn=lambda _env: SimpleNamespace(enabled=True),
            emit_spinner_policy_fn=lambda *_args, **_kwargs: None,
            use_spinner_policy_fn=_policy_context,
        )

        self.assertEqual(code, 0)
        self.assertNotIn(
            {"event": "action.command.finish", "command": "test", "code": 0},
            orchestrator.runtime.events,
        )
        self.assertIn(
            {
                "event": "ui.spinner.disabled",
                "component": "action.command",
                "command": "test",
                "op_id": "action.test",
                "reason": "interactive_command_spinner_suppressed",
            },
            orchestrator.runtime.events,
        )


if __name__ == "__main__":
    unittest.main()
