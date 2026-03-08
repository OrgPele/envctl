from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.config import LocalConfigState, PortDefaults, StartupProfile
from envctl_engine.config.persistence import (
    ManagedConfigValues,
    ensure_local_config_ignored,
    merge_managed_block,
    render_managed_block,
    save_local_config,
)


class ConfigPersistenceTests(unittest.TestCase):
    def test_merge_managed_block_preserves_unknown_lines(self) -> None:
        values = ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(True, True, True, True, False, False),
            trees_profile=StartupProfile(True, True, True, True, False, True),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
        )
        existing = "FOO=bar\n# comment\n\nBAR=baz\n"

        merged = merge_managed_block(existing, render_managed_block(values))

        self.assertIn("FOO=bar", merged)
        self.assertIn("BAR=baz", merged)
        self.assertIn("# >>> envctl managed startup config >>>", merged)
        self.assertIn("MAIN_BACKEND_ENABLE=true", merged)
        self.assertIn("BACKEND_DIR=backend", merged)
        self.assertIn("FRONTEND_DIR=frontend", merged)

    def test_save_local_config_rewrites_only_managed_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            path = repo / ".envctl"
            path.write_text(
                "FOO=bar\n# >>> envctl managed startup config >>>\nENVCTL_DEFAULT_MODE=main\n# <<< envctl managed startup config <<<\nBAR=baz\n",
                encoding="utf-8",
            )
            local_state = LocalConfigState(
                base_dir=repo,
                config_file_path=path,
                config_file_exists=True,
                config_source="envctl",
                active_source_path=path,
                legacy_source_path=None,
                explicit_path=None,
                parsed_values={},
                file_text=path.read_text(encoding="utf-8"),
            )
            values = ManagedConfigValues(
                default_mode="trees",
                main_profile=StartupProfile(True, False, True, True, False, False),
                trees_profile=StartupProfile(True, True, True, False, False, True),
                port_defaults=PortDefaults(8100, 9100, 5434, 6381, 5680, 11),
            )

            result = save_local_config(local_state=local_state, values=values)
            written = path.read_text(encoding="utf-8")

            self.assertEqual(result.path, path)
            self.assertIn("FOO=bar", written)
            self.assertIn("BAR=baz", written)
            self.assertIn("ENVCTL_DEFAULT_MODE=trees", written)
            self.assertIn("BACKEND_DIR=backend", written)
            self.assertIn("FRONTEND_DIR=frontend", written)
            self.assertIn("PORT_SPACING=11", written)
            self.assertNotIn("ENVCTL_DEFAULT_MODE=main", written)

    def test_ignore_local_config_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".git" / "info").mkdir(parents=True, exist_ok=True)

            updated_first, warning_first = ensure_local_config_ignored(repo)
            updated_second, warning_second = ensure_local_config_ignored(repo)
            exclude_text = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")

            self.assertTrue(updated_first)
            self.assertIsNone(warning_first)
            self.assertFalse(updated_second)
            self.assertIsNone(warning_second)
            self.assertEqual(exclude_text.count(".envctl"), 1)


if __name__ == "__main__":
    unittest.main()
