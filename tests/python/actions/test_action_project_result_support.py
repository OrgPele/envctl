from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from envctl_engine.actions.action_project_result_support import (
    clear_dashboard_pr_cache,
    first_output_line,
    persist_project_action_result,
    project_action_success_status,
    review_success_artifact_paths,
)
from envctl_engine.state.models import RunState


class _StateRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.saved_state: RunState | None = None

    def run_dir_path(self, run_id: str) -> Path:
        return self.root / "runs" / run_id

    def save_resume_state(self, *, state, emit, runtime_map_builder):  # noqa: ANN001
        _ = emit, runtime_map_builder
        self.saved_state = state
        return {}


class ActionProjectResultSupportTests(unittest.TestCase):
    def test_review_success_artifact_paths_parses_report_locations(self) -> None:
        paths = review_success_artifact_paths(
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
        )

        self.assertEqual(
            paths,
            {
                "output_dir": "/tmp/review-output",
                "summary_path": "/tmp/review-output/summary.md",
                "bundle_path": "/tmp/review-output/all.md",
            },
        )

    def test_project_action_success_status_detects_detached_head_pr_skip(self) -> None:
        completed = SimpleNamespace(stdout="Skipping Main (detached HEAD).\n", stderr="", returncode=0)

        self.assertEqual(project_action_success_status(command_name="pr", completed=completed), "skipped")
        self.assertEqual(first_output_line(" \n https://github.com/OrgPele/envctl/pull/246\n"), "https://github.com/OrgPele/envctl/pull/246")

    def test_clear_dashboard_pr_cache_clears_runtime_cache_only_when_present(self) -> None:
        runtime = SimpleNamespace(_dashboard_pr_url_cache={"stale": ("expires", None)})

        clear_dashboard_pr_cache(runtime)

        self.assertEqual(runtime._dashboard_pr_url_cache, {})
        clear_dashboard_pr_cache(SimpleNamespace())

    def test_persist_project_action_result_records_failure_summary_report_and_migrate_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = RunState(run_id="run-1", mode="main")
            repository = _StateRepository(Path(tmpdir))

            persist_project_action_result(
                command_name="migrate",
                mode="main",
                project_name="Main",
                status="failed",
                error_output="\x1b[31mboom\x1b[0m\nDATABASE_URL\n",
                extra_entry=None,
                load_existing_state=lambda mode: state if mode == "main" else None,
                state_repository=repository,
                emit=lambda *_args, **_kwargs: None,
                migrate_env_metadata={"env_file_source": "backend/.env"},
                failure_summary_lines=lambda **_kwargs: [
                    "pydantic_core._pydantic_core.ValidationError: missing env",
                    "hint: backend env source: backend/.env",
                ],
                migrate_failure_headline=lambda _output: "pydantic_core._pydantic_core.ValidationError: missing env",
            )

            self.assertIs(repository.saved_state, state)
            reports = state.metadata["project_action_reports"]
            self.assertIsInstance(reports, dict)
            entry = reports["Main"]["migrate"]  # type: ignore[index]
            self.assertEqual(entry["status"], "failed")
            self.assertEqual(entry["headline"], "pydantic_core._pydantic_core.ValidationError: missing env")
            self.assertEqual(entry["backend_env"], {"env_file_source": "backend/.env"})
            self.assertIn("hint: backend env source: backend/.env", entry["summary"])
            report_path = Path(str(entry["report_path"]))
            self.assertTrue(report_path.is_file())
            self.assertEqual(report_path.read_text(encoding="utf-8"), "boom\nDATABASE_URL\n")


if __name__ == "__main__":
    unittest.main()
