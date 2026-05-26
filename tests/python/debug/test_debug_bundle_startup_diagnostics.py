from __future__ import annotations

import unittest

from envctl_engine.debug.debug_bundle_startup_diagnostics import analyze_startup_diagnostics


class DebugBundleStartupDiagnosticsTests(unittest.TestCase):
    def test_startup_diagnostics_summarize_timing_breakdown_and_hotspots(self) -> None:
        timeline = [
            {
                "source": "debug",
                "event": "startup.execution",
                "mode": "fullstack",
                "workers": 2,
                "projects": ["Main", "Aux"],
                "ts_mono_ns": 0,
            },
            {
                "source": "debug",
                "event": "startup.phase",
                "phase": "requirements",
                "project": "Main",
                "duration_ms": 120.5,
                "status": "ok",
                "ts_mono_ns": 100_000_000,
            },
            {
                "source": "debug",
                "event": "requirements.timing.summary",
                "project": "Main",
                "duration_ms": 700.0,
                "ts_mono_ns": 200_000_000,
            },
            {
                "source": "debug",
                "event": "service.timing.summary",
                "project": "Main",
                "duration_ms": 200.0,
                "ts_mono_ns": 300_000_000,
            },
            {
                "source": "debug",
                "event": "resume.restore.project_timing",
                "project": "Aux",
                "total_ms": 50.0,
                "ts_mono_ns": 400_000_000,
            },
            {
                "source": "debug",
                "event": "requirements.adapter",
                "stage_durations_ms": {"listener_wait": 450.0, "probe": "50.0"},
                "ts_mono_ns": 500_000_000,
            },
            {
                "source": "debug",
                "event": "requirements.adapter.command_timing",
                "project": "Main",
                "stage": "docker ps",
                "duration_ms": 33.3,
                "returncode": 0,
                "ts_mono_ns": 600_000_000,
            },
            {"source": "debug", "event": "state.auto_resume.skipped", "reason": "project_mismatch"},
        ]

        diagnostics = analyze_startup_diagnostics(timeline)

        self.assertEqual(diagnostics.startup_breakdown["execution_mode"], "fullstack")
        self.assertEqual(diagnostics.startup_breakdown["workers"], 2)
        self.assertEqual(diagnostics.startup_breakdown["projects"], ["Main", "Aux"])
        self.assertEqual(diagnostics.known_total_ms, 950.0)
        self.assertEqual(diagnostics.requirements_total_ms, 700.0)
        self.assertEqual(diagnostics.resume_skip_reasons, {"project_mismatch": 1})
        self.assertEqual(
            diagnostics.requirements_stage_hotspots,
            [{"stage": "listener_wait", "total_ms": 450.0}, {"stage": "probe", "total_ms": 50.0}],
        )
        self.assertTrue(diagnostics.has_command_timing_detail)
        self.assertFalse(diagnostics.has_adapter_stage_detail)
        self.assertEqual(diagnostics.startup_breakdown["project_breakdown"][0]["project"], "Main")

    def test_startup_diagnostics_falls_back_to_project_summaries_for_slowest_components(self) -> None:
        timeline = [
            {
                "source": "debug",
                "event": "requirements.timing.summary",
                "project": "Main",
                "duration_ms": 100.0,
                "ts_mono_ns": 0,
            },
            {
                "source": "debug",
                "event": "service.timing.summary",
                "project": "Main",
                "duration_ms": 40.0,
                "ts_mono_ns": 100_000_000,
            },
        ]

        diagnostics = analyze_startup_diagnostics(timeline)

        self.assertEqual(
            [item["kind"] for item in diagnostics.slowest_components],
            ["requirements_summary", "service_summary"],
        )
        self.assertEqual(diagnostics.startup_breakdown["project_breakdown"][0]["total_ms"], 140.0)


if __name__ == "__main__":
    unittest.main()
