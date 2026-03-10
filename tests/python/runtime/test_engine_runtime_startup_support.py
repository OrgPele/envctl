from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_router import Route  # noqa: E402
from envctl_engine.runtime.engine_runtime import ProjectContext  # noqa: E402
from envctl_engine.runtime.engine_runtime_startup_support import (  # noqa: E402
    auto_resume_start_enabled,
    contexts_from_raw_projects,
    discover_projects,
    duplicate_project_context_error,
    effective_start_mode,
    load_auto_resume_state,
    reserve_project_ports,
    sanitize_legacy_resume_state,
    set_plan_port,
    set_plan_port_from_component,
    state_has_resumable_services,
    tree_parallel_startup_config,
)
from envctl_engine.state.models import PortPlan, RunState, ServiceRecord  # noqa: E402


class EngineRuntimeStartupSupportTests(unittest.TestCase):
    def test_effective_start_mode_switches_main_to_trees_for_setup_worktree(self) -> None:
        runtime = SimpleNamespace(_setup_worktree_requested=lambda route: True)
        route = Route(command="start", mode="main", raw_args=[], passthrough_args=[], projects=[], flags={})
        self.assertEqual(effective_start_mode(runtime, route), "trees")

    def test_auto_resume_start_enabled_respects_disabling_flags(self) -> None:
        route = Route(command="start", mode="main", raw_args=[], passthrough_args=[], projects=[], flags={})
        self.assertTrue(auto_resume_start_enabled(route))
        self.assertFalse(
            auto_resume_start_enabled(
                Route(
                    command="start",
                    mode="main",
                    raw_args=[],
                    passthrough_args=[],
                    projects=[],
                    flags={"no_resume": True},
                )
            )
        )

    def test_state_has_resumable_services_and_load_auto_resume_state(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="trees",
            services={"Feature Backend": ServiceRecord(name="Feature Backend", type="backend", cwd=".")},
        )
        runtime = SimpleNamespace(
            _project_name_from_service=lambda name: "Feature" if "Feature" in name else "",
            _try_load_existing_state=lambda **kwargs: state,
        )
        self.assertTrue(state_has_resumable_services(runtime, state))
        self.assertIs(load_auto_resume_state(runtime, "trees"), state)

    def test_tree_parallel_startup_config_defaults_for_plan_and_env(self) -> None:
        runtime = SimpleNamespace(env={}, config=SimpleNamespace(raw={}))
        route = Route(command="plan", mode="trees", raw_args=[], passthrough_args=[], projects=[], flags={})
        self.assertEqual(tree_parallel_startup_config(runtime, mode="trees", route=route, project_count=3), (True, 3))

    def test_contexts_and_duplicate_detection(self) -> None:
        runtime = SimpleNamespace(
            port_planner=SimpleNamespace(plan_project_stack=lambda name, index: {"backend": index})
        )
        contexts = contexts_from_raw_projects(
            runtime,
            [("feature-a-1", Path("/a")), ("feature-b-1", Path("/b"))],
            context_factory=ProjectContext,
        )
        self.assertEqual([ctx.name for ctx in contexts], ["feature-a-1", "feature-b-1"])
        duplicate_error = duplicate_project_context_error(
            [ProjectContext(name="A", root=Path("/a"), ports={}), ProjectContext(name="a", root=Path("/b"), ports={})]
        )
        self.assertIn("duplicate project identities", duplicate_error.lower())

    def test_sanitize_legacy_resume_state_and_set_plan_port_helpers(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(_emit=lambda event, **payload: events.append((event, payload)))
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd=".", pid=123, listener_pids=[1])
            },
        )
        sanitize_legacy_resume_state(runtime, state)
        self.assertIsNone(state.services["Main Backend"].pid)
        self.assertIsNone(state.services["Main Backend"].listener_pids)
        self.assertEqual(events[0][0], "resume.legacy_state.sanitized")

        plan = PortPlan(project="Main", requested=1, assigned=1, final=1, source="x")
        set_plan_port_from_component(plan, {"final": 5432})
        self.assertEqual(plan.final, 5432)
        set_plan_port(plan, 6379)
        self.assertEqual(plan.final, 6379)

    def test_discover_projects_and_reserve_project_ports(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        port_plan = PortPlan(project="Main", requested=8000, assigned=8000, final=8000, source="fixed")
        runtime = SimpleNamespace(
            config=SimpleNamespace(base_dir=Path("/repo"), trees_dir_name="trees"),
            port_planner=SimpleNamespace(
                plan_project_stack=lambda name, index: {
                    "backend": PortPlan(
                        project=name, requested=8000 + index, assigned=8000 + index, final=8000 + index, source="fixed"
                    )
                },
                reserve_next=lambda assigned, owner: assigned,
                max_port=9999,
                availability_mode="lock",
                update_final_port=lambda plan, reserved, source: None,
            ),
            _emit=lambda event, **payload: events.append((event, payload)),
            _lock_inventory=lambda: [],
        )
        contexts = discover_projects(runtime, mode="main", context_factory=ProjectContext)
        self.assertEqual(contexts[0].name, "Main")

        context = ProjectContext(name="Main", root=Path("/repo"), ports={"backend": port_plan})
        reserve_project_ports(runtime, context)
        self.assertEqual(events[-1][0], "port.reserved")


if __name__ == "__main__":
    unittest.main()
