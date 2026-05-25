from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import subprocess
import unittest

from envctl_engine.ui.dashboard import pr_selection_support


class DashboardPrSelectionSupportTests(unittest.TestCase):
    def test_pr_base_branch_options_deduplicates_case_insensitively_and_includes_default(self) -> None:
        runtime = SimpleNamespace(config=SimpleNamespace(base_dir=Path("/repo")))

        def run_fn(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=["git"],
                returncode=0,
                stdout="Main\nfeature\nmain\n",
                stderr="",
            )

        options = pr_selection_support.pr_base_branch_options(
            object(),
            runtime,
            default_branch="release",
            pr_git_root_fn=lambda _owner, _runtime: Path("/repo"),
            run_fn=run_fn,
        )

        self.assertEqual([item.token for item in options], ["feature", "Main", "release"])


if __name__ == "__main__":
    unittest.main()
