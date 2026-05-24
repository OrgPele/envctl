from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from envctl_engine.actions.action_runtime_facade import ActionRuntimeFacade


class ActionRuntimeFacadeTests(unittest.TestCase):
    def test_facade_routes_legacy_runtime_collaborators(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(
            env={"KEY": "value"},
            config=SimpleNamespace(raw={"CONFIG": "1"}),
            process_runner="runner",
            state_repository="state",
            _discover_projects=lambda *, mode: [SimpleNamespace(name=f"{mode}-project")],
            _selectors_from_passthrough=lambda args: set(args),
            _try_load_existing_state=lambda *, mode: SimpleNamespace(mode=mode),
            _project_name_from_service=lambda service_name: f"project-{service_name}",
            _select_project_targets=lambda **kwargs: kwargs,
            _unsupported_command=lambda command: 64 if command == "bad" else 1,
            _split_command=lambda raw, *, replacements: [raw, replacements["name"]],
            _trees_root_for_worktree=lambda root: Path(root).parents[1],
            _blast_worktree_before_delete=lambda **kwargs: [str(kwargs["source_command"])],
            _emit=lambda event, **payload: events.append((event, payload)),
        )

        facade = ActionRuntimeFacade(runtime)

        self.assertEqual(facade.env, {"KEY": "value"})
        self.assertEqual(facade.config.raw, {"CONFIG": "1"})
        self.assertEqual(facade.process_runner, "runner")
        self.assertEqual(facade.state_repository, "state")
        self.assertEqual([project.name for project in facade.discover_projects(mode="trees")], ["trees-project"])
        self.assertEqual(facade.selectors_from_passthrough(["alpha"]), {"alpha"})
        self.assertEqual(facade.load_existing_state(mode="main").mode, "main")
        self.assertEqual(facade.project_name_from_service("api"), "project-api")
        self.assertEqual(facade.select_project_targets(projects=["Main"]), {"projects": ["Main"]})
        self.assertEqual(facade.unsupported_command("bad"), 64)
        self.assertEqual(facade.split_command("echo {name}", replacements={"name": "Main"}), ["echo {name}", "Main"])
        self.assertEqual(facade._trees_root_for_worktree(Path("/repo/trees/feature/1")), Path("/repo/trees"))
        self.assertEqual(
            facade._blast_worktree_before_delete(
                project_name="feature-1",
                project_root=Path("/repo/trees/feature/1"),
                source_command="delete-worktree",
            ),
            ["delete-worktree"],
        )
        facade.emit("action.test", ok=True)
        self.assertEqual(events, [("action.test", {"ok": True})])
        self.assertIs(facade.raw_runtime, runtime)

    def test_facade_raises_clear_error_for_missing_required_collaborator(self) -> None:
        facade = ActionRuntimeFacade(SimpleNamespace())

        with self.assertRaisesRegex(AttributeError, "missing required action collaborator"):
            facade.discover_projects(mode="trees")


if __name__ == "__main__":
    unittest.main()
