from __future__ import annotations

import unittest

from envctl_engine.actions.actions_test_classification import (
    classify_test_command_source,
    is_package_test_command,
    package_test_positionals,
)


class ActionsTestClassificationTests(unittest.TestCase):
    def test_package_test_command_accepts_supported_direct_and_run_forms(self) -> None:
        for manager in ("bun", "npm", "pnpm", "yarn"):
            with self.subTest(manager=manager):
                self.assertTrue(is_package_test_command([manager, "test"]))
                self.assertTrue(is_package_test_command([manager, "run", "test"]))

    def test_package_test_command_rejects_non_test_scripts(self) -> None:
        self.assertFalse(is_package_test_command(["npm", "run", "test:unit"]))
        self.assertFalse(is_package_test_command(["pnpm", "exec", "vitest"]))
        self.assertFalse(is_package_test_command(["python", "-m", "pytest"]))
        self.assertFalse(is_package_test_command([]))

    def test_package_test_positionals_skip_runner_option_values(self) -> None:
        self.assertEqual(package_test_positionals(["npm", "test"]), [])
        self.assertEqual(
            package_test_positionals(
                [
                    "pnpm",
                    "run",
                    "test",
                    "--",
                    "--runInBand",
                    "--grep",
                    "login flow",
                    "--project=chromium",
                    "-t",
                    "subtest name",
                    "src/App.test.tsx",
                    "src/Other.test.tsx",
                ]
            ),
            ["src/App.test.tsx", "src/Other.test.tsx"],
        )

    def test_command_source_classification_uses_requested_surfaces(self) -> None:
        self.assertEqual(
            classify_test_command_source(
                ["python", "-m", "pytest", "tests/python"],
                include_backend=True,
                include_frontend=False,
            ),
            "backend_pytest",
        )
        self.assertEqual(
            classify_test_command_source(
                ["python", "-m", "unittest", "discover"],
                include_backend=True,
                include_frontend=False,
            ),
            "root_unittest",
        )
        self.assertEqual(
            classify_test_command_source(["pnpm", "test"], include_backend=False, include_frontend=True),
            "frontend_package_test",
        )
        self.assertEqual(
            classify_test_command_source(["pnpm", "test"], include_backend=True, include_frontend=True),
            "package_test",
        )
        self.assertEqual(
            classify_test_command_source(["custom", "test"], include_backend=True, include_frontend=True),
            "configured",
        )


if __name__ == "__main__":
    unittest.main()
