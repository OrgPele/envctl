from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.startup.service_execution_environment import (
    configured_service_types_for_mode,
    make_service_dependency_emitter,
    make_service_retry_emitter,
    project_env_for_service,
    project_service_log_paths,
    resolve_service_workdirs,
)


class ServiceExecutionEnvironmentTests(unittest.TestCase):
    def test_resolve_service_workdirs_falls_back_to_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "api").mkdir()
            config = SimpleNamespace(backend_dir_name="api", frontend_dir_name="web")

            backend_cwd, frontend_cwd = resolve_service_workdirs(config=config, project_root=root)

        self.assertEqual(backend_cwd, root / "api")
        self.assertEqual(frontend_cwd, root)

    def test_project_service_log_paths_sanitize_project_name(self) -> None:
        runtime = SimpleNamespace(_run_dir_path=lambda run_id: Path("/runs") / run_id)

        paths = project_service_log_paths(runtime=runtime, run_id="run-1", project_name="Feature / A")

        self.assertEqual(paths.safe_project_name, "Feature___A")
        self.assertEqual(paths.backend_log_path, "/runs/run-1/Feature___A_backend.txt")
        self.assertEqual(paths.frontend_log_path, "/runs/run-1/Feature___A_frontend.txt")

    def test_project_env_for_service_preserves_legacy_builders_without_service_name(self) -> None:
        calls: list[tuple[str | None, object]] = []

        class RuntimeStub:
            def _project_service_env(self, context, *, requirements, route, service_name=None):  # noqa: ANN001
                calls.append((service_name, route))
                if service_name is not None:
                    raise TypeError("unexpected keyword argument 'service_name'")
                return {"PROJECT": context.name}

        env = project_env_for_service(
            RuntimeStub(),
            SimpleNamespace(name="Main"),
            requirements=object(),
            route=object(),
            service_name="worker",
        )

        self.assertEqual(env, {"PROJECT": "Main"})
        self.assertEqual([call[0] for call in calls], ["worker", None])

    def test_project_env_for_service_normalizes_empty_builder_result(self) -> None:
        class RuntimeStub:
            def _project_service_env(self, context, *, requirements, route, service_name=None):  # noqa: ANN001
                _ = (context, requirements, route, service_name)
                return None

        env = project_env_for_service(
            RuntimeStub(),
            SimpleNamespace(name="Main"),
            requirements=object(),
            route=object(),
            service_name="worker",
        )

        self.assertEqual(env, {})

    def test_configured_service_types_use_mode_aware_config_when_available(self) -> None:
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                all_app_service_names_for_mode=lambda mode, project_root: [mode, project_root.name, "worker"]
            )
        )

        services = configured_service_types_for_mode(runtime, "trees", Path("/repo/project-a"))

        self.assertEqual(services, {"trees", "project-a", "worker"})

    def test_service_dependency_emitter_records_event_and_timing_message(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(
            env={"ENVCTL_DEBUG_RESTORE_TIMING": "true"},
            config=SimpleNamespace(raw={}),
            _emit=lambda event, **payload: events.append((event, payload)),
        )
        orchestrator = SimpleNamespace(runtime=runtime, _suppress_timing_output=lambda route: False)
        emitter = make_service_dependency_emitter(
            orchestrator=orchestrator,
            runtime=runtime,
            route=SimpleNamespace(flags={}),
        )

        out = StringIO()
        with redirect_stdout(out):
            emitter(service="backend", dependency="redis")

        self.assertEqual(events, [("service.dependency.selected", {"service": "backend", "dependency": "redis"})])
        self.assertIn("Starting dependency service redis because backend depends_on=redis", out.getvalue())

    def test_service_retry_emitter_normalizes_blank_errors(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(_emit=lambda event, **payload: events.append((event, payload)))

        emitter = make_service_retry_emitter(runtime=runtime, project_name="Main")
        emitter("backend", 8000, 8001, 2, "  ")

        self.assertEqual(
            events,
            [
                (
                    "service.retry",
                    {
                        "project": "Main",
                        "service": "backend",
                        "failed_port": 8000,
                        "retry_port": 8001,
                        "attempt": 2,
                        "error": None,
                    },
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
