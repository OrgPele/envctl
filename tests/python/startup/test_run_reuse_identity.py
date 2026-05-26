from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.run_reuse_identity import (
    ProjectIdentity,
    _identity_keys,
    _root_mismatches,
    _startup_identity_mismatch,
    build_startup_identity_metadata,
    identities_to_payload,
    normalize_project_root,
    project_identities_from_contexts,
    project_identities_from_state,
)
from envctl_engine.state.models import RunState, ServiceRecord


class RunReuseIdentityTests(unittest.TestCase):
    def test_build_startup_identity_metadata_records_roots_and_fingerprint_payload(self) -> None:
        context = SimpleNamespace(name="Main", root=Path("/tmp/repo"))
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                backend_dir_name="api",
                frontend_dir_name="web",
                additional_services=(),
                startup_enabled_for_mode=lambda mode: mode == "main",
                service_enabled_for_mode=lambda mode, service: service == "backend",
                requirement_enabled_for_mode=lambda mode, requirement: requirement == "postgres",
            )
        )

        metadata = build_startup_identity_metadata(
            runtime,
            runtime_mode="main",
            project_contexts=[context],
            base_metadata={"keep": True},
            route=Route(command="start", mode="main", raw_args=["start"], flags={}),
        )

        self.assertEqual(metadata["keep"], True)
        self.assertEqual(metadata["project_roots"], {"Main": normalize_project_root("/tmp/repo")})
        identity = metadata["startup_identity"]
        self.assertEqual(identity["mode"], "main")
        self.assertEqual(identity["projects"], [{"name": "Main", "root": normalize_project_root("/tmp/repo")}])
        self.assertEqual(identity["services"], {"backend": True, "frontend": False})
        self.assertIn("fingerprint", identity)

    def test_project_identities_from_state_uses_metadata_requirements_and_services(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="trees",
            services={
                "Feature Backend": ServiceRecord(name="Feature Backend", type="backend", cwd="/tmp/feature/backend"),
            },
            requirements={"Main": object()},
            metadata={"project_roots": {"Main": "/tmp/main"}},
        )
        runtime = SimpleNamespace(_project_name_from_service=lambda service_name: service_name.split()[0])

        self.assertEqual(
            identities_to_payload(project_identities_from_state(runtime, state)),
            [
                {"name": "Feature", "root": None},
                {"name": "Main", "root": normalize_project_root("/tmp/main")},
            ],
        )

    def test_context_identity_sorting_and_weak_keys_are_stable(self) -> None:
        identities = project_identities_from_contexts(
            [
                SimpleNamespace(name="Beta", root="/tmp/beta"),
                SimpleNamespace(name="alpha", root=None),
                SimpleNamespace(name="", root="/tmp/ignored"),
            ]
        )

        self.assertEqual([identity.name for identity in identities], ["alpha", "Beta"])
        self.assertEqual(_identity_keys(identities, weak=True), {("alpha", None), ("beta", None)})

    def test_startup_identity_mismatch_ignores_matching_fingerprints_and_reports_changed_fields(self) -> None:
        self.assertEqual(
            _startup_identity_mismatch({"fingerprint": "same", "mode": "main"}, {"fingerprint": "same", "mode": "trees"}),
            {},
        )

        mismatch = _startup_identity_mismatch(
            {"mode": "main", "services": {"backend": True}},
            {"mode": "trees", "services": {"backend": True}},
        )

        self.assertEqual(mismatch, {"fields": ["mode"]})

    def test_root_mismatches_compare_only_strong_roots(self) -> None:
        selected = [ProjectIdentity("Main", "/repo"), ProjectIdentity("Weak", None)]
        state = [ProjectIdentity("Main", "/other"), ProjectIdentity("Weak", "/weak")]

        self.assertEqual(_root_mismatches(selected, state), {"Main"})


if __name__ == "__main__":
    unittest.main()
