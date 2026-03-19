from __future__ import annotations

import json
import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
import sys
from io import StringIO
from contextlib import redirect_stderr, redirect_stdout

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime import cli


class CommandExitCodeTests(unittest.TestCase):
    def test_help_returns_zero(self) -> None:
        with (
            patch("envctl_engine.runtime.cli.check_prereqs", return_value=(True, None)),
            patch("envctl_engine.runtime.cli.ensure_local_config", return_value=self._bootstrap_result()),
        ):
            code = cli.run(["--help"], env={})
        self.assertEqual(code, 0)

    def test_invalid_typo_alias_is_actionable_failure(self) -> None:
        stderr = StringIO()
        with (
            redirect_stderr(stderr),
            patch("envctl_engine.runtime.cli.check_prereqs", return_value=(True, None)),
            patch("envctl_engine.runtime.cli.ensure_local_config", return_value=self._bootstrap_result()),
        ):
            code = cli.run(["tees=true"], env={})
        self.assertEqual(code, 1)
        self.assertIn("Unknown option", stderr.getvalue())

    def test_shell_nonzero_is_mapped_to_actionable_failure(self) -> None:
        with (
            patch("envctl_engine.runtime.cli.check_prereqs", return_value=(True, None)),
            patch("envctl_engine.runtime.cli.ensure_local_config", return_value=self._bootstrap_result()),
        ):
            code = cli.run(["--resume"], env={}, shell_runner=lambda _argv: 7)
        self.assertEqual(code, 1)

    def test_keyboard_interrupt_returns_controlled_quit_code(self) -> None:
        def interrupted(_argv):
            raise KeyboardInterrupt

        with (
            patch("envctl_engine.runtime.cli.check_prereqs", return_value=(True, None)),
            patch("envctl_engine.runtime.cli.ensure_local_config", return_value=self._bootstrap_result()),
        ):
            code = cli.run(["--resume"], env={}, shell_runner=interrupted)
        self.assertEqual(code, 2)

    def test_python_dispatcher_result_is_returned(self) -> None:
        with (
            patch("envctl_engine.runtime.cli.check_prereqs", return_value=(True, None)),
            patch("envctl_engine.runtime.cli.ensure_local_config", return_value=self._bootstrap_result()),
        ):
            code = cli.run(
                ["--plan"],
                env={},
                shell_runner=lambda _argv: self.fail("shell runner should not be used"),
                dispatcher=lambda _route, _config: 0,
            )
        self.assertEqual(code, 0)

    def test_cli_route_uses_default_mode_from_repo_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".envctl").write_text("ENVCTL_DEFAULT_MODE=trees\n", encoding="utf-8")

            seen: dict[str, object] = {}

            def dispatcher(route, _config):  # noqa: ANN001
                seen["mode"] = route.mode
                seen["command"] = route.command
                return 0

            with patch("envctl_engine.runtime.cli.check_prereqs", return_value=(True, None)):
                code = cli.run(
                    [],
                    env={
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                    },
                    dispatcher=dispatcher,
                )

            self.assertEqual(code, 0)
            self.assertEqual(seen.get("command"), "start")
            self.assertEqual(seen.get("mode"), "trees")

    def test_start_command_fails_when_rich_dependency_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            env = {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(runtime),
                "POSTGRES_MAIN_ENABLE": "false",
                "REDIS_ENABLE": "false",
                "SUPABASE_MAIN_ENABLE": "false",
                "N8N_ENABLE": "false",
            }
            (repo / ".envctl").write_text("ENVCTL_DEFAULT_MODE=main\n", encoding="utf-8")
            stderr = StringIO()
            with (
                redirect_stderr(stderr),
                patch("envctl_engine.runtime.cli._python_dependency_available", return_value=False),
            ):
                code = cli.run(["start"], env=env, dispatcher=lambda _route, _config: 0)
            self.assertEqual(code, 1)
            self.assertIn("Missing required Python packages", stderr.getvalue())

    def test_missing_envctl_bootstraps_before_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            seen: dict[str, object] = {}

            def dispatcher(route, config):  # noqa: ANN001
                seen["command"] = route.command
                seen["config_exists"] = config.config_file_exists
                return 0

            def bootstrap(*, base_dir, env, emit=None):  # noqa: ANN001
                _ = emit
                (Path(base_dir) / ".envctl").write_text("ENVCTL_DEFAULT_MODE=main\n", encoding="utf-8")
                return type("BootstrapResult", (), {"changed": True, "message": "saved"})()

            with (
                patch("envctl_engine.runtime.cli.ensure_local_config", side_effect=bootstrap),
                patch("envctl_engine.runtime.cli.check_prereqs", return_value=(True, None)),
            ):
                code = cli.run(
                    ["start"],
                    env={
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                    },
                    dispatcher=dispatcher,
                )

            self.assertEqual(code, 0)
            self.assertEqual(seen.get("command"), "start")
            self.assertTrue(seen.get("config_exists"))

    def test_missing_envctl_allows_headless_config_set_without_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            with patch("envctl_engine.runtime.cli.ensure_local_config") as bootstrap:
                code = cli.run(
                    ["config", "--set", "ENVCTL_DEFAULT_MODE=trees", "--set", "BACKEND_DIR=api", "--headless"],
                    env={
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                    },
                )

            self.assertEqual(code, 0)
            bootstrap.assert_not_called()
            config_text = (repo / ".envctl").read_text(encoding="utf-8")
            self.assertIn("ENVCTL_DEFAULT_MODE=trees", config_text)
            self.assertIn("BACKEND_DIR=api", config_text)

    def test_show_config_skips_bootstrap_when_envctl_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            with patch("envctl_engine.runtime.cli.ensure_local_config") as bootstrap:
                code = cli.run(
                    ["--show-config", "--json"],
                    env={
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                    },
                )

            self.assertEqual(code, 0)
            bootstrap.assert_not_called()

    def test_plan_skips_bootstrap_when_envctl_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            with patch("envctl_engine.runtime.cli.ensure_local_config") as bootstrap:
                code = cli.run(
                    ["--plan", "feature-a"],
                    env={
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                    },
                    dispatcher=lambda _route, _config: 0,
                )

            self.assertEqual(code, 0)
            bootstrap.assert_not_called()

    def test_resume_skips_bootstrap_when_envctl_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            with patch("envctl_engine.runtime.cli.ensure_local_config") as bootstrap:
                code = cli.run(
                    ["--resume"],
                    env={
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                    },
                    dispatcher=lambda _route, _config: 0,
                )

            self.assertEqual(code, 0)
            bootstrap.assert_not_called()

    def test_install_prompts_skips_bootstrap_when_envctl_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            home = Path(tmpdir) / "home"
            repo.mkdir(parents=True, exist_ok=True)

            with patch("envctl_engine.runtime.cli.ensure_local_config") as bootstrap:
                code = cli.run(
                    ["install-prompts", "--cli", "codex", "--dry-run"],
                    env={
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "HOME": str(home),
                    },
                )

            self.assertEqual(code, 0)
            bootstrap.assert_not_called()

    def test_codex_tmux_skips_bootstrap_when_envctl_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)

            with patch("envctl_engine.runtime.cli.ensure_local_config") as bootstrap:
                code = cli.run(
                    ["codex-tmux", "--dry-run"],
                    env={
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                    },
                    dispatcher=lambda _route, _config: 0,
                )

            self.assertEqual(code, 0)
            bootstrap.assert_not_called()

    def test_install_prompts_overwrite_without_approval_returns_failure_and_skips_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            home = Path(tmpdir) / "home"
            target = home / ".codex" / "prompts" / "implement_task.md"
            repo.mkdir(parents=True, exist_ok=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("old prompt\n", encoding="utf-8")
            stdout = StringIO()

            with (
                patch("envctl_engine.runtime.cli.ensure_local_config") as bootstrap,
                patch("sys.stdin.isatty", return_value=False),
                patch("sys.stdout.isatty", return_value=False),
                redirect_stdout(stdout),
            ):
                code = cli.run(
                    ["install-prompts", "--cli", "codex", "--json"],
                    env={
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "HOME": str(home),
                    },
                )

            self.assertEqual(code, 1)
            bootstrap.assert_not_called()
            self.assertEqual(target.read_text(encoding="utf-8"), "old prompt\n")
            self.assertIn("Overwrite approval required", stdout.getvalue())

    def test_install_prompts_yes_overwrite_returns_zero_and_skips_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            home = Path(tmpdir) / "home"
            target = home / ".codex" / "prompts" / "implement_task.md"
            repo.mkdir(parents=True, exist_ok=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("old prompt\n", encoding="utf-8")

            with patch("envctl_engine.runtime.cli.ensure_local_config") as bootstrap:
                code = cli.run(
                    ["install-prompts", "--cli", "codex", "--yes"],
                    env={
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "HOME": str(home),
                    },
                )

            self.assertEqual(code, 0)
            bootstrap.assert_not_called()
            self.assertTrue(target.read_text(encoding="utf-8").startswith("You are implementing real code, end-to-end."))

    def test_install_prompts_cli_run_writes_then_overwrites_without_backup_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            home = Path(tmpdir) / "home"
            target = home / ".codex" / "prompts" / "implement_task.md"
            repo.mkdir(parents=True, exist_ok=True)
            first_stdout = StringIO()
            second_stdout = StringIO()

            with (
                patch("envctl_engine.runtime.cli.ensure_local_config") as bootstrap,
            ):
                with redirect_stdout(first_stdout):
                    first_code = cli.run(
                        ["install-prompts", "--cli", "codex", "--json"],
                        env={
                            "RUN_REPO_ROOT": str(repo),
                            "RUN_SH_RUNTIME_DIR": str(runtime),
                            "HOME": str(home),
                        },
                    )
                with redirect_stdout(second_stdout):
                    second_code = cli.run(
                        ["install-prompts", "--cli", "codex", "--yes", "--json"],
                        env={
                            "RUN_REPO_ROOT": str(repo),
                            "RUN_SH_RUNTIME_DIR": str(runtime),
                            "HOME": str(home),
                        },
                    )

            self.assertEqual(first_code, 0)
            self.assertEqual(second_code, 0)
            bootstrap.assert_not_called()
            first_payload = json.loads(first_stdout.getvalue())
            second_payload = json.loads(second_stdout.getvalue())
            self.assertEqual(first_payload["preset"], "all")
            self.assertEqual(second_payload["preset"], "all")
            self.assertTrue(all(item["status"] == "written" for item in first_payload["results"]))
            self.assertTrue(all(item["status"] == "overwritten" for item in second_payload["results"]))
            self.assertTrue(target.exists())
            self.assertTrue((target.parent / "review_worktree_imp.md").exists())
            self.assertEqual(list(home.rglob("*.bak-*")), [])

    def test_install_prompts_cli_run_installs_review_worktree_prompt_with_origin_review_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            home = Path(tmpdir) / "home"
            target = home / ".codex" / "prompts" / "review_worktree_imp.md"
            repo.mkdir(parents=True, exist_ok=True)

            with patch("envctl_engine.runtime.cli.ensure_local_config") as bootstrap:
                code = cli.run(
                    ["install-prompts", "--cli", "codex", "--preset", "review_worktree_imp", "--json"],
                    env={
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "HOME": str(home),
                    },
                )

            self.assertEqual(code, 0)
            bootstrap.assert_not_called()
            written = target.read_text(encoding="utf-8")
            self.assertIn("current local repo directory is the unedited baseline", written)
            self.assertIn("defaults to the worktree created from the current plan file", written)
            self.assertIn("Launch arguments: `$ARGUMENTS`", written)
            self.assertIn("Treat only the first path-like token as the explicit worktree override", written)
            self.assertIn("use that bundle as the primary review guide", written)
            self.assertIn("original plan file", written)
            self.assertNotIn("MAIN_TASK.md", written)
            self.assertNotIn("OLD_TASK_", written)
            self.assertIn("read-only", written)
            self.assertIn("findings-first", written)

    def test_doctor_repo_resolves_root_without_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            nested = repo / "sub" / "dir"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            nested.mkdir(parents=True, exist_ok=True)
            seen: dict[str, object] = {}

            def dispatcher(_route, config):  # noqa: ANN001
                seen["base_dir"] = config.base_dir
                return 0

            with patch("envctl_engine.runtime.cli.ensure_local_config") as bootstrap:
                code = cli.run(
                    ["doctor", "--repo", str(nested)],
                    env={
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                    },
                    dispatcher=dispatcher,
                )

            self.assertEqual(code, 0)
            bootstrap.assert_not_called()
            self.assertEqual(seen.get("base_dir"), repo.resolve())

    def test_cwd_inside_repo_resolves_repo_root_for_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            nested = repo / "sub" / "dir"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            nested.mkdir(parents=True, exist_ok=True)
            seen: dict[str, object] = {}

            def dispatcher(_route, config):  # noqa: ANN001
                seen["base_dir"] = config.base_dir
                return 0

            with patch("envctl_engine.runtime.cli.Path.cwd", return_value=nested.resolve()):
                code = cli.run(
                    ["--help"],
                    env={
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                    },
                    dispatcher=dispatcher,
                )

            self.assertEqual(code, 0)
            self.assertEqual(seen.get("base_dir"), repo.resolve())

    def test_installed_cli_install_subcommand_supports_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            shell_file = Path(tmpdir) / ".zshrc"
            shell_file.write_text("# existing\n", encoding="utf-8")
            out = StringIO()
            with patch.object(sys, "argv", [str(Path(tmpdir) / "bin" / "envctl")]), redirect_stdout(out):
                code = cli.run(["install", "--shell-file", str(shell_file), "--dry-run"], env={})
            self.assertEqual(code, 0)
            self.assertIn("# >>> envctl PATH >>>", out.getvalue())
            self.assertEqual(shell_file.read_text(encoding="utf-8"), "# existing\n")

    def test_installed_cli_uninstall_removes_path_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            shell_file = Path(tmpdir) / ".zshrc"
            shell_file.write_text(
                '# >>> envctl PATH >>>\nexport PATH="/tmp/bin:$PATH"\n# <<< envctl PATH <<<\n',
                encoding="utf-8",
            )
            with patch.object(sys, "argv", [str(Path(tmpdir) / "bin" / "envctl")]):
                code = cli.run(["uninstall", "--shell-file", str(shell_file)], env={})
            self.assertEqual(code, 0)
            self.assertEqual(shell_file.read_text(encoding="utf-8"), "")

    def test_default_command_opens_disabled_dashboard_flow_when_startup_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".envctl").write_text("MAIN_STARTUP_ENABLE=false\n", encoding="utf-8")
            seen: dict[str, object] = {}

            def dispatcher(route, _config):  # noqa: ANN001
                seen["command"] = route.command
                seen["mode"] = route.mode
                return 0

            with patch("envctl_engine.runtime.cli.check_prereqs", return_value=(True, None)):
                code = cli.run(
                    [],
                    env={
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                    },
                    dispatcher=dispatcher,
                )

            self.assertEqual(code, 0)
            self.assertEqual(seen.get("command"), "start")
            self.assertEqual(seen.get("mode"), "main")

    def test_run_restores_terminal_state_in_finally_on_success(self) -> None:
        with (
            patch("envctl_engine.runtime.cli.check_prereqs", return_value=(True, None)),
            patch("envctl_engine.runtime.cli.ensure_local_config", return_value=self._bootstrap_result()),
            patch("envctl_engine.runtime.cli._best_effort_restore_terminal_state") as restore_mock,
        ):
            code = cli.run(["--help"], env={})
        self.assertEqual(code, 0)
        restore_mock.assert_called_once()

    def test_run_restores_terminal_state_in_finally_on_route_error(self) -> None:
        with (
            redirect_stderr(StringIO()),
            patch("envctl_engine.runtime.cli._best_effort_restore_terminal_state") as restore_mock,
        ):
            code = cli.run(["tees=true"], env={})
        self.assertEqual(code, 1)
        restore_mock.assert_called_once()

    @staticmethod
    def _bootstrap_result():
        return type("BootstrapResult", (), {"changed": False, "message": None})()


if __name__ == "__main__":
    unittest.main()
