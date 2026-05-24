from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.ui.dashboard import review_tab_support


def _route(**kwargs: object) -> Route:
    defaults: dict[str, object] = {"command": "review", "mode": "trees", "projects": []}
    defaults.update(kwargs)
    return Route(**defaults)  # type: ignore[arg-type]


def _state(**kwargs: object) -> RunState:
    defaults: dict[str, object] = {"run_id": "r1", "mode": "trees", "services": {}, "metadata": {}}
    defaults.update(kwargs)
    return RunState(**defaults)  # type: ignore[arg-type]


class _Runtime:
    def __init__(self, base_dir: Path) -> None:
        self.config = SimpleNamespace(base_dir=base_dir)
        self.events: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def _emit(self, *args: object, **kwargs: object) -> None:
        self.events.append((args, kwargs))


class _Owner:
    def __init__(self, target: tuple[str, Path] | None = None, decision: str = "skip") -> None:
        self.target = target
        self.decision = decision

    def _review_tab_target(self, route: Route, state: RunState, runtime: object) -> tuple[str, Path] | None:
        _ = route, state, runtime
        return self.target

    def _prompt_review_tab_menu(self, runtime: object, *, project_name: str) -> str:
        _ = runtime, project_name
        return self.decision


class DashboardReviewTabSupportTests(unittest.TestCase):
    def test_review_tab_target_rejects_main_repo_and_accepts_single_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            worktree = repo / "trees" / "feature-a" / "1"
            worktree.mkdir(parents=True)
            runtime = _Runtime(repo)
            state = _state(metadata={"project_roots": {"Main": ".", "feature-a-1": str(worktree)}})

            main = review_tab_support.review_tab_target(
                _Owner(),
                _route(projects=["Main"]),
                state,
                runtime,
                repo_root_from_runtime_fn=lambda _runtime: repo,
                project_roots_for_route_fn=lambda _owner, route, _state, _runtime: {
                    name: repo if name == "Main" else worktree for name in route.projects
                },
                resolve_git_root_fn=lambda project_root, _repo_root: project_root,
            )
            feature = review_tab_support.review_tab_target(
                _Owner(),
                _route(projects=["feature-a-1"]),
                state,
                runtime,
                repo_root_from_runtime_fn=lambda _runtime: repo,
                project_roots_for_route_fn=lambda _owner, route, _state, _runtime: {
                    name: worktree for name in route.projects
                },
                resolve_git_root_fn=lambda project_root, _repo_root: project_root,
            )

        self.assertIsNone(main)
        self.assertEqual(feature, ("feature-a-1", worktree))

    def test_apply_review_tab_launch_selection_sets_flag_only_when_accepted_and_ready(self) -> None:
        runtime = _Runtime(Path("."))
        route = _route(projects=["feature-a-1"])
        owner = _Owner(target=("feature-a-1", Path("trees/feature-a/1")), decision="commit")

        result = review_tab_support.apply_review_tab_launch_selection(
            owner,
            route,
            _state(),
            runtime,
            review_agent_launch_readiness_fn=lambda _runtime: SimpleNamespace(
                ready=True,
                reason="ready",
                cli="codex",
                missing=(),
            ),
        )

        self.assertIs(result, route)
        self.assertTrue(route.flags["dashboard_review_tab_launch"])
        self.assertEqual(runtime.events[-1][0], ("dashboard.review_tab.accepted",))

    def test_maybe_offer_review_tab_launch_invokes_launcher_after_success(self) -> None:
        runtime = _Runtime(Path("/repo"))
        launched: list[dict[str, object]] = []
        owner = _Owner(target=("feature-a-1", Path("/repo/trees/feature-a/1")))
        route = _route(projects=["feature-a-1"], flags={"dashboard_review_tab_launch": True})
        state = _state(
            metadata={
                "project_action_reports": {
                    "feature-a-1": {"review": {"status": "success", "bundle_path": "/tmp/review.md"}}
                }
            }
        )

        review_tab_support.maybe_offer_review_tab_launch(
            owner,
            route,
            state,
            runtime,
            launch_review_agent_terminal_fn=lambda *args, **kwargs: launched.append(kwargs),
            repo_root_from_runtime_fn=lambda _runtime: Path("/repo"),
        )

        self.assertEqual(launched[0]["project_name"], "feature-a-1")
        self.assertEqual(launched[0]["review_bundle_path"], Path("/tmp/review.md"))


if __name__ == "__main__":
    unittest.main()
