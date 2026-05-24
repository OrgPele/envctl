from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from envctl_engine.actions.project_action_domain import DirtyWorktreeReport
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.ui.dashboard import pr_scope_support


def _report(project_name: str, *, git_root: Path) -> DirtyWorktreeReport:
    return DirtyWorktreeReport(
        project_name=project_name,
        project_root=Path("/tmp") / project_name,
        git_root=git_root,
        staged=True,
        unstaged=False,
        untracked=False,
    )


class DashboardPrScopeSupportTests(unittest.TestCase):
    def test_dirty_pr_reports_deduplicates_selected_projects_by_git_root(self) -> None:
        repo_root = Path("/repo")
        git_root = Path("/repo/.git-root")
        runtime = SimpleNamespace(config=SimpleNamespace(base_dir=repo_root))
        state = RunState(
            run_id="run-1",
            mode="trees",
            metadata={"project_roots": {"feature-a": "/repo/worktrees/a", "feature-b": "/repo/worktrees/b"}},
        )
        route = Route(command="pr", mode="trees", projects=["feature-a", "feature-b"])
        probes: list[tuple[Path, str]] = []

        def probe(project_root: Path, _repo_root: Path, *, project_name: str) -> DirtyWorktreeReport:
            probes.append((project_root, project_name))
            return _report(project_name, git_root=git_root)

        reports = pr_scope_support.dirty_pr_reports(
            object(),
            route,
            state,
            runtime,
            probe_dirty_worktree_fn=probe,
        )

        self.assertEqual([report.project_name for report in reports], ["feature-a"])
        self.assertEqual([project_name for _root, project_name in probes], ["feature-a", "feature-b"])


if __name__ == "__main__":
    unittest.main()
