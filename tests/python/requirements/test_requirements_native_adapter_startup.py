from __future__ import annotations

import inspect
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.requirements.common import ContainerStartResult
from envctl_engine.startup.requirements_native_adapter import (
    NativeAdapterStartResult,
    start_requirement_with_native_adapter,
)
from envctl_engine.startup import requirements_startup_domain


class _FakeRunner:
    def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
        return subprocess.CompletedProcess(
            args=list(cmd),
            returncode=0,
            stdout="ok",
            stderr="",
        )


class _FakeRuntime:
    def __init__(self) -> None:
        self.env = {
            "ENVCTL_DEBUG_REQUIREMENTS_TRACE": "1",
            "ENVCTL_DEBUG_DOCKER_COMMAND_TIMING": "1",
        }
        self.config = SimpleNamespace(requirements_strict=True, raw={})
        self.process_runner = _FakeRunner()
        self.runtime_root = Path("/tmp/envctl-runtime")
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


class RequirementsNativeAdapterStartupTests(unittest.TestCase):
    def test_native_adapter_owner_emits_deep_trace_events(self) -> None:
        runtime = _FakeRuntime()
        with tempfile.TemporaryDirectory() as tmpdir:
            context = SimpleNamespace(name="Main", root=Path(tmpdir))

            def _fake_start_postgres_container(**kwargs):  # noqa: ANN003
                runner = kwargs["process_runner"]
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
                        {"stage": "probe.retry.restart", "reason": "retry", "detail": None, "elapsed_ms": 2.2},
                    ],
                    stage_durations_ms={"discover": 1.1, "restart": 2.2},
                    listener_wait_ms=12.34,
                    container_reused=True,
                    effective_port=5439,
                    port_adopted=True,
                    port_mismatch_requested_port=5432,
                    port_mismatch_existing_port=5439,
                    port_mismatch_action="adopt_existing",
                )

            outcome = start_requirement_with_native_adapter(
                runtime,
                context=context,
                service_name="postgres",
                port=5432,
                route=None,
                native_starters={"postgres": _fake_start_postgres_container},
            )

        self.assertEqual(
            outcome,
            NativeAdapterStartResult(
                success=True,
                error=None,
                effective_port=5439,
                port_adopted=True,
                container_name="envctl-postgres-main-test",
            ),
        )
        emitted_names = [str(event.get("event", "")) for event in runtime.events]
        self.assertIn("requirements.adapter.stage", emitted_names)
        self.assertIn("requirements.adapter.command_timing", emitted_names)
        self.assertIn("requirements.adapter.probe_attempt", emitted_names)
        self.assertIn("requirements.adapter.listener_wait", emitted_names)
        self.assertIn("requirements.adapter.retry_path", emitted_names)
        self.assertIn("requirements.adapter.port_mismatch", emitted_names)
        self.assertIn("requirements.adapter", emitted_names)

    def test_domain_keeps_private_wrapper_as_compatibility_facade(self) -> None:
        self.assertIs(requirements_startup_domain._NativeAdapterStartResult, NativeAdapterStartResult)
        domain_lines, _ = inspect.getsourcelines(requirements_startup_domain._start_requirement_with_native_adapter)
        self.assertLess(len(domain_lines), 30)


if __name__ == "__main__":
    unittest.main()
