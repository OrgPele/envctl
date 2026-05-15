from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]


class PrepareReleaseTests(unittest.TestCase):
    def test_apply_canonicalizes_readme_release_badge_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "pyproject.toml").write_text(
                textwrap.dedent(
                    """
                    [project]
                    name = "envctl"
                    version = "1.9.0"
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (repo / "README.md").write_text(
                '<a href="https://github.com/kfiramar/envctl/releases/tag/1.9.0">'
                '<img src="https://img.shields.io/badge/release-1.9.0-2ea043" alt="Release 1.9.0"></a>\n',
                encoding="utf-8",
            )

            env = dict(os.environ)
            env["GITHUB_REPOSITORY"] = "OrgPele/envctl"
            subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "prepare_release.py"),
                    "apply",
                    "--repo",
                    str(repo),
                    "--bump",
                    "patch",
                    "--notes-body",
                    "release notes",
                ],
                check=True,
                env=env,
                capture_output=True,
                text=True,
            )

            readme = (repo / "README.md").read_text(encoding="utf-8")
            self.assertIn("https://github.com/OrgPele/envctl/releases/tag/1.9.1", readme)
            self.assertIn("release-1.9.1", readme)
            self.assertIn("Release 1.9.1", readme)
            self.assertNotIn("github.com/kfiramar/envctl/releases/tag", readme)


if __name__ == "__main__":
    unittest.main()
