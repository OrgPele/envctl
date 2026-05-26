from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from envctl_engine.planning.plan_agent_launch_support import PlanAgentLaunchResult
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime

from tests.python.runtime.engine_runtime_real_startup_test_support import _EngineRuntimeRealStartupTestCase


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def _repo_with_remote_branch(root: Path) -> Path:
    origin = root / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    repo = root / "repo"
    subprocess.run(["git", "clone", str(origin), str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "test@example.test")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("main\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "main")
    _git(repo, "push", "origin", "HEAD:main")
    _git(repo, "checkout", "-b", "feature/import-launch")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "feature")
    _git(repo, "push", "origin", "HEAD:feature/import-launch")
    _git(repo, "checkout", "main")
    _git(repo, "branch", "-D", "feature/import-launch")
    return repo


class EngineRuntimeImportStartupTests(_EngineRuntimeRealStartupTestCase):
    def test_import_without_launch_flag_does_not_request_plan_agent_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            repo = _repo_with_remote_branch(tmp)
            engine = PythonEngineRuntime(
                self._config(
                    repo,
                    tmp / "runtime",
                    extra={
                        "TREES_STARTUP_ENABLE": "false",
                        "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                        "ENVCTL_WORKTREE_CODE_INTELLIGENCE": "off",
                    },
                ),
                env={"CMUX_WORKSPACE_ID": "workspace:4"},
            )

            with patch("envctl_engine.startup.lifecycle.launch_plan_agent_terminals") as launch:
                code = engine.dispatch(
                    parse_route(
                        ["--import", "feature/import-launch", "--headless", "--no-infra"],
                        env={},
                    )
                )

            assert code == 0
            launch.assert_not_called()

    def test_import_cmux_hands_imported_worktree_to_plan_agent_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            repo = _repo_with_remote_branch(tmp)
            runtime_dir = tmp / "runtime"
            engine = PythonEngineRuntime(
                self._config(
                    repo,
                    runtime_dir,
                    extra={
                        "TREES_STARTUP_ENABLE": "false",
                        "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                        "ENVCTL_WORKTREE_CODE_INTELLIGENCE": "off",
                    },
                ),
                env={"CMUX_WORKSPACE_ID": "workspace:4"},
            )
            launched: list[tuple[str, Path]] = []

            def _fake_launch(_runtime, *, route, created_worktrees):  # noqa: ANN001, ANN202
                assert route.command == "import"
                launched.extend((item.name, item.root) for item in created_worktrees)
                return PlanAgentLaunchResult(status="launched", reason="launched", outcomes=())

            with patch("envctl_engine.startup.lifecycle.launch_plan_agent_terminals", side_effect=_fake_launch):
                code = engine.dispatch(
                    parse_route(
                        ["--import", "feature/import-launch", "--cmux", "--headless", "--no-infra"],
                        env={},
                    )
                )

            assert code == 0
            assert launched == [
                ("imported-feature-import-launch", (repo / "trees" / "imported" / "feature-import-launch").resolve())
            ]

    def test_import_dry_run_previews_without_mutating_or_launching(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            repo = _repo_with_remote_branch(tmp)
            engine = PythonEngineRuntime(
                self._config(
                    repo,
                    tmp / "runtime",
                    extra={
                        "TREES_STARTUP_ENABLE": "false",
                        "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                        "ENVCTL_WORKTREE_CODE_INTELLIGENCE": "off",
                    },
                ),
                env={"CMUX_WORKSPACE_ID": "workspace:4"},
            )
            output = StringIO()

            with (
                patch("envctl_engine.startup.lifecycle.launch_plan_agent_terminals") as launch,
                redirect_stdout(output),
            ):
                code = engine.dispatch(
                    parse_route(
                        ["--import", "feature/import-launch", "--dry-run", "--cmux", "--headless", "--no-infra"],
                        env={},
                    )
                )

            assert code == 0
            launch.assert_not_called()
            worktree = repo / "trees" / "imported" / "feature-import-launch"
            assert not worktree.exists()
            preview = output.getvalue()
            assert "Dry run: no worktrees, git state, services, or AI sessions were modified." in preview
            assert "remote_ref=origin/feature/import-launch" in preview
            assert "local_branch=feature/import-launch" in preview
            assert "project=imported-feature-import-launch" in preview
            assert "action=would create" in preview
