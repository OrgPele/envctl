from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.config import load_config
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime


class ConfigCommandSupportTests(unittest.TestCase):
    def _isolated_git_env(self, tmpdir: str, *, excludes_path: Path | None = None) -> dict[str, str]:
        home = Path(tmpdir) / "home"
        xdg = Path(tmpdir) / "xdg"
        home.mkdir(parents=True, exist_ok=True)
        xdg.mkdir(parents=True, exist_ok=True)
        global_config = Path(tmpdir) / "gitconfig"
        global_config.write_text("", encoding="utf-8")
        env = {
            **os.environ,
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(xdg),
            "GIT_CONFIG_GLOBAL": str(global_config),
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        if excludes_path is not None:
            subprocess.run(
                ["git", "config", "--global", "core.excludesFile", str(excludes_path)],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
        return env

    def _runtime(self, repo: Path, runtime_root: Path) -> PythonEngineRuntime:
        config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime_root)})
        return PythonEngineRuntime(config, env={})

    def test_config_set_saves_repo_local_envctl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            runtime = self._runtime(repo, runtime_root)

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = runtime.dispatch(
                    parse_route(
                        [
                            "config",
                            "--set",
                            "ENVCTL_DEFAULT_MODE=trees",
                            "--set",
                            "BACKEND_DIR=api",
                            "--set",
                            "MAIN_STARTUP_ENABLE=false",
                        ],
                        env={},
                    )
                )

            self.assertEqual(code, 0)
            text = (repo / ".envctl").read_text(encoding="utf-8")
            self.assertIn("ENVCTL_DEFAULT_MODE=trees", text)
            self.assertIn("BACKEND_DIR=api", text)
            self.assertIn("MAIN_STARTUP_ENABLE=false", text)

    def test_config_stdin_json_updates_nested_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            runtime = self._runtime(repo, runtime_root)
            payload = {
                "default_mode": "trees",
                "directories": {"backend": "api", "frontend": "web"},
                "profiles": {
                    "main": {
                        "startup_enabled": False,
                        "backend": True,
                        "frontend": False,
                        "dependencies": {"postgres": True, "redis": True, "supabase": False, "n8n": False},
                    },
                    "trees": {
                        "startup_enabled": True,
                        "backend": True,
                        "frontend": True,
                        "dependencies": {"postgres": True, "redis": True, "supabase": False, "n8n": True},
                    },
                },
            }

            buffer = io.StringIO()
            with patch("sys.stdin", io.StringIO(json.dumps(payload))):
                with redirect_stdout(buffer):
                    code = runtime.dispatch(parse_route(["config", "--stdin-json", "--json"], env={}))

            self.assertEqual(code, 0)
            response = json.loads(buffer.getvalue())
            self.assertEqual(response["config"]["default_mode"], "trees")
            self.assertEqual(response["config"]["directories"]["backend"], "api")
            self.assertEqual(response["config"]["directories"]["frontend"], "web")
            self.assertEqual(response["config"]["profiles"]["main"]["startup_enabled"], False)
            text = (repo / ".envctl").read_text(encoding="utf-8")
            self.assertIn("FRONTEND_DIR=web", text)
            self.assertIn("MAIN_STARTUP_ENABLE=false", text)

    def test_config_json_output_includes_global_ignore_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            excludes_path = Path(tmpdir) / "git" / "ignore"
            excludes_path.parent.mkdir(parents=True, exist_ok=True)
            env = self._isolated_git_env(tmpdir, excludes_path=excludes_path)
            runtime = self._runtime(repo, runtime_root)
            runtime.env.update(env)

            buffer = io.StringIO()
            with patch.dict(os.environ, env, clear=True):
                with redirect_stdout(buffer):
                    code = runtime.dispatch(parse_route(["config", "--set", "ENVCTL_DEFAULT_MODE=trees", "--json"], env={}))

            self.assertEqual(code, 0)
            response = json.loads(buffer.getvalue())
            self.assertTrue(response["ignore_updated"])
            self.assertIsNone(response["ignore_warning"])
            self.assertEqual(response["ignore_status"]["code"], "updated_existing_global_excludes")
            self.assertEqual(response["ignore_status"]["scope"], "git_global_excludes")
            self.assertEqual(response["ignore_status"]["target_path"], str(excludes_path))
            self.assertEqual(
                response["ignore_status"]["managed_patterns"],
                [".envctl*", "MAIN_TASK.md", "OLD_TASK_*.md", "trees/", "trees-*"],
            )

    def test_headless_config_does_not_bootstrap_missing_global_excludes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            env = self._isolated_git_env(tmpdir)
            runtime = self._runtime(repo, runtime_root)
            runtime.env.update(env)

            buffer = io.StringIO()
            with patch.dict(os.environ, env, clear=True):
                with redirect_stdout(buffer):
                    code = runtime.dispatch(parse_route(["config", "--set", "ENVCTL_DEFAULT_MODE=trees", "--json"], env={}))

            self.assertEqual(code, 0)
            response = json.loads(buffer.getvalue())
            self.assertFalse(response["ignore_updated"])
            self.assertEqual(response["ignore_status"]["code"], "missing_global_excludes_configuration")
            self.assertIsNone(response["ignore_status"]["target_path"])

    def test_config_plain_output_warns_when_global_ignore_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            env = self._isolated_git_env(tmpdir)
            runtime = self._runtime(repo, runtime_root)
            runtime.env.update(env)

            buffer = io.StringIO()
            with patch.dict(os.environ, env, clear=True):
                with redirect_stdout(buffer):
                    code = runtime.dispatch(parse_route(["config", "--set", "ENVCTL_DEFAULT_MODE=trees"], env={}))

            self.assertEqual(code, 0)
            output = buffer.getvalue()
            self.assertIn("Saved startup config:", output)
            self.assertIn("Config saved. Restart required for running services to adopt changes.", output)
            self.assertIn("global excludes", output.lower())
            self.assertNotIn(".gitignore on save", output)


if __name__ == "__main__":
    unittest.main()
