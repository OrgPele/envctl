from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.inspection_support import dispatch_direct_inspection
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord


def _state() -> RunState:
    return RunState(
        run_id="run-show",
        mode="trees",
        metadata={"project_roots": {"Alpha": "/repo/trees/alpha/1", "Beta": "/repo/trees/beta/1"}},
        services={
            "Alpha Backend": ServiceRecord(name="Alpha Backend", type="backend", cwd="/repo/trees/alpha/1/api", project="Alpha", status="running"),
            "Beta Backend": ServiceRecord(name="Beta Backend", type="backend", cwd="/repo/trees/beta/1/api", project="Beta", status="running"),
        },
        requirements={
            "Alpha": RequirementsResult(project="Alpha", redis={"enabled": True, "success": True}),
            "Beta": RequirementsResult(project="Beta", redis={"enabled": True, "success": True}),
        },
    )


class ShowStateProjectGuardTests(unittest.TestCase):
    def _runtime(self, state: RunState | None = None):  # noqa: ANN201
        events: list[dict[str, object]] = []
        return SimpleNamespace(
            env={},
            runtime_root=Path("/tmp/envctl-runtime-test"),
            _state_lookup_strict_mode_match=lambda _route: True,
            _try_load_existing_state=lambda **_kwargs: state or _state(),
            _run_state_path=lambda: Path("/tmp/envctl-runtime-test/run_state.json"),
            _emit=lambda event, **payload: events.append({"event": event, **payload}),
            events=events,
        )

    def test_missing_project_json_fails_closed_without_rendering_other_state(self) -> None:
        runtime = self._runtime()
        route = Route(command="show-state", mode="trees", projects=["missing"], flags={"json": True})
        stdout = StringIO()

        with redirect_stdout(stdout):
            code = dispatch_direct_inspection(runtime, route)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(
            payload,
            {
                "ok": False,
                "error": "requested_project_not_running",
                "requested_project": "missing",
                "active_projects": ["Alpha", "Beta"],
            },
        )
        self.assertNotIn("state", payload)
        self.assertNotIn("Alpha Backend", json.dumps(payload))

    def test_missing_project_human_lists_requested_and_active_projects(self) -> None:
        runtime = self._runtime()
        route = Route(command="show-state", mode="trees", projects=["missing"], flags={})
        stdout = StringIO()

        with redirect_stdout(stdout):
            code = dispatch_direct_inspection(runtime, route)

        rendered = stdout.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("Requested project is not running: missing", rendered)
        self.assertIn("Active runtime projects: Alpha, Beta", rendered)

    def test_success_json_filters_state_and_runtime_map_to_selected_project(self) -> None:
        runtime = self._runtime()
        route = Route(command="show-state", mode="trees", projects=["alpha"], flags={"json": True})
        stdout = StringIO()

        with redirect_stdout(stdout):
            code = dispatch_direct_inspection(runtime, route)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(set(payload["state"]["services"]), {"Alpha Backend"})
        self.assertEqual(set(payload["state"]["requirements"]), {"Alpha"})
        self.assertEqual(set(payload["runtime_map"]["projects"]), {"Alpha"})
        events = [event for event in runtime.events if event.get("event") == "state.project_resolution.ok"]
        self.assertEqual(len(events), 1, msg=runtime.events)
        self.assertEqual(events[0]["selected_projects"], ["Alpha"])

    def test_success_json_with_all_keeps_full_state(self) -> None:
        runtime = self._runtime()
        route = Route(command="show-state", mode="trees", projects=["alpha"], flags={"json": True, "all": True})
        stdout = StringIO()

        with redirect_stdout(stdout):
            code = dispatch_direct_inspection(runtime, route)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(set(payload["state"]["services"]), {"Alpha Backend", "Beta Backend"})
        self.assertEqual(set(payload["runtime_map"]["projects"]), {"Alpha", "Beta"})

    def test_multiple_projects_are_rejected_for_show_state(self) -> None:
        runtime = self._runtime()
        route = Route(command="show-state", mode="trees", projects=["Alpha", "Beta"], flags={"json": True})
        stdout = StringIO()

        with redirect_stdout(stdout):
            code = dispatch_direct_inspection(runtime, route)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "multiple_projects_not_supported")
        self.assertEqual(payload["requested_projects"], ["Alpha", "Beta"])


if __name__ == "__main__":
    unittest.main()
