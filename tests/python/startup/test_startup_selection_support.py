from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from envctl_engine.runtime.command_router import Route, parse_route
from envctl_engine.startup.startup_selection_support import (
    _restart_service_types_for_project,
    restart_include_requirements,
    restart_target_projects,
    restart_target_projects_for_selected_services,
    select_start_tree_projects,
    state_project_names,
    trees_start_selection_required,
)
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.ui.selection_types import TargetSelection


class _RuntimeStub:
    def __init__(self, *, can_tty: bool = True) -> None:
        self._can_tty = can_tty
        self.events: list[tuple[str, dict[str, object]]] = []
        self.selection = TargetSelection(cancelled=False)
        self.selection_kwargs: dict[str, object] | None = None
        self.state: RunState | None = None

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append((event, dict(payload)))

    def _can_interactive_tty(self) -> bool:
        return self._can_tty

    def _try_load_existing_state(self, *, mode: str, strict_mode_match: bool = False):  # noqa: ANN001, ARG002
        return self.state

    def _select_project_targets(self, **kwargs):  # noqa: ANN001
        self.selection_kwargs = dict(kwargs)
        return self.selection

    @staticmethod
    def _project_name_from_service(name: str) -> str:
        raw = str(name).strip()
        for suffix in (" Backend", " Frontend"):
            if raw.endswith(suffix):
                return raw[: -len(suffix)].strip()
        return ""


