from __future__ import annotations

import hashlib
import json
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
from envctl_engine.startup.run_reuse_decision import state_has_resumable_services
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
        self.assertEqual(identity["application_runtime"], "process")
        self.assertEqual(identity["projects"], [{"name": "Main", "root": normalize_project_root("/tmp/repo")}])
        self.assertEqual(identity["services"], {"backend": True, "frontend": False})
        self.assertIn("fingerprint", identity)

    def test_build_startup_identity_metadata_preserves_unselected_roots_without_case_duplicates(self) -> None:
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                backend_dir_name="api",
                frontend_dir_name="web",
                additional_services=(),
                startup_enabled_for_mode=lambda _mode: True,
                service_enabled_for_mode=lambda _mode, service: service == "backend",
                requirement_enabled_for_mode=lambda _mode, _requirement: False,
            )
        )

        metadata = build_startup_identity_metadata(
            runtime,
            runtime_mode="trees",
            project_contexts=[SimpleNamespace(name="featurea", root=Path("/tmp/new-a"))],
            base_metadata={
                "project_roots": {
                    "FEATUREA": "/tmp/old-a",
                    "FeatureB": "/tmp/feature-b",
                }
            },
            route=Route(command="start", mode="trees", flags={}),
        )

        self.assertEqual(
            metadata["project_roots"],
            {
                "featurea": normalize_project_root("/tmp/new-a"),
                "FeatureB": normalize_project_root("/tmp/feature-b"),
            },
        )
        identity = metadata["startup_identity"]
        self.assertEqual(
            identity["projects"],
            [
                {"name": "featurea", "root": normalize_project_root("/tmp/new-a")},
                {"name": "FeatureB", "root": normalize_project_root("/tmp/feature-b")},
            ],
        )
        fingerprint_payload = {key: value for key, value in identity.items() if key != "fingerprint"}
        self.assertEqual(
            identity["fingerprint"],
            hashlib.sha256(json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")).hexdigest(),
        )

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

    def test_state_identity_and_resumability_prefer_multiword_record_project_metadata(self) -> None:
        service = ServiceRecord(
            name="Opaque API Runtime",
            type="backend",
            cwd="/tmp/customer-platform/runtime",
            project="Customer Platform",
        )
        state = RunState(
            run_id="run-metadata",
            mode="trees",
            services={service.name: service},
            metadata={"project_roots": {"Customer Platform": "/tmp/customer-platform"}},
        )
        runtime = SimpleNamespace(_project_name_from_service=lambda _name: "Opaque API")

        self.assertEqual(
            identities_to_payload(project_identities_from_state(runtime, state)),
            [
                {
                    "name": "Customer Platform",
                    "root": normalize_project_root("/tmp/customer-platform"),
                }
            ],
        )
        self.assertTrue(state_has_resumable_services(runtime, state))

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
            _startup_identity_mismatch(
                {"fingerprint": "same", "mode": "main"}, {"fingerprint": "same", "mode": "trees"}
            ),
            {},
        )

        mismatch = _startup_identity_mismatch(
            {"mode": "main", "services": {"backend": True}},
            {"mode": "trees", "services": {"backend": True}},
        )

        self.assertEqual(mismatch, {"fields": ["mode"]})

        self.assertEqual(
            _startup_identity_mismatch(
                {"mode": "main", "services": {"backend": True}},
                {"mode": "main", "services": {"backend": True}, "application_runtime": "process"},
            ),
            {},
        )
        self.assertEqual(
            _startup_identity_mismatch(
                {"mode": "main", "application_runtime": "process"},
                {"mode": "main", "application_runtime": "docker"},
            ),
            {"fields": ["application_runtime"]},
        )

    def test_root_mismatches_compare_only_strong_roots(self) -> None:
        selected = [ProjectIdentity("Main", "/repo"), ProjectIdentity("Weak", None)]
        state = [ProjectIdentity("Main", "/other"), ProjectIdentity("Weak", "/weak")]

        self.assertEqual(_root_mismatches(selected, state), {"Main"})


if __name__ == "__main__":
    unittest.main()
