from __future__ import annotations

import unittest

from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.execution_preparation import prepare_startup_execution
from envctl_engine.startup.session import StartupSession


class StartupExecutionPreparationTests(unittest.TestCase):
    def test_prepare_startup_execution_prewarms_docker_and_emits_phase(self) -> None:
        route = Route(command="start", mode="main", raw_args=[], passthrough_args=[], projects=[], flags={})
        session = StartupSession(
            requested_route=route,
            effective_route=route,
            requested_command="start",
            runtime_mode="main",
            run_id="run-1",
        )
        prewarm_calls: list[tuple[Route, str]] = []
        phases: list[tuple[str, dict[str, object]]] = []

        prepare_startup_execution(
            session=session,
            maybe_prewarm_docker=lambda *, route, mode: prewarm_calls.append((route, mode)),
            emit_phase=lambda session, phase, started_at, **extra: phases.append((phase, dict(extra))),
        )

        self.assertEqual(prewarm_calls, [(route, "main")])
        self.assertEqual(phases, [("docker_prewarm", {"status": "ok"})])


if __name__ == "__main__":
    unittest.main()
