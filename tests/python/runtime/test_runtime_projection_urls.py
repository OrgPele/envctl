from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.state.runtime_map import build_runtime_map, build_runtime_projection


class RuntimeProjectionUrlsTests(unittest.TestCase):
    def test_urls_reflect_final_listener_ports_after_rebind(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="trees",
            services={
                "Tree Alpha Backend": ServiceRecord(
                    name="Tree Alpha Backend",
                    type="backend",
                    cwd="/tmp/tree-alpha/backend",
                    requested_port=8000,
                    actual_port=8010,
                    status="running",
                ),
                "Tree Alpha Frontend": ServiceRecord(
                    name="Tree Alpha Frontend",
                    type="frontend",
                    cwd="/tmp/tree-alpha/frontend",
                    requested_port=9000,
                    actual_port=9002,
                    status="running",
                ),
            },
        )

        projection = build_runtime_projection(state)

        self.assertEqual(projection["Tree Alpha"]["backend_url"], "http://localhost:8010")
        self.assertEqual(projection["Tree Alpha"]["frontend_url"], "http://localhost:9002")

    def test_projection_prefers_actual_port_when_requested_differs(self) -> None:
        state = RunState(
            run_id="run-2",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd="/tmp/main/backend",
                    requested_port=8000,
                    actual_port=8105,
                    status="running",
                ),
                "Main Frontend": ServiceRecord(
                    name="Main Frontend",
                    type="frontend",
                    cwd="/tmp/main/frontend",
                    requested_port=9000,
                    actual_port=9106,
                    status="running",
                ),
            },
        )

        projection = build_runtime_projection(state)

        self.assertEqual(projection["Main"]["backend_url"], "http://localhost:8105")
        self.assertEqual(projection["Main"]["frontend_url"], "http://localhost:9106")

    def test_projection_hides_urls_for_unreachable_services(self) -> None:
        state = RunState(
            run_id="run-3",
            mode="trees",
            services={
                "Tree Alpha Backend": ServiceRecord(
                    name="Tree Alpha Backend",
                    type="backend",
                    cwd="/tmp/tree-alpha/backend",
                    requested_port=8000,
                    actual_port=8010,
                    status="stale",
                ),
                "Tree Alpha Frontend": ServiceRecord(
                    name="Tree Alpha Frontend",
                    type="frontend",
                    cwd="/tmp/tree-alpha/frontend",
                    requested_port=9000,
                    actual_port=9002,
                    status="unreachable",
                ),
            },
        )

        projection = build_runtime_projection(state)
        self.assertIsNone(projection["Tree Alpha"]["backend_url"])
        self.assertIsNone(projection["Tree Alpha"]["frontend_url"])
        self.assertEqual(projection["Tree Alpha"]["backend_status"], "stale")
        self.assertEqual(projection["Tree Alpha"]["frontend_status"], "unreachable")

    def test_projection_hides_urls_for_simulated_services(self) -> None:
        state = RunState(
            run_id="run-4",
            mode="trees",
            services={
                "Tree Alpha Backend": ServiceRecord(
                    name="Tree Alpha Backend",
                    type="backend",
                    cwd="/tmp/tree-alpha/backend",
                    requested_port=8000,
                    actual_port=8010,
                    status="simulated",
                ),
                "Tree Alpha Frontend": ServiceRecord(
                    name="Tree Alpha Frontend",
                    type="frontend",
                    cwd="/tmp/tree-alpha/frontend",
                    requested_port=9000,
                    actual_port=9002,
                    status="simulated",
                ),
            },
        )

        projection = build_runtime_projection(state)
        self.assertIsNone(projection["Tree Alpha"]["backend_url"])
        self.assertIsNone(projection["Tree Alpha"]["frontend_url"])
        self.assertEqual(projection["Tree Alpha"]["backend_status"], "simulated")
        self.assertEqual(projection["Tree Alpha"]["frontend_status"], "simulated")

    def test_projection_keeps_urls_for_services_marked_starting(self) -> None:
        state = RunState(
            run_id="run-5",
            mode="trees",
            services={
                "Tree Alpha Backend": ServiceRecord(
                    name="Tree Alpha Backend",
                    type="backend",
                    cwd="/tmp/tree-alpha/backend",
                    requested_port=8000,
                    actual_port=8010,
                    status="starting",
                ),
                "Tree Alpha Frontend": ServiceRecord(
                    name="Tree Alpha Frontend",
                    type="frontend",
                    cwd="/tmp/tree-alpha/frontend",
                    requested_port=9000,
                    actual_port=9002,
                    status="starting",
                ),
            },
        )

        projection = build_runtime_projection(state)
        self.assertEqual(projection["Tree Alpha"]["backend_url"], "http://localhost:8010")
        self.assertEqual(projection["Tree Alpha"]["frontend_url"], "http://localhost:9002")
        self.assertEqual(projection["Tree Alpha"]["backend_status"], "starting")
        self.assertEqual(projection["Tree Alpha"]["frontend_status"], "starting")

    def test_projection_hides_urls_for_running_non_listener_backend(self) -> None:
        state = RunState(
            run_id="run-6",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd="/tmp/main/backend",
                    status="running",
                    pid=1234,
                    listener_expected=False,
                ),
            },
        )

        projection = build_runtime_projection(state)

        self.assertIsNone(projection["Main"]["backend_url"])
        self.assertEqual(projection["Main"]["backend_status"], "running")

    def test_runtime_map_derives_public_url_from_final_rebound_port(self) -> None:
        state = RunState(
            run_id="run-7b",
            mode="main",
            services={
                "Main Voice Runtime": ServiceRecord(
                    name="Main Voice Runtime",
                    type="voice-runtime",
                    cwd="/tmp/main/voice-runtime",
                    requested_port=8010,
                    actual_port=8019,
                    status="running",
                    project="Main",
                    service_slug="voice-runtime",
                ),
            },
        )

        runtime_map = build_runtime_map(state, host="127.0.0.1")

        service = runtime_map["projects"]["Main"]["services"]["voice-runtime"]
        self.assertEqual(service["url"], "http://127.0.0.1:8019")
        self.assertEqual(service["public_url"], "http://127.0.0.1:8019")
        self.assertEqual(runtime_map["service_to_public_url"]["Main Voice Runtime"], "http://127.0.0.1:8019")

    def test_runtime_map_derives_project_name_from_shared_service_display_name(self) -> None:
        state = RunState(
            run_id="run-7c",
            mode="main",
            services={
                "Tree Alpha Voice Runtime": ServiceRecord(
                    name="Tree Alpha Voice Runtime",
                    type="voice_runtime",
                    cwd="/tmp/tree-alpha/voice-runtime",
                    requested_port=8010,
                    actual_port=8010,
                    status="running",
                ),
            },
        )

        runtime_map = build_runtime_map(state)

        self.assertIn("Tree Alpha", runtime_map["projects"])
        self.assertNotIn("Tree Alpha Voice", runtime_map["projects"])

    def test_runtime_map_exposes_generic_project_service_projection(self) -> None:
        state = RunState(
            run_id="run-7",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd="/tmp/main/backend",
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
                "Main Voice Runtime": ServiceRecord(
                    name="Main Voice Runtime",
                    type="voice-runtime",
                    cwd="/tmp/main/voice-runtime",
                    requested_port=8010,
                    actual_port=8012,
                    status="running",
                    public_url="https://voice.example.test",
                    health_url="https://voice.example.test/readyz",
                    project="Main",
                    service_slug="voice-runtime",
                ),
                "Main Worker": ServiceRecord(
                    name="Main Worker",
                    type="worker",
                    cwd="/tmp/main/backend",
                    pid=1234,
                    status="running",
                    listener_expected=False,
                ),
            },
        )

        runtime_map = build_runtime_map(state)
        project = runtime_map["projects"]["Main"]
        projection = runtime_map["projection"]["Main"]

        self.assertEqual(project["services"]["backend"]["port"], 8000)
        self.assertEqual(project["services"]["voice-runtime"]["port"], 8012)
        self.assertEqual(project["services"]["voice-runtime"]["url"], "http://localhost:8012")
        self.assertEqual(project["services"]["voice-runtime"]["public_url"], "https://voice.example.test")
        self.assertEqual(project["services"]["voice-runtime"]["health_url"], "https://voice.example.test/readyz")
        self.assertFalse(project["services"]["worker"]["listener_expected"])
        self.assertIsNone(project["services"]["worker"]["port"])
        self.assertEqual(projection["services"]["voice-runtime"]["url"], "http://localhost:8012")
        self.assertEqual(runtime_map["service_to_actual_port"]["Main Voice Runtime"], 8012)
        self.assertEqual(runtime_map["service_to_url"]["Main Voice Runtime"], "http://localhost:8012")
        self.assertEqual(runtime_map["service_to_public_url"]["Main Voice Runtime"], "https://voice.example.test")
        self.assertEqual(runtime_map["service_to_health_url"]["Main Voice Runtime"], "https://voice.example.test/readyz")


if __name__ == "__main__":
    unittest.main()
