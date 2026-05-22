from __future__ import annotations

from contextlib import nullcontext
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import cast
import tempfile
import threading
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.startup.resume_restore_support import restore_missing  # noqa: E402
import envctl_engine.startup.requirements_execution as requirements_execution_module  # noqa: E402
from envctl_engine.startup.protocols import StartupOrchestratorLike  # noqa: E402
from envctl_engine.startup.requirements_execution import (  # noqa: E402
    requirements_parallel_enabled,
    start_requirements_for_project as requirements_start_impl,
)
from envctl_engine.startup.service_execution import start_project_services as service_start_impl  # noqa: E402
from envctl_engine.startup.startup_execution_support import (  # noqa: E402
    _annotate_shared_main_requirements,
    _maybe_prewarm_docker,
    _requirements_failure_message,
    _shared_main_requirements,
    start_requirements_for_project,
    start_project_services,
    start_project_context,
)
from envctl_engine.startup.startup_orchestrator import StartupOrchestrator  # noqa: E402
from envctl_engine.startup.startup_selection_support import _tree_preselected_projects_from_state  # noqa: E402
from envctl_engine.config import AppServiceConfig  # noqa: E402
from envctl_engine.runtime.command_router import parse_route  # noqa: E402
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord  # noqa: E402


class _SpinnerStub:
    def __enter__(self) -> "_SpinnerStub":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def update(self, message: str) -> None:
        _ = message

    def fail(self, message: str) -> None:
        _ = message

    def succeed(self, message: str) -> None:
        _ = message


class _PortAllocatorStub:
    def reserve_next(self, preferred: int, *, owner: str) -> int:
        _ = owner
        return preferred

    def update_final_port(self, plan: object, final_port: int, *, source: str) -> None:
        _ = (plan, final_port, source)

    def release(self, port: int) -> None:
        _ = port


