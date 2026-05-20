from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from envctl_engine.actions.action_migrate_results import (
    MigrateResultRecord,
    migrate_result_record,
    migrate_result_records,
    print_migrate_result_records,
    shared_migrate_hint_lines,
    shared_report_parent,
)
from envctl_engine.test_output.parser_base import strip_ansi


class ActionMigrateResultTests(unittest.TestCase):
    def test_migrate_result_records_preserve_route_order_and_fallback_entries(self) -> None:
        metadata = {
            "feature-a-1": {
                "migrate": {
                    "status": "success",
                },
            },
        }
        fallback_entries = {
            "feature-b-1": {
                "status": "failed",
                "summary": "Traceback\nalembic.util.exc.CommandError: feature-b failed\nhint: retry",
                "report_path": "/tmp/feature-b-1_migrate.txt",
            },
        }

        records = migrate_result_records(
            project_names=["feature-a-1", "feature-b-1"],
            metadata=metadata,
            fallback_entries=fallback_entries,
            failure_headline=lambda summary: "alembic.util.exc.CommandError: feature-b failed",
        )

        self.assertEqual([record.project_name for record in records], ["feature-a-1", "feature-b-1"])
        self.assertEqual(records[0].status, "success")
        self.assertEqual(records[1].status, "failed")
        self.assertEqual(records[1].headline, "alembic.util.exc.CommandError: feature-b failed")
        self.assertEqual(records[1].hint_lines, ("hint: retry",))

    def test_migrate_result_record_ignores_unknown_status(self) -> None:
        self.assertIsNone(migrate_result_record(project_name="Main", action_entry={"status": "running"}))
        self.assertIsNone(migrate_result_record(project_name="Main", action_entry=None))

    def test_shared_hints_hide_backend_env_source_hint(self) -> None:
        records = [
            MigrateResultRecord(
                project_name="feature-a-1",
                status="failed",
                hint_lines=("hint: shared", "hint: backend env source: default"),
            ),
            MigrateResultRecord(
                project_name="feature-b-1",
                status="failed",
                hint_lines=("hint: shared", "hint: backend env source: default"),
            ),
        ]

        self.assertEqual(shared_migrate_hint_lines(records), ("hint: shared",))

    def test_print_migrate_result_records_compacts_shared_failure_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            parent = Path(tmpdir)
            report_a = parent / "feature-a-1_migrate.txt"
            report_b = parent / "feature-b-1_migrate.txt"
            records = [
                MigrateResultRecord(
                    project_name="feature-a-1",
                    status="failed",
                    headline="pydantic_core._pydantic_core.ValidationError: 2 validation errors for Settings",
                    hint_lines=("hint: shared", "hint: backend env source: default"),
                    report_path=str(report_a),
                ),
                MigrateResultRecord(
                    project_name="feature-b-1",
                    status="failed",
                    headline="pydantic_core._pydantic_core.ValidationError: 2 validation errors for Settings",
                    hint_lines=("hint: shared", "hint: backend env source: default"),
                    report_path=str(report_b),
                ),
            ]

            out = StringIO()
            with redirect_stdout(out):
                print_migrate_result_records(records=records, env={})

        visible = strip_ansi(out.getvalue())
        self.assertIn("migrate failed for feature-a-1", visible)
        self.assertIn("migrate failed for feature-b-1", visible)
        self.assertEqual(visible.count("hint: shared"), 1)
        self.assertNotIn("hint: backend env source:", visible)
        self.assertIn("migrate failure logs:", visible)
        self.assertIn(str(parent), visible)
        self.assertIn("- feature-a-1: feature-a-1_migrate.txt", visible)
        self.assertIn("- feature-b-1: feature-b-1_migrate.txt", visible)

    def test_print_migrate_result_records_preserves_success_and_failure_order(self) -> None:
        records = [
            MigrateResultRecord(project_name="feature-a-1", status="success"),
            MigrateResultRecord(
                project_name="feature-b-1",
                status="failed",
                headline="alembic.util.exc.CommandError: feature-b failed",
            ),
        ]

        out = StringIO()
        with redirect_stdout(out):
            print_migrate_result_records(records=records, env={})

        visible = strip_ansi(out.getvalue())
        self.assertLess(
            visible.index("migrate succeeded for feature-a-1"),
            visible.index("migrate failed for feature-b-1: alembic.util.exc.CommandError: feature-b failed"),
        )

    def test_shared_report_parent_requires_single_parent(self) -> None:
        records = [
            MigrateResultRecord(project_name="a", status="failed", report_path="/tmp/a/report.txt"),
            MigrateResultRecord(project_name="b", status="failed", report_path="/tmp/b/report.txt"),
        ]

        self.assertEqual(shared_report_parent(records), "")


if __name__ == "__main__":
    unittest.main()
