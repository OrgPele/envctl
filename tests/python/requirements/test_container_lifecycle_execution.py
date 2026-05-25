from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from envctl_engine.requirements.adapter_lifecycle_models import AdapterLifecycleEvent
from envctl_engine.requirements.adapter_lifecycle_models import ContainerLifecycleRun
from envctl_engine.requirements.adapter_lifecycle_models import ContainerLifecycleTemplate
from envctl_engine.requirements.adapter_lifecycle_models import project_container_lifecycle_result
from envctl_engine.requirements.common import ContainerStartResult
from envctl_engine.requirements.container_lifecycle_execution import ContainerLifecycleDockerClient
from envctl_engine.requirements.container_lifecycle_execution import ContainerLifecycleExecutor


class ContainerLifecycleExecutionTests(unittest.TestCase):
    def test_executor_owns_successful_create_probe_lifecycle(self) -> None:
        traced: list[dict[str, object]] = []
        template = ContainerLifecycleTemplate(
            service_name="postgres",
            container_name="envctl-postgres",
            process_runner=SimpleNamespace(),
            project_root=Path("/tmp/project"),
            env={},
            port=5432,
            container_port=5432,
            listener_wait_timeout=0.1,
            probe_attempts=2,
            restart_probe_attempts=3,
            recreate_probe_attempts=4,
            restart_on_probe_failure=True,
            recreate_on_probe_failure=True,
            retryable_probe_error=lambda _error: False,
            create_container=lambda: None,
            probe_readiness=lambda attempts: (attempts == 2, None),
            probe_failure_fallback="postgres did not become ready",
            trace_stage=traced.append,
        )

        with (
            patch("envctl_engine.requirements.container_lifecycle_docker.container_exists", return_value=(False, None)),
            patch("envctl_engine.requirements.container_lifecycle_execution.wait_for_port_ready", return_value=True),
        ):
            lifecycle = ContainerLifecycleExecutor(template).run()

        self.assertTrue(lifecycle.result.success)
        self.assertEqual(lifecycle.result.effective_port, 5432)
        self.assertFalse(lifecycle.container_reused)
        self.assertFalse(lifecycle.container_recreated)
        self.assertIn("discover", lifecycle.stage_durations_ms)
        self.assertIn("create", lifecycle.stage_durations_ms)
        self.assertIn("listener_wait", lifecycle.stage_durations_ms)
        self.assertIn("probe", lifecycle.stage_durations_ms)
        self.assertEqual([event.stage for event in lifecycle.events], ["discover", "probe.healthy"])
        self.assertEqual([event["stage"] for event in traced], ["discover", "probe.healthy"])

    def test_executor_exposes_lifecycle_helpers_as_methods_not_nested_functions(self) -> None:
        self.assertTrue(hasattr(ContainerLifecycleExecutor, "_emit"))
        self.assertTrue(hasattr(ContainerLifecycleExecutor, "_add_stage_duration"))
        self.assertTrue(hasattr(ContainerLifecycleExecutor, "_run_result"))
        self.assertTrue(hasattr(ContainerLifecycleExecutor, "_success"))
        self.assertTrue(hasattr(ContainerLifecycleExecutor, "_failure"))
        self.assertTrue(hasattr(ContainerLifecycleExecutor, "_reset_to_requested_port"))
        self.assertTrue(hasattr(ContainerLifecycleExecutor, "_recover_timeout_created_container"))
        self.assertTrue(hasattr(ContainerLifecycleExecutor, "_attempt_local_settle"))
        self.assertTrue(hasattr(ContainerLifecycleExecutor, "_discover_existing_container"))
        self.assertTrue(hasattr(ContainerLifecycleExecutor, "_start_or_create_container"))
        self.assertTrue(hasattr(ContainerLifecycleExecutor, "_start_existing_container"))
        self.assertTrue(hasattr(ContainerLifecycleExecutor, "_start_existing_failure"))
        self.assertTrue(hasattr(ContainerLifecycleExecutor, "_restart_after_probe_failure"))
        self.assertTrue(hasattr(ContainerLifecycleExecutor, "_recreate_after_restart_failure"))
        self.assertTrue(hasattr(ContainerLifecycleExecutor, "_run_readiness_probe_phase"))

        overview_names = set(ContainerLifecycleExecutor.run.__code__.co_varnames)
        self.assertNotIn("_emit", overview_names)
        self.assertNotIn("_failure", overview_names)

    def test_docker_operations_are_owned_by_lifecycle_client(self) -> None:
        self.assertTrue(hasattr(ContainerLifecycleDockerClient, "exists"))
        self.assertTrue(hasattr(ContainerLifecycleDockerClient, "host_port"))
        self.assertTrue(hasattr(ContainerLifecycleDockerClient, "status"))
        self.assertTrue(hasattr(ContainerLifecycleDockerClient, "state_error"))
        self.assertTrue(hasattr(ContainerLifecycleDockerClient, "stop_and_remove"))
        self.assertTrue(hasattr(ContainerLifecycleDockerClient, "start"))
        self.assertTrue(hasattr(ContainerLifecycleDockerClient, "restart"))

        source = Path("python/envctl_engine/requirements/container_lifecycle_execution.py").read_text(encoding="utf-8")
        docker_source = Path("python/envctl_engine/requirements/container_lifecycle_docker.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("class ContainerLifecycleDockerClient", docker_source)
        self.assertIn(
            "from envctl_engine.requirements.container_lifecycle_docker import ContainerLifecycleDockerClient",
            source,
        )
        self.assertIn("self._docker = ContainerLifecycleDockerClient(template)", source)
        self.assertLessEqual(source.count("run_docker("), 2)
        self.assertLessEqual(source.count("stop_and_remove_container("), 1)
        self.assertEqual(source.count("class ContainerLifecycleDockerClient"), 0)

    def test_lifecycle_run_projects_telemetry_to_result_once(self) -> None:
        lifecycle = ContainerLifecycleRun(
            result=ContainerStartResult(success=True, container_name="envctl-postgres"),
            events=[AdapterLifecycleEvent(stage="discover")],
            stage_durations_ms={"discover": 1.5},
            listener_wait_ms=2.5,
            container_reused=True,
            container_recreated=False,
        )

        result = project_container_lifecycle_result(lifecycle)

        self.assertIs(result, lifecycle.result)
        self.assertEqual(result.stage_events, [{"stage": "discover", "reason": None, "detail": None, "elapsed_ms": 0.0}])
        self.assertEqual(result.stage_durations_ms, {"discover": 1.5})
        self.assertEqual(result.listener_wait_ms, 2.5)
        self.assertTrue(result.container_reused)
        self.assertFalse(result.container_recreated)

        for adapter_path in [
            Path("python/envctl_engine/requirements/postgres.py"),
            Path("python/envctl_engine/requirements/redis.py"),
            Path("python/envctl_engine/requirements/n8n.py"),
        ]:
            source = adapter_path.read_text(encoding="utf-8")
            self.assertIn("return project_container_lifecycle_result(lifecycle_run)", source)
            self.assertNotIn("result.stage_events =", source)

    def test_success_projection_is_centralized(self) -> None:
        source = Path("python/envctl_engine/requirements/container_lifecycle_execution.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("success=True"), 1)
        self.assertEqual(source.count("port_mismatch_action=state.mismatch_action"), 2)

    def test_run_stays_as_phase_orchestrator(self) -> None:
        run_lines, _ = inspect.getsourcelines(ContainerLifecycleExecutor.run)
        self.assertLess(len(run_lines), 35)


if __name__ == "__main__":
    unittest.main()
