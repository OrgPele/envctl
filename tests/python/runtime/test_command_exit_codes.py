from __future__ import annotations

import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

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
        with (
            patch("envctl_engine.runtime.cli.check_prereqs", return_value=(True, None)),
            patch("envctl_engine.runtime.cli.ensure_local_config", return_value=self._bootstrap_result()),
        ):
            code = cli.run(["tees=true"], env={})
        self.assertEqual(code, 1)

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
            with patch("envctl_engine.runtime.cli._python_dependency_available", return_value=False):
                code = cli.run(["start"], env=env, dispatcher=lambda _route, _config: 0)
            self.assertEqual(code, 1)

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
        with patch("envctl_engine.runtime.cli._best_effort_restore_terminal_state") as restore_mock:
            code = cli.run(["tees=true"], env={})
        self.assertEqual(code, 1)
        restore_mock.assert_called_once()

    @staticmethod
    def _bootstrap_result():
        return type("BootstrapResult", (), {"changed": False, "message": None})()


if __name__ == "__main__":
    unittest.main()
