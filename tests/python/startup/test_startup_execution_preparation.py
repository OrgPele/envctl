from __future__ import annotations

import unittest

from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.execution_preparation import prepare_startup_execution, prepare_startup_execution_with_runtime
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

    def test_runtime_bound_prepare_startup_execution_uses_runtime_owner_dependencies(self) -> None:
        route = Route(command="start", mode="main", raw_args=[], passthrough_args=[], projects=[], flags={})
        session = StartupSession(
            requested_route=route,
            effective_route=route,
            requested_command="start",
            runtime_mode="main",
            run_id="run-1",
        )
        events: list[tuple[str, dict[str, object]]] = []
        docker_commands: list[tuple[list[str], float]] = []
        runtime = type(
            "RuntimeStub",
            (),
            {
                "env": {"ENVCTL_DOCKER_PREWARM": "1"},
                "config": type("ConfigStub", (), {"raw": {}})(),
                "_requirement_enabled": lambda self, requirement_id, *, mode, route: requirement_id == "postgres",
                "_command_exists": lambda self, command: command == "docker",
                "process_runner": type(
                    "RunnerStub",
                    (),
                    {
                        "run": lambda self, command, timeout: docker_commands.append((list(command), float(timeout)))
                        or type("ResultStub", (), {"returncode": 0, "stderr": "", "stdout": ""})(),
                    },
                )(),
                "_emit": lambda self, event, **payload: events.append((event, dict(payload))),
            },
        )()

        prepare_startup_execution_with_runtime(runtime, session)

        self.assertEqual(docker_commands, [(["docker", "ps"], 10.0)])
        self.assertEqual(events[-1][0], "startup.phase")
        self.assertEqual(events[-1][1]["phase"], "docker_prewarm")
        self.assertEqual(events[-1][1]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
