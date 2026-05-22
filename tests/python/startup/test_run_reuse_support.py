from __future__ import annotations

import unittest
from types import SimpleNamespace

from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.run_reuse_support import (
    dashboard_stopped_service_entries,
    fresh_start_replacement_services,
    prepare_dashboard_stopped_service_restore,
    replace_existing_project_services_for_fresh_start,
    metadata_without_dashboard_stopped_services,
    run_reuse_debug_orch_groups,
)


class RunReuseSupportTests(unittest.TestCase):
    def test_run_reuse_debug_orch_groups_only_apply_to_plan_commands(self) -> None:
        runtime = SimpleNamespace(env={"ENVCTL_DEBUG_PLAN_ORCH_GROUP": "alpha+ beta,gamma ,,"})

        self.assertEqual(run_reuse_debug_orch_groups(runtime, requested_command="plan"), {"alpha", "beta", "gamma"})
        self.assertEqual(run_reuse_debug_orch_groups(runtime, requested_command="start"), set())

    def test_dashboard_stopped_service_entries_normalizes_valid_backend_frontend_entries(self) -> None:
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
            ],
        )

    def test_dashboard_stopped_service_entries_ignores_missing_or_invalid_metadata(self) -> None:
        self.assertEqual(dashboard_stopped_service_entries(SimpleNamespace(metadata={})), [])
        self.assertEqual(dashboard_stopped_service_entries(SimpleNamespace(metadata={"dashboard_stopped_services": {}})), [])

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
        self.assertNotIn("dashboard_stopped_services", session.base_metadata)
        self.assertEqual(session.effective_route.projects, ["Main", "Other"])
        self.assertEqual(session.effective_route.flags["_restart_request"], True)
        self.assertEqual(session.effective_route.flags["_restore_dashboard_stopped_services"], True)
        self.assertEqual(session.effective_route.flags["services"], ["Main Frontend", "Other Backend"])
        self.assertEqual(session.effective_route.flags["restart_service_types"], ["backend", "frontend"])
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

    def test_fresh_start_replacement_services_selects_configured_service_types_for_target_projects(self) -> None:
        route = Route(command="start", mode="main", raw_args=["start"], flags={})
        candidate_state = SimpleNamespace(
            services={
                "Main Backend": SimpleNamespace(name="Main Backend", project="Main", type="backend"),
                "Main Frontend": SimpleNamespace(name="Main Frontend", project="Main", type="frontend"),
                "Other Backend": SimpleNamespace(name="Other Backend", project="Other", type="backend"),
            }
        )

        self.assertEqual(
            fresh_start_replacement_services(
                route=route,
                selected_contexts=[SimpleNamespace(name="Main")],
                candidate_state=candidate_state,
                configured_service_types={"backend"},
                additional_services=(),
                project_name_from_service=lambda name: str(name).removesuffix(" Backend").removesuffix(" Frontend"),
            ),
            {"Main Backend"},
        )

    def test_replace_existing_project_services_for_fresh_start_terminates_selected_services_and_orphans(self) -> None:
        route = Route(command="start", mode="trees", raw_args=["start"], flags={})
        session = SimpleNamespace(effective_route=route, runtime_mode="trees")
        candidate_state = SimpleNamespace(run_id="run-existing")
        events: list[tuple[str, dict[str, object]]] = []
        announced: list[object] = []
        progress: list[tuple[Route, str]] = []
        terminated: list[tuple[object, set[str], bool, bool]] = []
        orphaned: list[tuple[object, set[str], bool]] = []
        runtime = SimpleNamespace(
            _emit=lambda event, **payload: events.append((event, payload)),
            _terminate_services_from_state=lambda state, *, selected_services, aggressive, verify_ownership: terminated.append(
                (state, set(selected_services), aggressive, verify_ownership)
            ),
        )

        replace_existing_project_services_for_fresh_start(
            runtime=runtime,
            session=session,
            candidate_state=candidate_state,
            reason="startup_fingerprint_mismatch",
            fresh_start_replacement_services=lambda session, *, candidate_state: {"Main Backend", "Main Frontend"},
            announce_session_identifiers=announced.append,
            report_progress=lambda route, message: progress.append((route, message)),
            terminate_restart_orphan_listeners=lambda *, state, selected_services, aggressive: orphaned.append(
                (state, set(selected_services), aggressive)
            ),
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

    def test_replace_existing_project_services_for_fresh_start_skips_non_mismatch_or_dependencies_scope(self) -> None:
        runtime = SimpleNamespace(_emit=lambda *args, **kwargs: self.fail("replace should not emit"))
        candidate_state = SimpleNamespace(run_id="run-existing")

        for reason, flags in (
            ("no_matching_state", {}),
            ("startup_fingerprint_mismatch", {"runtime_scope": "dependencies"}),
        ):
            route = Route(command="start", mode="trees", raw_args=["start"], flags=flags)
            session = SimpleNamespace(effective_route=route, runtime_mode="trees")
            replace_existing_project_services_for_fresh_start(
                runtime=runtime,
                session=session,
                candidate_state=candidate_state,
                reason=reason,
                fresh_start_replacement_services=lambda session, *, candidate_state: self.fail("selection should skip"),
                announce_session_identifiers=lambda session: self.fail("announce should skip"),
                report_progress=lambda route, message: self.fail("progress should skip"),
                terminate_restart_orphan_listeners=lambda **kwargs: self.fail("orphan cleanup should skip"),
            )

    def test_fresh_start_replacement_services_honors_restart_service_type_filters(self) -> None:
        route = Route(
            command="restart",
            mode="main",
            raw_args=["restart"],
            flags={"_restart_request": True, "restart_service_types": ["frontend"]},
        )
        candidate_state = SimpleNamespace(
            services={
                "Main Backend": SimpleNamespace(name="Main Backend", project="Main", type="backend"),
                "Main Frontend": SimpleNamespace(name="Main Frontend", project="Main", type="frontend"),
            }
        )

        self.assertEqual(
            fresh_start_replacement_services(
                route=route,
                selected_contexts=[SimpleNamespace(name="Main")],
                candidate_state=candidate_state,
                configured_service_types={"backend", "frontend"},
                additional_services=(),
                project_name_from_service=lambda name: str(name).removesuffix(" Backend").removesuffix(" Frontend"),
            ),
            {"Main Frontend"},
        )


if __name__ == "__main__":
    unittest.main()
