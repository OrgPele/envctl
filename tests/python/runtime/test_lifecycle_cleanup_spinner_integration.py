from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.lifecycle_cleanup_orchestrator import LifecycleCleanupOrchestrator
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord
from envctl_engine.ui.spinner_service import SpinnerPolicy
from envctl_engine.ui.target_selector import TargetSelection


class _StateRepoStub:
    def __init__(self) -> None:
        self.saved_states: list[RunState] = []
        self.purge_calls: list[bool] = []

    def save_selected_stop_state(self, *, state, emit, runtime_map_builder):  # noqa: ANN001
        _ = emit, runtime_map_builder
        self.saved_states.append(state)
        return {}

    def purge(self, *, aggressive: bool = False) -> None:
        self.purge_calls.append(aggressive)


class _RuntimeStub:
    def __init__(self) -> None:
        self.env: dict[str, str] = {}
        self.config = SimpleNamespace(raw={})
        self.events: list[dict[str, object]] = []
        self.state_repository = _StateRepoStub()
        self.selection_calls: list[dict[str, object]] = []

    def _emit(self, event: str, **payload: object) -> None:
        entry = {"event": event}
        entry.update(payload)
        self.events.append(entry)

    def _try_load_existing_state(self, *args, **kwargs):  # noqa: ANN001, ARG002
        return None

    @staticmethod
    def _state_lookup_strict_mode_match(_route):  # noqa: ANN001
        return False

    def _terminate_services_from_state(self, *args, **kwargs):  # noqa: ANN001, ARG002
        return None

    def _release_port_session(self) -> None:
        return None

    @staticmethod
    def _project_name_from_service(name: str) -> str:
        return name.split(" ", 1)[0] if " " in name else ""

    def _select_grouped_targets(
        self,
        *,
        prompt: str,
        projects: list[object],
        services: list[str],
        allow_all: bool,
        multi: bool,
    ) -> TargetSelection:
        self.selection_calls.append(
            {
                "prompt": prompt,
                "projects": [str(getattr(project, "name", "")) for project in projects],
                "services": list(services),
                "allow_all": allow_all,
                "multi": multi,
            }
        )
        return TargetSelection(project_names=["Main"])


