from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]


class TestRunnerCliE2ETests(unittest.TestCase):
    def test_envctl_test_fails_when_mocked_command_prints_failures_but_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            project_root = tmp / "project"
            runtime_root = tmp / "runtime"
            project_root.mkdir(parents=True)
            (project_root / ".git").mkdir()
            fake_test = project_root / "fake_test.sh"
            fake_test.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env sh",
                        "printf '%s\\n' 'FAILED tests/test_auth.py::test_login - AssertionError: expected 200, got 500'",
                        "printf '%s\\n' '========================= 1 failed in 0.03s ========================='",
                        "exit 0",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_test.chmod(0o755)
            env = {
                **os.environ,
                "ENVCTL_USE_REPO_WRAPPER": "1",
                "RUN_REPO_ROOT": str(project_root),
                "RUN_SH_RUNTIME_DIR": str(runtime_root),
                "ENVCTL_DEFAULT_MODE": "main",
                "ENVCTL_ACTION_TEST_CMD": str(fake_test),
                "NO_COLOR": "1",
            }

            completed = subprocess.run(
                [sys.executable, str(REPO_ROOT / "bin" / "envctl"), "--test", "--main", "--headless"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )

        self.assertEqual(completed.returncode, 1, msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}")
        self.assertIn("✗ FAILED", completed.stdout)
        self.assertNotIn("✓ PASSED", completed.stdout)
        self.assertIn("test action failed:", completed.stdout)
        self.assertIn("tests/test_auth.py::test_login", completed.stdout)


if __name__ == "__main__":
    unittest.main()
