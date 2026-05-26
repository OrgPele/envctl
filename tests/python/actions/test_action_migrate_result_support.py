from __future__ import annotations

import contextlib
import io
from pathlib import Path
import tempfile
import unittest

from envctl_engine.actions.action_migrate_result_support import (
    MigrateResultRecord,
    migrate_result_record,
    print_migrate_result_records,
)


class ActionMigrateResultSupportTests(unittest.TestCase):
    def test_migrate_result_record_deduplicates_hints_and_derives_headline(self) -> None:
        record = migrate_result_record(
            project_name="feature-a-1",
            action_entry={
                "status": "failed",
                "summary": "RuntimeError: missing env\nhint: one\nhint: one\n",
                "report_path": "/tmp/report.txt",
            },
            failure_headline=lambda summary: summary.splitlines()[0],
        )

        self.assertEqual(
            record,
            MigrateResultRecord(
                project_name="feature-a-1",
                status="failed",
                headline="RuntimeError: missing env",
                hint_lines=("hint: one",),
                report_path="/tmp/report.txt",
            ),
        )

    def test_print_migrate_result_records_compacts_multi_project_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir)
            report_a = report_dir / "feature-a-migrate.txt"
            report_b = report_dir / "feature-b-migrate.txt"
            report_a.write_text("a\n", encoding="utf-8")
            report_b.write_text("b\n", encoding="utf-8")
            records = [
                MigrateResultRecord(
                    project_name="feature-a-1",
                    status="failed",
                    headline="RuntimeError: missing env",
                    hint_lines=("hint: one", "hint: backend env source: default"),
                    report_path=str(report_a),
                ),
                MigrateResultRecord(
                    project_name="feature-b-1",
                    status="failed",
                    headline="RuntimeError: missing env",
                    hint_lines=("hint: one", "hint: backend env source: default"),
                    report_path=str(report_b),
                ),
            ]

            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                print_migrate_result_records(records=records, env={}, interactive_tty=False)

        visible = stream.getvalue()
        self.assertIn("x migrate failed for feature-a-1: RuntimeError: missing env".replace("x", "✗"), visible)
        self.assertIn("x migrate failed for feature-b-1: RuntimeError: missing env".replace("x", "✗"), visible)
        self.assertIn("hint: one", visible)
        self.assertNotIn("backend env source", visible)
        self.assertIn("migrate failure logs:", visible)


if __name__ == "__main__":
    unittest.main()
