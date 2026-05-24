from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from envctl_engine.actions.project_action_support import (
    build_project_action_failure_handler,
    build_project_action_success_handler,
    first_output_line,
    persist_project_action_result,
    project_action_success_status,
    review_success_artifact_paths,
    write_project_action_failure_report,
)


class ProjectActionReportSupportTests(unittest.TestCase):
    def test_review_success_artifact_paths_parses_labeled_output(self) -> None:
        parsed = review_success_artifact_paths(
            stdout="\x1b[32mOutput directory\x1b[0m\n/tmp/review\nSummary file\n/tmp/summary.md\n",
            stderr="Full review bundle\n/tmp/bundle.json\n",
        )

        self.assertEqual(
            parsed,
            {
                "output_dir": "/tmp/review",
                "summary_path": "/tmp/summary.md",
                "bundle_path": "/tmp/bundle.json",
            },
        )

    def test_project_action_success_status_marks_detached_pr_skip(self) -> None:
        completed = SimpleNamespace(stdout="Skipping PR creation for detached HEAD\nmore detail\n")

        self.assertEqual(project_action_success_status(command_name="pr", completed=completed), "skipped")
        self.assertEqual(project_action_success_status(command_name="review", completed=completed), "success")

    def test_build_project_action_success_handler_persists_review_artifacts_and_status(self) -> None:
        persisted: list[dict[str, object]] = []
        cache_cleared: list[bool] = []

        handler = build_project_action_success_handler(
            command_name="review",
            mode="trees",
            interactive_command=True,
            clear_dashboard_pr_cache=lambda: cache_cleared.append(True),
            project_action_success_status_fn=project_action_success_status,
            review_success_artifact_paths_fn=review_success_artifact_paths,
            persist_project_action_result_fn=lambda **kwargs: persisted.append(kwargs),
            first_output_line_fn=first_output_line,
            emit_status=lambda _message: None,
        )

        handler(
            SimpleNamespace(name="feature-a-1"),
            SimpleNamespace(stdout="Output directory\n/tmp/review\nSummary file\n/tmp/review/summary.md\n", stderr=""),
        )

        self.assertEqual(cache_cleared, [True])
        self.assertEqual(persisted[0]["command_name"], "review")
        self.assertEqual(persisted[0]["mode"], "trees")
        self.assertEqual(persisted[0]["project_name"], "feature-a-1")
        self.assertEqual(persisted[0]["status"], "success")
        self.assertEqual(persisted[0]["error_output"], "")
        self.assertEqual(persisted[0]["extra_entry"], {"output_dir": "/tmp/review", "summary_path": "/tmp/review/summary.md"})

    def test_build_project_action_success_handler_reports_interactive_pr_url(self) -> None:
        statuses: list[str] = []

        handler = build_project_action_success_handler(
            command_name="pr",
            mode="main",
            interactive_command=True,
            clear_dashboard_pr_cache=lambda: None,
            project_action_success_status_fn=project_action_success_status,
            review_success_artifact_paths_fn=review_success_artifact_paths,
            persist_project_action_result_fn=lambda **_kwargs: None,
            first_output_line_fn=first_output_line,
            emit_status=statuses.append,
        )

        handler(SimpleNamespace(name="Main"), SimpleNamespace(stdout="\nhttps://github.test/pr/1\n", stderr=""))

        self.assertEqual(statuses, ["PR created: https://github.test/pr/1"])

    def test_build_project_action_failure_handler_persists_failed_status(self) -> None:
        persisted: list[dict[str, object]] = []

        handler = build_project_action_failure_handler(
            command_name="migrate",
            mode="main",
            persist_project_action_result_fn=lambda **kwargs: persisted.append(kwargs),
        )

        handler(SimpleNamespace(name="Main"), "RuntimeError: boom")

        self.assertEqual(
            persisted,
            [
                {
                    "command_name": "migrate",
                    "mode": "main",
                    "project_name": "Main",
                    "status": "failed",
                    "error_output": "RuntimeError: boom",
                }
            ],
        )

    def test_write_project_action_failure_report_writes_safe_project_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            runtime = SimpleNamespace(
                state_repository=SimpleNamespace(run_dir_path=lambda run_id: repo / "runs" / run_id)
            )

            report = write_project_action_failure_report(
                runtime,
                run_id="run-1",
                project_name="Feature A",
                command_name="review",
                output="boom",
            )
            report_text = report.read_text(encoding="utf-8")

            self.assertEqual(report.name, "Feature_A_review.txt")
        self.assertEqual(report_text, "boom\n")

    def test_persist_project_action_result_records_migrate_failure_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state = SimpleNamespace(run_id="run-1", metadata={})
            saved: list[object] = []
            runtime = SimpleNamespace(
                load_existing_state=lambda mode: state if mode == "trees" else None,
                state_repository=SimpleNamespace(
                    run_dir_path=lambda run_id: repo / "runs" / run_id,
                    save_resume_state=lambda **kwargs: saved.append(kwargs),
                ),
                emit=lambda *_args, **_kwargs: None,
            )

            persist_project_action_result(
                runtime=runtime,
                command_name="migrate",
                mode="trees",
                project_name="feature-a-1",
                status="failed",
                error_output="\x1b[31mRuntimeError: bad env\x1b[0m",
                migrate_env_contracts={"feature-a-1": {"env_file_source": "default"}},
                failure_summary_lines=lambda **_kwargs: ["RuntimeError: bad env", "hint: fix env"],
                failure_headline=lambda _output: "RuntimeError: bad env",
                runtime_map_builder=lambda _state: {},
            )

            entry = state.metadata["project_action_reports"]["feature-a-1"]["migrate"]
            self.assertEqual(entry["status"], "failed")
            self.assertEqual(entry["backend_env"], {"env_file_source": "default"})
            self.assertEqual(entry["headline"], "RuntimeError: bad env")
            self.assertEqual(entry["summary"], "RuntimeError: bad env\nhint: fix env")
            self.assertTrue(Path(str(entry["report_path"])).is_file())
            self.assertEqual(len(saved), 1)

    def test_first_output_line_skips_blank_lines(self) -> None:
        self.assertEqual(first_output_line("\n\n  https://example.test/pr/1\n"), "https://example.test/pr/1")


if __name__ == "__main__":
    unittest.main()
