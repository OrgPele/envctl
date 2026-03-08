from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "release_shipability_gate.py"


class ReleaseShipabilityGateCliTests(unittest.TestCase):
    def test_skip_tests_flag_is_accepted(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--skip-tests",
                "--repo",
                str(REPO_ROOT),
                "--required-path",
                "python/envctl_engine",
                "--required-scope",
                "python/envctl_engine",
                "--skip-parity-sync",
                "--skip-shell-prune-contract",
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotIn("unrecognized arguments: --skip-tests", result.stderr)


if __name__ == "__main__":
    unittest.main()
