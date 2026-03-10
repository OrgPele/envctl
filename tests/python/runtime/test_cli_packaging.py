from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import site
import subprocess
import sys
import tempfile
import tomllib
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]


class CliPackagingTests(unittest.TestCase):
    def test_pyproject_declares_installable_console_script(self) -> None:
        payload = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = payload["project"]
        self.assertEqual(project["name"], "envctl")
        self.assertEqual(project["scripts"]["envctl"], "envctl_engine.runtime.cli:main")
        self.assertEqual(project["requires-python"], ">=3.12,<3.15")
        self.assertIn("rich>=13.7", project["dependencies"])

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

    def test_regular_install_supports_doctor_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            with self._installed_env(editable=False) as env:
                result = subprocess.run(
                    [str(env["script"]), "doctor", "--repo", str(repo)],
                    capture_output=True,
                    text=True,
                    env=env["env"],
                    check=False,
                )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(result.stdout.strip())

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

    @staticmethod
    def _site_packages_path() -> str:
        candidates = [path for path in site.getsitepackages() if "site-packages" in path]
        if not candidates:
            raise unittest.SkipTest("Current interpreter does not expose site-packages for packaging smoke test")
        return os.pathsep.join(candidates)

    @contextmanager
    def _installed_env(self, *, editable: bool):
        site_packages = self._site_packages_path()
        with tempfile.TemporaryDirectory() as tmpdir:
            venv_dir = Path(tmpdir) / "venv"
            subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
            python_bin = venv_dir / "bin" / "python"
            env = dict(os.environ)
            env["PYTHONPATH"] = site_packages
            bootstrap = subprocess.run(
                [str(python_bin), "-m", "pip", "install", "setuptools>=77.0.0"],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            if bootstrap.returncode != 0:
                raise unittest.SkipTest(f"setuptools bootstrap failed for packaging smoke test: {bootstrap.stderr.strip()}")
            install_cmd = [
                str(python_bin),
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--no-build-isolation",
            ]
            if editable:
                install_cmd.extend(["-e", str(REPO_ROOT)])
            else:
                install_cmd.append(str(REPO_ROOT))
            subprocess.run(install_cmd, check=True, capture_output=True, text=True, env=env)
            runtime_env = dict(env)
            runtime_env.pop("PYTHONPATH", None)
            yield {
                "env": runtime_env,
                "script": venv_dir / "bin" / "envctl",
            }


if __name__ == "__main__":
    unittest.main()
