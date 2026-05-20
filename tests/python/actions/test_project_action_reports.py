from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from envctl_engine.actions.project_action_reports import (
    ProjectActionReportWriter,
    git_state_components,
    review_success_artifact_paths,
)
from envctl_engine.state.models import RunState


class _RuntimeStub:
    def __init__(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._dashboard_pr_url_cache: dict[str, object] = {}
        self._emitted_status: list[str] = []
        self._latest_state: RunState | None = RunState(run_id="run-1", mode="main")
        runtime_root = Path(self._tmpdir.name) / "runtime"
        self.state_repository = SimpleNamespace(
            run_dir_path=lambda run_id: runtime_root / "runs" / str(run_id),
            save_resume_state=self._save_resume_state,
        )

    @property
    def raw_runtime(self) -> object:
        return self

    def load_existing_state(self, *, mode: str) -> RunState | None:  # noqa: ARG002
        return self._latest_state

    def emit_status(self, message: str) -> None:
        self._emitted_status.append(message)

    def _save_resume_state(self, *, state, emit, runtime_map_builder):  # noqa: ANN001, ARG002
        self._latest_state = state
        return {}


class ProjectActionReportTests(unittest.TestCase):
    def test_pr_success_handler_clears_cache_emits_url_and_persists_success(self) -> None:
        runtime = _RuntimeStub()
        runtime._dashboard_pr_url_cache = {"stale": ("expires", None)}
        writer = ProjectActionReportWriter(runtime=runtime)
        handler = writer.success_handler(command_name="pr", mode="main", interactive_command=True)

        handler(
            SimpleNamespace(name="Main"),
            SimpleNamespace(stdout="https://github.com/OrgPele/envctl/pull/247\n", stderr="", returncode=0),
        )

        self.assertEqual(runtime._dashboard_pr_url_cache, {})
        self.assertEqual(runtime._emitted_status, ["PR created: https://github.com/OrgPele/envctl/pull/247"])
        assert runtime._latest_state is not None
        reports = runtime._latest_state.metadata["project_action_reports"]
        self.assertEqual(reports["Main"]["pr"]["status"], "success")

    def test_pr_success_handler_persists_skipped_for_detached_head_without_status_emit(self) -> None:
        runtime = _RuntimeStub()
        writer = ProjectActionReportWriter(runtime=runtime)
        handler = writer.success_handler(command_name="pr", mode="main", interactive_command=True)

        handler(SimpleNamespace(name="Main"), SimpleNamespace(stdout="Skipping Main (detached HEAD).\n"))

        assert runtime._latest_state is not None
        reports = runtime._latest_state.metadata["project_action_reports"]
        self.assertEqual(reports["Main"]["pr"]["status"], "skipped")
        self.assertEqual(runtime._emitted_status, [])

    def test_review_success_artifact_paths_are_persisted_from_labelled_output(self) -> None:
        runtime = _RuntimeStub()
        runtime._latest_state = RunState(run_id="run-1", mode="trees")
        writer = ProjectActionReportWriter(runtime=runtime)
        handler = writer.success_handler(command_name="review", mode="trees", interactive_command=True)

        handler(
            SimpleNamespace(name="feature-a-1"),
            SimpleNamespace(
                stdout=(
                    "Review Ready: feature-a-1\n"
                    "  Output directory\n"
                    "    /tmp/review-output\n"
                    "  Summary file\n"
                    "    /tmp/review-output/summary.md\n"
                    "  Full review bundle\n"
                    "    /tmp/review-output/all.md\n"
                ),
                stderr="",
            ),
        )

        assert runtime._latest_state is not None
        reports = runtime._latest_state.metadata["project_action_reports"]
        review_entry = reports["feature-a-1"]["review"]
        self.assertEqual(review_entry["status"], "success")
        self.assertEqual(review_entry["output_dir"], "/tmp/review-output")
        self.assertEqual(review_entry["summary_path"], "/tmp/review-output/summary.md")
        self.assertEqual(review_entry["bundle_path"], "/tmp/review-output/all.md")

    def test_failure_handler_persists_summary_report_and_migrate_metadata(self) -> None:
        runtime = _RuntimeStub()
        writer = ProjectActionReportWriter(
            runtime=runtime,
            migrate_env_contracts={"Main": {"DATABASE_URL": {"source": "managed"}}},
            failure_summary_lines=lambda command_name, error_output, migrate_env_metadata: [
                f"{command_name}: {error_output.splitlines()[0]}",
                f"metadata={bool(migrate_env_metadata)}",
            ],
            migrate_failure_headline=lambda output: f"headline: {output.splitlines()[0]}",
        )
        handler = writer.failure_handler(command_name="migrate", mode="main")

        handler(SimpleNamespace(name="Main"), "alembic failed\nline 2")

        assert runtime._latest_state is not None
        reports = runtime._latest_state.metadata["project_action_reports"]
        migrate_entry = reports["Main"]["migrate"]
        self.assertEqual(migrate_entry["status"], "failed")
        self.assertEqual(migrate_entry["headline"], "headline: alembic failed")
        self.assertEqual(migrate_entry["summary"], "migrate: alembic failed\nmetadata=True")
        self.assertEqual(migrate_entry["backend_env"], {"DATABASE_URL": {"source": "managed"}})
        report_path = Path(str(migrate_entry["report_path"]))
        self.assertTrue(report_path.is_file())
        self.assertIn("alembic failed", report_path.read_text(encoding="utf-8"))

    def test_review_success_artifact_paths_ignores_missing_labels(self) -> None:
        self.assertEqual(review_success_artifact_paths(stdout="Review Ready\n", stderr=""), {})

    def test_git_state_components_returns_empty_head_for_non_git_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            head, status_hash, status_lines = git_state_components(Path(tmpdir))

        self.assertEqual(head, "")
        self.assertEqual(len(status_hash), 40)
        self.assertEqual(status_lines, 0)


if __name__ == "__main__":
    unittest.main()
