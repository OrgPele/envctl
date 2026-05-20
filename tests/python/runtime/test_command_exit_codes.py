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
from envctl_engine.runtime.prompt_install_support import _target_path


class CommandExitCodeTests(unittest.TestCase):
    def _codex_target(self, *, home: Path, preset: str) -> Path:
        return _target_path(cli_name="codex", preset=preset, home=home, env={"HOME": str(home)})

    def _codex_skill_target(self, *, home: Path, preset: str) -> Path:
        skill_name = f"envctl-{preset.replace('_', '-')}"
        if preset == "review_task_imp":
            skill_name = "envctl-review-task"
        if preset == "review_worktree_imp":
            skill_name = "envctl-review-worktree"
        return home / ".codex" / "skills" / skill_name / "SKILL.md"

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

    def test_managed_linked_worktree_dispatch_keeps_execution_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = root / "runtime"
            repo = root / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            gitdir = repo / ".git" / "worktrees" / "feature-a-1"
            gitdir.mkdir(parents=True, exist_ok=True)
            worktree.mkdir(parents=True, exist_ok=True)
            (worktree / "api").mkdir(parents=True, exist_ok=True)
            (worktree / "api" / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
            (repo / ".git").mkdir(exist_ok=True)
            (repo / ".envctl").write_text("ENVCTL_DEFAULT_MODE=main\n", encoding="utf-8")
            (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")

            seen: dict[str, object] = {}

            def dispatcher(_route, config):  # noqa: ANN001
                seen["base_dir"] = config.base_dir
                seen["execution_root"] = config.execution_root
                seen["backend_dir_name"] = config.backend_dir_name
                return 0

            code = cli.run(
                ["--show-config"],
                env={"RUN_REPO_ROOT": str(worktree), "RUN_SH_RUNTIME_DIR": str(runtime)},
                dispatcher=dispatcher,
            )

        self.assertEqual(code, 0)
        self.assertEqual(seen.get("base_dir"), repo.resolve())
        self.assertEqual(seen.get("execution_root"), worktree.resolve())
        self.assertEqual(seen.get("backend_dir_name"), "api")

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

    def test_start_command_fails_with_source_checkout_runtime_bootstrap_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            launcher_root = Path(tmpdir) / "envctl-source"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (launcher_root / "python").mkdir(parents=True, exist_ok=True)
            (launcher_root / "python" / "requirements.txt").write_text(
                "prompt_toolkit>=3.0\npsutil>=5.9\nrich>=13.7\ntextual>=0.58\n",
                encoding="utf-8",
            )
            env = {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(runtime),
                "ENVCTL_ROOT_DIR": str(launcher_root),
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
            self.assertIn("Missing required envctl runtime Python packages", stderr.getvalue())
            self.assertIn("python/requirements.txt", stderr.getvalue())
            self.assertNotIn(".venv/bin/python -m pip install -e '.[dev]'", stderr.getvalue())

    def test_start_command_fails_with_installed_command_repair_guidance(self) -> None:
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
            self.assertIn("Missing required envctl runtime Python packages", stderr.getvalue())
            self.assertIn("pipx reinstall envctl", stderr.getvalue())
            self.assertNotIn("python/requirements.txt", stderr.getvalue())
            self.assertNotIn(".venv/bin/python -m pip install -e '.[dev]'", stderr.getvalue())

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

    def test_explicit_repo_arg_overrides_inherited_run_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            requested_repo = tmp_path / "requested-repo"
            inherited_repo = tmp_path / "inherited-repo"
            runtime = tmp_path / "runtime"
            for repo in (requested_repo, inherited_repo):
                (repo / ".git").mkdir(parents=True, exist_ok=True)
            (requested_repo / ".envctl").write_text("ENVCTL_DEFAULT_MODE=trees\n", encoding="utf-8")

            seen: dict[str, object] = {}

            def dispatcher(route, config):  # noqa: ANN001
                seen["mode"] = route.mode
                seen["base_dir"] = config.base_dir
                seen["config_exists"] = config.config_file_exists
                return 0

            with patch("envctl_engine.runtime.cli.check_prereqs", return_value=(True, None)):
                code = cli.run(
                    ["--repo", str(requested_repo), "start"],
                    env={
                        "RUN_REPO_ROOT": str(inherited_repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                    },
                    dispatcher=dispatcher,
                )

            self.assertEqual(code, 0)
            self.assertEqual(seen.get("mode"), "trees")
            self.assertEqual(seen.get("base_dir"), requested_repo.resolve())
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

    def test_supabase_user_list_json_skips_bootstrap_and_reports_missing_running_supabase(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            stdout = StringIO()

            with (
                patch("envctl_engine.runtime.cli.ensure_local_config") as bootstrap,
                patch("envctl_engine.runtime.cli.check_prereqs", return_value=(True, None)),
                redirect_stdout(stdout),
            ):
                code = cli.run(
                    ["supabase-user", "list", "--json"],
                    env={
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                    },
                )

            self.assertEqual(code, 1)
            bootstrap.assert_not_called()
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["command"], "list")
            self.assertEqual(payload["status"], "error")
            self.assertIn("SUPABASE_URL", payload["error"])

    def test_supabase_user_delete_requires_confirmation_without_headless_yes_or_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            stderr = StringIO()

            with (
                patch("envctl_engine.runtime.cli.check_prereqs", return_value=(True, None)),
                redirect_stderr(stderr),
            ):
                code = cli.run(
                    ["supabase-user", "delete", "e2e@example.test"],
                    env={
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "SUPABASE_URL": "http://localhost:54321",
                        "SUPABASE_SERVICE_ROLE_KEY": "service-role-secret",
                    },
                )

            self.assertEqual(code, 1)
            self.assertIn("requires --yes or --headless", stderr.getvalue())

    def test_install_prompts_overwrite_without_approval_returns_failure_and_skips_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            home = Path(tmpdir) / "home"
            target = self._codex_skill_target(home=home, preset="implement_task")
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
            target = self._codex_skill_target(home=home, preset="implement_task")
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
            self.assertIn("You are implementing real code, end-to-end.", target.read_text(encoding="utf-8"))

    def test_install_prompts_cli_run_writes_then_overwrites_without_backup_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            home = Path(tmpdir) / "home"
            target = self._codex_skill_target(home=home, preset="implement_task")
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
            self.assertTrue(self._codex_skill_target(home=home, preset="review_worktree_imp").exists())
            self.assertEqual(list(home.rglob("*.bak-*")), [])

    def test_install_prompts_cli_run_installs_review_worktree_prompt_with_origin_review_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            home = Path(tmpdir) / "home"
            target = self._codex_skill_target(home=home, preset="review_worktree_imp")
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
            self.assertIn("Launch arguments:\nadditional user instructions supplied with the invoking prompt", written)
            self.assertIn("Treat only the first path-like token as the explicit worktree override", written)
            self.assertIn("use that bundle as the primary review guide", written)
            self.assertIn("original plan file", written)
            self.assertNotIn("MAIN_TASK.md", written)
            self.assertNotIn("OLD_TASK_", written)
            self.assertIn("read-only", written)
            self.assertIn("findings-first", written)

    def test_install_prompts_cli_run_installs_opencode_review_prompt_with_original_plan_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            home = Path(tmpdir) / "home"
            target = home / ".config" / "opencode" / "commands" / "review_task_imp.md"
            repo.mkdir(parents=True, exist_ok=True)

            with patch("envctl_engine.runtime.cli.ensure_local_config") as bootstrap:
                code = cli.run(
                    ["install-prompts", "--cli", "opencode", "--preset", "review_task_imp", "--json"],
                    env={
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "HOME": str(home),
                    },
                )

            self.assertEqual(code, 0)
            bootstrap.assert_not_called()
            written = target.read_text(encoding="utf-8")
            self.assertIn("Authoritative source of truth: the original plan file that created this worktree.", written)
            self.assertIn(".envctl-state/worktree-provenance.json", written)
            self.assertIn("If no original plan file can be resolved, stop and report exactly what was missing", written)
            self.assertNotIn("Authoritative source of truth: `MAIN_TASK.md`.", written)
            self.assertNotIn("Verify functionality matches MAIN_TASK.md exactly", written)

    def test_install_prompts_cli_run_installs_create_plan_auto_codex_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            home = Path(tmpdir) / "home"
            target = self._codex_skill_target(home=home, preset="create_plan_auto_codex")
            repo.mkdir(parents=True, exist_ok=True)
            stdout = StringIO()

            with patch("envctl_engine.runtime.cli.ensure_local_config") as bootstrap, redirect_stdout(stdout):
                code = cli.run(
                    ["install-prompts", "--cli", "codex", "--preset", "create_plan_auto_codex", "--json"],
                    env={
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "HOME": str(home),
                    },
                )

            self.assertEqual(code, 0)
            bootstrap.assert_not_called()
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["skill_results"][0]["path"], str(target))
            self.assertTrue(target.exists())
            written = target.read_text(encoding="utf-8")
            self.assertIn("$envctl-create-plan-auto-codex", written)
            self.assertIn("ENVCTL_PLAN_AGENT_CODEX_CYCLES=<recommended_codex_cycles>", written)
            self.assertIn("exactly one integer from `0` through `8`", written)
            self.assertNotIn("ENVCTL_PLAN_AGENT_CODEX_CYCLES=4 envctl --plan <category>/<slug>", written)
            self.assertIn("--new-session", written)

    def test_install_prompts_cli_run_installs_create_plan_auto_opencode_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            home = Path(tmpdir) / "home"
            target = home / ".config" / "opencode" / "commands" / "create_plan_auto_opencode.md"
            repo.mkdir(parents=True, exist_ok=True)
            stdout = StringIO()

            with patch("envctl_engine.runtime.cli.ensure_local_config") as bootstrap, redirect_stdout(stdout):
                code = cli.run(
                    ["install-prompts", "--cli", "opencode", "--preset", "create_plan_auto_opencode", "--json"],
                    env={
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "HOME": str(home),
                    },
                )

            self.assertEqual(code, 0)
            bootstrap.assert_not_called()
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["results"][0]["path"], str(target))
            self.assertTrue(target.exists())
            written = target.read_text(encoding="utf-8")
            self.assertIn(
                "envctl --plan <category>/<slug> --tmux --opencode --entire-system "
                "--headless --new-session",
                written,
            )
            self.assertIn("Codex cycle settings are intentionally ignored for this surface", written)

    def test_install_prompts_cli_run_keeps_with_codex_skills_as_compatibility_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            home = Path(tmpdir) / "home"
            target = self._codex_skill_target(home=home, preset="ship_release")
            repo.mkdir(parents=True, exist_ok=True)
            stdout = StringIO()

            with patch("envctl_engine.runtime.cli.ensure_local_config") as bootstrap, redirect_stdout(stdout):
                code = cli.run(
                    [
                        "install-prompts",
                        "--cli",
                        "codex",
                        "--preset",
                        "ship_release",
                        "--with-codex-skills",
                        "--json",
                    ],
                    env={
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "HOME": str(home),
                    },
                )

            self.assertEqual(code, 0)
            bootstrap.assert_not_called()
            payload = json.loads(stdout.getvalue())
            self.assertIn("skill_results", payload)
            self.assertEqual(payload["skill_results"][0]["path"], str(target))
            self.assertTrue(target.exists())

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

    def test_explicit_repo_overrides_inherited_run_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            inherited_repo = Path(tmpdir) / "inherited-repo"
            explicit_repo = Path(tmpdir) / "explicit-repo"
            runtime = Path(tmpdir) / "runtime"
            nested = explicit_repo / "sub" / "dir"
            (inherited_repo / ".git").mkdir(parents=True, exist_ok=True)
            (explicit_repo / ".git").mkdir(parents=True, exist_ok=True)
            nested.mkdir(parents=True, exist_ok=True)
            seen: dict[str, object] = {}

            def dispatcher(_route, config):  # noqa: ANN001
                seen["base_dir"] = config.base_dir
                return 0

            with patch("envctl_engine.runtime.cli.ensure_local_config") as bootstrap:
                code = cli.run(
                    ["doctor", "--repo", str(nested)],
                    env={
                        "RUN_REPO_ROOT": str(inherited_repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                    },
                    dispatcher=dispatcher,
                )

            self.assertEqual(code, 0)
            bootstrap.assert_not_called()
            self.assertEqual(seen.get("base_dir"), explicit_repo.resolve())

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


    def test_cli_health_missing_project_json_fails_closed(self) -> None:
        state = self._runtime_smoke_state()
        stdout = StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            repo, env, dispatcher = self._runtime_smoke_dispatcher(Path(tmpdir), state)
            with patch("envctl_engine.runtime.cli.check_prereqs", return_value=(True, None)), redirect_stdout(stdout):
                code = cli.run(["health", "--project", "missing", "--json"], env=env, dispatcher=dispatcher)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "requested_project_not_running")
        self.assertEqual(payload["requested_project"], "missing")
        self.assertEqual(payload["active_projects"], ["Alpha"])

    def test_cli_show_state_missing_project_json_fails_closed(self) -> None:
        state = self._runtime_smoke_state()
        stdout = StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            repo, env, dispatcher = self._runtime_smoke_dispatcher(Path(tmpdir), state)
            with patch("envctl_engine.runtime.cli.check_prereqs", return_value=(True, None)), redirect_stdout(stdout):
                code = cli.run(["show-state", "--project", "missing", "--json"], env=env, dispatcher=dispatcher)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "requested_project_not_running")
        self.assertNotIn("state", payload)

    def test_cli_endpoints_active_project_json_reports_projected_urls(self) -> None:
        state = self._runtime_smoke_state()
        stdout = StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            repo, env, dispatcher = self._runtime_smoke_dispatcher(Path(tmpdir), state)
            with patch("envctl_engine.runtime.cli.check_prereqs", return_value=(True, None)), redirect_stdout(stdout):
                code = cli.run(["endpoints", "--project", "Alpha", "--json"], env=env, dispatcher=dispatcher)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["project"], "Alpha")
        self.assertEqual(payload["frontend"]["public_url"], "http://public.example.test:3100")
        self.assertEqual(payload["backend"]["public_url"], "http://public.example.test:8100")
        self.assertNotIn("Beta", json.dumps(payload))

    def test_cli_playwright_exports_qa_base_url_without_browser_binaries(self) -> None:
        state = self._runtime_smoke_state()
        stdout = StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            output_path = tmp_path / "qa-base-url.txt"
            repo, env, dispatcher = self._runtime_smoke_dispatcher(tmp_path, state)
            python_bin = __import__("shutil").which("python3") or sys.executable
            script = f"import os, pathlib; pathlib.Path({str(output_path)!r}).write_text(os.environ['QA_BASE_URL'])"
            with patch("envctl_engine.runtime.cli.check_prereqs", return_value=(True, None)), redirect_stdout(stdout):
                code = cli.run(
                    ["playwright", "--project", "Alpha", "--json", "--", python_bin, "-c", script],
                    env=env,
                    dispatcher=dispatcher,
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "http://public.example.test:3100")
            self.assertTrue(Path(payload["endpoints_path"]).is_file())

    def _runtime_smoke_state(self):  # noqa: ANN201
        from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord

        return RunState(
            run_id="run-cli-smoke",
            mode="trees",
            metadata={
                "project_roots": {"Alpha": "/tmp/alpha"},
                "dependency_mode": "isolated",
                "shared_dependencies": False,
            },
            services={
                "Alpha Backend": ServiceRecord(
                    name="Alpha Backend",
                    type="backend",
                    cwd="/tmp/alpha/api",
                    project="Alpha",
                    status="running",
                    actual_port=8100,
                ),
                "Alpha Frontend": ServiceRecord(
                    name="Alpha Frontend",
                    type="frontend",
                    cwd="/tmp/alpha/web",
                    project="Alpha",
                    status="running",
                    actual_port=3100,
                ),
            },
            requirements={"Alpha": RequirementsResult(project="Alpha", redis={"enabled": True, "success": True, "final": 6380})},
        )

    def _runtime_smoke_dispatcher(self, tmp_path: Path, state):  # noqa: ANN001, ANN201
        from envctl_engine.config import load_config
        from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
        import envctl_engine.runtime.engine_runtime as engine_runtime_module

        repo = tmp_path / "repo"
        runtime_root = tmp_path / "runtime"
        project_root = tmp_path / "alpha"
        (project_root / "api").mkdir(parents=True, exist_ok=True)
        (project_root / "web").mkdir(parents=True, exist_ok=True)
        state.metadata["project_roots"] = {"Alpha": str(project_root)}
        state.services["Alpha Backend"].cwd = str(project_root / "api")
        state.services["Alpha Frontend"].cwd = str(project_root / "web")
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / ".envctl").write_text("ENVCTL_DEFAULT_MODE=trees\nENVCTL_PUBLIC_HOST=public.example.test\n", encoding="utf-8")
        env = {"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime_root)}
        config = load_config(env)
        runtime = PythonEngineRuntime(config, env=env)
        runtime.state_repository.save_resume_state(
            state=state,
            emit=runtime._emit,
            runtime_map_builder=engine_runtime_module.build_runtime_map,
        )

        def dispatcher(route, config):  # noqa: ANN001
            return PythonEngineRuntime(config, env=env).dispatch(route)

        return repo, env, dispatcher

    @staticmethod
    def _bootstrap_result():
        return type("BootstrapResult", (), {"changed": False, "message": None})()


if __name__ == "__main__":
    unittest.main()