class StartupSelectionSupportTests(unittest.TestCase):
    @staticmethod
    def _trees_route(*, raw_args: list[str] | None = None) -> Route:
        args = ["--trees"] if raw_args is None else list(raw_args)
        return Route(
            command="start",
            mode="trees",
            raw_args=args,
            passthrough_args=[],
            projects=[],
            flags={},
        )

    def test_trees_start_selection_required_for_default_or_explicit_trees_start(self) -> None:
        self.assertTrue(
            trees_start_selection_required(
                route=self._trees_route(raw_args=["--trees"]),
                runtime_mode="trees",
            )
        )
        self.assertTrue(trees_start_selection_required(route=self._trees_route(raw_args=[]), runtime_mode="trees"))
        self.assertFalse(
            trees_start_selection_required(
                route=Route(
                    command="plan", mode="trees", raw_args=["--plan"], passthrough_args=[], projects=[], flags={}
                ),
                runtime_mode="trees",
            )
        )
        self.assertFalse(
            trees_start_selection_required(
                route=Route(
                    command="start",
                    mode="trees",
                    raw_args=[],
                    passthrough_args=[],
                    projects=["alpha"],
                    flags={},
                ),
                runtime_mode="trees",
            )
        )

    def test_state_project_discovery_prefers_explicit_multiword_service_metadata(self) -> None:
        runtime = _RuntimeStub()
        service_name = "My Project Optional Bad"
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                service_name: ServiceRecord(
                    name=service_name,
                    type="optional-bad",
                    cwd="/repo/optional-bad",
                    project="My Project",
                    service_slug="optional-bad",
                )
            },
        )

        self.assertEqual(state_project_names(runtime=runtime, state=state), {"My Project"})
        self.assertEqual(
            restart_target_projects(
                state=state,
                route=Route(command="restart", mode="main", flags={}),
                runtime=runtime,
            ),
            {"My Project"},
        )
        self.assertEqual(
            restart_target_projects_for_selected_services(
                selected_services={service_name},
                state=state,
                runtime=runtime,
            ),
            {"My Project"},
        )

    def test_state_project_discovery_uses_requirement_project_not_collision_storage_key(self) -> None:
        runtime = _RuntimeStub()
        state = RunState(
            run_id="run-1",
            mode="trees",
            requirements={
                "Main Restart Collision": SimpleNamespace(project="Main")  # type: ignore[dict-item]
            },
        )

        self.assertEqual(state_project_names(runtime=runtime, state=state), {"Main"})
        self.assertEqual(
            restart_target_projects(
                state=state,
                route=Route(command="restart", mode="trees", flags={"runtime_scope": "dependencies"}),
                runtime=runtime,
            ),
            {"Main"},
        )
    def test_restart_target_projects_resolves_stopped_additional_service_metadata(self) -> None:
        runtime = _RuntimeStub()
        state = RunState(
            run_id="run-1",
            mode="trees",
            services={
                "Other Backend": ServiceRecord(
                    name="Other Backend",
                    type="backend",
                    cwd="/repo/other/backend",
                    project="Other",
                )
            },
            metadata={
                "dashboard_stopped_services": [
                    {
                        "name": "Customer Platform Voice Runtime",
                        "project": "Customer Platform",
                        "type": "voice-runtime",
                    }
                ]
            },
        )

        for selector in (
            "voice-runtime",
            "Voice Runtime",
            "Customer Platform Voice Runtime",
            "service:voice-runtime",
        ):
            with self.subTest(selector=selector):
                targets = restart_target_projects(
                    state=state,
                    route=Route(
                        command="restart",
                        mode="trees",
                        flags={"services": [selector]},
                    ),
                    runtime=runtime,
                )

                self.assertEqual(targets, {"Customer Platform"})

    def test_select_start_tree_projects_preselects_from_previous_trees_state(self) -> None:
        runtime = _RuntimeStub(can_tty=True)
        runtime.state = RunState(
            run_id="run-prev",
            mode="trees",
            services={
                "alpha Backend": ServiceRecord(name="alpha Backend", type="backend", cwd="."),
                "gamma Frontend": ServiceRecord(name="gamma Frontend", type="frontend", cwd="."),
            },
        )
        runtime.selection = TargetSelection(project_names=["alpha", "gamma"])

        contexts = [SimpleNamespace(name="alpha"), SimpleNamespace(name="beta"), SimpleNamespace(name="gamma")]
        selected = select_start_tree_projects(runtime=runtime, route=self._trees_route(), project_contexts=contexts)

        self.assertEqual([ctx.name for ctx in selected], ["alpha", "gamma"])
        self.assertIsNotNone(runtime.selection_kwargs)
        assert runtime.selection_kwargs is not None
        self.assertEqual(runtime.selection_kwargs.get("prompt"), "Run worktrees for")
        self.assertEqual(runtime.selection_kwargs.get("initial_project_names"), ["alpha", "gamma"])

    def test_select_start_tree_projects_preselects_projects_backed_by_existing_plans(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            planning_dir = root / "todo" / "plans" / "implementations"
            planning_dir.mkdir(parents=True, exist_ok=True)
            (planning_dir / "alpha.md").write_text("# alpha\n", encoding="utf-8")
            (planning_dir / "gamma.md").write_text("# gamma\n", encoding="utf-8")
            runtime = _RuntimeStub(can_tty=True)
            runtime.selection = TargetSelection(project_names=["implementations_alpha-1"])
            runtime.config = SimpleNamespace(planning_dir=root / "todo" / "plans")

            contexts = [
                SimpleNamespace(name="implementations_alpha-1", root=root / "trees" / "alpha" / "1"),
                SimpleNamespace(name="implementations_beta-1", root=root / "trees" / "beta" / "1"),
                SimpleNamespace(name="implementations_gamma-1", root=root / "trees" / "gamma" / "1"),
            ]
            selected = select_start_tree_projects(runtime=runtime, route=self._trees_route(), project_contexts=contexts)

            self.assertEqual([ctx.name for ctx in selected], ["implementations_alpha-1"])
            self.assertIsNotNone(runtime.selection_kwargs)
            assert runtime.selection_kwargs is not None
            self.assertEqual(
                runtime.selection_kwargs.get("initial_project_names"),
                ["implementations_alpha-1", "implementations_gamma-1"],
            )

    def test_select_start_tree_projects_requires_explicit_selection_without_tty(self) -> None:
        runtime = _RuntimeStub(can_tty=False)
        runtime.selection = TargetSelection(project_names=["alpha"])
        contexts = [SimpleNamespace(name="alpha"), SimpleNamespace(name="beta")]

        selected = select_start_tree_projects(runtime=runtime, route=self._trees_route(), project_contexts=contexts)

        self.assertEqual(selected, [])
        self.assertIsNone(runtime.selection_kwargs)
        self.assertTrue(any(name == "trees.start.selector.skipped" for name, _ in runtime.events))

    def test_runtime_scope_flags_control_restart_requirements(self) -> None:
        self.assertFalse(restart_include_requirements(parse_route(["restart", "--backend"], env={})))
        self.assertFalse(restart_include_requirements(parse_route(["restart", "--fullstack"], env={})))
        self.assertTrue(restart_include_requirements(parse_route(["restart", "--dependencies"], env={})))
        self.assertTrue(restart_include_requirements(parse_route(["restart", "--entire-system"], env={})))
        self.assertTrue(restart_include_requirements(parse_route(["restart"], env={})))
        self.assertFalse(restart_include_requirements(parse_route(["restart", "--service", "Main Frontend"], env={})))

    def test_no_infra_selects_no_additional_application_services(self) -> None:
        route = Route(
            command="start",
            mode="main",
            flags={"launch_backend": False, "launch_frontend": False, "launch_dependencies": False},
        )

        self.assertEqual(
            _restart_service_types_for_project(
                route=route,
                project_name="Main",
                default_service_types={"backend", "frontend", "worker"},
            ),
            set(),
        )


if __name__ == "__main__":
    unittest.main()
