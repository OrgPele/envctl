from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime import cli
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.config import load_config


class PrereqPolicyTests(unittest.TestCase):
    def test_main_start_without_requirements_does_not_require_docker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                    "N8N_ENABLE": "false",
                }
            )
            route = parse_route(["start", "--main"], env={})

            def fake_which(binary: str) -> str | None:
                if binary == "git":
                    return "/usr/bin/git"
                if binary == "docker":
                    return None
                return f"/usr/bin/{binary}"

            with (
                patch("envctl_engine.runtime.cli.shutil.which", side_effect=fake_which),
                patch("envctl_engine.runtime.cli._python_dependency_available", return_value=True),
            ):
                ok, reason = cli.check_prereqs(route, config)

            self.assertTrue(ok)
            self.assertIsNone(reason)

    def test_setup_worktrees_requires_docker_using_effective_trees_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                    "N8N_ENABLE": "false",
                }
            )
            route = parse_route(["--setup-worktrees", "feature-a", "1"], env={})

            def fake_which(binary: str) -> str | None:
                if binary == "git":
                    return "/usr/bin/git"
                if binary == "docker":
                    return None
                return f"/usr/bin/{binary}"

            with (
                patch("envctl_engine.runtime.cli.shutil.which", side_effect=fake_which),
                patch("envctl_engine.runtime.cli._python_dependency_available", return_value=True),
            ):
                ok, reason = cli.check_prereqs(route, config)

            self.assertFalse(ok)
            self.assertIn("docker", str(reason))

    def test_start_fails_when_rich_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                    "N8N_ENABLE": "false",
                }
            )
            route = parse_route(["start", "--main"], env={})

            with (
                patch("envctl_engine.runtime.cli.shutil.which", return_value="/usr/bin/fake"),
                patch("envctl_engine.runtime.cli._python_dependency_available", return_value=False),
            ):
                ok, reason = cli.check_prereqs(route, config)

            self.assertFalse(ok)
            self.assertIn("rich", str(reason))
            self.assertIn("python -m pip install -e .", str(reason))


if __name__ == "__main__":
    unittest.main()
