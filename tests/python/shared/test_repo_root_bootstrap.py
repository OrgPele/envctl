from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]


class RepoRootBootstrapTests(unittest.TestCase):
    def _run_discovery(self, *, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests/python",
                "-p",
                "test_repo_root_bootstrap_probe.py",
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_repo_root_discovery_imports_python_package_without_pythonpath(self) -> None:
        completed = self._run_discovery()
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stdout:\n{completed.stdout}\n\nstderr:\n{completed.stderr}",
        )

    def test_repo_root_discovery_prefers_this_checkout_over_pythonpath_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_root = Path(tmpdir) / "foreign_checkout"
            fake_runtime = fake_root / "envctl_engine" / "runtime"
            fake_runtime.mkdir(parents=True, exist_ok=True)
            (fake_root / "envctl_engine" / "__init__.py").write_text('"""foreign checkout"""\n', encoding="utf-8")
            (fake_runtime / "__init__.py").write_text('"""foreign runtime"""\n', encoding="utf-8")
            (fake_runtime / "command_router.py").write_text(
                "raise RuntimeError('wrong checkout imported')\n",
                encoding="utf-8",
            )

            completed = self._run_discovery(extra_env={"PYTHONPATH": str(fake_root)})

        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stdout:\n{completed.stdout}\n\nstderr:\n{completed.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
