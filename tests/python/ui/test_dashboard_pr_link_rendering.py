from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.ui.dashboard import pr_link_rendering


class DashboardPrLinkRenderingTests(unittest.TestCase):
    def test_select_dashboard_pr_prefers_open_and_exact_merged_head(self) -> None:
        raw = (
            "["
            '{"url":"https://github.com/example/repo/pull/1","state":"MERGED","mergedAt":"2026-01-01","headRefOid":"abc123"},'
            '{"url":"https://github.com/example/repo/pull/2","state":"OPEN","mergedAt":null,"headRefOid":"def456"}'
            "]"
        )
        merged_only = (
            "["
            '{"url":"https://github.com/example/repo/pull/1","state":"MERGED","mergedAt":"2026-01-01","headRefOid":"abc123"},'
            '{"url":"not-a-url","state":"OPEN","mergedAt":null,"headRefOid":"abc123"}'
            "]"
        )

        self.assertEqual(
            pr_link_rendering.select_dashboard_pr(raw, head_oid="abc123"),
            ("https://github.com/example/repo/pull/2", "active"),
        )
        self.assertEqual(
            pr_link_rendering.select_dashboard_pr(merged_only, head_oid="abc123"),
            ("https://github.com/example/repo/pull/1", "merged"),
        )
        self.assertIsNone(pr_link_rendering.select_dashboard_pr("not json", head_oid="abc123"))

    def test_project_root_prefers_metadata_then_service_component_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            backend = repo / "backend"
            metadata_root = Path(tmpdir) / "metadata-root"
            backend.mkdir(parents=True)
            metadata_root.mkdir()

            metadata_state = RunState(
                run_id="run-1",
                mode="main",
                metadata={"project_roots": {"Main": str(metadata_root)}},
            )
            service_state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(backend),
                    )
                },
            )

            self.assertEqual(
                pr_link_rendering.dashboard_project_root(SimpleNamespace(), state=metadata_state, project="Main"),
                metadata_root,
            )
            self.assertEqual(
                pr_link_rendering.dashboard_project_root(SimpleNamespace(), state=service_state, project="Main"),
                repo,
            )

    def test_lookup_pr_caches_missing_and_positive_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            calls: list[tuple[str, ...]] = []

            class _Runner:
                def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                    _ = cwd, env, timeout
                    command = tuple(str(token) for token in cmd)
                    calls.append(command)
                    if command == ("git", "rev-parse", "--abbrev-ref", "HEAD"):
                        return SimpleNamespace(returncode=0, stdout="feature\n", stderr="")
                    if command == ("git", "rev-parse", "HEAD"):
                        return SimpleNamespace(returncode=0, stdout="abc123\n", stderr="")
                    if command[:4] == ("/usr/bin/gh", "pr", "list", "--head"):
                        return SimpleNamespace(
                            returncode=0,
                            stdout='[{"url":"https://github.com/example/repo/pull/7","state":"OPEN","mergedAt":null,"headRefOid":"abc123"}]',
                            stderr="",
                        )
                    return SimpleNamespace(returncode=1, stdout="", stderr="unsupported")

            runtime = SimpleNamespace(
                env={"ENVCTL_DASHBOARD_PR_CACHE_SECONDS": "30"},
                process_runner=_Runner(),
            )

            with patch.object(pr_link_rendering.shutil, "which", return_value="/usr/bin/gh"):
                first = pr_link_rendering.dashboard_lookup_pr(runtime, project="Main", project_root=repo)
                second = pr_link_rendering.dashboard_lookup_pr(runtime, project="Main", project_root=repo)

            self.assertEqual(first, ("https://github.com/example/repo/pull/7", "active"))
            self.assertEqual(second, first)
            self.assertEqual(sum(1 for call in calls if call[:2] == ("git", "rev-parse")), 4)
            self.assertEqual(sum(1 for call in calls if call[:4] == ("/usr/bin/gh", "pr", "list", "--head")), 1)


if __name__ == "__main__":
    unittest.main()
