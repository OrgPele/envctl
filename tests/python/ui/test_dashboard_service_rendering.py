from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.ui.dashboard import service_rendering


def _visual_url(_runtime: object, port: int) -> str:
    return f"http://visual.example:{port}"


def _status_badge(status: str) -> tuple[str, str, str]:
    if status == "running":
        return ("\u2713", "GREEN", "Running")
    if status == "unreachable":
        return ("\u2717", "RED", "Unreachable")
    return ("\u2022", "YELLOW", "Unknown")


class DashboardServiceRenderingTests(unittest.TestCase):
    def test_service_row_renders_listener_metadata_and_fallback_url(self) -> None:
        service = ServiceRecord(
            name="Main Backend",
            type="backend",
            cwd="/tmp/main",
            requested_port=8000,
            actual_port=8001,
            pid=111,
            listener_pids=[111, 222],
            status="unreachable",
            public_url="https://public.example",
            health_url="https://public.example/healthz",
        )

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            service_rendering.print_dashboard_service_row(
                SimpleNamespace(env={}),
                label="Backend",
                service=service,
                url=None,
                configured_not_running=False,
                stopped_not_running=False,
                ok_color="GREEN",
                warn_color="YELLOW",
                bad_color="RED",
                label_color="CYAN",
                dim="DIM",
                reset="RESET",
                visual_url_fn=_visual_url,
                status_badge_fn=_status_badge,
            )

        output = buffer.getvalue()
        self.assertIn("RED\u2717RESET CYANBackendRESET: http://visual.example:8001", output)
        self.assertIn("(PID: 111)", output)
        self.assertIn("[Listener PID: 222]", output)
        self.assertIn("public:RESET https://public.example", output)
        self.assertIn("health:RESET https://public.example/healthz", output)
        self.assertIn("port: requested 8000 -> actual 8001", output)

    def test_additional_service_rows_include_configured_and_stopped_slugs(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Voice Runtime": ServiceRecord(
                    name="Main Voice Runtime",
                    type="voice-runtime",
                    cwd="/tmp/main",
                    requested_port=8010,
                    actual_port=8010,
                    status="running",
                    service_slug="voice-runtime",
                )
            },
        )
        runtime = SimpleNamespace()
        captured: list[dict[str, object]] = []

        def _capture_row(**kwargs: object) -> None:
            captured.append(kwargs)

        runtime._print_dashboard_service_row = _capture_row

        service_rendering.print_dashboard_additional_service_rows(
            runtime,
            project="Main",
            project_item={"services": {"voice-runtime": {"name": "Main Voice Runtime", "url": "http://localhost:8010"}}},
            state=state,
            stopped_for_project={"webhook-relay": "Main Webhook Relay"},
            configured_missing_for_project={"worker"},
            runs_disabled_dashboard=False,
            configured_service_types=set(),
            ok_color="GREEN",
            warn_color="YELLOW",
            bad_color="RED",
            label_color="CYAN",
            dim="DIM",
            reset="RESET",
        )

        labels = [str(row["label"]) for row in captured]
        self.assertEqual(labels, ["Voice Runtime", "Webhook Relay", "Worker"])
        self.assertFalse(bool(captured[0]["configured_not_running"]))
        self.assertTrue(bool(captured[1]["stopped_not_running"]))
        self.assertTrue(bool(captured[2]["configured_not_running"]))

    def test_stopped_service_count_deduplicates_configured_missing(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Frontend": ServiceRecord(
                    name="Main Frontend",
                    type="frontend",
                    cwd="/tmp/main",
                    status="running",
                ),
            },
        )

        self.assertEqual(
            service_rendering.dashboard_visible_stopped_service_count(
                state,
                stopped_services={"Main": {"backend": "Main Backend"}},
                configured_missing_services={"Main": {"backend", "frontend", "worker"}},
            ),
            2,
        )

    def test_configured_service_helpers_normalize_metadata(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="main",
            metadata={
                "dashboard_configured_service_types": ["Backend", "worker", "worker", " FRONTEND "],
                "dashboard_project_configured_services": {
                    "Main": ["backend", "worker", "worker"],
                    "Aux": ["frontend"],
                },
                "dashboard_stopped_services": [
                    {"project": "Main", "type": "Worker", "name": "Main Worker"},
                    {"project": "Main", "type": "", "name": "ignored"},
                    "ignored",
                ],
                "dashboard_banner": "Runs are disabled for this project",
            },
        )

        self.assertEqual(
            service_rendering.dashboard_configured_service_types(state),
            {"backend", "frontend", "worker"},
        )
        self.assertEqual(
            service_rendering.dashboard_project_configured_services(state),
            {"Main": {"backend", "worker"}, "Aux": {"frontend"}},
        )
        self.assertEqual(
            service_rendering.dashboard_configured_service_total(
                projection={"Main": {}, "Aux": {}},
                configured_service_types={"backend", "worker"},
            ),
            4,
        )
        self.assertEqual(
            service_rendering.dashboard_stopped_services_by_project(state),
            {"Main": {"worker": "Main Worker"}},
        )
        self.assertTrue(service_rendering.dashboard_runs_disabled(state))


if __name__ == "__main__":
    unittest.main()
