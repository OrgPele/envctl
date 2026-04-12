from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from importlib import metadata as importlib_metadata

from envctl_engine.runtime import cli as runtime_cli
from envctl_engine.runtime import launcher_cli
from envctl_engine.runtime.launcher_support import LauncherError, resolve_envctl_version


class LauncherVersionTests(unittest.TestCase):
    def test_resolve_envctl_version_prefers_installed_metadata(self) -> None:
        with patch("envctl_engine.runtime.launcher_support.importlib_metadata.version", return_value="9.9.9"):
            self.assertEqual(resolve_envctl_version(), "9.9.9")

    def test_resolve_envctl_version_falls_back_to_pyproject_when_metadata_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text(
                "\n".join(
                    [
                        "[project]",
                        'name = "envctl"',
                        'version = "2.4.6"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            with patch(
                "envctl_engine.runtime.launcher_support.importlib_metadata.version",
                side_effect=importlib_metadata.PackageNotFoundError,
            ):
                self.assertEqual(resolve_envctl_version(project_root=root), "2.4.6")

    def test_resolve_envctl_version_raises_clear_error_when_metadata_and_fallback_are_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with (
                patch(
                    "envctl_engine.runtime.launcher_support.importlib_metadata.version",
                    side_effect=importlib_metadata.PackageNotFoundError,
                ),
                patch(
                    "envctl_engine.runtime.launcher_support._candidate_version_files",
                    return_value=[root / "pyproject.toml"],
                ),
            ):
                with self.assertRaises(LauncherError) as exc:
                    resolve_envctl_version(project_root=root)

        self.assertIn("Could not determine envctl version", str(exc.exception))

    def test_launcher_run_prints_version_without_repo_resolution(self) -> None:
        stdout = StringIO()
        with (
            redirect_stdout(stdout),
            patch("envctl_engine.runtime.launcher_cli._envctl_root", return_value=Path("/tmp/envctl-root")),
            patch("envctl_engine.runtime.launcher_cli.resolve_envctl_version", return_value="1.3.1") as version_mock,
            patch("envctl_engine.runtime.launcher_cli.resolve_repo_root") as resolve_repo_root,
            patch("envctl_engine.runtime.launcher_cli.runtime_cli.run") as runtime_run,
        ):
            code = launcher_cli.run(["--version"])

        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), "envctl 1.3.1\n")
        version_mock.assert_called_once_with(project_root=Path("/tmp/envctl-root"))
        resolve_repo_root.assert_not_called()
        runtime_run.assert_not_called()

    def test_launcher_run_allows_repo_flag_but_ignores_it_for_version(self) -> None:
        stdout = StringIO()
        with (
            redirect_stdout(stdout),
            patch("envctl_engine.runtime.launcher_cli._envctl_root", return_value=Path("/tmp/envctl-root")),
            patch("envctl_engine.runtime.launcher_cli.resolve_envctl_version", return_value="1.3.1"),
            patch("envctl_engine.runtime.launcher_cli.resolve_repo_root") as resolve_repo_root,
        ):
            code = launcher_cli.run(["--repo", "/tmp/repo", "--version"])

        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), "envctl 1.3.1\n")
        resolve_repo_root.assert_not_called()

    def test_launcher_run_rejects_trailing_args_for_version(self) -> None:
        stderr = StringIO()
        with (
            redirect_stderr(stderr),
            patch("envctl_engine.runtime.launcher_cli._envctl_root", return_value=Path("/tmp/envctl-root")),
        ):
            code = launcher_cli.run(["--version", "extra"])

        self.assertEqual(code, 1)
        self.assertIn("--version does not accept additional arguments", stderr.getvalue())

    def test_runtime_entrypoint_prints_version_without_bootstrap(self) -> None:
        stdout = StringIO()
        with (
            redirect_stdout(stdout),
            patch("envctl_engine.runtime.cli.ensure_local_config") as bootstrap,
            patch("envctl_engine.runtime.cli.resolve_envctl_version", return_value="1.3.1") as version_mock,
        ):
            code = runtime_cli.run(["--version"], env={})

        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), "envctl 1.3.1\n")
        bootstrap.assert_not_called()
        version_mock.assert_called_once_with(project_root=None)

    def test_runtime_entrypoint_rejects_trailing_args_for_version(self) -> None:
        stderr = StringIO()
        with redirect_stderr(stderr):
            code = runtime_cli.run(["--version", "extra"], env={})

        self.assertEqual(code, 1)
        self.assertIn("--version does not accept additional arguments", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
