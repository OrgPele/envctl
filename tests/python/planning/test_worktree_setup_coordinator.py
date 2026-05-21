from __future__ import annotations

import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from envctl_engine.planning.worktree_setup_coordinator import apply_setup_worktree_selection
from envctl_engine.runtime.command_router import Route


@dataclass
class ProjectContext:
    name: str
    root: Path


class WorktreeSetupCoordinatorTests(unittest.TestCase):
    def test_unrequested_setup_returns_original_contexts_without_callbacks(self) -> None:
        contexts = [ProjectContext(name="Main", root=Path("/repo"))]
        route = Route(command="start", mode="main", flags={})

        result = apply_setup_worktree_selection(
            route=route,
            project_contexts=contexts,
            setup_worktree_requested=lambda _route: False,
            env={},
            emit=None,
            coerce_setup_entries=self._unexpected,
            apply_multi_setup_entry=self._unexpected,
            apply_single_setup_entry=self._unexpected,
            resolve_included_setup_worktrees=self._unexpected,
            contexts_from_raw_projects=self._unexpected,
        )

        self.assertIs(result, contexts)

    def test_conflicting_existing_and_recreate_flags_fail_before_worktree_changes(self) -> None:
        route = Route(
            command="start",
            mode="main",
            flags={
                "setup_worktree": [{"feature": "feature-a", "iteration": "1"}],
                "setup_worktree_existing": True,
                "setup_worktree_recreate": True,
            },
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "Use only one of --setup-worktree-existing or --setup-worktree-recreate.",
        ):
            apply_setup_worktree_selection(
                route=route,
                project_contexts=[],
                setup_worktree_requested=lambda _route: True,
                env={},
                emit=None,
                coerce_setup_entries=lambda **kwargs: [("feature-a", "1")]
                if kwargs["flag_name"] == "setup_worktree"
                else [],
                apply_multi_setup_entry=self._unexpected,
                apply_single_setup_entry=self._unexpected,
                resolve_included_setup_worktrees=self._unexpected,
                contexts_from_raw_projects=self._unexpected,
            )

    def test_single_setup_filters_to_selected_and_included_contexts(self) -> None:
        route = Route(
            command="start",
            mode="main",
            flags={
                "setup_worktree": [{"feature": "feature-a", "iteration": "1"}],
                "include_existing_worktrees": ["feature-a-2", "missing"],
            },
        )
        raw_after = [
            ("Main", Path("/repo")),
            ("feature-a-1", Path("/repo/trees/feature-a/1")),
            ("feature-a-2", Path("/repo/trees/feature-a/2")),
        ]
        updates: list[str] = []

        def apply_single(**kwargs: Any) -> tuple[list[tuple[str, Path]], str]:
            updates.append(kwargs["enabled"].__class__.__name__)
            return raw_after, "feature-a-1"

        def resolve_include(**kwargs: Any) -> tuple[set[str], list[str]]:
            self.assertEqual(kwargs["selected_names"], {"feature-a-1"})
            self.assertEqual(kwargs["include_tokens"], ["feature-a-2", "missing"])
            return {"feature-a-1", "feature-a-2"}, ["missing"]

        result = apply_setup_worktree_selection(
            route=route,
            project_contexts=[ProjectContext(name="Main", root=Path("/repo"))],
            setup_worktree_requested=lambda _route: True,
            env={"ENVCTL_SPINNER": "off"},
            emit=None,
            coerce_setup_entries=lambda **kwargs: [("feature-a", "1")]
            if kwargs["flag_name"] == "setup_worktree"
            else [],
            apply_multi_setup_entry=self._unexpected,
            apply_single_setup_entry=apply_single,
            resolve_included_setup_worktrees=resolve_include,
            contexts_from_raw_projects=lambda raw_projects: [
                ProjectContext(name=name, root=root) for name, root in raw_projects
            ],
        )

        self.assertEqual([context.name for context in result], ["feature-a-1", "feature-a-2"])
        self.assertEqual(updates, ["bool"])

    def test_completed_setup_without_selection_returns_refreshed_contexts(self) -> None:
        route = Route(
            command="start",
            mode="main",
            flags={"setup_worktrees": [{"feature": "feature-a", "count": "1"}]},
        )
        refreshed = [ProjectContext(name="feature-a-1", root=Path("/repo/trees/feature-a/1"))]

        result = apply_setup_worktree_selection(
            route=route,
            project_contexts=[],
            setup_worktree_requested=lambda _route: True,
            env={"ENVCTL_SPINNER": "off"},
            emit=None,
            coerce_setup_entries=lambda **kwargs: [("feature-a", "1")]
            if kwargs["flag_name"] == "setup_worktrees"
            else [],
            apply_multi_setup_entry=lambda **_kwargs: ([(refreshed[0].name, refreshed[0].root)], set()),
            apply_single_setup_entry=self._unexpected,
            resolve_included_setup_worktrees=self._unexpected,
            contexts_from_raw_projects=lambda _raw_projects: refreshed,
        )

        self.assertEqual(result, refreshed)

    def _unexpected(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("callback should not be called")
