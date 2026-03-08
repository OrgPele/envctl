from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.startup import requirements_startup_domain
from envctl_engine.state.models import PortPlan
from envctl_engine.requirements.common import ContainerStartResult
from envctl_engine.requirements.orchestrator import RequirementsOrchestrator


class _FakeRunner:
    def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
        return subprocess.CompletedProcess(
            args=list(cmd),
            returncode=0,
            stdout="ok",
            stderr="",
        )

    def wait_for_port(self, port, *, timeout=30.0):  # noqa: ANN001, ARG002
        return True


class _FakeRuntime:
    def __init__(self) -> None:
        self.env = {
            "ENVCTL_DEBUG_REQUIREMENTS_TRACE": "1",
            "ENVCTL_DEBUG_DOCKER_COMMAND_TIMING": "1",
        }
        self.config = SimpleNamespace(requirements_strict=True, raw={})
        self.process_runner = _FakeRunner()
        self.events: list[dict[str, object]] = []

    def _command_override_value(self, _key: str) -> str | None:
        return None

    def _command_exists(self, _name: str) -> bool:
        return True

    def _command_env(self, *, port: int, extra: dict[str, str] | None = None) -> dict[str, str]:
        _ = port
        return dict(extra or {})

    def _runtime_env_overrides(self, _route) -> dict[str, str]:  # noqa: ANN001
        return {}

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append({"event": event, **payload})


class _FakePortPlanner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def update_final_port(self, plan: PortPlan, final_port: int, *, source: str) -> None:
        plan.final = int(final_port)
        self.calls.append({"final_port": int(final_port), "source": str(source)})


class _ComponentRuntime(_FakeRuntime):
    def __init__(self) -> None:
        super().__init__()
        self._conflict_remaining: dict[str, int] = {}
        self.port_planner = _FakePortPlanner()
        self.requirements = RequirementsOrchestrator()

    def _start_requirement_with_native_adapter(  # noqa: ANN001
        self,
        *,
        context,
        service_name: str,
        port: int,
        route=None,
    ) -> requirements_startup_domain._NativeAdapterStartResult | None:
        _ = context, service_name, port, route
        return requirements_startup_domain._NativeAdapterStartResult(
            success=True,
            error=None,
            effective_port=6399,
            port_adopted=True,
        )

    def _requirement_command_resolved(self, *, service_name: str, port: int, project_root: Path):  # noqa: ANN001
        _ = service_name, port, project_root
        return (["echo", "unused"], "unused")

    def _requirement_bind_max_retries(self) -> int:
        return 1


class RequirementsStartupDomainTests(unittest.TestCase):
    def test_native_adapter_emits_deep_requirement_trace_events(self) -> None:
        runtime = _FakeRuntime()
        with tempfile.TemporaryDirectory() as tmpdir:
            context = SimpleNamespace(name="Main", root=Path(tmpdir))

            def _fake_start_postgres_container(**kwargs):  # noqa: ANN003
                runner = kwargs["process_runner"]
                # Simulate probe command to feed command/probe timing traces.
                _ = runner.run(
                    [
                        "docker",
                        "exec",
                        "envctl-postgres-main-test",
                        "pg_isready",
                        "-h",
                        "127.0.0.1",
                    ],
                    cwd=kwargs["project_root"],
                    env=kwargs["env"],
                    timeout=30.0,
                )
                return ContainerStartResult(
                    success=True,
                    container_name="envctl-postgres-main-test",
                    stage_events=[
                        {"stage": "discover", "reason": None, "detail": None, "elapsed_ms": 1.1},
                        {
                            "stage": "probe.retry.restart",
                            "reason": "transient_probe_timeout_retryable",
                            "detail": None,
                            "elapsed_ms": 2.2,
                        },
                    ],
                    stage_durations_ms={"discover": 1.1, "probe": 2.2, "restart": 0.9},
                    listener_wait_ms=12.34,
                    container_reused=True,
                    container_recreated=False,
                    effective_port=5439,
                    port_adopted=True,
                    port_mismatch_requested_port=5432,
                    port_mismatch_existing_port=5439,
                    port_mismatch_action="adopt_existing",
                )

            with patch.object(
                requirements_startup_domain,
                "start_postgres_container",
                side_effect=_fake_start_postgres_container,
            ):
                outcome = requirements_startup_domain._start_requirement_with_native_adapter(
                    runtime,
                    context=context,
                    service_name="postgres",
                    port=5432,
                    route=None,
                )

        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertTrue(outcome.success)
        self.assertEqual(int(outcome.effective_port or 0), 5439)
        self.assertTrue(outcome.port_adopted)

        emitted_names = [str(event.get("event", "")) for event in runtime.events]
        self.assertIn("requirements.adapter.stage", emitted_names)
        self.assertIn("requirements.adapter.command_timing", emitted_names)
        self.assertIn("requirements.adapter.probe_attempt", emitted_names)
        self.assertIn("requirements.adapter.listener_wait", emitted_names)
        self.assertIn("requirements.adapter.retry_path", emitted_names)
        self.assertIn("requirements.adapter.port_mismatch", emitted_names)
        self.assertIn("requirements.adapter", emitted_names)

        adapter_events = [item for item in runtime.events if item.get("event") == "requirements.adapter"]
        self.assertTrue(adapter_events)
        adapter_event = adapter_events[-1]
        self.assertEqual(int(adapter_event.get("docker_command_count", 0)), 1)
        self.assertEqual(int(adapter_event.get("probe_attempt_count", 0)), 1)
        self.assertAlmostEqual(float(adapter_event.get("listener_wait_ms", 0.0)), 12.34, places=2)
        self.assertEqual(bool(adapter_event.get("container_reused")), True)
        self.assertEqual(bool(adapter_event.get("container_recreated")), False)
        self.assertEqual(int(adapter_event.get("effective_port", 0)), 5439)
        self.assertEqual(bool(adapter_event.get("port_adopted")), True)
        self.assertIsInstance(adapter_event.get("stage_durations_ms"), dict)

    def test_start_requirement_component_adopts_effective_port_and_emits_adopt_event(self) -> None:
        runtime = _ComponentRuntime()
        with tempfile.TemporaryDirectory() as tmpdir:
            context = SimpleNamespace(name="Main", root=Path(tmpdir))
            plan = PortPlan(
                project="Main",
                requested=6380,
                assigned=6380,
                final=6380,
                source="requested",
                retries=0,
            )
            outcome = requirements_startup_domain._start_requirement_component(
                runtime,
                context=context,
                name="redis",
                plan=plan,
                reserve_next=lambda port: int(port),
                strict=False,
                route=None,
            )

        self.assertTrue(outcome.success)
        self.assertEqual(int(outcome.final_port), 6399)
        self.assertEqual(int(plan.final), 6399)
        self.assertTrue(runtime.port_planner.calls)
        self.assertEqual(runtime.port_planner.calls[-1]["source"], "adopt_existing")
        adopt_events = [item for item in runtime.events if item.get("event") == "requirements.port_adopted"]
        self.assertTrue(adopt_events)
        self.assertEqual(int(adopt_events[-1].get("adopted_port", 0)), 6399)
        self.assertEqual(int(adopt_events[-1].get("requested_port", 0)), 6380)


if __name__ == "__main__":
    unittest.main()
