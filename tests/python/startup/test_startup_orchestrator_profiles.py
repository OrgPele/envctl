from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_router import Route, parse_route
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.runtime.engine_runtime_env import requirement_enabled_for_mode
from envctl_engine.startup.startup_orchestrator import StartupOrchestrator
from envctl_engine.startup.finalization import build_success_run_state
from envctl_engine.startup.session import StartupSession
from envctl_engine.state.models import RequirementsResult
from envctl_engine.startup.startup_selection_support import (
    _restart_selected_services,
    _restart_service_types_for_project,
    restart_target_projects,
)


class StartupOrchestratorProfileTests(unittest.TestCase):
    def _assert_restart_service_types_for_main_backend(
        self,
        *,
        default_service_types: set[str],
        expected: set[str],
    ) -> None:
        route = parse_route(["restart", "--service", "Main Backend"], env={"ENVCTL_DEFAULT_MODE": "main"})
        route.flags["_restart_request"] = True

        selected = StartupOrchestrator._restart_service_types_for_project(
            route=route,
            project_name="Main",
            default_service_types=default_service_types,
        )

        self.assertEqual(selected, expected)

    @staticmethod
    def _build_run_state_with_configured_services(
        *,
        enabled_service_types: set[str],
        context_names: list[str],
    ):
        runtime = SimpleNamespace(
            config=SimpleNamespace(runtime_scope_id="scope-1"),
            _run_dir_path=lambda run_id: Path("/tmp/runtime") / run_id,
            _service_enabled_for_mode=lambda mode, service_name: service_name in enabled_service_types,
        )
        contexts = [SimpleNamespace(name=name, root=Path(f"/tmp/repo/{name}"), ports={}) for name in context_names]
        route = Route(command="up", mode="main", raw_args=[], passthrough_args=[], projects=[], flags={})
        session = StartupSession(
            requested_route=route,
            effective_route=route,
            requested_command="up",
            runtime_mode="main",
            run_id="run-1",
            selected_contexts=contexts,
        )
        return build_success_run_state(runtime, session)  # type: ignore[arg-type]

    def test_restart_synthetic_backend_service_selects_configured_backend_only(self) -> None:
        self._assert_restart_service_types_for_main_backend(
            default_service_types={"backend", "frontend"},
            expected={"backend"},
        )

    def test_restart_synthetic_backend_service_is_rejected_for_frontend_only_profile(self) -> None:
        self._assert_restart_service_types_for_main_backend(
            default_service_types={"frontend"},
            expected=set(),
        )

    def test_build_run_state_writes_project_scoped_configured_services(self) -> None:
        state = self._build_run_state_with_configured_services(
            enabled_service_types={"backend", "frontend"},
            context_names=["Main"],
        )

        self.assertEqual(
            state.metadata.get("dashboard_project_configured_services"),
            {"Main": ["backend", "frontend"]},
        )

    def test_build_run_state_omits_project_scoped_configured_services_when_no_services_enabled(self) -> None:
        state = self._build_run_state_with_configured_services(
            enabled_service_types=set(),
            context_names=["Main"],
        )

        self.assertNotIn("dashboard_project_configured_services", state.metadata)

    def test_build_run_state_writes_project_scoped_configured_services_for_multiple_contexts(self) -> None:
        state = self._build_run_state_with_configured_services(
            enabled_service_types={"frontend"},
            context_names=["Zeta", "Alpha"],
        )

        self.assertEqual(
            state.metadata.get("dashboard_project_configured_services"),
            {"Alpha": ["frontend"], "Zeta": ["frontend"]},
        )

    def test_build_run_state_marks_tree_shared_dependency_dashboard_scope(self) -> None:
        runtime = SimpleNamespace(
            config=SimpleNamespace(runtime_scope_id="scope-1"),
            _run_dir_path=lambda run_id: Path("/tmp/runtime") / run_id,
            _service_enabled_for_mode=lambda _mode, _service_name: False,
        )
        contexts = [
            SimpleNamespace(name="feature-a-1", root=Path("/tmp/repo/trees/feature-a/1"), ports={}),
            SimpleNamespace(name="feature-b-1", root=Path("/tmp/repo/trees/feature-b/1"), ports={}),
        ]
        route = parse_route(["--trees"], env={})
        session = StartupSession(
            requested_route=route,
            effective_route=route,
            requested_command="start",
            runtime_mode="trees",
            run_id="run-1",
            selected_contexts=contexts,
            requirements_by_project={
                "feature-a-1": RequirementsResult(project="Main", redis={"enabled": True, "success": True}),
                "feature-b-1": RequirementsResult(project="Main", redis={"enabled": True, "success": True}),
            },
        )

        state = build_success_run_state(runtime, session)  # type: ignore[arg-type]

        self.assertEqual(state.metadata.get("dashboard_dependency_scope"), "shared")
        self.assertEqual(state.metadata.get("dashboard_shared_dependency_project"), "Main")
        self.assertEqual(state.metadata.get("dependency_mode"), "shared")
        self.assertTrue(state.metadata.get("shared_dependencies"))

    def test_build_run_state_does_not_mark_isolated_tree_dependency_dashboard_scope(self) -> None:
        runtime = SimpleNamespace(
            config=SimpleNamespace(runtime_scope_id="scope-1"),
            _run_dir_path=lambda run_id: Path("/tmp/runtime") / run_id,
            _service_enabled_for_mode=lambda _mode, _service_name: False,
        )
        contexts = [SimpleNamespace(name="feature-a-1", root=Path("/tmp/repo/trees/feature-a/1"), ports={})]
        route = parse_route(["--trees", "--isolated-deps"], env={})
        session = StartupSession(
            requested_route=route,
            effective_route=route,
            requested_command="start",
            runtime_mode="trees",
            run_id="run-1",
            selected_contexts=contexts,
        )

        state = build_success_run_state(runtime, session)  # type: ignore[arg-type]

        self.assertNotEqual(state.metadata.get("dashboard_dependency_scope"), "shared")
        self.assertNotIn("dashboard_shared_dependency_project", state.metadata)
        self.assertEqual(state.metadata.get("dependency_mode"), "isolated")
        self.assertFalse(state.metadata.get("shared_dependencies"))
        self.assertEqual(state.metadata.get("dependency_scope_requested"), "isolated")

    def test_build_run_state_marks_main_dependency_mode_as_shared(self) -> None:
        runtime = SimpleNamespace(
            config=SimpleNamespace(runtime_scope_id="scope-1"),
            _run_dir_path=lambda run_id: Path("/tmp/runtime") / run_id,
            _service_enabled_for_mode=lambda _mode, _service_name: False,
        )
        contexts = [SimpleNamespace(name="Main", root=Path("/tmp/repo"), ports={})]
        route = parse_route(["--main"], env={})
        session = StartupSession(
            requested_route=route,
            effective_route=route,
            requested_command="start",
            runtime_mode="main",
            run_id="run-main",
            selected_contexts=contexts,
        )

        state = build_success_run_state(runtime, session)  # type: ignore[arg-type]

        self.assertEqual(state.metadata.get("dependency_mode"), "shared")
        self.assertTrue(state.metadata.get("shared_dependencies"))

    def test_build_run_state_merges_preserved_services_before_new_project_results(self) -> None:
        runtime = SimpleNamespace(
            config=SimpleNamespace(runtime_scope_id="scope-1"),
            _run_dir_path=lambda run_id: Path("/tmp/runtime") / run_id,
            _service_enabled_for_mode=lambda _mode, _service_name: False,
        )
        context = SimpleNamespace(name="Main", root=Path("/tmp/repo"), ports={})
        route = parse_route(["--main"], env={})
        preserved_backend = ServiceRecord(name="Main Backend", type="backend", cwd="/tmp/repo/backend", pid=1111)
        new_backend = ServiceRecord(name="Main Backend", type="backend", cwd="/tmp/repo/backend", pid=2222)
        preserved_worker = ServiceRecord(name="Main Worker", type="worker", cwd="/tmp/repo/worker", pid=3333)
        session = StartupSession(
            requested_route=route,
            effective_route=route,
            requested_command="start",
            runtime_mode="main",
            run_id="run-main",
            selected_contexts=[context],
            preserved_services={
                "Main Backend": preserved_backend,
                "Main Worker": preserved_worker,
            },
            preserved_requirements={
                "Main": RequirementsResult(project="Main", redis={"enabled": True, "success": True, "final": 6379})
            },
            services_by_project={"Main": {"Main Backend": new_backend}},
            requirements_by_project={
                "Main": RequirementsResult(project="Main", redis={"enabled": True, "success": True, "final": 6380})
            },
        )

        state = build_success_run_state(runtime, session)  # type: ignore[arg-type]

        self.assertIs(state.services["Main Backend"], new_backend)
        self.assertIs(state.services["Main Worker"], preserved_worker)
        self.assertEqual(state.requirements["Main"].redis["final"], 6380)

    def test_restart_service_types_respect_default_service_set(self) -> None:
        route = parse_route(["restart", "--service", "Main Frontend"], env={"ENVCTL_DEFAULT_MODE": "main"})
        route.flags["_restart_request"] = True

        selected = StartupOrchestrator._restart_service_types_for_project(
            route=route,
            project_name="Main",
            default_service_types={"backend"},
        )

        self.assertEqual(selected, set())

    def test_restart_explicit_empty_service_types_selects_no_app_services(self) -> None:
        route = Route(
            command="restart",
            mode="trees",
            raw_args=["restart"],
            passthrough_args=[],
            projects=["feature-a-1"],
            flags={
                "services": [],
                "restart_service_types": [],
                "restart_include_requirements": True,
                "_restart_request": True,
            },
        )

        selected = StartupOrchestrator._restart_service_types_for_project(
            route=route,
            project_name="feature-a-1",
            default_service_types={"backend", "frontend", "voice-runtime"},
            additional_services=(SimpleNamespace(name="voice-runtime", depends_on=("backend",), start_order=100),),
        )

        self.assertEqual(selected, set())


    def test_start_service_selector_expands_configured_service_dependencies_with_event(self) -> None:
        config = SimpleNamespace(
            additional_services=(
                SimpleNamespace(
                    name="voice-runtime",
                    depends_on=("backend",),
                    start_order=100,
                ),
            )
        )
        route = Route(
            command="start",
            mode="main",
            flags={"services": ["voice-runtime"]},
            raw_args=["start", "--service", "voice-runtime"],
        )
        emitted: list[tuple[str, dict[str, object]]] = []
        route.flags["emit_service_dependency"] = lambda **payload: emitted.append(("emit", payload))

        selected = _restart_service_types_for_project(
            route=route,
            project_name="Main",
            default_service_types={"backend", "frontend", "voice-runtime"},
            additional_services=config.additional_services,
        )

        self.assertEqual(selected, {"backend", "voice-runtime"})
        self.assertEqual(emitted[0][1]["service"], "voice-runtime")
        self.assertEqual(emitted[0][1]["dependency"], "backend")

    def test_start_service_selector_can_ignore_configured_service_dependencies(self) -> None:
        route = Route(
            command="start",
            mode="main",
            flags={"services": ["voice-runtime"], "ignore_service_deps": True},
            raw_args=["start", "--service", "voice-runtime", "--ignore-service-deps"],
        )

        selected = _restart_service_types_for_project(
            route=route,
            project_name="Main",
            default_service_types={"backend", "frontend", "voice-runtime"},
            additional_services=(SimpleNamespace(name="voice-runtime", depends_on=("backend",), start_order=100),),
        )

        self.assertEqual(selected, {"voice-runtime"})

    def test_restart_additional_service_selectors_preserve_project_and_service_type(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd="/repo/backend"),
                "Main Voice Runtime": ServiceRecord(
                    name="Main Voice Runtime",
                    type="voice-runtime",
                    cwd="/repo/voice-runtime",
                    project="Main",
                    service_slug="voice-runtime",
                ),
            },
        )
        runtime = SimpleNamespace(_project_name_from_service=lambda name: "Main" if name.startswith("Main ") else "")
        for selector in ("voice-runtime", "service:voice-runtime", "Voice Runtime", "Main Voice Runtime"):
            with self.subTest(selector=selector):
                route = Route(command="restart", mode="main", flags={"services": [selector], "_restart_request": True})
                selected = _restart_selected_services(state=state, route=route)
                targets = restart_target_projects(
                    state=state,
                    route=route,
                    runtime=runtime,
                )
                service_types = StartupOrchestrator._restart_service_types_for_project(
                    route=route,
                    project_name="Main",
                    default_service_types={"backend", "frontend", "voice-runtime"},
                )
                self.assertEqual(selected, {"Main Voice Runtime"})
                self.assertEqual(targets, {"Main"})
                self.assertEqual(service_types, {"voice-runtime"})

    def test_restart_service_types_accept_additional_service_slugs(self) -> None:
        route = Route(
            command="restart",
            mode="main",
            raw_args=[],
            passthrough_args=[],
            projects=["Main"],
            flags={"restart_service_types": ["voice-runtime"], "_restart_request": True},
        )

        selected = StartupOrchestrator._restart_service_types_for_project(
            route=route,
            project_name="Main",
            default_service_types={"backend", "frontend", "voice-runtime"},
            additional_services=(SimpleNamespace(name="voice-runtime", depends_on=("backend",), start_order=100),),
        )

        self.assertEqual(selected, {"voice-runtime"})

    def test_runtime_scope_flags_select_startup_service_types(self) -> None:
        backend_route = parse_route(["--backend"], env={})
        self.assertEqual(
            StartupOrchestrator._restart_service_types_for_project(
                route=backend_route,
                project_name="Main",
                default_service_types={"backend", "frontend"},
            ),
            {"backend"},
        )

        frontend_route = parse_route(["--frontend"], env={})
        self.assertEqual(
            StartupOrchestrator._restart_service_types_for_project(
                route=frontend_route,
                project_name="Main",
                default_service_types={"backend", "frontend"},
            ),
            {"frontend"},
        )

        dependencies_route = parse_route(["--dependencies"], env={})
        self.assertEqual(
            StartupOrchestrator._restart_service_types_for_project(
                route=dependencies_route,
                project_name="Main",
                default_service_types={"backend", "frontend"},
            ),
            set(),
        )

        fullstack_route = parse_route(["--fullstack"], env={})
        self.assertEqual(
            StartupOrchestrator._restart_service_types_for_project(
                route=fullstack_route,
                project_name="Main",
                default_service_types={"backend", "frontend"},
            ),
            {"backend", "frontend"},
        )

    def test_startup_only_flags_select_individual_worktree_launch_parts(self) -> None:
        route = parse_route(["--tree", "--fullstack", "--only-frontend"], env={})
        self.assertEqual(
            StartupOrchestrator._restart_service_types_for_project(
                route=route,
                project_name="feature-a-1",
                default_service_types={"backend", "frontend"},
            ),
            {"frontend"},
        )
        self.assertFalse(route.flags.get("launch_dependencies"))

        route = parse_route(["--tree", "--fullstack", "--only-backend"], env={})
        self.assertEqual(
            StartupOrchestrator._restart_service_types_for_project(
                route=route,
                project_name="feature-a-1",
                default_service_types={"backend", "frontend"},
            ),
            {"backend"},
        )
        self.assertFalse(route.flags.get("launch_dependencies"))

        route = parse_route(["--tree", "--fullstack", "--no-infra"], env={})
        self.assertEqual(
            StartupOrchestrator._restart_service_types_for_project(
                route=route,
                project_name="feature-a-1",
                default_service_types={"backend", "frontend"},
            ),
            set(),
        )

    def test_no_deps_disables_startup_requirements_for_worktree_runs(self) -> None:
        class Config:
            def startup_enabled_for_mode(self, mode: str) -> bool:
                return True

            def requirement_enabled_for_mode(self, mode: str, requirement_name: str) -> bool:
                return True

        runtime = SimpleNamespace(config=Config())
        route = parse_route(["--tree", "--no-deps"], env={})

        self.assertFalse(requirement_enabled_for_mode(runtime, "trees", "redis", route=route))

    def test_worktree_defaults_to_shared_deps_main_requirement_profile(self) -> None:
        class Config:
            def startup_enabled_for_mode(self, mode: str) -> bool:
                return True

            def requirement_enabled_for_mode(self, mode: str, requirement_name: str) -> bool:
                if mode == "main":
                    return requirement_name in {"redis", "n8n"}
                return False

        runtime = SimpleNamespace(config=Config())
        route = parse_route(["--trees"], env={})

        self.assertTrue(requirement_enabled_for_mode(runtime, "trees", "redis", route=route))
        self.assertTrue(requirement_enabled_for_mode(runtime, "trees", "n8n", route=route))
        self.assertFalse(requirement_enabled_for_mode(runtime, "trees", "postgres", route=route))

        isolated_route = parse_route(["--trees", "--isolated-deps"], env={})
        self.assertFalse(requirement_enabled_for_mode(runtime, "trees", "redis", route=isolated_route))

    def test_worktree_shared_dependency_default_is_disabled_by_app_only_flags(self) -> None:
        class Config:
            def startup_enabled_for_mode(self, mode: str) -> bool:
                return True

            def requirement_enabled_for_mode(self, mode: str, requirement_name: str) -> bool:
                return True

        runtime = SimpleNamespace(config=Config())
        for args in (
            ["--trees", "--no-deps"],
            ["--trees", "--only-backend"],
            ["--trees", "--only-frontend"],
            ["--trees", "--no-infra"],
        ):
            with self.subTest(args=args):
                route = parse_route(list(args), env={})
                self.assertFalse(requirement_enabled_for_mode(runtime, "trees", "redis", route=route))

    def test_runtime_scope_flags_control_restart_requirements(self) -> None:
        self.assertFalse(StartupOrchestrator._restart_include_requirements(parse_route(["restart", "--backend"], env={})))
        self.assertFalse(StartupOrchestrator._restart_include_requirements(parse_route(["restart", "--fullstack"], env={})))
        self.assertTrue(StartupOrchestrator._restart_include_requirements(parse_route(["restart", "--dependencies"], env={})))
        self.assertTrue(StartupOrchestrator._restart_include_requirements(parse_route(["restart", "--entire-system"], env={})))
        self.assertTrue(StartupOrchestrator._restart_include_requirements(parse_route(["restart"], env={})))
        self.assertFalse(
            StartupOrchestrator._restart_include_requirements(
                parse_route(["restart", "--service", "Main Frontend"], env={})
            )
        )

    def test_non_restart_defaults_to_configured_service_types(self) -> None:
        selected = StartupOrchestrator._restart_service_types_for_project(
            route=None,
            project_name="Main",
            default_service_types={"frontend"},
        )

        self.assertEqual(selected, {"frontend"})


if __name__ == "__main__":
    unittest.main()
