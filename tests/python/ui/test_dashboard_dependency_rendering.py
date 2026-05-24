from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

from envctl_engine.state.models import RequirementsResult, RunState
from envctl_engine.ui.dashboard import dependency_rendering


def _visual_url(_runtime: object, port: int) -> str:
    return f"http://visual.example:{port}"


def _severity_color(severity: str) -> str:
    return {
        "success": "GREEN",
        "warning": "YELLOW",
        "neutral": "YELLOW",
    }.get(severity, "RED")


class DashboardDependencyRenderingTests(unittest.TestCase):
    def test_dependency_line_renders_visual_url_and_external_failure(self) -> None:
        requirements = RequirementsResult(
            project="Main",
            redis={"enabled": True, "runtime_status": "healthy", "final": 6380, "success": True},
            n8n={
                "enabled": True,
                "runtime_status": "unreachable",
                "external": True,
                "external_url": "https://n8n.example",
                "success": False,
            },
            failures=["n8n unavailable"],
        )

        redis_line = dependency_rendering.dashboard_dependency_line(
            SimpleNamespace(),
            requirements=requirements,
            dependency_id="redis",
            display_name="redis",
            reset="RESET",
            visual_url_fn=_visual_url,
            severity_color_fn=_severity_color,
        )
        n8n_line = dependency_rendering.dashboard_dependency_line(
            SimpleNamespace(),
            requirements=requirements,
            dependency_id="n8n",
            display_name="n8n",
            reset="RESET",
            visual_url_fn=_visual_url,
            severity_color_fn=_severity_color,
        )
        postgres_line = dependency_rendering.dashboard_dependency_line(
            SimpleNamespace(),
            requirements=requirements,
            dependency_id="postgres",
            display_name="postgres",
            reset="RESET",
            visual_url_fn=_visual_url,
            severity_color_fn=_severity_color,
        )

        self.assertEqual(redis_line, "    GREEN\u2713RESET redis: http://visual.example:6380 [Healthy]")
        self.assertEqual(n8n_line, "    RED\u2717RESET n8n: https://n8n.example [External Unreachable]")
        self.assertIsNone(postgres_line)

    def test_shared_dependency_scope_infers_legacy_tree_requirements(self) -> None:
        shared = RequirementsResult(
            project="Main",
            redis={"enabled": True, "runtime_status": "healthy", "final": 6380, "success": True},
        )
        state = RunState(
            run_id="run-1",
            mode="trees",
            requirements={
                "feature-a-1": shared,
                "feature-b-1": shared,
            },
        )

        self.assertEqual(dependency_rendering.dashboard_dependency_scope(state), "shared")

    def test_shared_dependency_rows_use_selected_project(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="trees",
            requirements={
                "Main": RequirementsResult(
                    project="Main",
                    redis={"enabled": True, "runtime_status": "healthy", "final": 6380, "success": True},
                ),
                "feature-a": RequirementsResult(
                    project="feature-a",
                    n8n={"enabled": True, "runtime_status": "healthy", "final": 5678, "success": True},
                ),
            },
            metadata={"dashboard_shared_dependency_project": "feature-a"},
        )

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            dependency_rendering.print_dashboard_shared_dependency_rows(
                SimpleNamespace(),
                state=state,
                ok_color="GREEN",
                warn_color="YELLOW",
                bad_color="RED",
                label_color="CYAN",
                reset="RESET",
                visual_url_fn=_visual_url,
                severity_color_fn=_severity_color,
            )

        output = buffer.getvalue()
        self.assertIn("Shared dependencies:", output)
        self.assertIn("n8n: http://visual.example:5678 [Healthy]", output)
        self.assertNotIn("redis:", output)


if __name__ == "__main__":
    unittest.main()
