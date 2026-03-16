from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest

from envctl_engine.runtime.launcher_support import (
    ORIGINAL_WRAPPER_ARGV0_ENVVAR,
    find_shadowed_installed_envctl,
    is_explicit_wrapper_path,
    select_envctl_reexec_target,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


class CliPackagingTests(unittest.TestCase):
    @staticmethod
    def _interpreter_can_import(python_bin: str, module_name: str) -> bool:
        result = subprocess.run(
            [
                python_bin,
                "-P",
                "-c",
                (
                    "import importlib.util, sys; "
                    f"raise SystemExit(0 if importlib.util.find_spec({module_name!r}) else 1)"
                ),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0

    @classmethod
    def _packaging_python(cls) -> str:
        candidates: list[str] = []
        for raw in (sys.executable, shutil.which("python3"), shutil.which("python3.12"), shutil.which("python")):
            if not raw:
                continue
            if raw not in candidates:
                candidates.append(raw)
        for candidate in candidates:
            if cls._interpreter_can_import(candidate, "setuptools") and cls._interpreter_can_import(candidate, "build"):
                return candidate
        raise unittest.SkipTest("No available interpreter exposes both setuptools and build for packaging smoke")

    def test_repo_wrapper_detects_shadowed_installed_envctl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            repo_bin = tmp_path / "repo-bin"
            installed_bin = tmp_path / "installed-bin"
            repo_bin.mkdir()
            installed_bin.mkdir()
            current = repo_bin / "envctl"
            alternate = installed_bin / "envctl"
            current.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            alternate.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            current.chmod(0o755)
            alternate.chmod(0o755)

            result = find_shadowed_installed_envctl(
                current,
                env={"PATH": os.pathsep.join((str(repo_bin), str(installed_bin)))},
            )

        self.assertEqual(result, alternate.resolve())

    def test_repo_wrapper_detects_no_shadowed_binary_when_only_current_is_on_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_bin = Path(tmpdir) / "repo-bin"
            repo_bin.mkdir()
            current = repo_bin / "envctl"
            current.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            current.chmod(0o755)

            result = find_shadowed_installed_envctl(
                current,
                env={"PATH": str(repo_bin)},
            )

        self.assertIsNone(result)

    def test_explicit_absolute_wrapper_path_skips_shadow_redirect(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            current = tmp_path / "repo" / "bin" / "envctl"
            alternate = tmp_path / "installed" / "envctl"
            current.parent.mkdir(parents=True)
            alternate.parent.mkdir(parents=True)
            current.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            alternate.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            current.chmod(0o755)
            alternate.chmod(0o755)

            self.assertTrue(is_explicit_wrapper_path(current, str(current)))
            self.assertIsNone(
                select_envctl_reexec_target(
                    current,
                    str(current),
                    alternate=alternate,
                )
            )

    def test_explicit_relative_wrapper_paths_are_treated_as_wrapper_intent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            repo_root = tmp_path / "repo"
            current = repo_root / "bin" / "envctl"
            alternate = tmp_path / "installed" / "envctl"
            current.parent.mkdir(parents=True)
            alternate.parent.mkdir(parents=True)
            current.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            alternate.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            current.chmod(0o755)
            alternate.chmod(0o755)

            self.assertTrue(is_explicit_wrapper_path(current, "./bin/envctl", cwd=repo_root))
            self.assertTrue(is_explicit_wrapper_path(current, "bin/envctl", cwd=repo_root))
            self.assertIsNone(
                select_envctl_reexec_target(
                    current,
                    "./bin/envctl",
                    cwd=repo_root,
                    alternate=alternate,
                )
            )

    def test_explicit_symlink_wrapper_path_is_treated_as_wrapper_intent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            current = tmp_path / "repo" / "bin" / "envctl"
            symlink_path = tmp_path / "shim" / "envctl"
            current.parent.mkdir(parents=True)
            symlink_path.parent.mkdir(parents=True)
            current.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            current.chmod(0o755)
            symlink_path.symlink_to(current)

            self.assertTrue(is_explicit_wrapper_path(current, str(symlink_path)))

    def test_explicit_wrapper_path_ignores_ambient_preserved_argv0_without_explicit_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            current = tmp_path / "repo" / "bin" / "envctl"
            current.parent.mkdir(parents=True)
            current.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            current.chmod(0o755)

            original = os.environ.get(ORIGINAL_WRAPPER_ARGV0_ENVVAR)
            try:
                os.environ[ORIGINAL_WRAPPER_ARGV0_ENVVAR] = "envctl"
                self.assertTrue(is_explicit_wrapper_path(current, str(current)))
            finally:
                if original is None:
                    os.environ.pop(ORIGINAL_WRAPPER_ARGV0_ENVVAR, None)
                else:
                    os.environ[ORIGINAL_WRAPPER_ARGV0_ENVVAR] = original

    def test_bare_envctl_keeps_shadow_redirect_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            current = tmp_path / "repo" / "bin" / "envctl"
            alternate = tmp_path / "installed" / "envctl"
            current.parent.mkdir(parents=True)
            alternate.parent.mkdir(parents=True)
            current.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            alternate.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            current.chmod(0o755)
            alternate.chmod(0o755)

            self.assertFalse(is_explicit_wrapper_path(current, "envctl"))
            self.assertEqual(
                select_envctl_reexec_target(current, "envctl", alternate=alternate),
                alternate,
            )

    def test_env_var_override_forces_repo_wrapper_even_for_bare_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            current = tmp_path / "repo" / "bin" / "envctl"
            alternate = tmp_path / "installed" / "envctl"
            current.parent.mkdir(parents=True)
            alternate.parent.mkdir(parents=True)
            current.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            alternate.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            current.chmod(0o755)
            alternate.chmod(0o755)

            self.assertIsNone(
                select_envctl_reexec_target(
                    current,
                    "envctl",
                    env={"ENVCTL_USE_REPO_WRAPPER": "1"},
                    alternate=alternate,
                )
            )

    def test_bare_argv0_wins_over_ambient_original_wrapper_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            current = tmp_path / "repo" / "bin" / "envctl"
            alternate = tmp_path / "installed" / "envctl"
            current.parent.mkdir(parents=True)
            alternate.parent.mkdir(parents=True)
            current.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            alternate.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            current.chmod(0o755)
            alternate.chmod(0o755)

            self.assertEqual(
                select_envctl_reexec_target(
                    current,
                    "envctl",
                    env={ORIGINAL_WRAPPER_ARGV0_ENVVAR: str(current)},
                    alternate=alternate,
                ),
                alternate,
            )

    def test_preserved_original_argv0_controls_redirect_after_python_reexec(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            current = tmp_path / "repo" / "bin" / "envctl"
            alternate = tmp_path / "installed" / "envctl"
            current.parent.mkdir(parents=True)
            alternate.parent.mkdir(parents=True)
            current.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            alternate.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            current.chmod(0o755)
            alternate.chmod(0o755)

            self.assertEqual(
                select_envctl_reexec_target(
                    current,
                    str(current),
                    env={ORIGINAL_WRAPPER_ARGV0_ENVVAR: "envctl"},
                    alternate=alternate,
                ),
                alternate,
            )

    def test_explicit_wrapper_subprocess_skips_shadowed_installed_envctl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            repo_root = tmp_path / "project"
            (repo_root / ".git").mkdir(parents=True)
            installed_bin = tmp_path / "installed-bin"
            installed_bin.mkdir()
            installed = installed_bin / "envctl"
            installed.write_text("#!/bin/sh\necho INSTALLED_SENTINEL\n", encoding="utf-8")
            installed.chmod(0o755)

            env = dict(os.environ)
            env["PATH"] = os.pathsep.join((str(installed_bin), env.get("PATH", "")))
            result = subprocess.run(
                [str(REPO_ROOT / "bin" / "envctl"), "doctor", "--repo", str(repo_root)],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Launcher: envctl", result.stdout)
        self.assertNotIn("INSTALLED_SENTINEL", result.stdout)
        self.assertNotIn("shadowing installed envctl", result.stderr)

    def test_explicit_wrapper_subprocess_ignores_stale_preserved_argv0_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            repo_root = tmp_path / "project"
            (repo_root / ".git").mkdir(parents=True)
            installed_bin = tmp_path / "installed-bin"
            installed_bin.mkdir()
            installed = installed_bin / "envctl"
            installed.write_text("#!/bin/sh\necho INSTALLED_SENTINEL\n", encoding="utf-8")
            installed.chmod(0o755)

            env = dict(os.environ)
            env[ORIGINAL_WRAPPER_ARGV0_ENVVAR] = "envctl"
            env["PATH"] = os.pathsep.join((str(installed_bin), env.get("PATH", "")))
            result = subprocess.run(
                [str(REPO_ROOT / "bin" / "envctl"), "doctor", "--repo", str(repo_root)],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Launcher: envctl", result.stdout)
        self.assertNotIn("INSTALLED_SENTINEL", result.stdout)
        self.assertNotIn("shadowing installed envctl", result.stderr)

    def test_bare_envctl_subprocess_redirects_to_shadowed_installed_envctl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            repo_bin = tmp_path / "repo-bin"
            installed_bin = tmp_path / "installed-bin"
            repo_bin.mkdir()
            installed_bin.mkdir()
            (repo_bin / "envctl").symlink_to(REPO_ROOT / "bin" / "envctl")
            installed = installed_bin / "envctl"
            installed.write_text("#!/bin/sh\necho INSTALLED_SENTINEL\n", encoding="utf-8")
            installed.chmod(0o755)

            env = dict(os.environ)
            env["PATH"] = os.pathsep.join((str(repo_bin), str(installed_bin), env.get("PATH", "")))
            result = subprocess.run(
                ["envctl", "doctor", "--repo", str(tmp_path)],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "INSTALLED_SENTINEL")
        self.assertIn("shadowing installed envctl", result.stderr)

    def test_repo_wrapper_override_subprocess_forces_wrapper_on_bare_envctl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            repo_root = tmp_path / "project"
            repo_bin = tmp_path / "repo-bin"
            installed_bin = tmp_path / "installed-bin"
            repo_bin.mkdir()
            installed_bin.mkdir()
            (repo_root / ".git").mkdir(parents=True)
            (repo_bin / "envctl").symlink_to(REPO_ROOT / "bin" / "envctl")
            installed = installed_bin / "envctl"
            installed.write_text("#!/bin/sh\necho INSTALLED_SENTINEL\n", encoding="utf-8")
            installed.chmod(0o755)

            env = dict(os.environ)
            env["ENVCTL_USE_REPO_WRAPPER"] = "1"
            env["PATH"] = os.pathsep.join((str(repo_bin), str(installed_bin), env.get("PATH", "")))
            result = subprocess.run(
                ["envctl", "doctor", "--repo", str(repo_root)],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Launcher: envctl", result.stdout)
        self.assertNotIn("INSTALLED_SENTINEL", result.stdout)
        self.assertNotIn("shadowing installed envctl", result.stderr)

    def test_pyproject_declares_installable_console_script(self) -> None:
        payload = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = payload["project"]
        self.assertEqual(project["name"], "envctl")
        self.assertEqual(project["scripts"]["envctl"], "envctl_engine.runtime.cli:main")
        self.assertEqual(project["requires-python"], ">=3.12,<3.15")
        self.assertIn("rich>=13.7", project["dependencies"])

    def test_pyproject_declares_release_validation_dev_extra(self) -> None:
        payload = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        dev_dependencies = set(payload["project"]["optional-dependencies"]["dev"])
        self.assertTrue(any(item.startswith("pytest") for item in dev_dependencies))
        self.assertTrue(any(item.startswith("build") for item in dev_dependencies))
        self.assertTrue(any(item.startswith("ruff") for item in dev_dependencies))
        self.assertTrue(any(item.startswith("basedpyright") for item in dev_dependencies))
        self.assertTrue(any(item.startswith("vulture") for item in dev_dependencies))

    def test_release_version_metadata_is_aligned_for_1_3_0(self) -> None:
        payload = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = payload["project"]
        self.assertEqual(project["version"], "1.3.0")

        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("releases/tag/1.3.0", readme)
        self.assertIn("release-1.3.0", readme)
        self.assertIn("Release 1.3.0", readme)

    def test_release_notes_exist_for_1_3_0(self) -> None:
        notes = (REPO_ROOT / "docs" / "changelog" / "RELEASE_NOTES_1.3.0.md").read_text(encoding="utf-8")
        self.assertTrue(notes.startswith("# envctl 1.3.0"))
        self.assertRegex(notes, re.compile(r"\b1\.3\.0\b"))

    def test_build_smoke_is_warning_free(self) -> None:
        packaging_python = self._packaging_python()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    packaging_python,
                    "-P",
                    "-m",
                    "build",
                    "--wheel",
                    "--sdist",
                    "--no-isolation",
                    "--outdir",
                    str(Path(tmpdir) / "dist"),
                    str(REPO_ROOT),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        combined_output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        self.assertEqual(result.returncode, 0, msg=combined_output)
        self.assertNotIn("SetuptoolsDeprecationWarning", combined_output)

    def test_editable_install_exposes_envctl_help(self) -> None:
        with self._installed_env(editable=True) as env:
            result = subprocess.run(
                [str(env["script"]), "--help"],
                capture_output=True,
                text=True,
                env=env["env"],
                check=False,
            )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("envctl Python runtime", result.stdout)
        self.assertIn("Commands:", result.stdout)

    def test_editable_install_with_dependencies_imports_runtime_packages(self) -> None:
        with self._installed_env(editable=True, install_deps=True) as env:
            self._assert_runtime_dependencies_available(env)

    def test_regular_install_supports_doctor_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            with self._installed_env(editable=False, install_deps=True) as env:
                self._assert_runtime_dependencies_available(env)
                result = subprocess.run(
                    [str(env["script"]), "doctor", "--repo", str(repo)],
                    capture_output=True,
                    text=True,
                    env=env["env"],
                    check=False,
                )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(result.stdout.strip())

    def test_regular_install_supports_direct_inspection_command_spelling(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            with self._installed_env(editable=False) as env:
                result = subprocess.run(
                    [str(env["script"]), "--repo", str(repo), "list-commands"],
                    capture_output=True,
                    text=True,
                    env=env["env"],
                    check=False,
                )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("list-commands", result.stdout)

    def test_regular_install_supports_install_and_uninstall_shell_path_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            shell_file = Path(tmpdir) / ".zshrc"
            shell_file.write_text("# existing\n", encoding="utf-8")
            with self._installed_env(editable=False) as env:
                install = subprocess.run(
                    [str(env["script"]), "install", "--shell-file", str(shell_file)],
                    capture_output=True,
                    text=True,
                    env=env["env"],
                    check=False,
                )
                uninstall = subprocess.run(
                    [str(env["script"]), "uninstall", "--shell-file", str(shell_file)],
                    capture_output=True,
                    text=True,
                    env=env["env"],
                    check=False,
                )
            self.assertEqual(install.returncode, 0, msg=install.stderr)
            self.assertEqual(uninstall.returncode, 0, msg=uninstall.stderr)
            self.assertNotIn("# >>> envctl PATH >>>", shell_file.read_text(encoding="utf-8"))

    def _assert_runtime_dependencies_available(self, env: dict[str, object]) -> None:
        result = subprocess.run(
            [
                str(env["python"]),
                "-c",
                "import prompt_toolkit, psutil, rich, textual; print('deps-ok')",
            ],
            capture_output=True,
            text=True,
            env=env["env"],
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("deps-ok", result.stdout)

    def _build_stub_dependency_wheels(self, wheelhouse: Path) -> None:
        packaging_python = self._packaging_python()
        wheelhouse.mkdir(parents=True, exist_ok=True)
        packages = {
            "rich": ("rich", "99.0.0"),
            "textual": ("textual", "99.0.0"),
            "prompt_toolkit": ("prompt_toolkit", "99.0.0"),
            "psutil": ("psutil", "99.0.0"),
        }
        for distribution_name, (module_name, version) in packages.items():
            package_root = wheelhouse / f"{distribution_name}-src"
            module_dir = package_root / module_name
            module_dir.mkdir(parents=True, exist_ok=True)
            (module_dir / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
            (package_root / "pyproject.toml").write_text(
                "\n".join(
                    [
                        "[build-system]",
                        'requires = ["setuptools>=77.0.0"]',
                        'build-backend = "setuptools.build_meta"',
                        "",
                        "[project]",
                        f'name = "{distribution_name}"',
                        f'version = "{version}"',
                        "",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    packaging_python,
                    "-P",
                    "-m",
                    "build",
                    "--wheel",
                    "--no-isolation",
                    "--outdir",
                    str(wheelhouse),
                ],
                cwd=package_root,
                check=True,
                capture_output=True,
                text=True,
            )

    @contextmanager
    def _installed_env(self, *, editable: bool, install_deps: bool = False):
        with tempfile.TemporaryDirectory() as tmpdir:
            packaging_python = self._packaging_python()
            venv_dir = Path(tmpdir) / "venv"
            subprocess.run([packaging_python, "-m", "venv", "--system-site-packages", str(venv_dir)], check=True)
            python_bin = venv_dir / "bin" / "python"
            env = dict(os.environ)
            install_cmd = [
                str(python_bin),
                "-m",
                "pip",
                "install",
                "--no-build-isolation",
            ]
            if install_deps:
                wheelhouse = Path(tmpdir) / "wheelhouse"
                self._build_stub_dependency_wheels(wheelhouse)
                install_cmd.extend(["--no-index", "--find-links", str(wheelhouse)])
            else:
                install_cmd.append("--no-deps")
            if editable:
                install_cmd.extend(["-e", str(REPO_ROOT)])
            else:
                install_cmd.append(str(REPO_ROOT))
            subprocess.run(install_cmd, check=True, capture_output=True, text=True, env=env)
            yield {
                "env": env,
                "python": python_bin,
                "script": venv_dir / "bin" / "envctl",
            }


if __name__ == "__main__":
    unittest.main()
