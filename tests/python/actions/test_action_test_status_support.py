from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from envctl_engine.actions.action_test_status_support import (
    command_start_status,
    render_test_execution_status,
    render_test_scope_status,
)


class ActionTestStatusSupportTests(unittest.TestCase):
    def test_status_rendering_matches_action_command_surface(self) -> None:
        targets: list[object] = [SimpleNamespace(name="api"), SimpleNamespace(name="web")]

        self.assertEqual(command_start_status("test", targets), "Running test for 2 targets...")
        self.assertEqual(
            render_test_scope_status(["api"], run_all=False, untested=False, failed=True),
            "Rerunning failed tests for api...",
        )
        self.assertEqual(
            render_test_execution_status(["python", "-m", "pytest"], args=[], source="default", cwd=Path("/repo")),
            "Running pytest suite at tests...",
        )
        self.assertEqual(
            render_test_execution_status(
                ["bash", "/repo/scripts/test-all-trees.sh"],
                args=["projects=api,web"],
                source="configured",
                cwd=Path("/repo"),
            ),
            "Running tree test matrix for 2 selected project(s)...",
        )

    def test_package_test_status_uses_neutral_selected_target_language(self) -> None:
        self.assertEqual(
            render_test_execution_status(
                ["npm", "test", "--", "src/App.test.tsx"],
                args=[],
                source="frontend_package_test",
                cwd=Path("/repo/frontend"),
            ),
            "Running npm test script with 1 selected target(s) in /repo/frontend...",
        )
        self.assertEqual(
            render_test_execution_status(
                ["pnpm", "run", "test", "--", "--runInBand", "src/App.test.tsx", "src/Other.test.tsx"],
                args=[],
                source="frontend_package_test",
                cwd=Path("/repo/frontend"),
            ),
            "Running pnpm test script with 2 selected target(s) in /repo/frontend...",
        )
        self.assertEqual(
            render_test_execution_status(
                ["pnpm", "run", "test", "--", "--grep", "login", "src/App.test.tsx"],
                args=[],
                source="frontend_package_test",
                cwd=Path("/repo/frontend"),
            ),
            "Running pnpm test script with 1 selected target(s) in /repo/frontend...",
        )

    def test_pytest_status_ignores_options_when_selecting_suite_target(self) -> None:
        self.assertEqual(
            render_test_execution_status(
                ["python", "-m", "pytest", "-q", "--maxfail=1", "tests/python/actions/test_actions.py"],
                args=[],
                source="default",
                cwd=Path("/repo"),
            ),
            "Running pytest suite at tests/python/actions/test_actions.py...",
        )
        self.assertEqual(
            render_test_execution_status(
                ["python", "-m", "pytest", "-q", "--maxfail=1"],
                args=[],
                source="default",
                cwd=Path("/repo"),
            ),
            "Running pytest suite at tests...",
        )
        self.assertEqual(
            render_test_execution_status(
                ["python", "-m", "pytest", "-k", "smoke", "tests/python/actions"],
                args=[],
                source="default",
                cwd=Path("/repo"),
            ),
            "Running pytest suite at tests/python/actions...",
        )
        self.assertEqual(
            render_test_execution_status(
                ["python", "-m", "pytest", "--cache-clear", "tests/python/actions"],
                args=[],
                source="default",
                cwd=Path("/repo"),
            ),
            "Running pytest suite at tests/python/actions...",
        )
        self.assertEqual(
            render_test_execution_status(
                ["python", "-m", "pytest", "--rootdir", "/repo", "tests/python/actions"],
                args=[],
                source="default",
                cwd=Path("/repo"),
            ),
            "Running pytest suite at tests/python/actions...",
        )

    def test_pytest_status_distinguishes_failed_selectors_from_suite_paths(self) -> None:
        self.assertEqual(
            render_test_execution_status(
                ["python", "-m", "pytest", "tests/python/actions/test_actions.py"],
                args=[],
                source="default",
                cwd=Path("/repo"),
            ),
            "Running pytest suite at tests/python/actions/test_actions.py...",
        )
        self.assertEqual(
            render_test_execution_status(
                [
                    "python",
                    "-m",
                    "pytest",
                    "tests/python/actions/test_actions.py::ActionTests::test_one",
                    "tests/python/actions/test_more.py::test_two",
                ],
                args=[],
                source="default",
                cwd=Path("/repo"),
            ),
            "Rerunning failed pytest cases (2)...",
        )


if __name__ == "__main__":
    unittest.main()
