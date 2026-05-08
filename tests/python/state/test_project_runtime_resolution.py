from __future__ import annotations

import unittest
from types import SimpleNamespace

from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord
from envctl_engine.state.project_runtime import (
    active_project_names,
    cwd_runtime_warnings,
    dependency_mode_summary,
    infer_cwd_project,
    requested_project_not_running_payload,
    resolve_requested_project_state,
)


class ProjectRuntimeResolutionTests(unittest.TestCase):
    def test_active_project_names_include_requirements_services_and_metadata_roots(self) -> None:
        state = RunState(
            run_id="run-projects",
            mode="trees",
            services={
                "service-a": ServiceRecord(name="service-a", type="backend", cwd="/tmp/a", project="alpha"),
                "beta Frontend": ServiceRecord(name="beta Frontend", type="frontend", cwd="/tmp/b"),
            },
            requirements={"gamma": RequirementsResult(project="gamma")},
            metadata={"project_roots": {"delta": "/tmp/d"}},
        )

        self.assertEqual(active_project_names(state), ["alpha", "beta", "delta", "gamma"])

    def test_requested_project_match_filters_state_to_canonical_project(self) -> None:
        state = RunState(
            run_id="run-active",
            mode="trees",
            services={
                "Alpha Backend": ServiceRecord(name="Alpha Backend", type="backend", cwd="/tmp/a", project="Alpha"),
                "Beta Frontend": ServiceRecord(name="Beta Frontend", type="frontend", cwd="/tmp/b", project="Beta"),
            },
            requirements={
                "Alpha": RequirementsResult(project="Alpha"),
                "Beta": RequirementsResult(project="Beta"),
            },
            metadata={"project_roots": {"Alpha": "/tmp/a", "Beta": "/tmp/b"}},
        )

        resolution = resolve_requested_project_state(state, ["alpha"], command="health")

        self.assertTrue(resolution.ok)
        self.assertEqual(resolution.requested_project, "alpha")
        self.assertEqual(resolution.selected_projects, ["Alpha"])
        self.assertIsNotNone(resolution.state)
        assert resolution.state is not None
        self.assertEqual(set(resolution.state.services), {"Alpha Backend"})
        self.assertEqual(set(resolution.state.requirements), {"Alpha"})
        self.assertEqual(resolution.state.metadata["project_roots"], {"Alpha": "/tmp/a"})

    def test_missing_requested_project_returns_fail_closed_payload(self) -> None:
        state = RunState(
            run_id="run-active",
            mode="trees",
            services={"Active Backend": ServiceRecord(name="Active Backend", type="backend", cwd="/tmp/a")},
        )

        resolution = resolve_requested_project_state(state, ["missing"], command="health")

        self.assertFalse(resolution.ok)
        self.assertEqual(resolution.error, "requested_project_not_running")
        self.assertEqual(
            resolution.payload(),
            {
                "ok": False,
                "error": "requested_project_not_running",
                "requested_project": "missing",
                "active_projects": ["Active"],
            },
        )

    def test_single_project_commands_reject_multiple_projects(self) -> None:
        state = RunState(
            run_id="run-active",
            mode="trees",
            requirements={"alpha": RequirementsResult(project="alpha"), "beta": RequirementsResult(project="beta")},
        )

        resolution = resolve_requested_project_state(
            state,
            ["alpha", "beta"],
            command="endpoints",
            allow_multi=False,
        )

        self.assertFalse(resolution.ok)
        self.assertEqual(resolution.error, "multiple_projects_not_supported")
        self.assertEqual(resolution.payload()["requested_projects"], ["alpha", "beta"])

    def test_payload_helper_uses_stable_error_contract(self) -> None:
        self.assertEqual(
            requested_project_not_running_payload(requested_project="missing", active_projects=["active"]),
            {
                "ok": False,
                "error": "requested_project_not_running",
                "requested_project": "missing",
                "active_projects": ["active"],
            },
        )

    def test_dependency_mode_summary_prefers_explicit_metadata_and_derives_legacy_shared(self) -> None:
        explicit = RunState(
            run_id="run-explicit",
            mode="trees",
            metadata={"dependency_mode": "isolated", "shared_dependencies": False},
        )
        self.assertEqual(dependency_mode_summary(explicit), {"dependency_mode": "isolated", "shared_dependencies": False})

        legacy_shared = RunState(
            run_id="run-legacy",
            mode="trees",
            metadata={"dashboard_dependency_scope": "shared"},
        )
        self.assertEqual(dependency_mode_summary(legacy_shared), {"dependency_mode": "shared", "shared_dependencies": True})

        unknown = RunState(run_id="run-unknown", mode="trees")
        self.assertEqual(dependency_mode_summary(unknown), {"dependency_mode": "unknown", "shared_dependencies": None})

    def test_runtime_backed_project_names_use_runtime_canonical_service_lookup(self) -> None:
        runtime = SimpleNamespace(_project_name_from_service=lambda service_name: "Canonical")
        state = RunState(
            run_id="run-runtime",
            mode="trees",
            services={"raw-service": ServiceRecord(name="raw-service", type="backend", cwd="/tmp/raw")},
        )

        self.assertEqual(active_project_names(state, runtime=runtime), ["Canonical"])

    def test_cwd_runtime_warning_reports_when_invocation_cwd_differs_from_active_project(self) -> None:
        state = RunState(
            run_id="run-cwd",
            mode="trees",
            services={"beta Backend": ServiceRecord(name="beta Backend", type="backend", cwd="/repo/trees/beta/1")},
            metadata={"project_roots": {"alpha": "/repo/trees/alpha/1", "beta": "/repo/trees/beta/1"}},
        )
        runtime = SimpleNamespace(env={"ENVCTL_INVOCATION_CWD": "/repo/trees/alpha/1/api"})

        cwd_project, warnings = cwd_runtime_warnings(state, runtime=runtime)

        self.assertEqual(cwd_project, "alpha")
        self.assertEqual(warnings[0]["code"], "cwd_runtime_mismatch")
        self.assertEqual(warnings[0]["active_projects"], ["beta"])

    def test_cwd_warning_is_suppressed_when_explicit_project_is_supplied(self) -> None:
        state = RunState(
            run_id="run-cwd-explicit",
            mode="trees",
            services={"beta Backend": ServiceRecord(name="beta Backend", type="backend", cwd="/repo/trees/beta/1")},
            metadata={"project_roots": {"alpha": "/repo/trees/alpha/1", "beta": "/repo/trees/beta/1"}},
        )
        runtime = SimpleNamespace(env={"ENVCTL_INVOCATION_CWD": "/repo/trees/alpha/1/api"})

        self.assertEqual(cwd_runtime_warnings(state, runtime=runtime, requested_projects=["beta"]), ("alpha", []))
        self.assertEqual(infer_cwd_project(state, runtime=runtime), "alpha")


if __name__ == "__main__":
    unittest.main()
