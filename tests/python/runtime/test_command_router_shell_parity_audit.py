from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "audit_command_router_vs_shell.py"


class CommandRouterShellParityAuditTests(unittest.TestCase):
    def test_shell_parser_parity_audit_matrix(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--fail-on-mismatch", "--json"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            self.fail(result.stdout or result.stderr)


if __name__ == "__main__":
    unittest.main()
