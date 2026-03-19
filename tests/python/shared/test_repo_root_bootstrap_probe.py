from __future__ import annotations

from pathlib import Path
import unittest

from envctl_engine.runtime.command_router import list_supported_commands


class RepoRootBootstrapProbeTests(unittest.TestCase):
    def test_runtime_package_imports_from_repo_root_discovery(self) -> None:
        self.assertIn("doctor", list_supported_commands())
        self.assertTrue(Path(__file__).is_file())


if __name__ == "__main__":
    unittest.main()
