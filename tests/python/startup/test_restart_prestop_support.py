from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.ports import PortPlanner
from envctl_engine.startup.restart_prestop_support import (
    RestartOrphanListenerScan,
    apply_restart_port_assignments,
    apply_restart_ports_to_contexts,
    handle_restart_prestop,
    terminate_restart_orphan_listeners,
    restart_matching_orphan_listeners,
    restart_orphan_listener_scan,
    restart_fallback_start_route,
    restart_port_assignments,
    restart_prestop_state,
    restart_prestop_selection,
    restart_prestop_preservation,
    restart_start_route,
)


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _RecordingSpinner:
    def __init__(self) -> None:
        self.events: list[str] = []

    def __enter__(self):
        self.events.append("enter")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.events.append("exit")
        return False

    def succeed(self, message: str) -> None:
        self.events.append(f"succeed:{message}")

    def fail(self, message: str) -> None:
        self.events.append(f"fail:{message}")


class RestartPrestopSupportTests(unittest.TestCase):
    def test_handle_restart_prestop_noops_for_non_restart_routes(self) -> None:
        route = Route(command="start", mode="main", raw_args=["start"], flags={})
        session = SimpleNamespace(effective_route=route, runtime_mode="main")
        runtime = SimpleNamespace()

        result = handle_restart_prestop(
            runtime=runtime,
            session=session,
            suppress_progress_output=lambda route: False,
            terminate_restart_orphan_listeners=lambda **kwargs: self.fail("orphan cleanup should not run"),
            spinner_factory=lambda *args, **kwargs: self.fail("spinner should not start"),
            use_spinner_policy_fn=lambda policy: self.fail("spinner policy should not start"),
            resolve_spinner_policy_fn=lambda env: self.fail("spinner policy should not resolve"),
            emit_spinner_policy_fn=lambda *args, **kwargs: self.fail("spinner policy should not emit"),
        )

        self.assertIsNone(result)

    def test_handle_restart_prestop_rewrites_to_start_when_no_existing_state(self) -> None:
        route = Route(command="restart", mode="main", raw_args=["restart"], flags={})
        session = SimpleNamespace(effective_route=route, runtime_mode="main")
        runtime = SimpleNamespace(
            _effective_start_mode=lambda route: "main",
            _try_load_existing_state=lambda *, mode: None,
            _emit=lambda *args, **kwargs: None,
        )

        result = handle_restart_prestop(
            runtime=runtime,
            session=session,
            suppress_progress_output=lambda route: False,
            terminate_restart_orphan_listeners=lambda **kwargs: self.fail("orphan cleanup should not run"),
            spinner_factory=lambda *args, **kwargs: self.fail("spinner should not start"),
            use_spinner_policy_fn=lambda policy: self.fail("spinner policy should not start"),
            resolve_spinner_policy_fn=lambda env: self.fail("spinner policy should not resolve"),
            emit_spinner_policy_fn=lambda *args, **kwargs: self.fail("spinner policy should not emit"),
        )

        self.assertIsNone(result)
        self.assertEqual(session.runtime_mode, "main")
        self.assertEqual(session.effective_route.command, "start")
        self.assertTrue(session.effective_route.flags["_restart_request"])

    def test_handle_restart_prestop_stops_selected_services_and_preserves_remaining_state(self) -> None:
        route = Route(
            command="restart",
            mode="main",
            raw_args=["restart"],
            flags={"services": ["Main Backend"], "restart_include_requirements": True},
        )
        session = SimpleNamespace(
            effective_route=route,
            runtime_mode="main",
            restart_state=None,
            preserved_requirements={},
            preserved_services={},
            base_metadata={"new": True},
        )
        state = SimpleNamespace(
            run_id="run-old",
            mode="main",
            services={"Main Backend": object(), "Other Backend": object()},
            requirements={"Main": object(), "Other": object()},
            metadata={"state_source_run_ids": ["run-ancestor"], "old": True},
        )
        events: list[tuple[str, dict[str, object]]] = []
        released: list[object] = []
        terminated: list[tuple[object, set[str]]] = []
        orphan_calls: list[dict[str, object]] = []
        spinner = _RecordingSpinner()

        runtime = SimpleNamespace(
            env={},
            _effective_start_mode=lambda route: "main",
            _try_load_existing_state=lambda *, mode: state,
            _project_name_from_service=lambda name: str(name).removesuffix(" Backend"),
            _terminate_services_from_state=lambda state, *, selected_services, aggressive, verify_ownership: (
                terminated.append((state, set(selected_services)))
            ),
            _release_requirement_ports=released.append,
            _emit=lambda event, **payload: events.append((event, payload)),
        )

        result = handle_restart_prestop(
            runtime=runtime,
            session=session,
            suppress_progress_output=lambda route: False,
            terminate_restart_orphan_listeners=lambda **kwargs: orphan_calls.append(dict(kwargs)),
            spinner_factory=lambda *args, **kwargs: spinner,
            use_spinner_policy_fn=lambda policy: _NullContext(),
            resolve_spinner_policy_fn=lambda env: SimpleNamespace(enabled=True),
            emit_spinner_policy_fn=lambda emit, policy, *, context: emit("spinner.policy", **context),
        )

        self.assertIsNone(result)
        self.assertIs(session.restart_state, state)
        self.assertEqual(terminated, [(state, {"Main Backend"})])
        self.assertEqual(len(orphan_calls), 1)
        self.assertEqual(orphan_calls[0]["selected_services"], {"Main Backend"})
        self.assertEqual(released, [state.requirements["Main"]])
        self.assertEqual(session.preserved_services, {"Other Backend": state.services["Other Backend"]})
        self.assertEqual(session.preserved_requirements, {"Other": state.requirements["Other"]})
        self.assertEqual(session.base_metadata["state_source_run_ids"], ["run-ancestor", "run-old"])
        self.assertTrue(session.base_metadata["old"])
        self.assertTrue(session.base_metadata["new"])
        self.assertEqual(session.effective_route.command, "start")
        self.assertEqual(session.effective_route.flags["_restart_selected_services"], ["Main Backend"])
        self.assertEqual(spinner.events, ["enter", "succeed:Restart pre-stop complete", "exit"])
        self.assertIn(
            (
                "restart.selection",
                {"include_requirements": True, "target_projects": ["Main"], "selected_services": ["Main Backend"]},
            ),
            events,
        )

    def test_handle_restart_prestop_aborts_without_mutating_session_when_termination_fails(self) -> None:
        route = Route(
            command="restart",
            mode="main",
            flags={"services": ["Main Backend"]},
        )
        session = SimpleNamespace(
            effective_route=route,
            runtime_mode="main",
            restart_state=None,
            preserved_requirements={},
            preserved_services={},
            base_metadata={},
        )
        state = SimpleNamespace(
            run_id="run-old",
            mode="main",
            services={"Main Backend": object()},
            requirements={"Main": object()},
            metadata={},
        )
        runtime = SimpleNamespace(
            env={},
            _effective_start_mode=lambda _route: "main",
            _try_load_existing_state=lambda *, mode: state,
            _project_name_from_service=lambda _name: "Main",
            _terminate_services_from_state=lambda *_args, **_kwargs: {"Main Backend"},
            _release_requirement_ports=lambda _requirements: self.fail("ports must remain reserved"),
            _emit=lambda *_args, **_kwargs: None,
        )

        with self.assertRaisesRegex(RuntimeError, "Main Backend"):
            handle_restart_prestop(
                runtime=runtime,
                session=session,
                suppress_progress_output=lambda _route: True,
                terminate_restart_orphan_listeners=lambda **_kwargs: self.fail("orphans must not be reaped"),
                spinner_factory=lambda *_args, **_kwargs: _RecordingSpinner(),
                use_spinner_policy_fn=lambda _policy: _NullContext(),
                resolve_spinner_policy_fn=lambda _env: SimpleNamespace(enabled=False),
                emit_spinner_policy_fn=lambda *_args, **_kwargs: None,
            )

        self.assertEqual(session.preserved_services, {})
        self.assertEqual(session.preserved_requirements, {})
        self.assertEqual(session.base_metadata, {})
        self.assertTrue(session.preserve_existing_state_on_failure)
        self.assertIs(session.restart_state, state)
        self.assertIs(session.effective_route, route)

    def test_handle_restart_prestop_aborts_when_orphan_exit_is_unconfirmed(self) -> None:
        route = Route(command="restart", mode="main", flags={"services": ["Main Backend"]})
        session = SimpleNamespace(
            effective_route=route,
            runtime_mode="main",
            restart_state=None,
            preserved_requirements={},
            preserved_services={},
            base_metadata={},
        )
        state = SimpleNamespace(
            run_id="run-old",
            mode="main",
            services={"Main Backend": object()},
            requirements={"Main": object()},
            metadata={},
        )
        runtime = SimpleNamespace(
            env={},
            _effective_start_mode=lambda _route: "main",
            _try_load_existing_state=lambda *, mode: state,
            _project_name_from_service=lambda _name: "Main",
            _terminate_services_from_state=lambda *_args, **_kwargs: set(),
            _release_requirement_ports=lambda _requirements: self.fail("ports must remain reserved"),
            _emit=lambda *_args, **_kwargs: None,
        )

        with self.assertRaisesRegex(RuntimeError, "orphan listeners.*4242"):
            handle_restart_prestop(
                runtime=runtime,
                session=session,
                suppress_progress_output=lambda _route: True,
                terminate_restart_orphan_listeners=lambda **_kwargs: {4242},
                spinner_factory=lambda *_args, **_kwargs: _RecordingSpinner(),
                use_spinner_policy_fn=lambda _policy: _NullContext(),
                resolve_spinner_policy_fn=lambda _env: SimpleNamespace(enabled=False),
                emit_spinner_policy_fn=lambda *_args, **_kwargs: None,
            )

        self.assertTrue(session.preserve_existing_state_on_failure)
        self.assertEqual(session.preserved_services, {})
        self.assertIs(session.effective_route, route)

    def test_restart_fallback_start_route_preserves_request_context_and_marks_restart(self) -> None:
        route = Route(
            command="restart",
            mode="trees",
            raw_args=["restart", "--project", "Feature"],
            passthrough_args=["--", "extra"],
            projects=["Feature"],
            flags={"runtime_scope": "backend"},
        )

        updated = restart_fallback_start_route(route, restart_lookup_mode="trees")

        self.assertEqual(updated.command, "start")
        self.assertEqual(updated.mode, "trees")
        self.assertEqual(updated.raw_args, route.raw_args)
        self.assertEqual(updated.passthrough_args, route.passthrough_args)
        self.assertEqual(updated.projects, ["Feature"])
        self.assertEqual(updated.flags["runtime_scope"], "backend")
        self.assertTrue(updated.flags["_restart_request"])

    def test_restart_start_route_records_sorted_selection_policy(self) -> None:
        route = Route(command="restart", mode="main", raw_args=["restart"], flags={"force": True})

        updated = restart_start_route(
            route,
            restart_lookup_mode="main",
            selected_services={"Main Frontend", "Main Backend"},
            target_projects={"Main"},
            include_requirements=False,
        )

        self.assertEqual(updated.command, "start")
        self.assertEqual(updated.flags["_restart_selected_services"], ["Main Backend", "Main Frontend"])
        self.assertEqual(updated.flags["_restart_target_projects"], ["Main"])
        self.assertFalse(updated.flags["_restart_include_requirements"])
        self.assertTrue(updated.flags["_restart_request"])
        self.assertTrue(updated.flags["force"])

    def test_restart_prestop_state_rejects_mode_mismatch_and_builds_fallback_route(self) -> None:
        route = Route(command="restart", mode="trees", raw_args=["restart", "--trees"], flags={})
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(
            _effective_start_mode=lambda route: "trees",
            _try_load_existing_state=lambda *, mode: SimpleNamespace(mode="main", run_id="run-main"),
            _emit=lambda event, **payload: events.append((event, payload)),
        )

        result = restart_prestop_state(route=route, runtime=runtime)

        self.assertEqual(result.restart_lookup_mode, "trees")
        self.assertIsNone(result.state)
        self.assertIsNotNone(result.fallback_route)
        assert result.fallback_route is not None
        self.assertEqual(result.fallback_route.command, "start")
        self.assertTrue(result.fallback_route.flags["_restart_request"])
        self.assertEqual(
            events,
            [
                (
                    "restart.state_mode_mismatch",
                    {"requested_mode": "trees", "loaded_mode": "main", "run_id": "run-main"},
                )
            ],
        )

    def test_restart_prestop_state_inherits_docker_runtime_from_saved_state(self) -> None:
        route = Route(command="restart", mode="main", raw_args=["restart"], flags={})
        state = SimpleNamespace(
            mode="main",
            run_id="run-docker",
            metadata={"application_runtime": "docker"},
            services={},
        )
        runtime = SimpleNamespace(
            env={},
            _effective_start_mode=lambda route: "main",
            _try_load_existing_state=lambda *, mode: state,
            _emit=lambda event, **payload: None,
        )

        result = restart_prestop_state(route=route, runtime=runtime)

        self.assertIs(result.state, state)
        self.assertTrue(route.flags["docker"])
        self.assertEqual(runtime.env["DOCKER_MODE"], "true")

    def test_restart_prestop_preservation_splits_services_and_requirements(self) -> None:
        state = SimpleNamespace(
            services={
                "Main Backend": object(),
                "Main Frontend": object(),
                "Other Backend": object(),
            },
            requirements={
                "Main": SimpleNamespace(name="main requirements"),
                "Other": SimpleNamespace(name="other requirements"),
            },
        )

        result = restart_prestop_preservation(
            state,
            selected_services={"Main Backend", "Main Frontend"},
            include_requirements=True,
            target_projects={"Main"},
        )

        self.assertEqual(set(result.preserved_services), {"Other Backend"})
        self.assertEqual(set(result.requirements_to_release), {"Main"})
        self.assertEqual(set(result.preserved_requirements), {"Other"})

    def test_restart_prestop_preservation_preserves_requirements_when_not_included(self) -> None:
        state = SimpleNamespace(
            services={"Main Backend": object()},
            requirements={"Main": object()},
        )

        result = restart_prestop_preservation(
            state,
            selected_services={"Main Backend"},
            include_requirements=False,
            target_projects={"Main"},
        )

        self.assertEqual(result.preserved_services, {})
        self.assertEqual(result.requirements_to_release, {})
        self.assertEqual(set(result.preserved_requirements), {"Main"})

    def test_restart_prestop_selection_falls_back_to_selected_service_projects_for_requirements(self) -> None:
        state = SimpleNamespace(
            services={
                "Main Backend": SimpleNamespace(project="Main", type="backend"),
                "Other Backend": SimpleNamespace(project="Other", type="backend"),
            }
        )
        route = Route(
            command="restart",
            mode="main",
            raw_args=["restart"],
            flags={"restart_include_requirements": True, "services": ["Main Backend"]},
        )
        runtime = SimpleNamespace(
            _project_name_from_service=lambda service_name: str(service_name).removesuffix(" Backend")
        )

        selection = restart_prestop_selection(state=state, route=route, runtime=runtime)

        self.assertEqual(selection.selected_services, {"Main Backend"})
        self.assertEqual(selection.target_projects, {"Main"})
        self.assertTrue(selection.include_requirements)

    def test_restart_port_assignments_use_actual_port_then_requested_port_for_selected_services(self) -> None:
        state = SimpleNamespace(
            services={
                "Main Backend": SimpleNamespace(
                    name="Main Backend",
                    project="Main",
                    type="backend",
                    actual_port=8001,
                    requested_port=8000,
                ),
                "Main Frontend": SimpleNamespace(
                    name="Main Frontend",
                    project="Main",
                    type="frontend",
                    actual_port=None,
                    requested_port=3000,
                ),
                "Other Backend": SimpleNamespace(
                    name="Other Backend",
                    project="Other",
                    type="backend",
                    actual_port=8100,
                    requested_port=8100,
                ),
            }
        )

        self.assertEqual(
            restart_port_assignments(
                state,
                selected_services={"Main Backend", "Main Frontend"},
                project_name_from_service=lambda name: str(name).removesuffix(" Backend").removesuffix(" Frontend"),
            ),
            {"main": {"backend": 8001, "frontend": 3000}},
        )

    def test_restart_port_assignments_uses_project_name_fallback_and_ignores_invalid_ports(self) -> None:
        state = SimpleNamespace(
            services={
                "Fallback Backend": SimpleNamespace(
                    name="Fallback Backend",
                    project="",
                    type="backend",
                    actual_port=0,
                    requested_port=8000,
                ),
                "Fallback Frontend": SimpleNamespace(
                    name="Fallback Frontend",
                    project="",
                    type="frontend",
                    actual_port=-1,
                    requested_port=None,
                ),
            }
        )

        self.assertEqual(
            restart_port_assignments(
                state,
                selected_services={"Fallback Backend", "Fallback Frontend"},
                project_name_from_service=lambda name: str(name).removesuffix(" Backend").removesuffix(" Frontend"),
            ),
            {"fallback": {"backend": 8000}},
        )

    def test_apply_restart_port_assignments_updates_matching_context_plans(self) -> None:
        main_backend = SimpleNamespace(port=None, source=None)
        main_frontend = SimpleNamespace(port=None, source=None)
        other_backend = SimpleNamespace(port=None, source=None)
        contexts = [
            SimpleNamespace(name="Main", ports={"backend": main_backend, "frontend": main_frontend}),
            SimpleNamespace(name="Other", ports={"backend": other_backend}),
        ]
        assignments = {"main": {"backend": 8000, "frontend": 3000}, "missing": {"backend": 9000}}
        set_calls: list[tuple[object, int]] = []

        apply_restart_port_assignments(
            contexts,
            assignments,
            set_plan_port=lambda plan, port: set_calls.append((plan, port)),
        )

        self.assertEqual(set_calls, [(main_backend, 8000), (main_frontend, 3000)])
        self.assertEqual(main_backend.source, "restart")
        self.assertEqual(main_frontend.source, "restart")
        self.assertIsNone(other_backend.source)

    def test_restart_orphan_listener_scan_tracks_selected_cwds_and_nearby_ports(self) -> None:
        state = SimpleNamespace(
            services={
                "Main Backend": SimpleNamespace(
                    type="backend",
                    cwd="/repo/backend",
                    actual_port=8010,
                    requested_port=8000,
                ),
                "Main Frontend": SimpleNamespace(
                    type="frontend",
                    cwd="/repo/frontend",
                    actual_port=None,
                    requested_port=3010,
                ),
                "Other Backend": SimpleNamespace(
                    type="backend",
                    cwd="/repo/other",
                    actual_port=8110,
                    requested_port=8100,
                ),
            }
        )

        scan = restart_orphan_listener_scan(
            state,
            selected_services={"Main Backend", "Main Frontend"},
            backend_port_base=8000,
            frontend_port_base=3000,
            port_spacing=2,
        )

        self.assertEqual(scan.selected_by_cwd, {"/repo/backend": {"backend"}, "/repo/frontend": {"frontend"}})
        self.assertTrue({8000, 8001, 8010, 8011, 8012}.issubset(scan.ports_by_type["backend"]))
        self.assertTrue({3000, 3001, 3009, 3010, 3011}.issubset(scan.ports_by_type["frontend"]))
        self.assertNotIn(8110, scan.ports_by_type["backend"])

    def test_restart_orphan_listener_scan_ignores_services_without_supported_type_or_cwd(self) -> None:
        state = SimpleNamespace(
            services={
                "Main Worker": SimpleNamespace(type="worker", cwd="/repo/worker", actual_port=9000),
                "Main Backend": SimpleNamespace(type="backend", cwd="", actual_port=8000),
            }
        )

        scan = restart_orphan_listener_scan(
            state,
            selected_services={"Main Worker", "Main Backend"},
            backend_port_base=8000,
            frontend_port_base=3000,
            port_spacing=1,
        )

        self.assertEqual(scan.selected_by_cwd, {})

    def test_restart_matching_orphan_listeners_filters_by_pid_cwd_and_dedupes(self) -> None:
        scan = RestartOrphanListenerScan(
            ports_by_type={"backend": {8000, 8001}, "frontend": set()},
            selected_by_cwd={"/repo/backend": {"backend"}},
        )
        listeners = {8000: [0, 10, 11], 8001: [10, 12]}
        cwd_by_pid = {10: "/repo/backend", 11: "/other", 12: "/repo/backend"}

        matches = restart_matching_orphan_listeners(
            scan,
            listener_pids_for_port=lambda port: listeners.get(port, []),
            process_cwd=lambda pid: cwd_by_pid.get(pid),
        )

        self.assertEqual([(match.pid, match.port) for match in matches], [(10, 8000), (12, 8001)])

    def test_apply_restart_ports_to_contexts_noops_without_state_or_selected_services(self) -> None:
        set_calls: list[tuple[object, int]] = []
        context = SimpleNamespace(name="Main", ports={"backend": SimpleNamespace(source=None)})
        route = Route(command="start", mode="main", flags={})

        apply_restart_ports_to_contexts(
            None,
            route=route,
            contexts=[context],
            project_name_from_service=lambda name: "Main",
            set_plan_port=lambda plan, port: set_calls.append((plan, port)),
        )
        apply_restart_ports_to_contexts(
            SimpleNamespace(services={}),
            route=route,
            contexts=[context],
            project_name_from_service=lambda name: "Main",
            set_plan_port=lambda plan, port: set_calls.append((plan, port)),
        )

        self.assertEqual(set_calls, [])

    def test_apply_restart_ports_to_contexts_uses_restart_selection_flags(self) -> None:
        backend_plan = SimpleNamespace(source=None)
        context = SimpleNamespace(name="Main", ports={"backend": backend_plan})
        route = Route(
            command="start",
            mode="main",
            flags={"_restart_selected_services": ["Main Backend"]},
        )
        state = SimpleNamespace(
            services={
                "Main Backend": SimpleNamespace(
                    name="Main Backend",
                    project="Main",
                    type="backend",
                    actual_port=8001,
                    requested_port=8000,
                )
            }
        )

        apply_restart_ports_to_contexts(
            state,
            route=route,
            contexts=[context],
            project_name_from_service=lambda name: str(name).removesuffix(" Backend"),
            set_plan_port=lambda plan, port: setattr(plan, "port", port),
        )

        self.assertEqual(backend_plan.port, 8001)
        self.assertEqual(backend_plan.source, "restart")

    def test_terminate_restart_orphan_listeners_releases_successfully_terminated_ports(self) -> None:
        state = SimpleNamespace(
            services={
                "Main Backend": SimpleNamespace(type="backend", cwd="/repo/backend", actual_port=8000),
            }
        )
        released: list[int] = []
        terminated: list[tuple[int, float, float]] = []

        failed = terminate_restart_orphan_listeners(
            state=state,
            selected_services={"Main Backend"},
            aggressive=True,
            backend_port_base=8000,
            frontend_port_base=3000,
            port_spacing=0,
            listener_pids_for_port=lambda port: [42] if port == 8000 else [],
            process_cwd=lambda pid: "/repo/backend" if pid == 42 else None,
            terminate_pid=lambda pid, *, term_timeout, kill_timeout: (
                terminated.append((pid, term_timeout, kill_timeout)) or True
            ),
            port_planner=SimpleNamespace(release=released.append),
        )

        self.assertEqual(terminated, [(42, 0.5, 1.0)])
        self.assertEqual(released, [8000])
        self.assertEqual(failed, set())

    def test_restart_orphan_cleanup_releases_verified_prior_session_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = PortPlanner(
                lock_dir=tmpdir,
                session_id="prior-session",
                availability_checker=lambda _port: True,
            )
            current = PortPlanner(
                lock_dir=tmpdir,
                session_id="current-session",
                availability_checker=lambda _port: True,
            )
            prior.reserve_next(8000, owner="Main:backend")
            state = SimpleNamespace(
                services={
                    "Main Backend": SimpleNamespace(
                        project="Main",
                        type="backend",
                        cwd="/repo/backend",
                        actual_port=8000,
                        port_lock_session="prior-session",
                    )
                }
            )

            failed = terminate_restart_orphan_listeners(
                state=state,
                selected_services={"Main Backend"},
                aggressive=True,
                backend_port_base=8000,
                frontend_port_base=3000,
                port_spacing=0,
                listener_pids_for_port=lambda port: [42] if port == 8000 else [],
                process_cwd=lambda pid: "/repo/backend" if pid == 42 else None,
                terminate_pid=lambda *_args, **_kwargs: True,
                port_planner=current,
            )

            self.assertEqual(failed, set())
            self.assertEqual(list(Path(tmpdir).glob("*.lock")), [])

    def test_stale_restart_state_cannot_release_newer_same_owner_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            newer = PortPlanner(
                lock_dir=tmpdir,
                session_id="newer-session",
                availability_checker=lambda _port: True,
            )
            cleanup = PortPlanner(
                lock_dir=tmpdir,
                session_id="cleanup-session",
                availability_checker=lambda _port: True,
            )
            newer.reserve_next(8000, owner="Main:backend")
            state = SimpleNamespace(
                services={
                    "Main Backend": SimpleNamespace(
                        project="Main",
                        type="backend",
                        cwd="/repo/backend",
                        actual_port=8000,
                        port_lock_session="stale-session",
                    )
                }
            )

            failed = terminate_restart_orphan_listeners(
                state=state,
                selected_services={"Main Backend"},
                aggressive=True,
                backend_port_base=8000,
                frontend_port_base=3000,
                port_spacing=0,
                listener_pids_for_port=lambda port: [42] if port == 8000 else [],
                process_cwd=lambda pid: "/repo/backend" if pid == 42 else None,
                terminate_pid=lambda *_args, **_kwargs: True,
                port_planner=cleanup,
            )

            self.assertEqual(failed, set())
            self.assertTrue((Path(tmpdir) / "8000.lock").exists())

    def test_terminate_restart_orphan_listeners_reports_unconfirmed_exits_without_releasing_ports(self) -> None:
        state = SimpleNamespace(
            services={
                "Main Backend": SimpleNamespace(type="backend", cwd="/repo/backend", actual_port=8000),
            }
        )
        released: list[int] = []

        failed = terminate_restart_orphan_listeners(
            state=state,
            selected_services={"Main Backend"},
            aggressive=True,
            backend_port_base=8000,
            frontend_port_base=3000,
            port_spacing=0,
            listener_pids_for_port=lambda port: [42] if port == 8000 else [],
            process_cwd=lambda pid: "/repo/backend" if pid == 42 else None,
            terminate_pid=lambda *_args, **_kwargs: False,
            port_planner=SimpleNamespace(release=released.append),
        )

        self.assertEqual(failed, {42})
        self.assertEqual(released, [])


if __name__ == "__main__":
    unittest.main()
