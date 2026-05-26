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
from envctl_engine.config.git_global_ignore import GlobalIgnoreStatus
from envctl_engine.config.persistence import ConfigSaveResult
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.test_output.parser_base import strip_ansi


class _TtyStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


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
                            "--set",
                            "ENVCTL_UI_VISUAL_HOST=192.0.2.42",
                            "--set",
                            "ENVCTL_PUBLIC_HOST=203.0.113.10",
                        ],
                        env={},
                    )
                )

            self.assertEqual(code, 0)
            text = (repo / ".envctl").read_text(encoding="utf-8")
            self.assertIn("ENVCTL_DEFAULT_MODE=trees", text)
            self.assertIn("BACKEND_DIR=api", text)
            self.assertIn("MAIN_STARTUP_ENABLE=false", text)
            self.assertIn("ENVCTL_UI_VISUAL_HOST=192.0.2.42", text)
            self.assertIn("ENVCTL_PUBLIC_HOST=203.0.113.10", text)

    def test_config_set_from_managed_linked_worktree_saves_main_repo_envctl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime_root = root / "runtime"
            gitdir = repo / ".git" / "worktrees" / "feature-a-1"
            gitdir.mkdir(parents=True, exist_ok=True)
            worktree.mkdir(parents=True, exist_ok=True)
            (repo / ".git").mkdir(exist_ok=True)
            (repo / ".envctl").write_text("ENVCTL_DEFAULT_MODE=main\n", encoding="utf-8")
            (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
            runtime = self._runtime(worktree, runtime_root)

            with redirect_stdout(io.StringIO()):
                code = runtime.dispatch(
                    parse_route(
                        [
                            "config",
                            "--set",
                            "ENVCTL_DEFAULT_MODE=trees",
                            "--set",
                            "BACKEND_DIR=api",
                        ],
                        env={},
                    )
                )

            self.assertEqual(code, 0)
            self.assertEqual(runtime.config.base_dir, repo.resolve())
            main_text = (repo / ".envctl").read_text(encoding="utf-8")
            self.assertIn("ENVCTL_DEFAULT_MODE=trees", main_text)
            self.assertIn("BACKEND_DIR=api", main_text)
            self.assertFalse((worktree / ".envctl").exists())

    def test_config_command_emits_progress_events_for_interactive_spinner_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            runtime = self._runtime(repo, runtime_root)

            with redirect_stdout(io.StringIO()):
                code = runtime.dispatch(parse_route(["config", "--set", "ENVCTL_DEFAULT_MODE=trees"], env={}))

            self.assertEqual(code, 0)
            start_events = [event for event in runtime.events if event.get("event") == "config.command.start"]
            finish_events = [event for event in runtime.events if event.get("event") == "config.command.finish"]
            self.assertTrue(start_events)
            self.assertTrue(finish_events)
            self.assertEqual(finish_events[-1].get("code"), 0)

    def test_config_stdin_json_updates_nested_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            runtime = self._runtime(repo, runtime_root)
            payload = {
                "default_mode": "trees",
                "network": {"public_host": "203.0.113.20"},
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
            self.assertEqual(response["config"]["network"]["public_host"], "203.0.113.20")
            text = (repo / ".envctl").read_text(encoding="utf-8")
            self.assertIn("FRONTEND_DIR=web", text)
            self.assertIn("MAIN_STARTUP_ENABLE=false", text)
            self.assertIn("ENVCTL_PUBLIC_HOST=203.0.113.20", text)

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
            self.assertEqual(Path(response["agent_instructions"]["path"]), (repo / "AGENTS.md").resolve())
            self.assertTrue(response["agent_instructions"]["updated"])
            self.assertIsNone(response["agent_instructions"]["warning"])

    def test_headless_config_bootstraps_missing_global_excludes(self) -> None:
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
            self.assertTrue(response["ignore_updated"])
            self.assertIsNone(response["ignore_warning"])
            self.assertEqual(response["ignore_status"]["code"], "configured_global_excludes")
            excludes_path = Path(response["ignore_status"]["target_path"])
            self.assertEqual(excludes_path, Path(tmpdir) / "home" / ".gitignore_global")
            self.assertEqual(
                response["ignore_status"]["managed_patterns"],
                [".envctl*", "MAIN_TASK.md", "OLD_TASK_*.md", "trees/", "trees-*"],
            )
            self.assertIn("MAIN_TASK.md", excludes_path.read_text(encoding="utf-8"))

    def test_config_plain_output_reports_configured_global_ignore_when_missing(self) -> None:
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
            self.assertIn(f"Configured Git global excludes at {Path(tmpdir) / 'home' / '.gitignore_global'}.", output)
            self.assertIn("Updated agent instructions:", output)
            self.assertIn(str((repo / "AGENTS.md").resolve()), output)
            self.assertNotIn(".gitignore on save", output)
            self.assertNotIn("not configured", output.lower())

    def test_config_plain_output_reports_updated_global_ignore_target(self) -> None:
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
                    code = runtime.dispatch(parse_route(["config", "--set", "ENVCTL_DEFAULT_MODE=trees"], env={}))

            self.assertEqual(code, 0)
            output = buffer.getvalue()
            self.assertIn("Saved startup config:", output)
            self.assertIn(f"Updated Git global excludes at {excludes_path}.", output)

    def test_config_plain_output_hyperlinks_saved_path_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            runtime = self._runtime(repo, runtime_root)
            runtime.env["ENVCTL_UI_HYPERLINK_MODE"] = "on"

            buffer = _TtyStringIO()
            with redirect_stdout(buffer):
                code = runtime.dispatch(parse_route(["config", "--set", "ENVCTL_DEFAULT_MODE=trees"], env={}))

            self.assertEqual(code, 0)
            self.assertIn("\x1b]8;;file://", buffer.getvalue())
            self.assertIn(str(repo / ".envctl"), strip_ansi(buffer.getvalue()))

    def test_config_plain_output_hyperlinks_ignore_warning_paths_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            runtime = self._runtime(repo, runtime_root)
            runtime.env["ENVCTL_UI_HYPERLINK_MODE"] = "on"
            excludes_path = Path(tmpdir) / "home" / ".gitignore_global"
            warning = f"Could not update global git excludes at {excludes_path}: denied"
            fake_save_result = ConfigSaveResult(
                path=repo / ".envctl",
                ignore_updated=False,
                ignore_warning=warning,
                ignore_status=GlobalIgnoreStatus(
                    code="global_excludes_write_failed",
                    updated=False,
                    scope="git_global_excludes",
                    target_path=excludes_path,
                    managed_patterns=(".envctl*",),
                    warning=warning,
                ),
            )

            buffer = _TtyStringIO()
            with (
                redirect_stdout(buffer),
                patch("envctl_engine.config.command_support.save_local_config", return_value=fake_save_result),
            ):
                code = runtime.dispatch(parse_route(["config", "--set", "ENVCTL_DEFAULT_MODE=trees"], env={}))

            self.assertEqual(code, 0)
            self.assertGreaterEqual(buffer.getvalue().count("\x1b]8;;file://"), 2)
            self.assertNotIn(warning, buffer.getvalue())
            plain = strip_ansi(buffer.getvalue())
            self.assertIn(str(repo / ".envctl"), plain)
            self.assertIn(warning, plain)


if __name__ == "__main__":
    unittest.main()
