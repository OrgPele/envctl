from __future__ import annotations

import unittest

from envctl_engine.actions.action_migrate_failure_support import (
    migrate_env_source_hint_lines,
    migrate_failure_headline,
    migrate_failure_headline_from_lines,
    migrate_failure_hint_lines,
    project_action_failure_summary_lines,
)


class ActionMigrateFailureSupportTests(unittest.TestCase):
    def test_migrate_failure_hint_lines_explain_missing_env_from_alembic_env(self) -> None:
        hints = migrate_failure_hint_lines(
            "\x1b[31mTraceback\x1b[0m\n"
            '  File "/repo/backend/alembic/env.py", line 1, in <module>\n'
            "pydantic_core._pydantic_core.ValidationError: field required\n"
            "DATABASE_URL\n"
            "REDIS_URL\n"
        )

        self.assertIn(
            "hint: migrate failed before Alembic reached revisions because required env vars were missing "
            "(DATABASE_URL, REDIS_URL).",
            hints,
        )
        self.assertIn("hint: envctl migrate loads backend env from backend/.env by default.", hints)

    def test_migrate_env_source_hint_lines_include_override_resolution(self) -> None:
        hints = migrate_env_source_hint_lines(
            {
                "env_file_source": "override",
                "env_file_path": "/repo/backend/.env.local",
                "override_requested": True,
                "override_resolution": "repo_relative",
            }
        )

        self.assertEqual(
            hints,
            ["hint: backend env source: override | /repo/backend/.env.local | override_resolution=repo_relative"],
        )

    def test_project_action_failure_summary_lines_merges_migrate_hints_and_env_source(self) -> None:
        lines = project_action_failure_summary_lines(
            command_name="migrate",
            error_output='File "/repo/backend/alembic/env.py"\nValidationError\nDATABASE_URL\n',
            migrate_env_metadata={"env_file_source": "default"},
            format_summary_error_lines=lambda _output: ["Traceback (most recent call last):", "RuntimeError: bad"],
        )

        self.assertEqual(lines[0], "RuntimeError: bad")
        self.assertIn(
            "hint: migrate failed before Alembic reached revisions because required env vars were missing "
            "(DATABASE_URL).",
            lines,
        )
        self.assertIn("hint: backend env source: default", lines)

    def test_migrate_failure_headline_prefers_actionable_exception(self) -> None:
        lines = [
            "Traceback (most recent call last):",
            'File "/repo/backend/alembic/env.py", line 1, in <module>',
            "alembic.util.exc.CommandError: migration failed",
        ]

        self.assertEqual(
            migrate_failure_headline_from_lines(lines),
            "alembic.util.exc.CommandError: migration failed",
        )
        self.assertEqual(
            migrate_failure_headline("\n".join(lines)),
            "alembic.util.exc.CommandError: migration failed",
        )


if __name__ == "__main__":
    unittest.main()
