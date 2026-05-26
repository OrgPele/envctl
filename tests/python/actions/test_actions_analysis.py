from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from envctl_engine.actions.actions_analysis import default_migrate_command


class ActionsAnalysisTests(unittest.TestCase):
    def test_pdm_backend_does_not_use_poetry_for_default_migrate_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            backend = project_root / "backend"
            venv_bin = backend / ".venv" / "bin"
            venv_bin.mkdir(parents=True, exist_ok=True)
            (backend / "pyproject.toml").write_text("[tool.pdm]\nname = 'backend'\n", encoding="utf-8")
            (venv_bin / "alembic").write_text("", encoding="utf-8")

            with patch("envctl_engine.actions.actions_analysis.shutil.which", return_value="/usr/bin/poetry"):
                resolution = default_migrate_command(project_root)

        self.assertEqual(resolution.command, [str(venv_bin / "alembic"), "upgrade", "head"])
        self.assertEqual(resolution.cwd, backend)
        self.assertIsNone(resolution.error)


if __name__ == "__main__":
    unittest.main()