class LifecycleCleanupSpinnerIntegrationTests(unittest.TestCase):
    def test_stop_all_emits_spinner_policy_and_lifecycle(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = LifecycleCleanupOrchestrator(runtime)
        route = Route(command="stop-all", mode="main")
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
            patch("envctl_engine.runtime.lifecycle_cleanup_orchestrator.spinner", side_effect=fake_spinner),
            patch(
                "envctl_engine.runtime.lifecycle_cleanup_orchestrator.resolve_spinner_policy",
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
        self.assertEqual(spinner_calls, [("Stopping all services and runtime state...", True)])
        self.assertTrue(any(item.get("event") == "ui.spinner.policy" for item in runtime.events))
        lifecycle = [item for item in runtime.events if item.get("event") == "ui.spinner.lifecycle"]
        self.assertTrue(any(item.get("state") == "success" for item in lifecycle))

    def test_stop_selector_miss_does_not_start_spinner(self) -> None:
        runtime = _RuntimeStub()
        runtime._try_load_existing_state = lambda *args, **kwargs: RunState(  # type: ignore[method-assign]
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd="/tmp/main/backend",
                    requested_port=8000,
                    actual_port=8000,
                    pid=123,
                    status="running",
                )
            },
        )
        orchestrator = LifecycleCleanupOrchestrator(runtime)
        route = Route(command="stop", mode="main")

        @contextmanager
        def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
            _ = message, enabled, start_immediately
            raise AssertionError("spinner should not start when stop target resolution fails")

        with (
            patch("envctl_engine.runtime.lifecycle_cleanup_orchestrator.spinner", side_effect=fake_spinner),
            patch.object(orchestrator, "_select_services_for_stop", return_value=set()),
        ):
            code = orchestrator.execute(route)

        self.assertEqual(code, 1)

    def test_stop_runtime_scope_backend_selects_backend_services_without_prompt(self) -> None:
        runtime = _RuntimeStub()
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd=".", pid=1),
                "Main Frontend": ServiceRecord(name="Main Frontend", type="frontend", cwd=".", pid=2),
                "Other Backend": ServiceRecord(name="Other Backend", type="backend", cwd=".", pid=3),
            },
        )
        orchestrator = LifecycleCleanupOrchestrator(runtime)
        route = Route(command="stop", mode="main", flags={"runtime_scope": "backend", "batch": True})

        selected = orchestrator._select_services_for_stop(state, route)

        self.assertEqual(selected, {"Main Backend", "Other Backend"})
        self.assertEqual(runtime.selection_calls, [])

    def test_stop_dependencies_scope_releases_requirements_without_terminating_services(self) -> None:
        runtime = _RuntimeStub()
        released: list[int] = []
        terminated: list[set[str] | None] = []
        runtime.port_planner = SimpleNamespace(release=lambda port: released.append(port))
        runtime._terminate_services_from_state = lambda _state, **kwargs: terminated.append(  # type: ignore[method-assign]
            kwargs.get("selected_services")
        )
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd=".", pid=1),
            },
            requirements={
                "Main": RequirementsResult(project="Main", db={"enabled": True, "final": 5432}),
            },
        )
        runtime._try_load_existing_state = lambda *args, **kwargs: state  # type: ignore[method-assign]
        orchestrator = LifecycleCleanupOrchestrator(runtime)
        route = Route(command="stop", mode="main", flags={"runtime_scope": "dependencies", "batch": True})

        code = orchestrator.execute(route)

        self.assertEqual(code, 0)
        self.assertEqual(terminated, [])
        self.assertEqual(released, [5432])
        self.assertEqual(state.services.keys(), {"Main Backend"})
        self.assertEqual(state.requirements, {})
        self.assertEqual(runtime.state_repository.saved_states[0].services.keys(), {"Main Backend"})

    def test_stop_selected_dependency_component_preserves_services_and_other_dependencies(self) -> None:
        runtime = _RuntimeStub()
        released: list[int] = []
        terminated: list[set[str] | None] = []
        runtime.port_planner = SimpleNamespace(release=lambda port: released.append(port))
        runtime._terminate_services_from_state = lambda _state, **kwargs: terminated.append(  # type: ignore[method-assign]
            kwargs.get("selected_services")
        )
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd=".", pid=1),
            },
            requirements={
                "Main": RequirementsResult(
                    project="Main",
                    db={"enabled": True, "final": 5432},
                    redis={"enabled": True, "final": 6379},
                ),
            },
        )
        runtime._try_load_existing_state = lambda *args, **kwargs: state  # type: ignore[method-assign]
        orchestrator = LifecycleCleanupOrchestrator(runtime)
        route = Route(
            command="stop",
            mode="main",
            flags={
                "stop_dependency_components": ["Main:redis"],
                "stop_preserve_requirements": True,
                "batch": True,
            },
        )

        code = orchestrator.execute(route)

        self.assertEqual(code, 0)
        self.assertEqual(terminated, [])
        self.assertEqual(released, [6379])
        self.assertIn("Main Backend", state.services)
        self.assertIn("Main", state.requirements)
        self.assertFalse(state.requirements["Main"].redis.get("enabled", False))
        self.assertTrue(state.requirements["Main"].db.get("enabled", False))
        self.assertEqual(runtime.state_repository.saved_states[0].services.keys(), {"Main Backend"})

    def test_stop_selected_services_can_leave_dependencies_running(self) -> None:
        runtime = _RuntimeStub()
        released: list[int] = []
        terminated: list[set[str] | None] = []
        runtime.port_planner = SimpleNamespace(release=lambda port: released.append(port))
        runtime._terminate_services_from_state = lambda _state, **kwargs: terminated.append(  # type: ignore[method-assign]
            kwargs.get("selected_services")
        )
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd=".", pid=1),
            },
            requirements={
                "Main": RequirementsResult(project="Main", db={"enabled": True, "final": 5432}),
            },
        )
        runtime._try_load_existing_state = lambda *args, **kwargs: state  # type: ignore[method-assign]
        orchestrator = LifecycleCleanupOrchestrator(runtime)
        route = Route(
            command="stop",
            mode="main",
            flags={
                "services": ["Main Backend"],
                "stop_preserve_requirements": True,
                "batch": True,
            },
        )

        code = orchestrator.execute(route)

        self.assertEqual(code, 0)
        self.assertEqual(terminated, [{"Main Backend"}])
        self.assertEqual(released, [])
        self.assertEqual(state.services, {})
        self.assertIn("Main", state.requirements)
        self.assertEqual(runtime.state_repository.saved_states[0].requirements.keys(), {"Main"})
        stopped_services = runtime.state_repository.saved_states[0].metadata.get("dashboard_stopped_services")
        self.assertEqual(
            stopped_services,
            [{"name": "Main Backend", "project": "Main", "type": "backend"}],
        )

    def test_interactive_stop_all_services_preserves_stopped_dashboard_state(self) -> None:
        runtime = _RuntimeStub()
        terminated: list[set[str] | None] = []
        runtime._terminate_services_from_state = lambda _state, **kwargs: terminated.append(  # type: ignore[method-assign]
            kwargs.get("selected_services")
        )
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd="/repo/backend", pid=1),
                "Main Frontend": ServiceRecord(name="Main Frontend", type="frontend", cwd="/repo/frontend", pid=2),
            },
            metadata={"project_roots": {"Main": "/repo"}},
        )
        runtime._try_load_existing_state = lambda *args, **kwargs: state  # type: ignore[method-assign]
        orchestrator = LifecycleCleanupOrchestrator(runtime)
        route = Route(
            command="stop",
            mode="main",
            flags={
                "services": ["Main Backend", "Main Frontend"],
                "stop_preserve_requirements": True,
                "interactive_command": True,
                "batch": True,
            },
        )

        code = orchestrator.execute(route)

        self.assertEqual(code, 0)
        self.assertEqual(terminated, [{"Main Backend", "Main Frontend"}])
        self.assertEqual(state.services, {})
        self.assertEqual(runtime.state_repository.purge_calls, [])
        self.assertEqual(len(runtime.state_repository.saved_states), 1)
        saved = runtime.state_repository.saved_states[0]
        self.assertEqual(saved.services, {})
        self.assertEqual(
            saved.metadata.get("dashboard_stopped_services"),
            [
                {"name": "Main Backend", "project": "Main", "type": "backend"},
                {"name": "Main Frontend", "project": "Main", "type": "frontend"},
            ],
        )

    def test_stop_selection_routes_through_runtime_backend_selector(self) -> None:
        runtime = _RuntimeStub()
        runtime._try_load_existing_state = lambda *args, **kwargs: RunState(  # type: ignore[method-assign]
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd="/tmp/main/backend",
                    requested_port=8000,
                    actual_port=8000,
                    pid=123,
                    status="running",
                )
            },
        )
        orchestrator = LifecycleCleanupOrchestrator(runtime)
        route = Route(command="stop", mode="main", flags={"interactive_command": True})
        state = runtime._try_load_existing_state()
        assert state is not None

        with (
            patch(
                "envctl_engine.runtime.lifecycle_cleanup_orchestrator.RuntimeTerminalUI._can_interactive_tty",
                return_value=True,
            ),
            patch(
                "envctl_engine.runtime.lifecycle_cleanup_orchestrator.RuntimeTerminalUI.flush_pending_interactive_input"
            ) as flush_mock,
        ):
            selected = orchestrator._select_services_for_stop(state, route)

        self.assertEqual(selected, {"Main Backend"})
        self.assertEqual(runtime.selection_calls[0]["prompt"], "Stop services")
        flush_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
