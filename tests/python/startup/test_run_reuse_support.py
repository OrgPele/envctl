from __future__ import annotations

import unittest
from types import SimpleNamespace

from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.run_reuse_support import (
    dashboard_stopped_service_entries,
    fresh_start_replacement_services,
    mark_run_reused,
    prepare_dashboard_stopped_service_restore,
    replace_existing_project_services_for_fresh_start,
    metadata_without_dashboard_stopped_services,
    run_reuse_debug_orch_groups,
)


class RunReuseSupportTests(unittest.TestCase):
    def test_mark_run_reused_recovers_from_malformed_counter(self) -> None:
        updated = mark_run_reused({"run_reuse_count": "not-a-number"}, reason="exact_match")

        self.assertEqual(updated["run_reuse_count"], 1)
        self.assertEqual(updated["last_reuse_reason"], "exact_match")

    def test_run_reuse_debug_orch_groups_only_apply_to_plan_commands(self) -> None:
        runtime = SimpleNamespace(env={"ENVCTL_DEBUG_PLAN_ORCH_GROUP": "alpha+ beta,gamma ,,"})

        self.assertEqual(run_reuse_debug_orch_groups(runtime, requested_command="plan"), {"alpha", "beta", "gamma"})
        self.assertEqual(run_reuse_debug_orch_groups(runtime, requested_command="start"), set())

    def test_dashboard_stopped_service_entries_normalizes_all_valid_service_types(self) -> None:
        state = SimpleNamespace(
            metadata={
                "dashboard_stopped_services": [
                    {"project": " Main ", "type": " Frontend ", "name": " Main Frontend "},
                    {"project": "Main", "type": "backend", "name": ""},
                    {"project": "", "type": "frontend", "name": "missing project"},
                    {"project": "Main", "type": "worker", "name": "Main Worker"},
                    "invalid",
                ]
            }
        )

        self.assertEqual(
            dashboard_stopped_service_entries(state),
            [
                {"project": "Main", "type": "frontend", "name": "Main Frontend"},
                {"project": "Main", "type": "backend", "name": "Main Backend"},
                {"project": "Main", "type": "worker", "name": "Main Worker"},
            ],
        )

    def test_dashboard_stopped_service_entries_ignores_missing_or_invalid_metadata(self) -> None:
        self.assertEqual(dashboard_stopped_service_entries(SimpleNamespace(metadata={})), [])
        self.assertEqual(
            dashboard_stopped_service_entries(SimpleNamespace(metadata={"dashboard_stopped_services": {}})), []
        )

    def test_metadata_without_dashboard_stopped_services_removes_restored_entries_only(self) -> None:
        metadata = {
            "keep": True,
            "dashboard_stopped_services": [
                {"name": "Main Frontend", "project": "Main", "type": "frontend"},
                {"name": "Main Backend", "project": "Main", "type": "backend"},
                "invalid",
            ],
        }

        self.assertEqual(
            metadata_without_dashboard_stopped_services(
                metadata,
                restored_service_names={"Main Frontend"},
            ),
            {
                "keep": True,
                "dashboard_stopped_services": [
                    {"name": "Main Backend", "project": "Main", "type": "backend"},
                    "invalid",
                ],
            },
        )

    def test_metadata_without_dashboard_stopped_services_drops_key_when_all_entries_restored(self) -> None:
        metadata = {
            "dashboard_stopped_services": [
                {"name": "Main Frontend", "project": "Main", "type": "frontend"},
            ],
            "keep": True,
        }

        self.assertEqual(
            metadata_without_dashboard_stopped_services(
                metadata,
                restored_service_names={"Main Frontend"},
            ),
            {"keep": True},
        )

    def test_metadata_without_dashboard_stopped_services_is_project_scoped(self) -> None:
        entries = [
            {
                "name": f"{project} Voice Runtime",
                "project": project,
                "type": "voice-runtime",
            }
            for project in ("Customer Platform", "Other")
        ]

        updated = metadata_without_dashboard_stopped_services(
            {"dashboard_stopped_services": entries, "keep": True},
            restored_service_types_by_project={"Customer Platform": {"voice-runtime"}},
        )

        self.assertEqual(updated["dashboard_stopped_services"], [entries[1]])
        self.assertTrue(updated["keep"])

    def test_prepare_dashboard_stopped_service_restore_rewrites_route_and_preserves_active_state(self) -> None:
        route = Route(command="start", mode="trees", raw_args=["start"], flags={})
        session = SimpleNamespace(
            selected_contexts=[SimpleNamespace(name="Main"), SimpleNamespace(name="Other")],
            effective_route=route,
            runtime_mode="trees",
            base_metadata={},
            preserved_services={},
            preserved_requirements={},
            contexts_to_start=[],
        )
        candidate_state = SimpleNamespace(
            run_id="run-existing",
            services={"Main Backend": object()},
            requirements={"Main": object()},
            metadata={
                "dashboard_stopped_services": [
                    {"project": "Main", "type": "frontend", "name": "Main Frontend"},
                    {"project": "Main", "type": "voice-runtime", "name": "Main Voice Runtime"},
                    {"project": "Other", "type": "backend", "name": "Other Backend"},
                ],
                "keep": True,
            },
        )
        events: list[tuple[str, dict[str, object]]] = []
        phases: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(_emit=lambda event, **payload: events.append((event, payload)))

        restored = prepare_dashboard_stopped_service_restore(
            runtime=runtime,
            session=session,
            candidate_state=candidate_state,
            reuse_started=12.0,
            decision_kind="resume_subset",
            emit_phase=lambda session, phase, started_at, **payload: phases.append((phase, payload)),
        )

        self.assertTrue(restored)
        self.assertEqual(session.contexts_to_start, [session.selected_contexts[0], session.selected_contexts[1]])
        self.assertEqual(session.preserved_services, candidate_state.services)
        self.assertEqual(session.preserved_requirements, candidate_state.requirements)
        self.assertEqual(session.base_metadata["keep"], True)
        self.assertEqual(
            session.base_metadata["dashboard_stopped_services"],
            candidate_state.metadata["dashboard_stopped_services"],
        )
        self.assertEqual(session.effective_route.projects, ["Main", "Other"])
        self.assertEqual(session.effective_route.flags["_restart_request"], True)
        self.assertEqual(session.effective_route.flags["_restore_dashboard_stopped_services"], True)
        self.assertEqual(
            session.effective_route.flags["services"],
            ["Main Frontend", "Main Voice Runtime", "Other Backend"],
        )
        self.assertEqual(
            session.effective_route.flags["restart_service_types"],
            ["backend", "frontend", "voice-runtime"],
        )
        self.assertEqual(
            session.effective_route.flags["_restart_service_types_by_project"],
            {
                "Main": ["frontend", "voice-runtime"],
                "Other": ["backend"],
            },
        )
        self.assertEqual(phases[0][0], "auto_resume_evaluate")
        self.assertEqual(phases[0][1]["status"], "restore_stopped_services")
        self.assertEqual(phases[0][1]["match_mode"], "subset")
        self.assertEqual(
            [event for event, _payload in events],
            ["state.auto_resume.restore_stopped_services", "state.run_reuse.applied"],
        )

    def test_prepare_dashboard_stopped_service_restore_ignores_active_or_unselected_entries(self) -> None:
        route = Route(command="start", mode="trees", raw_args=["start"], flags={})
        session = SimpleNamespace(
            selected_contexts=[SimpleNamespace(name="Main")],
            effective_route=route,
            runtime_mode="trees",
        )
        candidate_state = SimpleNamespace(
            run_id="run-existing",
            services={"Main Frontend": object()},
            requirements={},
            metadata={
                "dashboard_stopped_services": [
                    {"project": "Main", "type": "frontend", "name": "Main Frontend"},
                    {"project": "Other", "type": "backend", "name": "Other Backend"},
                ]
            },
        )
        runtime = SimpleNamespace(_emit=lambda *args, **kwargs: self.fail("restore should not emit"))

        self.assertFalse(
            prepare_dashboard_stopped_service_restore(
                runtime=runtime,
                session=session,
                candidate_state=candidate_state,
                reuse_started=12.0,
                decision_kind="resume_exact",
                emit_phase=lambda *args, **kwargs: self.fail("restore should not emit phase"),
            )
        )

    def test_fresh_start_replacement_services_selects_every_service_for_target_projects(self) -> None:
        candidate_state = SimpleNamespace(
            services={
                "Main Backend": SimpleNamespace(name="Main Backend", project="Main", type="backend"),
                "Main Frontend": SimpleNamespace(name="Main Frontend", project="Main", type="frontend"),
                "Other Backend": SimpleNamespace(name="Other Backend", project="Other", type="backend"),
            }
        )

        self.assertEqual(
            fresh_start_replacement_services(
                selected_contexts=[SimpleNamespace(name="Main")],
                candidate_state=candidate_state,
                project_name_from_service=lambda name: str(name).removesuffix(" Backend").removesuffix(" Frontend"),
            ),
            {"Main Backend", "Main Frontend"},
        )

    def test_unfiltered_explicit_no_resume_replaces_tracked_removed_additional_services(self) -> None:
        state = SimpleNamespace(
            services={
                "Main Backend": SimpleNamespace(name="Main Backend", project="Main", type="backend"),
                "Main Old Worker": SimpleNamespace(
                    name="Main Old Worker",
                    project="Main",
                    type="old-worker",
                    service_slug="old-worker",
                ),
            }
        )

        selected = fresh_start_replacement_services(
            selected_contexts=[SimpleNamespace(name="Main")],
            candidate_state=state,
            project_name_from_service=lambda _name: "Main",
        )

        self.assertEqual(selected, {"Main Backend", "Main Old Worker"})

    def test_fresh_start_replacement_services_respects_launch_only_filter(self) -> None:
        state = SimpleNamespace(
            services={
                "Main Backend": SimpleNamespace(project="Main", type="backend"),
                "Main Frontend": SimpleNamespace(project="Main", type="frontend"),
                "Main Old Worker": SimpleNamespace(project="Main", type="old-worker"),
            }
        )

        cases = (
            ({"no_resume": True, "launch_backend": True, "launch_frontend": False}, {"Main Backend"}),
            ({"no_resume": True, "launch_backend": False, "launch_frontend": True}, {"Main Frontend"}),
            ({"no_resume": True, "launch_backend": False, "launch_frontend": False}, set()),
        )
        for flags, expected in cases:
            with self.subTest(flags=flags):
                selected = fresh_start_replacement_services(
                    route=Route(command="start", mode="trees", raw_args=["start"], flags=flags),
                    selected_contexts=[SimpleNamespace(name="Main")],
                    candidate_state=state,
                    project_name_from_service=lambda _name: "Main",
                )

                self.assertEqual(selected, expected)

    def test_fresh_start_no_dependencies_flag_keeps_unfiltered_removed_service_cleanup(self) -> None:
        state = SimpleNamespace(
            services={
                "Main Backend": SimpleNamespace(project="Main", type="backend"),
                "Main Old Worker": SimpleNamespace(project="Main", type="old-worker"),
            }
        )

        selected = fresh_start_replacement_services(
            route=Route(
                command="start",
                mode="trees",
                raw_args=["start", "--no-resume", "--no-dependencies"],
                flags={"no_resume": True, "launch_dependencies": False},
            ),
            selected_contexts=[SimpleNamespace(name="Main")],
            candidate_state=state,
            project_name_from_service=lambda _name: "Main",
        )

        self.assertEqual(selected, {"Main Backend", "Main Old Worker"})

    def test_replace_existing_project_services_for_fresh_start_terminates_selected_services_and_orphans(self) -> None:
        route = Route(command="start", mode="trees", raw_args=["start"], flags={})
        session = SimpleNamespace(
            effective_route=route,
            runtime_mode="trees",
            selected_contexts=[SimpleNamespace(name="Main")],
            preserved_services={},
            preserved_requirements={},
            base_metadata={},
        )
        candidate_state = SimpleNamespace(
            run_id="run-existing",
            services={
                "Main Backend": SimpleNamespace(project="Main"),
                "Main Frontend": SimpleNamespace(project="Main"),
                "Other Backend": SimpleNamespace(project="Other"),
            },
            requirements={
                "Main": SimpleNamespace(project="Main"),
                "Other": SimpleNamespace(project="Other"),
            },
            metadata={"state_source_run_ids": ["run-ancestor"], "keep": True},
        )
        events: list[tuple[str, dict[str, object]]] = []
        announced: list[object] = []
        progress: list[tuple[Route, str]] = []
        terminated: list[tuple[object, set[str], bool, bool]] = []
        orphaned: list[tuple[object, set[str], bool]] = []
        runtime = SimpleNamespace(
            _emit=lambda event, **payload: events.append((event, payload)),
            _terminate_services_from_state=lambda state, *, selected_services, aggressive, verify_ownership: (
                terminated.append((state, set(selected_services), aggressive, verify_ownership)) or set()
            ),
            _project_name_from_service=lambda name: str(name).removesuffix(" Backend").removesuffix(" Frontend"),
            _release_requirement_ports=lambda requirements: released.append(requirements),
        )
        released: list[object] = []

        replace_existing_project_services_for_fresh_start(
            runtime=runtime,
            session=session,
            candidate_state=candidate_state,
            reason="startup_fingerprint_mismatch",
            announce_session_identifiers=announced.append,
            report_progress=lambda route, message: progress.append((route, message)),
            terminate_restart_orphan_listeners=lambda *, state, selected_services, aggressive: orphaned.append(
                (state, set(selected_services), aggressive)
            ) or set(),
        )

        self.assertEqual(announced, [session])
        self.assertEqual(progress, [(route, "Startup selection changed; replacing 2 existing service(s)...")])
        self.assertEqual(
            events,
            [
                (
                    "state.run_reuse.replace_existing_services",
                    {
                        "run_id": "run-existing",
                        "mode": "trees",
                        "reason": "startup_fingerprint_mismatch",
                        "selected_services": ["Main Backend", "Main Frontend"],
                    },
                )
            ],
        )
        self.assertEqual(terminated, [(candidate_state, {"Main Backend", "Main Frontend"}, False, True)])
        self.assertEqual(orphaned, [(candidate_state, {"Main Backend", "Main Frontend"}, True)])
        self.assertEqual(released, [candidate_state.requirements["Main"]])
        self.assertEqual(session.preserved_services, {"Other Backend": candidate_state.services["Other Backend"]})
        self.assertEqual(session.preserved_requirements, {"Other": candidate_state.requirements["Other"]})
        self.assertEqual(session.base_metadata["state_source_run_ids"], ["run-ancestor", "run-existing"])
        self.assertTrue(session.base_metadata["keep"])

    def test_explicit_no_resume_replaces_matching_services_instead_of_leaking_a_second_copy(self) -> None:
        route = Route(command="start", mode="trees", flags={"no_resume": True})
        session = SimpleNamespace(
            effective_route=route,
            runtime_mode="trees",
            selected_contexts=[SimpleNamespace(name="feature-a")],
            preserved_services={},
            preserved_requirements={},
            base_metadata={},
        )
        candidate_state = SimpleNamespace(
            run_id="run-existing",
            services={"feature-a Backend": SimpleNamespace(project="feature-a")},
            requirements={},
            metadata={},
        )
        terminated: list[set[str]] = []
        progress: list[str] = []
        runtime = SimpleNamespace(
            _emit=lambda *_args, **_kwargs: None,
            _terminate_services_from_state=lambda _state, *, selected_services, **_kwargs: terminated.append(
                set(selected_services)
            ) or set(),
            _project_name_from_service=lambda name: str(name).removesuffix(" Backend"),
            _release_requirement_ports=lambda _requirements: None,
        )

        replace_existing_project_services_for_fresh_start(
            runtime=runtime,
            session=session,
            candidate_state=candidate_state,
            reason="explicit_no_resume",
            announce_session_identifiers=lambda _session: None,
            report_progress=lambda _route, message: progress.append(message),
            terminate_restart_orphan_listeners=lambda **_kwargs: set(),
        )

        self.assertEqual(terminated, [{"feature-a Backend"}])
        self.assertEqual(progress, ["Auto-resume disabled; replacing 1 existing service(s)..."])

    def test_explicit_no_resume_rebinds_reserved_plan_to_released_service_port(self) -> None:
        route = Route(command="start", mode="main", flags={"no_resume": True})
        backend_plan = SimpleNamespace(assigned=8001, final=8001, source="retry")
        context = SimpleNamespace(name="Main", ports={"backend": backend_plan})
        service = SimpleNamespace(
            name="Main Backend",
            project="Main",
            type="backend",
            service_slug="backend",
            listener_expected=True,
            actual_port=8000,
            requested_port=8000,
        )
        session = SimpleNamespace(
            effective_route=route,
            runtime_mode="main",
            selected_contexts=[context],
            preserved_services={},
            preserved_requirements={},
            base_metadata={},
        )
        candidate_state = SimpleNamespace(
            run_id="run-existing",
            services={"Main Backend": service},
            requirements={},
            metadata={},
        )
        calls: list[tuple[str, int, str]] = []
        runtime = SimpleNamespace(
            port_planner=SimpleNamespace(
                release=lambda port, *, owner: calls.append(("release", port, owner)),
            ),
            _emit=lambda *_args, **_kwargs: None,
            _project_name_from_service=lambda _name: "Main",
            _terminate_services_from_state=lambda *_args, **_kwargs: set(),
            _release_requirement_ports=lambda _requirements: None,
        )

        replace_existing_project_services_for_fresh_start(
            runtime=runtime,
            session=session,
            candidate_state=candidate_state,
            reason="explicit_no_resume",
            announce_session_identifiers=lambda _session: None,
            report_progress=lambda _route, _message: None,
            terminate_restart_orphan_listeners=lambda **_kwargs: set(),
        )

        self.assertEqual(calls, [("release", 8001, "Main:backend")])
        self.assertEqual((backend_plan.assigned, backend_plan.final), (8000, 8000))
        self.assertEqual(backend_plan.source, "fresh_start_replacement")

    def test_backend_scoped_fresh_start_preserves_frontend_and_existing_requirements(self) -> None:
        route = Route(
            command="start",
            mode="trees",
            flags={"no_resume": True, "runtime_scope": "backend"},
        )
        backend = SimpleNamespace(project="feature-a", type="backend")
        frontend = SimpleNamespace(project="feature-a", type="frontend")
        requirements = SimpleNamespace(project="feature-a")
        candidate_state = SimpleNamespace(
            run_id="run-existing",
            services={"feature-a Backend": backend, "feature-a Frontend": frontend},
            requirements={"feature-a": requirements},
            metadata={},
        )
        session = SimpleNamespace(
            effective_route=route,
            runtime_mode="trees",
            selected_contexts=[SimpleNamespace(name="feature-a")],
            preserved_services={},
            preserved_requirements={},
            base_metadata={},
        )
        terminated: list[set[str]] = []
        released: list[object] = []
        runtime = SimpleNamespace(
            config=SimpleNamespace(additional_services=()),
            _emit=lambda *_args, **_kwargs: None,
            _project_name_from_service=lambda name: str(name).rsplit(" ", 1)[0],
            _terminate_services_from_state=lambda _state, *, selected_services, **_kwargs: (
                terminated.append(set(selected_services)) or set()
            ),
            _release_requirement_ports=released.append,
        )

        replace_existing_project_services_for_fresh_start(
            runtime=runtime,
            session=session,
            candidate_state=candidate_state,
            reason="explicit_no_resume",
            announce_session_identifiers=lambda _session: None,
            report_progress=lambda *_args: None,
            terminate_restart_orphan_listeners=lambda **_kwargs: set(),
        )

        self.assertEqual(terminated, [{"feature-a Backend"}])
        self.assertEqual(session.preserved_services, {"feature-a Frontend": frontend})
        self.assertEqual(session.preserved_requirements, {"feature-a": requirements})
        self.assertEqual(released, [])

    def test_explicit_no_resume_failure_keeps_previous_state_authoritative(self) -> None:
        route = Route(command="start", mode="trees", flags={"no_resume": True})
        original_service = SimpleNamespace(project="feature-a")
        original_requirements = SimpleNamespace(project="feature-a")
        candidate_state = SimpleNamespace(
            run_id="run-existing",
            services={"feature-a Backend": original_service},
            requirements={"feature-a": original_requirements},
            metadata={"keep": True},
        )
        session = SimpleNamespace(
            effective_route=route,
            runtime_mode="trees",
            selected_contexts=[SimpleNamespace(name="feature-a")],
            preserved_services={"sentinel": object()},
            preserved_requirements={"sentinel": object()},
            base_metadata={"sentinel": True},
        )
        runtime = SimpleNamespace(
            _emit=lambda *_args, **_kwargs: None,
            _project_name_from_service=lambda _name: "feature-a",
            _terminate_services_from_state=lambda *_args, **_kwargs: {"feature-a Backend"},
            _release_requirement_ports=lambda _requirements: self.fail("failed replacement must not release ports"),
        )

        with self.assertRaisesRegex(RuntimeError, "feature-a Backend"):
            replace_existing_project_services_for_fresh_start(
                runtime=runtime,
                session=session,
                candidate_state=candidate_state,
                reason="explicit_no_resume",
                announce_session_identifiers=lambda _session: None,
                report_progress=lambda _route, _message: None,
                terminate_restart_orphan_listeners=lambda **_kwargs: self.fail("must not reap after failure"),
            )

        self.assertEqual(set(session.preserved_services), {"sentinel", "feature-a Backend"})
        self.assertEqual(set(session.preserved_requirements), {"sentinel", "feature-a"})
        self.assertTrue(session.base_metadata["sentinel"])
        self.assertTrue(session.base_metadata["keep"])
        self.assertEqual(session.base_metadata["state_source_run_ids"], ["run-existing"])
        self.assertTrue(session.preserve_existing_state_on_failure)

    def test_explicit_no_resume_missing_termination_result_keeps_previous_state_authoritative(self) -> None:
        route = Route(command="start", mode="trees", flags={"no_resume": True})
        service = SimpleNamespace(project="feature-a")
        candidate_state = SimpleNamespace(
            run_id="run-existing",
            services={"feature-a Backend": service},
            requirements={"feature-a": SimpleNamespace(project="feature-a")},
            metadata={},
        )
        session = SimpleNamespace(
            effective_route=route,
            runtime_mode="trees",
            selected_contexts=[SimpleNamespace(name="feature-a")],
            preserved_services={},
            preserved_requirements={},
            base_metadata={},
        )
        runtime = SimpleNamespace(
            _emit=lambda *_args, **_kwargs: None,
            _project_name_from_service=lambda _name: "feature-a",
            _terminate_services_from_state=lambda *_args, **_kwargs: None,
            _release_requirement_ports=lambda _requirements: self.fail("ports must remain reserved"),
        )

        with self.assertRaisesRegex(RuntimeError, "feature-a Backend"):
            replace_existing_project_services_for_fresh_start(
                runtime=runtime,
                session=session,
                candidate_state=candidate_state,
                reason="explicit_no_resume",
                announce_session_identifiers=lambda _session: None,
                report_progress=lambda *_args: None,
                terminate_restart_orphan_listeners=lambda **_kwargs: self.fail("orphans must not be reaped"),
            )

        self.assertTrue(session.preserve_existing_state_on_failure)
        self.assertEqual(session.preserved_services, candidate_state.services)
        self.assertEqual(session.preserved_requirements, candidate_state.requirements)

    def test_fresh_start_preserves_source_authority_when_termination_raises(self) -> None:
        service = SimpleNamespace(project="feature-a")
        requirements = SimpleNamespace(project="feature-a")
        candidate_state = SimpleNamespace(
            run_id="run-existing",
            services={"feature-a Backend": service},
            requirements={"feature-a": requirements},
            metadata={"authority": "old"},
        )
        session = SimpleNamespace(
            effective_route=Route(command="start", mode="trees", flags={"no_resume": True}),
            runtime_mode="trees",
            selected_contexts=[SimpleNamespace(name="feature-a")],
            preserved_services={},
            preserved_requirements={},
            base_metadata={},
        )

        def fail_termination(*_args, **_kwargs):  # noqa: ANN202
            raise OSError("service lock unlink failed")

        runtime = SimpleNamespace(
            _emit=lambda *_args, **_kwargs: None,
            _project_name_from_service=lambda _name: "feature-a",
            _terminate_services_from_state=fail_termination,
            _release_requirement_ports=lambda _requirements: self.fail("ports must remain reserved"),
        )

        with self.assertRaisesRegex(OSError, "service lock unlink failed"):
            replace_existing_project_services_for_fresh_start(
                runtime=runtime,
                session=session,
                candidate_state=candidate_state,
                reason="explicit_no_resume",
                announce_session_identifiers=lambda _session: None,
                report_progress=lambda *_args: None,
                terminate_restart_orphan_listeners=lambda **_kwargs: self.fail("orphans must not be reaped"),
            )

        self.assertTrue(session.preserve_existing_state_on_failure)
        self.assertEqual(session.preserved_services, candidate_state.services)
        self.assertEqual(session.preserved_requirements, candidate_state.requirements)
        self.assertEqual(session.base_metadata["authority"], "old")
        self.assertEqual(session.base_metadata["state_source_run_ids"], ["run-existing"])

    def test_fresh_start_preserves_source_authority_when_requirement_release_raises(self) -> None:
        requirements = SimpleNamespace(project="feature-a")
        candidate_state = SimpleNamespace(
            run_id="run-existing",
            services={},
            requirements={"feature-a": requirements},
            metadata={"authority": "old"},
        )
        session = SimpleNamespace(
            effective_route=Route(command="start", mode="trees", flags={"no_resume": True}),
            runtime_mode="trees",
            selected_contexts=[SimpleNamespace(name="feature-a")],
            preserved_services={},
            preserved_requirements={},
            base_metadata={},
        )

        def fail_release(_requirements):  # noqa: ANN001, ANN202
            raise OSError("requirement lock unlink failed")

        runtime = SimpleNamespace(
            _emit=lambda *_args, **_kwargs: None,
            _project_name_from_service=lambda _name: "",
            _terminate_services_from_state=lambda *_args, **_kwargs: self.fail("no services to terminate"),
            _release_requirement_ports=fail_release,
        )

        with self.assertRaisesRegex(OSError, "requirement lock unlink failed"):
            replace_existing_project_services_for_fresh_start(
                runtime=runtime,
                session=session,
                candidate_state=candidate_state,
                reason="explicit_no_resume",
                announce_session_identifiers=lambda _session: self.fail("no announcement expected"),
                report_progress=lambda *_args: self.fail("no progress expected"),
                terminate_restart_orphan_listeners=lambda **_kwargs: self.fail("no orphan scan expected"),
            )

        self.assertTrue(session.preserve_existing_state_on_failure)
        self.assertEqual(session.preserved_requirements, candidate_state.requirements)
        self.assertEqual(session.base_metadata["state_source_run_ids"], ["run-existing"])

    def test_fresh_start_aborts_when_orphan_exit_is_unconfirmed(self) -> None:
        route = Route(command="start", mode="trees", flags={"no_resume": True})
        candidate_state = SimpleNamespace(
            run_id="run-existing",
            services={"feature-a Backend": SimpleNamespace(project="feature-a")},
            requirements={"feature-a": SimpleNamespace(project="feature-a")},
            metadata={},
        )
        session = SimpleNamespace(
            effective_route=route,
            runtime_mode="trees",
            selected_contexts=[SimpleNamespace(name="feature-a")],
            preserved_services={},
            preserved_requirements={},
            base_metadata={},
        )
        runtime = SimpleNamespace(
            _emit=lambda *_args, **_kwargs: None,
            _project_name_from_service=lambda _name: "feature-a",
            _terminate_services_from_state=lambda *_args, **_kwargs: set(),
            _release_requirement_ports=lambda _requirements: self.fail("ports must remain reserved"),
        )

        with self.assertRaisesRegex(RuntimeError, "orphan listeners.*4242"):
            replace_existing_project_services_for_fresh_start(
                runtime=runtime,
                session=session,
                candidate_state=candidate_state,
                reason="explicit_no_resume",
                announce_session_identifiers=lambda _session: None,
                report_progress=lambda *_args: None,
                terminate_restart_orphan_listeners=lambda **_kwargs: {4242},
            )

        self.assertTrue(session.preserve_existing_state_on_failure)
        self.assertEqual(session.preserved_services, candidate_state.services)
        self.assertEqual(session.preserved_requirements, candidate_state.requirements)

    def test_explicit_no_resume_supersedes_requirement_only_state(self) -> None:
        route = Route(
            command="start",
            mode="trees",
            projects=["feature-a"],
            flags={"no_resume": True},
        )
        target_requirements = SimpleNamespace(project="feature-a")
        other_requirements = SimpleNamespace(project="feature-b")
        candidate_state = SimpleNamespace(
            run_id="run-existing",
            services={},
            requirements={"feature-a": target_requirements, "feature-b": other_requirements},
            metadata={},
        )
        session = SimpleNamespace(
            effective_route=route,
            runtime_mode="trees",
            selected_contexts=[SimpleNamespace(name="feature-a")],
            preserved_services={},
            preserved_requirements={},
            base_metadata={},
        )
        released: list[object] = []
        runtime = SimpleNamespace(
            _emit=lambda *_args, **_kwargs: None,
            _project_name_from_service=lambda _name: "",
            _terminate_services_from_state=lambda *_args, **_kwargs: self.fail("no service termination expected"),
            _release_requirement_ports=released.append,
        )

        replace_existing_project_services_for_fresh_start(
            runtime=runtime,
            session=session,
            candidate_state=candidate_state,
            reason="explicit_no_resume",
            announce_session_identifiers=lambda _session: self.fail("empty replacement needs no announcement"),
            report_progress=lambda _route, _message: self.fail("empty replacement needs no progress"),
            terminate_restart_orphan_listeners=lambda **_kwargs: self.fail("no orphan scan expected"),
        )

        self.assertEqual(released, [target_requirements])
        self.assertEqual(session.preserved_requirements, {"feature-b": other_requirements})
        self.assertEqual(session.base_metadata["state_source_run_ids"], ["run-existing"])

    def test_no_reusable_runtime_still_supersedes_requirement_only_state(self) -> None:
        target_requirements = SimpleNamespace(project="feature-a")
        candidate_state = SimpleNamespace(
            run_id="run-existing",
            services={},
            requirements={"feature-a": target_requirements},
            metadata={"existing": True},
        )
        session = SimpleNamespace(
            effective_route=Route(command="start", mode="trees", flags={}),
            runtime_mode="trees",
            selected_contexts=[SimpleNamespace(name="feature-a")],
            preserved_services={},
            preserved_requirements={},
            base_metadata={},
        )
        released: list[object] = []
        runtime = SimpleNamespace(
            _emit=lambda *_args, **_kwargs: None,
            _project_name_from_service=lambda _name: "",
            _terminate_services_from_state=lambda *_args, **_kwargs: self.fail("no services should be stopped"),
            _release_requirement_ports=released.append,
        )

        replace_existing_project_services_for_fresh_start(
            runtime=runtime,
            session=session,
            candidate_state=candidate_state,
            reason="no_reusable_runtime",
            announce_session_identifiers=lambda _session: self.fail("no services need an announcement"),
            report_progress=lambda _route, _message: self.fail("no services need progress"),
            terminate_restart_orphan_listeners=lambda **_kwargs: self.fail("no orphan scan expected"),
        )

        self.assertEqual(released, [target_requirements])
        self.assertEqual(session.base_metadata["state_source_run_ids"], ["run-existing"])

    def test_dependencies_only_fresh_start_preserves_services_but_replaces_selected_requirements(self) -> None:
        target_service = SimpleNamespace(project="feature-a")
        other_service = SimpleNamespace(project="feature-b")
        target_requirements = SimpleNamespace(project="feature-a")
        other_requirements = SimpleNamespace(project="feature-b")
        candidate_state = SimpleNamespace(
            run_id="run-existing",
            services={"feature-a Backend": target_service, "feature-b Backend": other_service},
            requirements={"feature-a": target_requirements, "feature-b": other_requirements},
            metadata={},
        )
        session = SimpleNamespace(
            effective_route=Route(command="start", mode="trees", flags={"runtime_scope": "dependencies"}),
            runtime_mode="trees",
            selected_contexts=[SimpleNamespace(name="feature-a")],
            preserved_services={},
            preserved_requirements={},
            base_metadata={},
        )
        released: list[object] = []
        runtime = SimpleNamespace(
            _emit=lambda *_args, **_kwargs: None,
            _project_name_from_service=lambda _name: "feature-a",
            _terminate_services_from_state=lambda *_args, **_kwargs: self.fail("app services must be preserved"),
            _release_requirement_ports=released.append,
        )

        replace_existing_project_services_for_fresh_start(
            runtime=runtime,
            session=session,
            candidate_state=candidate_state,
            reason="startup_fingerprint_mismatch",
            announce_session_identifiers=lambda _session: self.fail("app services must be preserved"),
            report_progress=lambda _route, _message: self.fail("app services must be preserved"),
            terminate_restart_orphan_listeners=lambda **_kwargs: self.fail("no orphan scan expected"),
        )

        self.assertEqual(session.preserved_services, candidate_state.services)
        self.assertEqual(session.preserved_requirements, {"feature-b": other_requirements})
        self.assertEqual(released, [target_requirements])
        self.assertEqual(session.base_metadata["state_source_run_ids"], ["run-existing"])

    def test_fresh_start_replacement_services_does_not_leave_disabled_service_types_running(self) -> None:
        candidate_state = SimpleNamespace(
            services={
                "Main Backend": SimpleNamespace(name="Main Backend", project="Main", type="backend"),
                "Main Frontend": SimpleNamespace(name="Main Frontend", project="Main", type="frontend"),
            }
        )

        self.assertEqual(
            fresh_start_replacement_services(
                selected_contexts=[SimpleNamespace(name="Main")],
                candidate_state=candidate_state,
                project_name_from_service=lambda name: str(name).removesuffix(" Backend").removesuffix(" Frontend"),
            ),
            {"Main Backend", "Main Frontend"},
        )


if __name__ == "__main__":
    unittest.main()
