from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.shared.dependency_compose_assets import (  # noqa: E402
    dependency_compose_asset_dir,
    materialize_dependency_compose,
    supabase_managed_env,
)


class DependencyComposeAssetsTests(unittest.TestCase):
    def test_dependency_asset_dirs_exist_for_all_managed_dependencies(self) -> None:
        for dependency_name in ("postgres", "redis", "n8n", "supabase"):
            asset_dir = dependency_compose_asset_dir(dependency_name)
            self.assertTrue(asset_dir.is_dir(), dependency_name)
            self.assertTrue((asset_dir / "docker-compose.yml").is_file(), dependency_name)

    def test_materialize_dependency_compose_copies_assets_and_writes_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_root = Path(tmpdir)
            materialized = materialize_dependency_compose(
                runtime_root=runtime_root,
                dependency_name="supabase",
                project_name="feature/a-1",
                compose_project_name="envctl-supabase-feature-a-1",
                env_values=supabase_managed_env(db_port=5432, env={}),
            )

            self.assertTrue(materialized.compose_file.is_file())
            self.assertTrue(materialized.env_file.is_file())
            self.assertTrue((materialized.stack_root / "kong.yml").is_file())
            self.assertTrue((materialized.stack_root / "init" / "01-create-n8n-db.sql").is_file())
            self.assertIn("SUPABASE_DB_PORT=5432", materialized.env_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
