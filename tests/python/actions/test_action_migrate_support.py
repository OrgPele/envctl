from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from envctl_engine.actions.action_migrate_support import (
    MigrateResultRecord,
    MigrateProjectContext,
    migrate_backend_cwd,
    migrate_component_port,
    migrate_failure_headline,
    migrate_failure_headline_from_lines,
    migrate_env_source_hint_lines,
    migrate_failure_hint_lines,
    migrate_project_context,
    migrate_requirements_for_target,
    project_action_failure_summary_lines,
    migrate_result_record,
    print_migrate_result_records,
)
from envctl_engine.state.models import PortPlan, RequirementsResult
from envctl_engine.test_output.parser_base import strip_ansi


class ActionMigrateSupportTests(unittest.TestCase):
    def test_migrate_result_record_deduplicates_hints_and_derives_headline(self) -> None:
        record = migrate_result_record(
            project_name="feature-a-1",
            action_entry={
                "status": "failed",
                "summary": "\n".join(
                    [
                        "Traceback (most recent call last):",
                        "RuntimeError: migration failed",
                        "hint: check DATABASE_URL",
                        "hint: check DATABASE_URL",
                    ]
                ),
                "report_path": "/tmp/report.txt",
            },
            failure_headline=lambda summary: summary.splitlines()[1],
        )

        self.assertEqual(
            record,
            MigrateResultRecord(
                project_name="feature-a-1",
                status="failed",
                headline="RuntimeError: migration failed",
                hint_lines=("hint: check DATABASE_URL",),
                report_path="/tmp/report.txt",
            ),
        )

    def test_migrate_failure_hint_lines_explain_missing_env_from_alembic_env(self) -> None:
        hints = migrate_failure_hint_lines(
            "\n".join(
                [
                    "Traceback (most recent call last):",
                    '  File "/repo/backend/alembic/env.py", line 12, in <module>',
                    "pydantic_core._pydantic_core.ValidationError: 2 validation errors for Settings",
                    "DATABASE_URL",
                    "  Field required [type=missing]",
                    "REDIS_URL",
                    "  Field required [type=missing]",
                ]
            )
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
                "env_file_path": "/repo/backend/custom.env",
                "override_requested": True,
                "override_resolution": "found",
            }
        )

        self.assertEqual(
            hints,
            ["hint: backend env source: override | /repo/backend/custom.env | override_resolution=found"],
        )

    def test_migrate_failure_headline_prefers_actionable_exception(self) -> None:
        lines = [
            "Traceback (most recent call last):",
            'File "/tmp/project/backend/alembic/env.py", line 19, in <module>',
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

    def test_project_action_failure_summary_lines_merges_migrate_hints_and_env_source(self) -> None:
        lines = project_action_failure_summary_lines(
            command_name="migrate",
            error_output="\n".join(
                [
                    "Traceback (most recent call last):",
                    '  File "/repo/backend/alembic/env.py", line 12, in <module>',
                    "pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings",
                    "DATABASE_URL",
                    "  Field required [type=missing]",
                ]
            ),
            migrate_env_metadata={
                "env_file_source": "override",
                "env_file_path": "/repo/backend/custom.env",
                "override_requested": True,
                "override_resolution": "missing",
            },
        )

        self.assertEqual(lines[0], "pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings")
        self.assertIn(
            "hint: migrate failed before Alembic reached revisions because required env vars were missing "
            "(DATABASE_URL).",
            lines,
        )
        self.assertIn(
            "hint: backend env source: override | /repo/backend/custom.env | override_resolution=missing",
            lines,
        )
        self.assertEqual(len(lines), len(dict.fromkeys(lines)))

    def test_migrate_project_context_projects_dependency_ports_from_requirements_state(self) -> None:
        requirements = RequirementsResult(
            project="feature-a-1",
            components={
                "postgres": {"requested": 5433},
                "redis": {"assigned": 6380},
                "n8n": {"final": 5679},
                "supabase": {"final": 6543},
            },
        )

        context = migrate_project_context(
            project_name="feature-a-1",
            project_root=Path("/repo/trees/feature-a/1"),
            requirements=requirements,
        )

        self.assertEqual(
            context,
            MigrateProjectContext(
                name="feature-a-1",
                root=Path("/repo/trees/feature-a/1"),
                ports={
                    "db": PortPlan(
                        project="feature-a-1",
                        requested=5433,
                        assigned=5433,
                        final=5433,
                        source="requirements_state",
                    ),
                    "redis": PortPlan(
                        project="feature-a-1",
                        requested=6380,
                        assigned=6380,
                        final=6380,
                        source="requirements_state",
                    ),
                    "n8n": PortPlan(
                        project="feature-a-1",
                        requested=5679,
                        assigned=5679,
                        final=5679,
                        source="requirements_state",
                    ),
                },
            ),
        )
        self.assertEqual(migrate_component_port({"final": 0, "requested": "2222", "assigned": 3333}), 2222)

    def test_migrate_requirements_for_target_matches_project_name_case_insensitively(self) -> None:
        requirements = RequirementsResult(project="Feature-A-1")
        runtime = SimpleNamespace(
            load_existing_state=lambda mode=None: SimpleNamespace(requirements={"Feature-A-1": requirements})
        )
        route = SimpleNamespace(mode="trees")

        self.assertIs(
            migrate_requirements_for_target(runtime=runtime, route=route, project_name="feature-a-1"),
            requirements,
        )

    def test_migrate_backend_cwd_prefers_backend_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.assertEqual(migrate_backend_cwd(root), root)
            (root / "backend").mkdir()
            self.assertEqual(migrate_backend_cwd(root), root / "backend")

    def test_print_migrate_result_records_compacts_multi_project_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir) / "reports"
            report_dir.mkdir()
            report_a = report_dir / "feature-a-migrate.txt"
            report_b = report_dir / "feature-b-migrate.txt"
            report_a.write_text("a\n", encoding="utf-8")
            report_b.write_text("b\n", encoding="utf-8")
            records = [
                MigrateResultRecord(
                    project_name="feature-a-1",
                    status="failed",
                    headline="RuntimeError: missing env",
                    hint_lines=("hint: shared fix", "hint: backend env source: default"),
                    report_path=str(report_a),
                ),
                MigrateResultRecord(
                    project_name="feature-b-1",
                    status="failed",
                    headline="RuntimeError: missing env",
                    hint_lines=("hint: shared fix", "hint: backend env source: default"),
                    report_path=str(report_b),
                ),
            ]
            stdout = StringIO()

            with redirect_stdout(stdout):
                print_migrate_result_records(records=records, env={}, interactive_tty=False)

        visible = strip_ansi(stdout.getvalue())
        self.assertIn("✗ migrate failed for feature-a-1: RuntimeError: missing env", visible)
        self.assertIn("✗ migrate failed for feature-b-1: RuntimeError: missing env", visible)
        self.assertEqual(visible.count("hint: shared fix"), 1)
        self.assertNotIn("hint: backend env source:", visible)
        self.assertIn("migrate failure logs:", visible)
        self.assertIn(str(report_dir), visible)
        self.assertIn(f"- feature-a-1: {report_a.name}", visible)
        self.assertIn(f"- feature-b-1: {report_b.name}", visible)


if __name__ == "__main__":
    unittest.main()
