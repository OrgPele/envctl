from __future__ import annotations

from types import SimpleNamespace
import unittest

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.ui.dashboard import project_target_support
from envctl_engine.ui.target_selector import TargetSelection


def _route(command: str, **kwargs: object) -> Route:
    return Route(command=command, mode="main", **kwargs)  # type: ignore[arg-type]


def _state(**kwargs: object) -> RunState:
    defaults: dict[str, object] = {"run_id": "r1", "mode": "main", "services": {}, "metadata": {}}
    defaults.update(kwargs)
    return RunState(**defaults)  # type: ignore[arg-type]


class _Runtime:
    def __init__(self) -> None:
        self.events: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.selection = TargetSelection(project_names=[])
        self.selection_calls: list[dict[str, object]] = []

    def _emit(self, *args: object, **kwargs: object) -> None:
        self.events.append((args, kwargs))

    def _select_project_targets(self, **kwargs: object) -> TargetSelection:
        self.selection_calls.append(kwargs)
        return self.selection


class _Owner:
    def __init__(self) -> None:
        self.projects: list[object] = []
        self.prompt_message: str | None = None
        self.target_route: Route | None = None

    def _apply_project_target_selection(self, route: Route, state: RunState, rt: object) -> Route | None:
        _ = state, rt
        return self.target_route if self.target_route is not None else route

    @staticmethod
    def _route_has_explicit_target(route: Route, runtime: object) -> bool:
        _ = runtime
        return bool(route.projects or route.flags.get("all"))

    def _project_names_from_state(self, state: RunState, rt: object) -> list[object]:
        _ = state, rt
        return list(self.projects)

    @staticmethod
    def _single_project_name(projects: list[object]) -> str:
        names = [str(getattr(project, "name", "")).strip() for project in projects]
        names = [name for name in names if name]
        return names[0] if len(names) == 1 else ""

    @staticmethod
    def _interactive_target_prompt(command: str) -> str:
        return f"Choose {command} scope"

    @staticmethod
    def _no_target_selected_message(command: str) -> str:
        return f"No {command} target selected."

    def _prompt_commit_message(self, runtime: object) -> str | None:
        _ = runtime
        return self.prompt_message


class DashboardProjectTargetSupportTests(unittest.TestCase):
    def test_dashboard_owned_target_selection_commands_excludes_downstream_selectors(self) -> None:
        commands = project_target_support.dashboard_owned_target_selection_commands()

        self.assertEqual(commands, {"test", "pr", "commit", "review", "migrate", "blast-worktree"})
        self.assertNotIn("restart", commands)

    def test_apply_project_target_selection_defaults_single_project(self) -> None:
        owner = _Owner()
        owner.projects = [SimpleNamespace(name="Main")]
        runtime = _Runtime()
        route = _route("test")

        result = project_target_support.apply_project_target_selection(owner, route, _state(), runtime)

        self.assertIs(result, route)
        self.assertEqual(route.projects, ["Main"])
        self.assertEqual(runtime.selection_calls, [])
        self.assertEqual(runtime.events[0][0], ("dashboard.target_scope.defaulted",))
        self.assertEqual(runtime.events[0][1]["scope"], "single_project")

    def test_apply_project_target_selection_scopes_all_selection_to_run_state_projects(self) -> None:
        owner = _Owner()
        owner.projects = [SimpleNamespace(name="Main"), SimpleNamespace(name="Docs")]
        runtime = _Runtime()
        runtime.selection = TargetSelection(all_selected=True)
        route = _route("test")

        result = project_target_support.apply_project_target_selection(owner, route, _state(mode="trees"), runtime)

        self.assertIs(result, route)
        self.assertEqual(route.projects, ["Main", "Docs"])
        self.assertNotIn("all", route.flags)
        self.assertEqual(runtime.events[0][1]["scope"], "run_state_all_selection")

    def test_apply_project_target_selection_keeps_global_all_when_no_run_state_projects(self) -> None:
        owner = _Owner()
        runtime = _Runtime()
        runtime.selection = TargetSelection(all_selected=True)
        route = _route("review")

        result = project_target_support.apply_project_target_selection(owner, route, _state(), runtime)

        self.assertIs(result, route)
        self.assertEqual(route.projects, [])
        self.assertEqual(route.flags, {"all": True})

    def test_apply_commit_selection_preserves_existing_commit_message_sources(self) -> None:
        owner = _Owner()
        runtime = _Runtime()

        route = project_target_support.apply_commit_selection(
            owner,
            _route("commit", flags={"commit_message": " existing "}),
            _state(),
            runtime,
        )
        file_route = project_target_support.apply_commit_selection(
            owner,
            _route("commit", flags={"commit_message_file": "message.txt"}),
            _state(),
            runtime,
        )

        self.assertEqual(route.flags["commit_message"], " existing ")  # type: ignore[union-attr]
        self.assertEqual(file_route.flags["commit_message_file"], "message.txt")  # type: ignore[union-attr]
        self.assertEqual(runtime.events, [])

    def test_apply_commit_selection_prompts_and_replaces_message_file(self) -> None:
        owner = _Owner()
        owner.prompt_message = "  ship it  "
        runtime = _Runtime()
        route = _route("commit", flags={"commit_message_file": "   "})

        result = project_target_support.apply_commit_selection(owner, route, _state(), runtime)

        self.assertIs(result, route)
        self.assertEqual(route.flags, {"commit_message": "ship it"})
        self.assertEqual(runtime.events[0][0], ("dashboard.commit_message.selected",))
        self.assertEqual(runtime.events[0][1]["length"], len("ship it"))


if __name__ == "__main__":
    unittest.main()
