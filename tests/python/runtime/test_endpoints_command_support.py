from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from types import SimpleNamespace
import unittest

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.endpoints_command_support import build_endpoints_payload, run_endpoints_command
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord


class EndpointsCommandSupportTests(unittest.TestCase):
    def test_missing_project_returns_fail_closed_json(self) -> None:
        runtime = SimpleNamespace(
            env={},
            config=SimpleNamespace(raw={}),
            _try_load_existing_state=lambda **_kwargs: RunState(
                run_id="run-1",
                mode="trees",
                services={"Active Backend": ServiceRecord(name="Active Backend", type="backend", cwd="/tmp/a")},
            ),
            _state_lookup_strict_mode_match=lambda _route: True,
            _emit=lambda *_args, **_kwargs: None,
        )
        route = Route(command="endpoints", mode="trees", projects=["missing"], flags={"json": True})

        stdout = StringIO()
        with redirect_stdout(stdout):
            code = run_endpoints_command(runtime, route)

        self.assertEqual(code, 1)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {
                "ok": False,
                "error": "requested_project_not_running",
                "requested_project": "missing",
                "active_projects": ["Active"],
            },
        )

    def test_active_project_json_reports_urls_dependency_ports_and_mode(self) -> None:
        state = RunState(
            run_id="run-2",
            mode="trees",
            metadata={
                "project_roots": {"feature-a-1": "/repo/trees/feature-a/1", "feature-b-1": "/repo/trees/b/1"},
                "dependency_mode": "isolated",
                "shared_dependencies": False,
            },
            services={
                "feature-a-1 Backend": ServiceRecord(
                    name="feature-a-1 Backend",
                    type="backend",
                    cwd="/repo/trees/feature-a/1/api",
                    project="feature-a-1",
                    status="running",
                    actual_port=8100,
                ),
                "feature-a-1 Frontend": ServiceRecord(
                    name="feature-a-1 Frontend",
                    type="frontend",
                    cwd="/repo/trees/feature-a/1/web",
                    project="feature-a-1",
                    status="running",
                    actual_port=3100,
                    public_url="https://feature-a.example.test",
                ),
                "feature-a-1 Voice Runtime": ServiceRecord(
                    name="feature-a-1 Voice Runtime",
                    type="voice-runtime",
                    cwd="/repo/trees/feature-a/1/voice-runtime",
                    project="feature-a-1",
                    status="running",
                    actual_port=8110,
                    public_url="https://voice.feature-a.example.test",
                    health_url="http://localhost:8110/readyz",
                ),
                "feature-b-1 Frontend": ServiceRecord(
                    name="feature-b-1 Frontend",
                    type="frontend",
                    cwd="/repo/trees/b/1/web",
                    project="feature-b-1",
                    status="running",
                    actual_port=3200,
                ),
            },
            requirements={
                "feature-a-1": RequirementsResult(
                    project="feature-a-1",
                    redis={"enabled": True, "success": True, "final": 6380, "runtime_status": "healthy"},
                    supabase={
                        "enabled": True,
                        "success": True,
                        "resources": {"db": 5432, "api": 54321, "primary": 5432, "requested": 5432},
                    },
                ),
                "feature-b-1": RequirementsResult(project="feature-b-1", redis={"enabled": True, "final": 6381}),
            },
        )

        payload = build_endpoints_payload(
            state,
            project="feature-a-1",
            env={"ENVCTL_PUBLIC_HOST": "public.example.test"},
            config=SimpleNamespace(
                raw={},
                additional_services=(SimpleNamespace(name="voice-runtime"),),
            ),
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["project"], "feature-a-1")
        self.assertEqual(payload["run_id"], "run-2")
        self.assertEqual(payload["dependency_mode"], "isolated")
        self.assertFalse(payload["shared_dependencies"])
        self.assertEqual(payload["project_root"], "/repo/trees/feature-a/1")
        self.assertEqual(payload["frontend"]["local_url"], "http://localhost:3100")
        self.assertEqual(payload["frontend"]["public_url"], "https://feature-a.example.test")
        self.assertEqual(payload["backend"]["local_url"], "http://localhost:8100")
        self.assertEqual(payload["backend"]["public_url"], "http://public.example.test:8100")
        self.assertEqual(payload["additional_services"]["voice-runtime"]["port"], 8110)
        self.assertEqual(
            payload["additional_services"]["voice-runtime"]["public_url"],
            "https://voice.feature-a.example.test",
        )
        self.assertEqual(
            payload["additional_services"]["voice-runtime"]["health_url"],
            "http://localhost:8110/readyz",
        )
        self.assertEqual(payload["dependencies"]["redis"]["port"], 6380)
        self.assertEqual(payload["dependencies"]["supabase"]["port"], 54321)
        self.assertEqual(payload["dependencies"]["supabase"]["resources"], {"api": 54321, "db": 5432, "primary": 5432})
        self.assertEqual(payload["dependencies"]["supabase_db"]["port"], 5432)
        self.assertEqual(payload["dependencies"]["supabase_api"]["port"], 54321)
        self.assertNotIn("feature-b-1", json.dumps(payload))

    def test_supabase_api_endpoint_does_not_fallback_to_db_port_when_api_resource_is_missing(self) -> None:
        state = RunState(
            run_id="run-missing-api",
            mode="main",
            requirements={
                "Main": RequirementsResult(
                    project="Main",
                    supabase={
                        "enabled": True,
                        "success": True,
                        "final": 5574,
                        "resources": {"db": 5574, "primary": 5574, "requested": 5662},
                    },
                )
            },
        )

        payload = build_endpoints_payload(state, project="Main", env={}, config=SimpleNamespace(raw={}))

        self.assertEqual(payload["dependencies"]["supabase"]["resources"], {"db": 5574, "primary": 5574})
        self.assertEqual(payload["dependencies"]["supabase_db"]["port"], 5574)
        self.assertIsNone(payload["dependencies"]["supabase_api"]["port"])

    def test_command_uses_runtime_project_resolver_for_endpoint_services(self) -> None:
        state = RunState(
            run_id="run-runtime-endpoints",
            mode="trees",
            services={
                "opaque-backend": ServiceRecord(
                    name="opaque-backend",
                    type="backend",
                    cwd="/tmp/canonical/api",
                    status="running",
                    actual_port=8100,
                ),
                "opaque-frontend": ServiceRecord(
                    name="opaque-frontend",
                    type="frontend",
                    cwd="/tmp/canonical/web",
                    status="running",
                    actual_port=3100,
                ),
            },
        )
        runtime = SimpleNamespace(
            env={"ENVCTL_PUBLIC_HOST": "public.example.test"},
            config=SimpleNamespace(raw={}),
            _try_load_existing_state=lambda **_kwargs: state,
            _state_lookup_strict_mode_match=lambda _route: True,
            _project_name_from_service=lambda _service_name: "Canonical",
            _emit=lambda *_args, **_kwargs: None,
        )
        route = Route(command="endpoints", mode="trees", projects=["Canonical"], flags={"json": True})

        stdout = StringIO()
        with redirect_stdout(stdout):
            code = run_endpoints_command(runtime, route)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["backend"]["local_url"], "http://localhost:8100")
        self.assertEqual(payload["project_root"], "/tmp/canonical/api")
        self.assertEqual(payload["frontend"]["public_url"], "http://public.example.test:3100")

    def test_command_requires_project_when_state_has_multiple_projects(self) -> None:
        runtime = SimpleNamespace(
            env={},
            config=SimpleNamespace(raw={}),
            _try_load_existing_state=lambda **_kwargs: RunState(
                run_id="run-multi",
                mode="trees",
                requirements={"alpha": RequirementsResult(project="alpha"), "beta": RequirementsResult(project="beta")},
            ),
            _state_lookup_strict_mode_match=lambda _route: True,
            _emit=lambda *_args, **_kwargs: None,
        )
        route = Route(command="endpoints", mode="trees", flags={"json": True})

        stdout = StringIO()
        with redirect_stdout(stdout):
            code = run_endpoints_command(runtime, route)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "project_required")
        self.assertEqual(payload["active_projects"], ["alpha", "beta"])


if __name__ == "__main__":
    unittest.main()