class StartupSupportModuleDecouplingTests(unittest.TestCase):
    def test_startup_execution_support_reexports_new_owner_modules(self) -> None:
        self.assertIs(start_requirements_for_project, requirements_start_impl)
        self.assertIs(start_project_services, service_start_impl)

    def test_startup_orchestrator_does_not_retain_selected_context_pass_through_wrappers(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_record_project_startup"))
        self.assertFalse(hasattr(StartupOrchestrator, "_record_plan_agent_handoff_local_startup_failure"))

    def test_startup_orchestrator_does_not_retain_selected_context_startup_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_start_selected_contexts"))

    def test_startup_orchestrator_does_not_retain_context_selection_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_select_contexts"))

    def test_startup_orchestrator_does_not_retain_restart_port_application_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_apply_restart_ports"))

    def test_startup_orchestrator_does_not_retain_tree_selection_pass_through_wrappers(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_trees_start_selection_required"))
        self.assertFalse(hasattr(StartupOrchestrator, "_select_start_tree_projects"))

    def test_startup_orchestrator_does_not_retain_process_runtime_pass_through_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_process_runtime"))

    def test_startup_orchestrator_does_not_retain_restart_selection_pass_through_wrappers(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_restart_include_requirements"))
        self.assertFalse(hasattr(StartupOrchestrator, "_restart_service_types_for_project"))

    def test_startup_orchestrator_does_not_retain_prewarm_pass_through_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_maybe_prewarm_docker"))

    def test_startup_orchestrator_does_not_retain_requirements_timing_pass_through_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_requirements_timing_enabled"))

    def test_startup_orchestrator_does_not_retain_configured_service_types_pass_through_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_configured_service_types_for_mode"))

    def test_startup_orchestrator_does_not_retain_project_warning_render_pass_through_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_render_project_startup_warnings"))

    def test_startup_orchestrator_does_not_retain_fresh_start_replacement_services_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_fresh_start_replacement_services"))

    def test_startup_orchestrator_does_not_retain_dashboard_stopped_services_static_wrappers(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_dashboard_stopped_service_entries"))
        self.assertFalse(hasattr(StartupOrchestrator, "_metadata_without_dashboard_stopped_services"))

    def test_startup_orchestrator_does_not_retain_restart_requirements_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_requirements_for_restart_context"))

    def test_startup_orchestrator_does_not_retain_suppress_timing_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_suppress_timing_output"))

    def test_startup_orchestrator_does_not_retain_suppress_progress_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_suppress_progress_output"))

    def test_startup_orchestrator_does_not_retain_report_progress_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_report_progress"))

    def test_startup_orchestrator_does_not_retain_process_cwd_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_process_cwd"))

    def test_startup_orchestrator_does_not_retain_plan_dry_run_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_resolve_plan_dry_run"))

    def test_startup_orchestrator_does_not_retain_emit_snapshot_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_emit_snapshot"))

    def test_startup_orchestrator_does_not_retain_emit_phase_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_emit_phase"))

    def test_startup_orchestrator_does_not_retain_plan_agent_handoff_decision_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_should_degrade_to_plan_agent_handoff"))

    def test_startup_orchestrator_does_not_retain_run_reuse_replacement_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_replace_existing_project_services_for_fresh_start"))

    def test_startup_orchestrator_does_not_retain_dashboard_stopped_restore_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_prepare_dashboard_stopped_service_restore"))

    def test_startup_orchestrator_does_not_retain_plan_agent_handoff_validation_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_validate_plan_agent_handoff"))

    def test_startup_orchestrator_does_not_retain_plan_agent_launch_spinner_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_launch_plan_agent_terminals_with_spinner"))

    def test_startup_orchestrator_does_not_retain_prepare_execution_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_prepare_execution"))

    def test_startup_orchestrator_does_not_retain_route_contract_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_validate_route_contract"))

    def test_startup_orchestrator_does_not_retain_run_id_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_ensure_run_id"))

    def test_startup_orchestrator_does_not_retain_resolved_run_id_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_resolved_run_id"))

    def test_startup_orchestrator_does_not_retain_announce_session_identifiers_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_announce_session_identifiers"))

    def test_startup_orchestrator_does_not_retain_create_session_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_create_session"))

    def test_startup_orchestrator_does_not_retain_strict_truth_reconcile_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_reconcile_strict_truth"))

    def test_startup_orchestrator_does_not_retain_finalize_failure_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_finalize_failure"))

    def test_startup_orchestrator_does_not_retain_degraded_handoff_finalization_wrapper(self) -> None:
        self.assertFalse(hasattr(StartupOrchestrator, "_finalize_plan_agent_degraded_handoff"))

    def test_requirements_parallel_defaults_to_sequential_on_macos_with_cli_override(self) -> None:
        runtime = SimpleNamespace(env={}, config=SimpleNamespace(raw={}))
        orchestrator = SimpleNamespace(runtime=runtime)

        with mock.patch.object(requirements_execution_module.sys, "platform", "darwin"):
            self.assertFalse(
                requirements_parallel_enabled(orchestrator, route=parse_route(["start"], env={}), enabled_count=3)
            )
            self.assertTrue(
                requirements_parallel_enabled(
                    orchestrator,
                    route=parse_route(["start", "--deps-parallel"], env={}),
                    enabled_count=3,
                )
            )

        with mock.patch.object(requirements_execution_module.sys, "platform", "linux"):
            self.assertTrue(
                requirements_parallel_enabled(orchestrator, route=parse_route(["start"], env={}), enabled_count=3)
            )
            self.assertFalse(
                requirements_parallel_enabled(
                    orchestrator,
                    route=parse_route(["start", "--requirements-sequential"], env={}),
                    enabled_count=3,
                )
            )

        runtime.env["ENVCTL_REQUIREMENTS_PARALLEL"] = "true"
        with mock.patch.object(requirements_execution_module.sys, "platform", "darwin"):
            self.assertTrue(
                requirements_parallel_enabled(orchestrator, route=parse_route(["start"], env={}), enabled_count=3)
            )

    def test_annotate_shared_main_requirements_reconciles_container_ports_before_reuse(self) -> None:
        requirements = RequirementsResult(
            project="Main",
            supabase={
                "enabled": True,
                "success": True,
                "final": 5662,
                "resources": {"primary": 5662, "db": 5662, "api": 54551},
            },
        )

        def reconcile(project, req, *, project_root=None):  # noqa: ANN001, ANN202
            self.assertEqual(project, "Main")
            self.assertEqual(project_root, Path("/tmp/repo"))
            req.component("supabase")["final"] = 5574
            req.component("supabase")["resources"]["primary"] = 5574
            req.component("supabase")["resources"]["db"] = 5574
            req.component("supabase")["resources"]["api"] = 54463
            return []

        orchestrator = SimpleNamespace(
            runtime=SimpleNamespace(
                config=SimpleNamespace(execution_root=Path("/tmp/repo")),
                _reconcile_project_requirement_truth=reconcile,
            )
        )

        cloned = _annotate_shared_main_requirements(orchestrator, requirements)

        self.assertEqual(requirements.component("supabase")["final"], 5662)
        self.assertEqual(cloned.component("supabase")["final"], 5574)
        self.assertEqual(cloned.component("supabase")["resources"]["db"], 5574)
        self.assertEqual(cloned.component("supabase")["resources"]["api"], 54463)

    def test_shared_main_requirements_reconciles_cached_requirements_before_reuse(self) -> None:
        requirements = RequirementsResult(
            project="Main",
            supabase={
                "enabled": True,
                "success": True,
                "final": 5662,
                "resources": {"primary": 5662, "db": 5662, "api": 54551},
            },
        )

        def reconcile(project, req, *, project_root=None):  # noqa: ANN001, ANN202
            self.assertEqual(project, "Main")
            self.assertEqual(project_root, Path("/tmp/repo"))
            req.component("supabase")["final"] = 5574
            req.component("supabase")["resources"]["primary"] = 5574
            req.component("supabase")["resources"]["db"] = 5574
            req.component("supabase")["resources"]["api"] = 54463
            return []

        orchestrator = SimpleNamespace(
            _shared_dependency_requirements=requirements,
            runtime=SimpleNamespace(
                config=SimpleNamespace(execution_root=Path("/tmp/repo")),
                _reconcile_project_requirement_truth=reconcile,
            ),
        )

        reused = _shared_main_requirements(orchestrator, route=parse_route(["start"], env={}))

        self.assertIs(reused, requirements)
        self.assertEqual(reused.component("supabase")["final"], 5574)
        self.assertEqual(reused.component("supabase")["resources"]["db"], 5574)
        self.assertEqual(reused.component("supabase")["resources"]["api"], 54463)

    def test_shared_main_requirements_starts_fresh_when_existing_state_reconciles_unreachable(self) -> None:
        stale = RequirementsResult(
            project="Main",
            redis={"enabled": True, "success": True, "final": 6496},
            supabase={"enabled": True, "success": True, "final": 5446},
            n8n={"enabled": True, "success": True, "final": 5795},
        )
        fresh = RequirementsResult(
            project="Main",
            redis={"enabled": True, "success": True, "final": 6557, "runtime_status": "healthy"},
            supabase={"enabled": True, "success": True, "final": 5610, "runtime_status": "healthy"},
            n8n={"enabled": True, "success": True, "final": 5856, "runtime_status": "healthy"},
        )
        events: list[tuple[str, dict[str, object]]] = []
        reserved: list[str] = []

        def reconcile(project, req, *, project_root=None):  # noqa: ANN001, ANN202
            self.assertEqual(project, "Main")
            self.assertEqual(project_root, Path("/tmp/repo"))
            for dependency_id in ("redis", "supabase", "n8n"):
                component = req.component(dependency_id)
                component["runtime_status"] = "healthy" if component.get("final") in {6557, 5610, 5856} else "unreachable"
            return [
                {"project": project, "component": dependency_id, "status": "unreachable"}
                for dependency_id in ("redis", "supabase", "n8n")
                if req.component(dependency_id).get("runtime_status") == "unreachable"
            ]

        orchestrator = cast(
            StartupOrchestratorLike,
            SimpleNamespace(
                runtime=SimpleNamespace(
                    config=SimpleNamespace(execution_root=Path("/tmp/repo")),
                    port_planner=SimpleNamespace(plan_project_stack=lambda project, index=0: {}),
                    _try_load_existing_state=lambda mode, strict_mode_match: RunState(
                        run_id="run-stale-main",
                        mode="main",
                        requirements={"Main": stale},
                    ),
                    _requirements_ready=lambda req: all(
                        not bool(req.component(dependency_id).get("enabled", False))
                        or bool(req.component(dependency_id).get("success", False))
                        for dependency_id in ("redis", "supabase", "n8n")
                    ),
                    _reconcile_project_requirement_truth=reconcile,
                    _reserve_project_ports=lambda context: reserved.append(context.name),
                    _emit=lambda event, **payload: events.append((event, payload)),
                )
            )
        )

        with mock.patch(
            "envctl_engine.startup.startup_execution_support.requirements_for_restart_context",
            return_value=fresh,
        ) as start_requirements:
            reused = _shared_main_requirements(orchestrator, route=parse_route(["start"], env={}))

        self.assertEqual(reused.component("redis")["final"], 6557)
        self.assertEqual(reused.component("supabase")["final"], 5610)
        self.assertEqual(reused.component("n8n")["final"], 5856)
        self.assertEqual(reserved, ["Main"])
        self.assertEqual(start_requirements.call_count, 1)
        self.assertIn(("requirements.shared.reuse_stale", {"project": "Main", "source_run_id": "run-stale-main"}), events)

    def test_start_project_context_rejects_invalid_supabase_auth_user_config_before_services(self) -> None:
        order: list[str] = []
        requirements = RequirementsResult(
            project="Main",
            supabase={
                "enabled": True,
                "success": True,
                "final": 5432,
                "resources": {"db": 5432, "api": 54321, "primary": 5432},
            },
            health="healthy",
            failures=[],
        )
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                supabase_auth_users=(),
                supabase_auth_user_errors=("Supabase Auth user 'e2e' requires ENVCTL_SUPABASE_USER_E2E_EMAIL",),
                supabase_auth_users_strict=True,
            ),
            _reserve_project_ports=lambda context: order.append("reserve"),
            _requirements_ready=lambda value: value is requirements,
            _record_project_startup_warning=lambda project, warning: None,
            _consume_project_startup_warnings=lambda project: [],
            _emit=lambda event, **payload: None,
            _assert_project_services_post_start_truth=lambda **kwargs: None,
            _terminate_started_services=lambda services: None,
            runtime_root=Path("/tmp/runtime-root"),
        )
        orchestrator = SimpleNamespace(
            runtime=runtime,
            _report_progress=lambda route, message, project=None: None,
            start_project_services=lambda context, requirements, run_id, route: order.append("services") or {},
            start_requirements_for_project=lambda context, mode, route: requirements,
        )

        with self.assertRaisesRegex(RuntimeError, "Invalid Supabase Auth user config"):
            start_project_context(
                orchestrator,
                context=SimpleNamespace(name="Main", root=Path("/tmp/repo"), ports={}),
                mode="main",
                route=parse_route(["start"], env={}),
                run_id="run-1",
            )

        self.assertNotIn("services", order)

    def test_start_project_context_syncs_supabase_auth_users_before_services(self) -> None:
        order: list[str] = []
        events: list[tuple[str, dict[str, object]]] = []
        auth_user = SimpleNamespace(name="e2e", email="e2e@example.test", enabled_for_mode=lambda _mode: True)
        requirements = RequirementsResult(
            project="Main",
            supabase={
                "enabled": True,
                "success": True,
                "final": 5432,
                "resources": {"db": 5432, "api": 54321, "primary": 5432},
            },
            health="healthy",
            failures=[],
        )

        def project_env(**kwargs):  # noqa: ANN003, ANN201
            _ = kwargs
            return {
                "SUPABASE_URL": "http://localhost:54321",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role-secret",
            }

        runtime = SimpleNamespace(
            config=SimpleNamespace(supabase_auth_users=(auth_user,), supabase_auth_users_strict=True),
            _reserve_project_ports=lambda context: order.append("reserve"),
            _requirements_ready=lambda value: value is requirements,
            _record_project_startup_warning=lambda project, warning: None,
            _consume_project_startup_warnings=lambda project: [],
            _emit=lambda event, **payload: (
                order.append(event), events.append((event, payload))
            ) if event.startswith("supabase.auth_users") else None,
            _assert_project_services_post_start_truth=lambda **kwargs: None,
            _terminate_started_services=lambda services: None,
        )
        context = SimpleNamespace(name="Main", root=Path("/tmp/repo"), ports={})

        def sync(**kwargs):  # noqa: ANN003, ANN201
            order.append("sync")
            return SimpleNamespace(
                success=True,
                results=(SimpleNamespace(name="e2e", status="created", id="auth-user-id", email="e2e@example.test"),),
                artifact={"users": {"e2e": {"id": "auth-user-id", "email": "e2e@example.test", "status": "created"}}},
            )

        orchestrator = SimpleNamespace(
            runtime=runtime,
            _report_progress=lambda route, message, project=None: None,
            start_project_services=lambda context, requirements, run_id, route: order.append("services") or {},
            start_requirements_for_project=lambda context, mode, route: requirements,
        )
        with (
            mock.patch(
                "envctl_engine.startup.startup_execution_support._supabase_project_env",
                side_effect=project_env,
            ),
            mock.patch(
                "envctl_engine.startup.startup_execution_support.sync_supabase_auth_users",
                side_effect=sync,
            ),
        ):
            result = start_project_context(
                orchestrator,
                context=context,
                mode="main",
                route=parse_route(["start"], env={}),
                run_id="run-1",
            )

        self.assertEqual(order[0], "reserve")
        self.assertLess(order.index("sync"), order.index("services"))
        user_events = [payload for event, payload in events if event == "supabase.auth_users.sync.user"]
        self.assertEqual(len(user_events), 1)
        self.assertEqual(user_events[0]["email_hash"], hashlib.sha256(b"e2e@example.test").hexdigest())
        self.assertNotIn("email", user_events[0])
        self.assertEqual(result.requirements.supabase["auth_users"]["e2e"]["id"], "auth-user-id")

    def test_tree_preselected_projects_uses_local_state_helpers(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="trees",
            services={
                "Feature Backend": ServiceRecord(name="Feature Backend", type="backend", cwd="."),
            },
            requirements={
                "Main": RequirementsResult(project="Main", components={}, health="healthy", failures=[]),
            },
        )
        runtime = SimpleNamespace(
            _try_load_existing_state=lambda **kwargs: state,
            _project_name_from_service=lambda name: name.split()[0],
        )
        project_contexts = [
            SimpleNamespace(name="Main"),
            SimpleNamespace(name="Feature"),
            SimpleNamespace(name="Missing"),
        ]

        result = _tree_preselected_projects_from_state(
            runtime=runtime,
            project_contexts=project_contexts,
        )

        self.assertEqual(result, ["Feature", "Main"])

    def test_maybe_prewarm_docker_does_not_require_orchestrator_wrapper_methods(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(
            env={},
            config=SimpleNamespace(raw={}),
            _requirement_enabled=lambda requirement_id, mode, route: requirement_id == "postgres",
            _command_exists=lambda command: command == "docker",
            process_runner=SimpleNamespace(
                run=lambda command, timeout: SimpleNamespace(returncode=0, stderr="", stdout="")
            ),
            _emit=lambda event, **payload: events.append((event, payload)),
        )

        _maybe_prewarm_docker(SimpleNamespace(runtime=runtime), route=None, mode="main")

        self.assertEqual(events[-1][0], "requirements.docker_prewarm")
        self.assertEqual(events[-1][1]["used"], True)
        self.assertEqual(events[-1][1]["success"], True)
        self.assertEqual(events[-1][1]["command"], ["docker", "ps"])

    def test_restore_missing_uses_runtime_port_allocator_without_resume_wrappers(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(
            port_planner=_PortAllocatorStub(),
            env={},
            config=SimpleNamespace(raw={}, base_dir=Path("/tmp")),
            _project_name_from_service=lambda name: "Main",
            _requirements_ready=lambda requirements: True,
            _emit=lambda event, **payload: events.append((event, payload)),
            _tree_parallel_startup_config=lambda **kwargs: (False, 1),
            _resume_context_for_project=lambda state, project: None,
        )
        state = RunState(run_id="run-1", mode="main", services={}, requirements={})

        errors = restore_missing(
            SimpleNamespace(runtime=runtime),
            state,
            ["Main Backend"],
            spinner_factory=lambda *args, **kwargs: _SpinnerStub(),
            spinner_enabled_fn=lambda env: False,
            use_spinner_policy_fn=lambda policy: nullcontext(),
            emit_spinner_policy_fn=lambda emit, policy, context: None,
            resolve_spinner_policy_fn=lambda env: SimpleNamespace(enabled=False, backend="rich", style="dots"),
        )

        self.assertEqual(errors, ["Main: project root not found"])
        self.assertEqual(events[0][0], "resume.restore.execution")
        self.assertEqual(events[-1][0], "resume.restore.timing")

    def test_restore_missing_restarts_only_stale_services_when_requirements_are_healthy(self) -> None:
        released_ports: list[int] = []
        terminated_services: list[str] = []
        startup_routes: list[object] = []

        class RecordingPortAllocator:
            def reserve_next(self, preferred: int, *, owner: str) -> int:
                _ = owner
                return preferred

            def update_final_port(self, plan: object, final_port: int, *, source: str) -> None:
                _ = source
                plan.final = final_port

            def release(self, port: int) -> None:
                released_ports.append(port)

        context = SimpleNamespace(
            name="Main",
            root=Path("/tmp/repo"),
            ports={
                "backend": SimpleNamespace(assigned=8000, final=8000),
                "frontend": SimpleNamespace(assigned=9000, final=9000),
            },
        )
        requirements = RequirementsResult(project="Main", health="healthy")
        backend = ServiceRecord(
            name="Main Backend",
            type="backend",
            cwd="/tmp/repo/backend",
            pid=1111,
            requested_port=8000,
            actual_port=8000,
            status="running",
        )
        frontend = ServiceRecord(
            name="Main Frontend",
            type="frontend",
            cwd="/tmp/repo/frontend",
            pid=2222,
            requested_port=9000,
            actual_port=9000,
            status="stale",
        )

        def start_project_services(_context, *, requirements, run_id, route):  # noqa: ANN001
            _ = requirements, run_id
            startup_routes.append(route)
            return {
                "Main Frontend": ServiceRecord(
                    name="Main Frontend",
                    type="frontend",
                    cwd="/tmp/repo/frontend",
                    pid=3333,
                    requested_port=9000,
                    actual_port=9000,
                    status="running",
                )
            }

        runtime = SimpleNamespace(
            port_planner=RecordingPortAllocator(),
            env={},
            config=SimpleNamespace(raw={}, base_dir=Path("/tmp/repo")),
            _project_name_from_service=lambda name: "Main",
            _requirements_ready=lambda value: value is requirements and value.health == "healthy",
            _reconcile_project_requirement_truth=lambda project, req, project_root=None: [],
            _emit=lambda event, **payload: None,
            _tree_parallel_startup_config=lambda **kwargs: (False, 1),
            _resume_context_for_project=lambda state, project: context,
            _terminate_service_record=lambda service, **kwargs: terminated_services.append(service.name) or True,
            _service_port=lambda service: service.actual_port,
            _release_requirement_ports=lambda req: self.fail("healthy reused requirements should not be released"),
            _reserve_project_ports=lambda ctx: self.fail("partial service restore should reserve only selected services"),
            _start_requirements_for_project=lambda *args, **kwargs: self.fail("healthy requirements should be reused"),
            _start_project_services=start_project_services,
        )
        state = RunState(
            run_id="run-1",
            mode="main",
            services={"Main Backend": backend, "Main Frontend": frontend},
            requirements={"Main": requirements},
        )

        errors = restore_missing(
            SimpleNamespace(runtime=runtime),
            state,
            ["Main Frontend"],
            route=parse_route(["resume", "--main"], env={}),
            spinner_factory=lambda *args, **kwargs: _SpinnerStub(),
            spinner_enabled_fn=lambda env: False,
            use_spinner_policy_fn=lambda policy: nullcontext(),
            emit_spinner_policy_fn=lambda emit, policy, context: None,
            resolve_spinner_policy_fn=lambda env: SimpleNamespace(enabled=False, backend="rich", style="dots"),
        )

        self.assertEqual(errors, [])
        self.assertEqual(terminated_services, ["Main Frontend"])
        self.assertEqual(released_ports, [9000])
        self.assertIs(state.services["Main Backend"], backend)
        self.assertEqual(state.services["Main Frontend"].pid, 3333)
        self.assertEqual(len(startup_routes), 1)
        self.assertTrue(startup_routes[0].flags.get("_restart_request"))
        self.assertEqual(startup_routes[0].flags.get("restart_service_types"), ["frontend"])

    def test_requirements_failure_message_summarizes_docker_daemon_outage(self) -> None:
        requirements = RequirementsResult(
            project="Main",
            components={
                "redis": {
                    "enabled": True,
                    "success": False,
                    "error": (
                        "failed to connect to the docker API at "
                        "unix:///Users/kfiramar/.docker/run/docker.sock; "
                        "check if the path is correct and if the daemon is running"
                    ),
                },
                "n8n": {
                    "enabled": True,
                    "success": False,
                    "error": (
                        "failed to connect to the docker API at "
                        "unix:///Users/kfiramar/.docker/run/docker.sock; "
                        "check if the path is correct and if the daemon is running"
                    ),
                },
                "supabase": {
                    "enabled": True,
                    "success": False,
                    "error": (
                        "failed to connect to the docker API at "
                        "unix:///Users/kfiramar/.docker/run/docker.sock; "
                        "check if the path is correct and if the daemon is running"
                    ),
                },
            },
            health="degraded",
            failures=[
                "redis:FailureClass.HARD_START_FAILURE:failed to connect to the docker API",
                "n8n:FailureClass.HARD_START_FAILURE:failed to connect to the docker API",
                "supabase:FailureClass.HARD_START_FAILURE:failed to connect to the docker API",
            ],
        )

        message = _requirements_failure_message("Main", requirements)

        self.assertIn("Docker is not running.", message)
        self.assertIn("Docker is required for Main dependencies:", message)
        self.assertIn("redis", message)
        self.assertIn("supabase", message)
        self.assertIn("n8n", message)
        self.assertNotIn("FailureClass.HARD_START_FAILURE", message)

    def test_requirements_failure_message_falls_back_for_non_docker_errors(self) -> None:
        requirements = RequirementsResult(
            project="Main",
            components={
                "postgres": {
                    "enabled": True,
                    "success": False,
                    "error": "bind: address already in use",
                }
            },
            health="degraded",
            failures=["postgres:FailureClass.BIND_CONFLICT_RETRYABLE:bind: address already in use"],
        )

        message = _requirements_failure_message("Main", requirements)

        self.assertEqual(
            message,
            "Requirements unavailable for Main: "
            "postgres:FailureClass.BIND_CONFLICT_RETRYABLE:bind: address already in use",
        )

    def test_requirements_failure_message_keeps_supabase_auth_kong_traceback_condensed(self) -> None:
        concise_error = (
            "Supabase DB is healthy but Supabase Auth/Kong is not reachable at "
            "http://127.0.0.1:54321/auth/v1/health: "
            "phase=http services=supabase-auth,supabase-kong public_port=54321 "
            "actions=initial_probe,restart,recreate "
            "public_url=http://72.61.80.25:54321/auth/v1/health last_error="
            "urlopen error [Errno 111] Connection refused"
        )
        requirements = RequirementsResult(
            project="feature-a-1",
            components={
                "supabase": {
                    "enabled": True,
                    "success": False,
                    "error": concise_error,
                }
            },
            health="degraded",
            failures=[f"supabase:FailureClass.TRANSIENT_PROBE_TIMEOUT_RETRYABLE:{concise_error}"],
        )

        message = _requirements_failure_message("feature-a-1", requirements)

        self.assertIn("Requirements unavailable for feature-a-1", message)
        self.assertIn("supabase:FailureClass.TRANSIENT_PROBE_TIMEOUT_RETRYABLE", message)
        self.assertIn("phase=http", message)
        self.assertIn("services=supabase-auth,supabase-kong", message)
        self.assertIn("public_url=http://72.61.80.25:54321/auth/v1/health", message)
        self.assertIn("actions=initial_probe,restart,recreate", message)
        self.assertIn("Connection refused", message)
        self.assertNotIn("Traceback", message)
        self.assertNotIn('File "', message)

    def test_start_project_services_allows_parallel_prep_with_sequential_attach_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            project_root = root / "repo"
            project_root.mkdir(parents=True, exist_ok=True)
            run_dir = root / "runtime" / "run-1"
            prep_started = {
                "backend": threading.Event(),
                "frontend": threading.Event(),
            }
            overlap_hits: list[str] = []
            attach_modes: list[bool] = []

            def prepare_backend_runtime(**kwargs: object) -> None:
                _ = kwargs
                prep_started["backend"].set()
                if prep_started["frontend"].wait(0.2):
                    overlap_hits.append("backend")

            def prepare_frontend_runtime(**kwargs: object) -> None:
                _ = kwargs
                prep_started["frontend"].set()
                if prep_started["backend"].wait(0.2):
                    overlap_hits.append("frontend")

            def start_project_with_attach(**kwargs: object) -> dict[str, ServiceRecord]:
                attach_modes.append(bool(kwargs["parallel_start"]))
                return {
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(project_root),
                        status="running",
                        requested_port=8000,
                        actual_port=8000,
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(project_root),
                        status="running",
                        requested_port=3000,
                        actual_port=3000,
                    ),
                }

            runtime = SimpleNamespace(
                port_planner=_PortAllocatorStub(),
                env={},
                config=SimpleNamespace(raw={}, backend_dir_name="backend", frontend_dir_name="frontend"),
                services=SimpleNamespace(start_project_with_attach=start_project_with_attach),
                _invoke_envctl_hook=lambda **kwargs: SimpleNamespace(found=False, success=False, payload=None),
                _run_dir_path=lambda run_id: run_dir,
                _project_service_env=lambda context, requirements, route=None: {},
                _resolve_backend_env_file=lambda context, backend_cwd: (None, False),
                _resolve_frontend_env_file=lambda context, frontend_cwd: None,
                _service_env_from_file=lambda base_env, env_file, include_app_env_file, env_file_authoritative=False: dict(base_env),
                _service_enabled_for_mode=lambda mode, service: True,
                process_runner=SimpleNamespace(start_background=lambda *args, **kwargs: None),
                _prepare_backend_runtime=prepare_backend_runtime,
                _prepare_frontend_runtime=prepare_frontend_runtime,
                _service_command_source=lambda **kwargs: "configured",
                _emit=lambda event, **payload: None,
            )
            orchestrator = SimpleNamespace(
                runtime=runtime,
                _restart_service_types_for_project=lambda **kwargs: {"backend", "frontend"},
                _suppress_timing_output=lambda route: True,
            )
            context = SimpleNamespace(
                name="Main",
                root=project_root,
                ports={
                    "backend": SimpleNamespace(final=8000),
                    "frontend": SimpleNamespace(final=3000),
                },
            )
            requirements = RequirementsResult(project="Main", components={}, health="healthy", failures=[])
            route = parse_route(
                ["start", "--service-sequential", "--service-prep-parallel"],
                env={"ENVCTL_DEFAULT_MODE": "main"},
            )

            records = start_project_services(
                orchestrator,
                context,
                requirements=requirements,
                run_id="run-1",
                route=route,
            )

            self.assertIn("Main Backend", records)
            self.assertIn("Main Frontend", records)
            self.assertEqual(attach_modes, [False])
            self.assertEqual(sorted(overlap_hits), ["backend", "frontend"])

    def test_start_project_services_integrates_additional_listener_and_worker_by_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            project_root = root / "repo"
            for dirname in ("backend", "frontend", "voice-runtime", "worker"):
                (project_root / dirname).mkdir(parents=True, exist_ok=True)
            run_dir = root / "runtime" / "run-integration"
            voice = AppServiceConfig(
                name="voice-runtime",
                env_suffix="VOICE_RUNTIME",
                enabled_main=True,
                enabled_trees=False,
                dir_name="voice-runtime",
                start_cmd="python -m voice --port {port}",
                port_base=8010,
                public_url_template="http://${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_HOST}:${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PORT}",
                health_url_template="http://${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_HOST}:${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PORT}/readyz",
                depends_on=("backend",),
            )
            worker = AppServiceConfig(
                name="worker",
                env_suffix="WORKER",
                enabled_main=False,
                enabled_trees=True,
                dir_name="worker",
                start_cmd="python worker.py",
                expect_listener=False,
                depends_on=("frontend",),
            )
            started_layers: list[tuple[str, ...]] = []

            def service_enabled_for_mode(mode: str, service_name: str) -> bool:
                if service_name in {"backend", "frontend"}:
                    return True
                if service_name == "voice-runtime":
                    return mode == "main"
                if service_name == "worker":
                    return mode == "trees"
                return False

            def project_service_env(context, requirements, route=None, service_name=None):  # noqa: ANN001
                _ = requirements, route
                env = {"ENVCTL_PROJECT_NAME": context.name}
                if service_name == "voice-runtime":
                    port = context.ports["voice-runtime"].final
                    env.update(
                        {
                            "ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_HOST": "localhost",
                            "ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PORT": str(port),
                            "ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PUBLIC_URL": f"http://localhost:{port}",
                            "ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_HEALTH_URL": f"http://localhost:{port}/readyz",
                        }
                    )
                return env

            def start_services_with_attach(**kwargs: object) -> dict[str, ServiceRecord]:
                descriptors = tuple(kwargs["descriptors"])
                started_layers.append(tuple(descriptor.service_type for descriptor in descriptors))
                records: dict[str, ServiceRecord] = {}
                for descriptor in descriptors:
                    descriptor.start(descriptor.requested_port)
                    actual = descriptor.detect_actual(1234, descriptor.requested_port)
                    service_type = descriptor.service_type
                    name = {
                        "backend": "Main Backend",
                        "frontend": "Main Frontend",
                        "voice-runtime": "Main Voice Runtime",
                        "worker": "Main Worker",
                    }[service_type]
                    records[name] = ServiceRecord(
                        name=name,
                        type=service_type,
                        cwd=descriptor.cwd,
                        requested_port=descriptor.requested_port or None,
                        actual_port=actual or None,
                        status="running",
                        listener_expected=descriptor.listener_expected,
                        public_url=descriptor.public_url,
                        health_url=descriptor.health_url,
                        project="Main",
                        service_slug=service_type,
                    )
                return records

            runtime = SimpleNamespace(
                port_planner=_PortAllocatorStub(),
                env={
                    "ENVCTL_BACKEND_START_CMD": "python backend.py --port {port}",
                    "ENVCTL_FRONTEND_START_CMD": "npm run dev -- --port {port}",
                },
                config=SimpleNamespace(
                    raw={},
                    backend_dir_name="backend",
                    frontend_dir_name="frontend",
                    additional_services=(voice, worker),
                    all_app_service_names_for_mode=lambda mode: (
                        "backend",
                        "frontend",
                        *(service.name for service in (voice, worker) if service.enabled_for_mode(mode)),
                    ),
                    app_service_by_name=lambda name: {"voice-runtime": voice, "worker": worker}.get(name),
                ),
                services=SimpleNamespace(start_services_with_attach=start_services_with_attach),
                _invoke_envctl_hook=lambda **kwargs: SimpleNamespace(found=False, success=False, payload=None),
                _run_dir_path=lambda run_id: run_dir,
                _project_service_env=project_service_env,
                _resolve_backend_env_file=lambda context, backend_cwd: (None, False),
                _resolve_frontend_env_file=lambda context, frontend_cwd: None,
                _prepare_backend_runtime=lambda **kwargs: None,
                _prepare_frontend_runtime=lambda **kwargs: None,
                _service_env_from_file=lambda base_env, env_file, include_app_env_file, env_file_authoritative=False: dict(base_env),
                _service_enabled_for_mode=service_enabled_for_mode,
                _service_command_source=lambda **kwargs: "configured",
                _service_start_command_resolved=lambda service_name, **kwargs: ("python -c pass", "configured"),
                _split_command=lambda command, **kwargs: ["python", "-c", "pass"],
                process_runner=SimpleNamespace(start_background=lambda *args, **kwargs: SimpleNamespace(pid=1234)),
                _detect_service_actual_port=lambda service_name, pid, requested_port, **kwargs: 8022
                if service_name == "voice-runtime"
                else requested_port,
                _listener_truth_enforced=lambda: True,
                _service_listener_failure_detail=lambda **kwargs: "",
                _conflict_remaining={},
                _emit=lambda event, **payload: None,
            )
            orchestrator = SimpleNamespace(
                runtime=runtime,
                _restart_service_types_for_project=lambda route, project_name, default_service_types: set(default_service_types),
                _suppress_timing_output=lambda route: True,
            )
            context = SimpleNamespace(
                name="Main",
                root=project_root,
                ports={
                    "backend": SimpleNamespace(final=8000),
                    "frontend": SimpleNamespace(final=9000),
                    "voice-runtime": SimpleNamespace(final=8010),
                },
            )

            main_records = start_project_services(
                orchestrator,
                context,
                requirements=RequirementsResult(project="Main"),
                run_id="run-main",
                route=parse_route(["start", "--main", "--entire-system"], env={"ENVCTL_DEFAULT_MODE": "main"}),
            )
            trees_records = start_project_services(
                orchestrator,
                context,
                requirements=RequirementsResult(project="Main"),
                run_id="run-trees",
                route=parse_route(["start", "--trees", "--entire-system"], env={"ENVCTL_DEFAULT_MODE": "trees"}),
            )

        self.assertIn("Main Voice Runtime", main_records)
        self.assertNotIn("Main Worker", main_records)
        voice_record = main_records["Main Voice Runtime"]
        self.assertEqual(voice_record.actual_port, 8022)
        self.assertEqual(voice_record.public_url, "http://localhost:8022")
        self.assertEqual(voice_record.health_url, "http://localhost:8022/readyz")
        self.assertIn("Main Worker", trees_records)
        self.assertNotIn("Main Voice Runtime", trees_records)
        self.assertFalse(trees_records["Main Worker"].listener_expected)
        self.assertIsNone(trees_records["Main Worker"].actual_port)
        self.assertIn(("backend", "frontend", "voice-runtime"), started_layers)
        self.assertIn(("backend", "frontend", "worker"), started_layers)

    def test_start_project_services_resolves_additional_relative_command_from_service_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            project_root = root / "repo"
            service_root = project_root / "voice-runtime"
            service_root.mkdir(parents=True, exist_ok=True)
            run_dir = root / "runtime" / "run-relative-command"
            service = AppServiceConfig(
                name="voice-runtime",
                env_suffix="VOICE_RUNTIME",
                enabled_main=True,
                enabled_trees=True,
                dir_name="voice-runtime",
                start_cmd="scripts/envctl/start-voice-runtime.sh {port}",
                port_base=8010,
            )
            split_calls: list[dict[str, object]] = []

            def start_services_with_attach(**kwargs: object) -> dict[str, ServiceRecord]:
                records: dict[str, ServiceRecord] = {}
                for descriptor in kwargs["descriptors"]:
                    ok, detail, pid = descriptor.start(descriptor.requested_port)
                    self.assertTrue(ok, detail)
                    records["Main Voice Runtime"] = ServiceRecord(
                        name="Main Voice Runtime",
                        type="voice-runtime",
                        cwd=str(service_root),
                        requested_port=descriptor.requested_port,
                        actual_port=descriptor.requested_port,
                        status="running",
                        pid=pid,
                        project="Main",
                        service_slug="voice-runtime",
                    )
                return records

            runtime = SimpleNamespace(
                port_planner=_PortAllocatorStub(),
                env={},
                config=SimpleNamespace(
                    raw={},
                    backend_dir_name="backend",
                    frontend_dir_name="frontend",
                    additional_services=(service,),
                    all_app_service_names_for_mode=lambda mode: ("voice-runtime",),
                    app_service_by_name=lambda name: service if name == "voice-runtime" else None,
                ),
                services=SimpleNamespace(start_services_with_attach=start_services_with_attach),
                _invoke_envctl_hook=lambda **kwargs: SimpleNamespace(found=False, success=False, payload=None),
                _run_dir_path=lambda run_id: run_dir,
                _project_service_env=lambda context, requirements, route=None, service_name=None: {},
                _resolve_backend_env_file=lambda context, backend_cwd: (None, False),
                _resolve_frontend_env_file=lambda context, frontend_cwd: None,
                _prepare_backend_runtime=lambda **kwargs: None,
                _prepare_frontend_runtime=lambda **kwargs: None,
                _service_env_from_file=lambda base_env, env_file, include_app_env_file, env_file_authoritative=False: dict(base_env),
                _service_enabled_for_mode=lambda mode, service_name: service_name == "voice-runtime",
                _service_command_source=lambda **kwargs: "configured",
                _split_command=lambda command, **kwargs: split_calls.append({"command": command, **kwargs}) or [
                    "scripts/envctl/start-voice-runtime.sh",
                    str(kwargs["port"]),
                ],
                process_runner=SimpleNamespace(start_background=lambda *args, **kwargs: SimpleNamespace(pid=1234)),
                _detect_service_actual_port=lambda **kwargs: 8010,
                _listener_truth_enforced=lambda: True,
                _service_listener_failure_detail=lambda **kwargs: "",
                _conflict_remaining={},
                _emit=lambda event, **payload: None,
            )
            orchestrator = SimpleNamespace(
                runtime=runtime,
                _restart_service_types_for_project=lambda **kwargs: {"voice-runtime"},
                _suppress_timing_output=lambda route: True,
            )
            context = SimpleNamespace(
                name="Main",
                root=project_root,
                ports={
                    "backend": SimpleNamespace(final=8000),
                    "frontend": SimpleNamespace(final=9000),
                    "voice-runtime": SimpleNamespace(final=8010),
                },
            )

            records = start_project_services(
                orchestrator,
                context,
                requirements=RequirementsResult(project="Main"),
                run_id="run-relative-command",
                route=parse_route(["start", "--main", "--service", "voice-runtime"], env={}),
            )

        self.assertIn("Main Voice Runtime", records)
        self.assertEqual(Path(split_calls[0]["cwd"]).resolve(), service_root.resolve())

    def test_start_project_services_reprojects_additional_service_urls_after_rebound(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            project_root = root / "repo"
            (project_root / "voice-runtime").mkdir(parents=True, exist_ok=True)
            run_dir = root / "runtime" / "run-urls"
            service = AppServiceConfig(
                name="voice-runtime",
                env_suffix="VOICE_RUNTIME",
                enabled_main=True,
                enabled_trees=True,
                dir_name="voice-runtime",
                start_cmd="python -m voice --port {port}",
                port_base=8010,
                public_url_template="http://${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_HOST}:${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PORT}",
                health_url_template="http://${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_HOST}:${ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PORT}/readyz",
            )

            def project_service_env(context, requirements, route=None, service_name=None):  # noqa: ANN001
                _ = requirements, route
                env = {"ENVCTL_PROJECT_NAME": context.name}
                if service_name == "voice-runtime":
                    port = context.ports["voice-runtime"].final
                    env.update(
                        {
                            "ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_HOST": "localhost",
                            "ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PORT": str(port),
                            "ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_URL": f"http://localhost:{port}",
                            "ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_PUBLIC_URL": f"http://localhost:{port}",
                            "ENVCTL_SOURCE_SERVICE_VOICE_RUNTIME_HEALTH_URL": f"http://localhost:{port}/readyz",
                        }
                    )
                return env

            def start_services_with_attach(**kwargs: object) -> dict[str, ServiceRecord]:
                records: dict[str, ServiceRecord] = {}
                for descriptor in kwargs["descriptors"]:
                    descriptor.start(descriptor.requested_port)
                    actual = descriptor.detect_actual(1234, descriptor.requested_port)
                    records["Main Voice Runtime"] = ServiceRecord(
                        name="Main Voice Runtime",
                        type="voice-runtime",
                        cwd=str(project_root / "voice-runtime"),
                        requested_port=descriptor.requested_port,
                        actual_port=actual,
                        status="running",
                        public_url=descriptor.public_url,
                        health_url=descriptor.health_url,
                        project="Main",
                        service_slug="voice-runtime",
                    )
                return records

            runtime = SimpleNamespace(
                port_planner=_PortAllocatorStub(),
                env={},
                config=SimpleNamespace(
                    raw={},
                    backend_dir_name="backend",
                    frontend_dir_name="frontend",
                    additional_services=(service,),
                    all_app_service_names_for_mode=lambda mode: ("voice-runtime",),
                    app_service_by_name=lambda name: service if name == "voice-runtime" else None,
                ),
                services=SimpleNamespace(start_services_with_attach=start_services_with_attach),
                _invoke_envctl_hook=lambda **kwargs: SimpleNamespace(found=False, success=False, payload=None),
                _run_dir_path=lambda run_id: run_dir,
                _project_service_env=project_service_env,
                _resolve_backend_env_file=lambda context, backend_cwd: (None, False),
                _resolve_frontend_env_file=lambda context, frontend_cwd: None,
                _prepare_backend_runtime=lambda **kwargs: None,
                _prepare_frontend_runtime=lambda **kwargs: None,
                _service_env_from_file=lambda base_env, env_file, include_app_env_file, env_file_authoritative=False: dict(base_env),
                _service_enabled_for_mode=lambda mode, service_name: service_name == "voice-runtime",
                _service_command_source=lambda **kwargs: "configured",
                _split_command=lambda command, **kwargs: ["python", "-c", "pass"],
                process_runner=SimpleNamespace(start_background=lambda *args, **kwargs: SimpleNamespace(pid=1234)),
                _detect_service_actual_port=lambda **kwargs: 8019,
                _listener_truth_enforced=lambda: True,
                _service_listener_failure_detail=lambda **kwargs: "",
                _conflict_remaining={},
                _emit=lambda event, **payload: None,
            )
            orchestrator = SimpleNamespace(
                runtime=runtime,
                _restart_service_types_for_project=lambda **kwargs: {"voice-runtime"},
                _suppress_timing_output=lambda route: True,
            )
            context = SimpleNamespace(
                name="Main",
                root=project_root,
                ports={
                    "backend": SimpleNamespace(final=8000),
                    "frontend": SimpleNamespace(final=3000),
                    "voice-runtime": SimpleNamespace(final=8010),
                },
            )

            records = start_project_services(
                orchestrator,
                context,
                requirements=RequirementsResult(project="Main"),
                run_id="run-urls",
                route=parse_route(["start", "--main"], env={"ENVCTL_DEFAULT_MODE": "main"}),
            )

        record = records["Main Voice Runtime"]
        self.assertEqual(context.ports["voice-runtime"].final, 8019)
        self.assertEqual(record.public_url, "http://localhost:8019")
        self.assertEqual(record.health_url, "http://localhost:8019/readyz")


if __name__ == "__main__":
    unittest.main()
