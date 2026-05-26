from __future__ import annotations

import inspect
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.requirements.orchestrator import RequirementsOrchestrator
from envctl_engine.startup import requirements_startup_domain
from envctl_engine.startup.requirements_component_startup import start_requirement_component
from envctl_engine.startup.requirements_native_adapter import NativeAdapterStartResult
from envctl_engine.state.models import PortPlan


class _FakeRunner:
    def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
        return subprocess.CompletedProcess(list(cmd), 0, "ok", "")

    def wait_for_port(self, port, *, timeout=30.0):  # noqa: ANN001, ARG002
        return True


class _FakePortPlanner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def update_final_port(self, plan: PortPlan, final_port: int, *, source: str) -> None:
        plan.final = int(final_port)
        self.calls.append({"final_port": int(final_port), "source": str(source)})


class _FakeRuntime:
    def __init__(self) -> None:
        self.env: dict[str, str] = {}
        self.config = SimpleNamespace(requirements_strict=True, raw={})
        self.process_runner = _FakeRunner()
        self.runtime_root = Path("/tmp/envctl-runtime")
        self._conflict_remaining: dict[str, int] = {}
        self.port_planner = _FakePortPlanner()
        self.requirements = RequirementsOrchestrator()
        self.events: list[dict[str, object]] = []

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append({"event": event, **payload})

    def _supabase_fingerprint_path(self, project_name: str) -> Path:
        return Path("/tmp") / f"{project_name}.fingerprint.json"

    def _supabase_auto_reinit_enabled(self) -> bool:
        return False

    def _supabase_reinit_required_message(self) -> str:
        return "reinit required"

    def _run_supabase_reinit(self, **_kwargs) -> str | None:  # noqa: ANN003
        return None

    def _requirement_command_resolved(self, *, service_name: str, port: int, project_root: Path):  # noqa: ANN001
        _ = service_name, port, project_root
        return (["echo", "ok"], "configured")

    def _command_env(self, *, port: int, extra: dict[str, str] | None = None) -> dict[str, str]:
        _ = port
        return dict(extra or {})

    def _runtime_env_overrides(self, _route) -> dict[str, str]:  # noqa: ANN001
        return {}

    def _wait_for_requirement_listener(self, port: int) -> bool:
        _ = port
        return True

    def _requirement_bind_max_retries(self) -> int:
        return 1


class RequirementsComponentStartupTests(unittest.TestCase):
    def test_component_owner_adopts_native_effective_port_and_container_name(self) -> None:
        runtime = _FakeRuntime()
        with tempfile.TemporaryDirectory() as tmpdir:
            context = SimpleNamespace(name="Main", root=Path(tmpdir), ports={})
            plan = PortPlan(project="Main", requested=6380, assigned=6380, final=6380, source="requested")

            outcome = start_requirement_component(
                runtime,
                context=context,
                name="redis",
                plan=plan,
                reserve_next=lambda port: int(port),
                native_adapter_start=lambda **_kwargs: NativeAdapterStartResult(
                    success=True,
                    effective_port=6399,
                    port_adopted=True,
                    container_name="envctl-redis-main-test",
                ),
            )

        self.assertTrue(outcome.success)
        self.assertEqual(outcome.final_port, 6399)
        self.assertEqual(outcome.container_name, "envctl-redis-main-test")
        self.assertEqual(plan.final, 6399)
        self.assertEqual(runtime.port_planner.calls[-1]["source"], "adopt_existing")
        self.assertTrue(any(event.get("event") == "requirements.port_adopted" for event in runtime.events))

    def test_domain_keeps_component_start_as_compatibility_facade(self) -> None:
        domain_lines, _ = inspect.getsourcelines(requirements_startup_domain._start_requirement_component)
        self.assertLess(len(domain_lines), 35)


if __name__ == "__main__":
    unittest.main()
