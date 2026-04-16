from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from envctl_engine.test_output.test_runner import TestRunner


class TestRunnerEnvTests(unittest.TestCase):
    def test_ensure_helper_pythonpath_uses_supplied_env_without_reintroducing_wrapper_vars(self) -> None:
        helper_python_root = str(Path(__file__).resolve().parents[3] / "python")
        supplied_env = {
            "PATH": "/usr/bin",
            "PYTHONPATH": f"/existing{os.pathsep}/other",
            "KEEP_ME": "1",
        }
        parent_env = {
            "ENVCTL_USE_REPO_WRAPPER": "1",
            "ENVCTL_WRAPPER_ORIGINAL_ARGV0": "/root/projects/envctl/bin/envctl",
            "ENVCTL_WRAPPER_PYTHON_REEXEC": "1",
            "PARENT_ONLY": "present",
        }

        with patch.dict(os.environ, parent_env, clear=True):
            env_map = TestRunner._ensure_helper_pythonpath(supplied_env)

        assert env_map is not None
        self.assertEqual(env_map.get("KEEP_ME"), "1")
        self.assertEqual(env_map.get("PATH"), "/usr/bin")
        self.assertNotIn("ENVCTL_USE_REPO_WRAPPER", env_map)
        self.assertNotIn("ENVCTL_WRAPPER_ORIGINAL_ARGV0", env_map)
        self.assertNotIn("ENVCTL_WRAPPER_PYTHON_REEXEC", env_map)
        self.assertNotIn("PARENT_ONLY", env_map)
        self.assertTrue(env_map["PYTHONPATH"].startswith(helper_python_root))
        self.assertIn("/existing", env_map["PYTHONPATH"].split(os.pathsep))

    def test_ensure_helper_pythonpath_falls_back_to_parent_env_when_none_supplied(self) -> None:
        helper_python_root = str(Path(__file__).resolve().parents[3] / "python")
        with patch.dict(os.environ, {"PATH": "/usr/bin", "KEEP_PARENT": "1"}, clear=True):
            env_map = TestRunner._ensure_helper_pythonpath(None)

        assert env_map is not None
        self.assertEqual(env_map.get("KEEP_PARENT"), "1")
        self.assertEqual(env_map.get("PATH"), "/usr/bin")
        self.assertTrue(env_map["PYTHONPATH"].startswith(helper_python_root))


if __name__ == "__main__":
    unittest.main()
