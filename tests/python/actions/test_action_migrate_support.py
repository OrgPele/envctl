from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import tempfile
from pathlib import Path
import unittest

from envctl_engine.actions.action_migrate_support import (
    MigrateResultRecord,
    migrate_result_record,
    print_migrate_result_records,
    shared_report_parent,
    visible_migrate_hint_lines,
)


class ActionMigrateSupportTests(unittest.TestCase):
    def test_migrate_result_record_extracts_failure_headline_hints_and_report(self) -> None:
        record = migrate_result_record(
            project_name="Main",
            action_entry={
                "status": "failed",
                "summary": "\n".join(
                    [
                        "pydantic_core._pydantic_core.ValidationError: missing env",
                        "hint: backend env source: backend/.env",
                        "hint: APP_ENV_FILE is exported when an env file is found.",
                        "hint: APP_ENV_FILE is exported when an env file is found.",
                    ]
                ),
                "report_path": "/tmp/migrate.log",
            },
            migrate_failure_headline=lambda summary: summary.splitlines()[0],
        )

        self.assertEqual(
            record,
            MigrateResultRecord(
                project_name="Main",
                status="failed",
                headline="pydantic_core._pydantic_core.ValidationError: missing env",
                hint_lines=(
                    "hint: backend env source: backend/.env",
                    "hint: APP_ENV_FILE is exported when an env file is found.",
                ),
                report_path="/tmp/migrate.log",
            ),
        )

    def test_visible_migrate_hint_lines_hides_backend_env_source_hint(self) -> None:
        self.assertEqual(
            visible_migrate_hint_lines(
                (
                    "hint: backend env source: backend/.env",
                    "hint: APP_ENV_FILE is exported when an env file is found.",
                )
            ),
            ("hint: APP_ENV_FILE is exported when an env file is found.",),
        )

    def test_print_migrate_result_records_compacts_shared_failure_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            parent = Path(tmpdir)
            records = [
                MigrateResultRecord(
                    project_name="Main",
                    status="failed",
                    headline="missing env",
                    hint_lines=("hint: run envctl --dependencies first",),
                    report_path=str(parent / "Main_migrate.txt"),
                ),
                MigrateResultRecord(
                    project_name="Admin",
                    status="failed",
                    headline="missing env",
                    hint_lines=("hint: run envctl --dependencies first",),
                    report_path=str(parent / "Admin_migrate.txt"),
                ),
            ]

            output = StringIO()
            with redirect_stdout(output):
                print_migrate_result_records(records=records, env={"NO_COLOR": "1"})

            rendered = output.getvalue()
            self.assertIn("migrate failed for Main: missing env", rendered)
            self.assertIn("migrate failed for Admin: missing env", rendered)
            self.assertIn("hint: run envctl --dependencies first", rendered)
            self.assertIn("migrate failure logs:", rendered)
            self.assertIn(str(parent), rendered)
            self.assertIn("Main_migrate.txt", rendered)
            self.assertIn("Admin_migrate.txt", rendered)

    def test_shared_report_parent_requires_one_parent(self) -> None:
        self.assertEqual(
            shared_report_parent(
                [
                    MigrateResultRecord(project_name="Main", status="failed", report_path="/tmp/a/Main.txt"),
                    MigrateResultRecord(project_name="Admin", status="failed", report_path="/tmp/a/Admin.txt"),
                ]
            ),
            "/tmp/a",
        )
        self.assertEqual(
            shared_report_parent(
                [
                    MigrateResultRecord(project_name="Main", status="failed", report_path="/tmp/a/Main.txt"),
                    MigrateResultRecord(project_name="Admin", status="failed", report_path="/tmp/b/Admin.txt"),
                ]
            ),
            "",
        )


if __name__ == "__main__":
    unittest.main()
