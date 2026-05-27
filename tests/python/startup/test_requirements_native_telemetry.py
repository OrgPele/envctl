from __future__ import annotations

import subprocess
import unittest
from types import SimpleNamespace

from envctl_engine.requirements.common import ContainerStartResult
from envctl_engine.startup.requirements_native_telemetry import (
    CommandTimingRunnerProxy,
    NativeAdapterTelemetryEmitter,
    classify_docker_stage,
    extract_probe_attempts,
)


class _Runtime:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append({"event": event, **payload})


class _Runner:
    def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
        return subprocess.CompletedProcess(list(cmd), 0, "ok", "")


class RequirementsNativeTelemetryTests(unittest.TestCase):
    def test_classifies_docker_stages(self) -> None:
        self.assertEqual(classify_docker_stage(["docker", "ps"]), "discover")
        self.assertEqual(classify_docker_stage(["docker", "run", "redis"]), "create")
        self.assertEqual(classify_docker_stage(["docker", "exec", "redis", "redis-cli", "ping"]), "probe")
        self.assertEqual(classify_docker_stage(["python", "-m", "pytest"]), "other")

    def test_extract_probe_attempts_numbers_matching_docker_exec_probes(self) -> None:
        attempts = extract_probe_attempts(
            [
                {"command": ["docker", "exec", "db", "pg_isready"], "duration_ms": "2.5", "returncode": "0"},
                {"command": ["docker", "exec", "db", "echo", "ready"], "duration_ms": 1, "returncode": 0},
                {"command": ["docker", "exec", "db", "pg_isready"], "duration_ms": 3, "returncode": 1},
            ],
            service_name="postgres",
        )

        self.assertEqual([attempt["attempt"] for attempt in attempts], [1, 2])
        self.assertEqual([attempt["returncode"] for attempt in attempts], [0, 1])

    def test_command_timing_proxy_records_return_code_and_timeout(self) -> None:
        sink: list[dict[str, object]] = []
        proxy = CommandTimingRunnerProxy(_Runner(), sink=sink)

        proxy.run(["docker", "ps"], timeout=4.0)

        self.assertEqual(sink[0]["command"], ["docker", "ps"])
        self.assertEqual(sink[0]["returncode"], 0)
        self.assertEqual(sink[0]["timeout_s"], 4.0)
        self.assertEqual(sink[0]["timed_out"], False)

    def test_telemetry_emitter_records_trace_command_and_summary_events(self) -> None:
        runtime = _Runtime()
        context = SimpleNamespace(name="Main")
        result = ContainerStartResult(
            success=True,
            container_name="main-postgres",
            effective_port=5433,
            stage_events=[{"stage": "probe.retry.restart", "elapsed_ms": 5.1}],
            listener_wait_ms=4.2,
            probe_attempts=[{"attempt": "1", "duration_ms": "3.2", "returncode": "0"}],
            port_mismatch_action="adopt",
            port_mismatch_requested_port=5432,
            port_mismatch_existing_port=5433,
            port_adopted=True,
            container_reused=True,
        )

        NativeAdapterTelemetryEmitter(
            runtime,
            context=context,
            service_name="postgres",
            port=5432,
            result=result,
            trace_enabled=True,
            command_timing_enabled=True,
            command_timings=[{"command": ["docker", "ps"], "duration_ms": "2", "returncode": "0"}],
        ).emit()

        event_names = [str(event["event"]) for event in runtime.events]
        self.assertIn("requirements.adapter.stage", event_names)
        self.assertIn("requirements.adapter.retry_path", event_names)
        self.assertIn("requirements.adapter.probe_attempt", event_names)
        self.assertIn("requirements.adapter.port_mismatch", event_names)
        self.assertIn("requirements.adapter.command_timing", event_names)
        self.assertEqual(event_names[-1], "requirements.adapter")


if __name__ == "__main__":
    unittest.main()
