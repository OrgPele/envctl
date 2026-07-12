from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.runtime.command_router import Route, parse_route
from envctl_engine.startup.resume_restore_execution import (
    _apply_restore_runtime_mode,
    _projects_to_restore,
    _route_for_resume_restore,
)
from envctl_engine.startup.resume_restore_policy import (
    _configured_restore_service_types,
    _requirements_reuse_decision,
    _reserve_application_service_ports,
    _restore_parallel_config,
    _route_for_partial_service_restore,
    _service_types_for_names,
    apply_ports_to_context,
    project_root,
)
from envctl_engine.startup.resume_restore_results import apply_restore_result
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord


class ResumeRestorePolicyTests(unittest.TestCase):
    def test_docker_state_forces_docker_mode_for_direct_resume_restore(self) -> None:
        state = RunState(
            run_id="run-docker",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd="/repo/backend",
                    runtime_kind="docker",
                    container_id="stale-container",
                )
            },
        )
        route = Route(command="resume", mode="main", flags={"batch": True})

        restored_route = _route_for_resume_restore(
            route,
            state=state,
            suppress_timing_output=False,
        )

        self.assertTrue(restored_route.flags["docker"])
        self.assertTrue(restored_route.flags["_resume_restore"])
        self.assertTrue(restored_route.flags["batch"])
        runtime = SimpleNamespace(env={})
        _apply_restore_runtime_mode(runtime, restored_route)
        self.assertEqual(runtime.env["DOCKER_MODE"], "true")

    def test_plan_resume_defaults_to_parallel_tree_restore(self) -> None:
        captured_routes: list[Route] = []

        runtime = SimpleNamespace(
            _tree_parallel_startup_config=lambda **kwargs: captured_routes.append(kwargs["route"]) or (True, 3),
        )
        route = Route(
            command="resume",
            mode="main",
            raw_args=[],
            passthrough_args=[],
            projects=[],
            flags={"_resume_source_command": "plan"},
        )

        enabled, workers = _restore_parallel_config(
            SimpleNamespace(runtime=runtime),
            route=route,
            mode="main",
            project_count=3,
        )

        self.assertTrue(enabled)
        self.assertEqual(workers, 3)
        self.assertEqual(captured_routes[0].flags["parallel_trees"], True)

    def test_partial_restore_route_preserves_flags_and_adds_sorted_service_types(self) -> None:
        route = parse_route(["resume", "--main"], env={})

        updated = _route_for_partial_service_restore(
            route,
            selected_service_types={"frontend", "backend"},
        )

        self.assertTrue(updated.flags["_restart_request"])
        self.assertEqual(updated.flags["restart_service_types"], ["backend", "frontend"])
        self.assertEqual(updated.command, route.command)
        self.assertEqual(updated.mode, route.mode)

    def test_configured_restore_service_types_merges_ports_and_additional_services(self) -> None:
        class ExtraService:
            name = "worker"

            def enabled_for_project_root(self, mode: str, root: Path | None) -> bool:
                return mode == "main" and root == Path("/repo")

        runtime = SimpleNamespace(
            config=SimpleNamespace(additional_services=(ExtraService(),)),
            _service_enabled_for_mode=lambda mode, service: service == "backend",
        )
        context = SimpleNamespace(root=Path("/repo"), ports={"backend": object(), "frontend": object()})

        self.assertEqual(
            _configured_restore_service_types(runtime, mode="main", context=context),
            {"backend", "worker"},
        )

    def test_service_types_for_names_uses_record_type_before_name_suffix(self) -> None:
        services = {
            "Main API": ServiceRecord(name="Main API", type="backend", cwd="/repo/backend"),
            "Main Worker": ServiceRecord(name="Main Worker", type="", cwd="/repo/worker"),
        }

        self.assertEqual(
            _service_types_for_names(project="Main", service_names=list(services), services=services),
            {"backend", "worker"},
        )

    def test_requirements_reuse_reconciles_endpoint_truth(self) -> None:
        requirements = RequirementsResult(project="Main", health="healthy")
        runtime = SimpleNamespace(
            _requirements_ready=lambda req: True,
            _reconcile_project_requirement_truth=lambda project, req, project_root=None: ["postgres changed"],
        )

        reused, reason = _requirements_reuse_decision(
            SimpleNamespace(),
            runtime,
            project="Main",
            requirements=requirements,
            project_root=Path("/repo"),
        )

        self.assertFalse(reused)
        self.assertEqual(reason, "dependency_endpoint_changed")

    def test_reserve_application_service_ports_rebinds_and_emits_events(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        testcase = self

        class Allocator:
            def reserve_next(self, preferred: int, *, owner: str) -> int:
                testcase.assertEqual(preferred, 8000)
                testcase.assertEqual(owner, "Main:backend")
                return 8100

            def update_final_port(self, plan: object, final_port: int, *, source: str) -> None:
                testcase.assertEqual(source, "retry")
                plan.final = final_port

        plan = SimpleNamespace(assigned=8000, final=8000)
        runtime = SimpleNamespace(_emit=lambda event, **payload: events.append((event, payload)))
        context = SimpleNamespace(name="Main", ports={"backend": plan, "frontend": SimpleNamespace(assigned=9000, final=9000)})

        _reserve_application_service_ports(
            SimpleNamespace(),
            runtime,
            context,
            Allocator(),
            selected_service_types={"backend"},
        )

        self.assertEqual(plan.final, 8100)
        self.assertEqual([event for event, _payload in events], ["port.rebound", "port.reserved"])

    def test_project_root_uses_metadata_then_service_cwd_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            backend = repo / "backend"
            backend.mkdir(parents=True)
            runtime = SimpleNamespace(
                config=SimpleNamespace(base_dir=Path(tmpdir)),
                _project_name_from_service=lambda _name: "Feature",
            )
            state = SimpleNamespace(
                metadata={},
                services={"Feature Backend": SimpleNamespace(cwd=str(backend))},
            )

            self.assertEqual(project_root(SimpleNamespace(runtime=runtime), state, "Feature"), repo)

    def test_resume_project_discovery_and_root_prefer_service_project_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service_root = Path(tmpdir) / "customer-platform" / "voice"
            service_root.mkdir(parents=True)
            service = ServiceRecord(
                name="Opaque Runtime Process",
                type="voice-runtime",
                cwd=str(service_root),
                project="Customer Platform",
            )
            state = RunState(
                run_id="run-extra",
                mode="trees",
                services={service.name: service},
            )
            runtime = SimpleNamespace(
                config=SimpleNamespace(base_dir=Path(tmpdir)),
                _project_name_from_service=lambda _name: "Opaque Runtime",
                _requirements_ready=lambda _requirements: True,
            )

            self.assertEqual(
                _projects_to_restore(runtime, state=state, missing_services=[service.name]),
                ["Customer Platform"],
            )
            self.assertEqual(
                project_root(SimpleNamespace(runtime=runtime), state, "Customer Platform"),
                service_root,
            )

    def test_projects_to_restore_deduplicates_service_and_requirement_project_case(self) -> None:
        service = ServiceRecord(
            name="Main Backend",
            type="backend",
            cwd="/tmp/repo/backend",
            project="Main",
        )
        requirements = RequirementsResult(project="main", health="degraded")
        state = RunState(
            run_id="run-casefold",
            mode="main",
            services={service.name: service},
            requirements={"main": requirements},
        )
        runtime = SimpleNamespace(
            _project_name_from_service=lambda _name: "Main",
            _requirements_ready=lambda value: value is not requirements,
        )

        self.assertEqual(
            _projects_to_restore(runtime, state=state, missing_services=[service.name]),
            ["Main"],
        )

    def test_apply_ports_to_context_projects_service_ports(self) -> None:
        backend_plan = SimpleNamespace(port=None)
        frontend_plan = SimpleNamespace(port=None)
        calls: list[tuple[object, int]] = []
        runtime = SimpleNamespace(
            _project_name_from_service=lambda _name: "Main",
            _set_plan_port=lambda plan, port: calls.append((plan, port)),
            _set_plan_port_from_component=lambda plan, component: None,
        )
        context = SimpleNamespace(name="Main", ports={"backend": backend_plan, "frontend": frontend_plan})
        state = SimpleNamespace(
            requirements={},
            services={
                "Main Backend": SimpleNamespace(type="backend", actual_port=8000, requested_port=8000),
                "Main Frontend": SimpleNamespace(type="frontend", actual_port=9000, requested_port=9000),
            },
        )

        apply_ports_to_context(SimpleNamespace(runtime=runtime), context, state)

        self.assertEqual(calls, [(backend_plan, 8000), (frontend_plan, 9000)])

    def test_apply_ports_to_context_uses_record_project_metadata(self) -> None:
        backend_plan = SimpleNamespace(port=None)
        calls: list[tuple[object, int]] = []
        runtime = SimpleNamespace(
            _project_name_from_service=lambda _name: "Opaque Runtime",
            _set_plan_port=lambda plan, port: calls.append((plan, port)),
            _set_plan_port_from_component=lambda plan, component: None,
        )
        context = SimpleNamespace(
            name="Customer Platform",
            ports={"backend": backend_plan, "frontend": SimpleNamespace(port=None)},
        )
        service = ServiceRecord(
            name="Opaque API Process",
            type="backend",
            cwd="/tmp/customer-platform/api",
            actual_port=8100,
            project="Customer Platform",
        )
        state = RunState(run_id="run-ports", mode="trees", services={service.name: service})

        apply_ports_to_context(SimpleNamespace(runtime=runtime), context, state)

        self.assertEqual(calls, [(backend_plan, 8100)])

    def test_apply_ports_to_context_finds_case_insensitive_requirements_key(self) -> None:
        db_plan = SimpleNamespace(port=None)
        projected: list[tuple[object, dict[str, object]]] = []
        runtime = SimpleNamespace(
            _project_name_from_service=lambda _name: "Main",
            _set_plan_port=lambda _plan, _port: None,
            _set_plan_port_from_component=lambda plan, component: projected.append((plan, component)),
        )
        context = SimpleNamespace(name="Main", ports={"db": db_plan})
        requirements = RequirementsResult(
            project="main",
            db={"enabled": True, "success": True, "final": 5544},
        )
        state = RunState(
            run_id="run-requirement-case",
            mode="main",
            requirements={"main": requirements},
        )

        apply_ports_to_context(SimpleNamespace(runtime=runtime), context, state)

        self.assertIn((db_plan, requirements.db), projected)

    def test_failed_restore_retains_unterminated_service_under_collision_safe_key(self) -> None:
        old = ServiceRecord(
            name="Main Backend",
            type="backend",
            cwd="/tmp/repo/backend",
            project="Main",
            pid=1111,
            status="running",
        )
        replacement = ServiceRecord(
            name="Main Backend",
            type="backend",
            cwd="/tmp/repo/backend",
            project="Main",
            pid=2222,
            status="starting",
        )
        state = RunState(run_id="run-collision", mode="main", services={old.name: old})
        errors: list[str] = []

        apply_restore_result(
            state,
            project="Main",
            result={
                "error": "replacement cleanup was unconfirmed",
                "unterminated_services": {replacement.name: replacement},
            },
            errors=errors,
            timing_enabled=False,
            timing_lines=[],
            project_totals_ms={},
        )

        self.assertEqual({service.pid for service in state.services.values()}, {1111, 2222})
        collision_name = next(name for name in state.services if "Resume Collision" in name)
        self.assertEqual(state.services[collision_name].status, "termination_failed")
        self.assertTrue(state.services[collision_name].degraded)
        self.assertEqual(state.metadata["termination_failed_services"], [collision_name])
        self.assertEqual(errors, ["Main: replacement cleanup was unconfirmed"])

    def test_successful_restore_retains_cross_project_service_name_collisions(self) -> None:
        state = RunState(run_id="run-success-collision", mode="trees")

        for project, pid in (("Alpha", 101), ("Beta", 202)):
            service = ServiceRecord(
                name="Shared Worker",
                type="worker",
                cwd=f"/{project.casefold()}",
                project=project,
                pid=pid,
                status="running",
            )
            apply_restore_result(
                state,
                project=project,
                result={
                    "error": None,
                    "remove_service_names": ["Shared Worker"],
                    "project_services": {"Shared Worker": service},
                },
                errors=[],
                timing_enabled=False,
                timing_lines=[],
                project_totals_ms={},
            )

        self.assertEqual({service.pid for service in state.services.values()}, {101, 202})
        self.assertEqual({service.project for service in state.services.values()}, {"Alpha", "Beta"})
        collision_name = next(name for name in state.services if "Resume Collision" in name)
        self.assertEqual(state.services[collision_name].name, collision_name)


if __name__ == "__main__":
    unittest.main()
