from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
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

    def test_supabase_managed_env_defaults_to_jwt_shaped_auth_keys(self) -> None:
        env = supabase_managed_env(db_port=5432, public_port=54321, env={})

        self.assertEqual(env["SUPABASE_ANON_KEY"].count("."), 2)
        self.assertEqual(env["SUPABASE_SERVICE_ROLE_KEY"].count("."), 2)
        self.assertNotEqual(env["SUPABASE_ANON_KEY"], env["SUPABASE_SERVICE_ROLE_KEY"])
        self.assertNotEqual(env["SUPABASE_ANON_KEY"], "local-anon-key")
        self.assertNotEqual(env["SUPABASE_SERVICE_ROLE_KEY"], "local-service-role-key")

    def test_materialize_dependency_compose_copies_assets_and_writes_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_root = Path(tmpdir)
            materialized = materialize_dependency_compose(
                runtime_root=runtime_root,
                dependency_name="supabase",
                project_name="feature/a-1",
                compose_project_name="envctl-supabase-feature-a-1",
                env_values=supabase_managed_env(db_port=5432, public_port=54321, env={}),
            )

            self.assertTrue(materialized.compose_file.is_file())
            self.assertTrue(materialized.env_file.is_file())
            self.assertTrue((materialized.stack_root / "kong.yml").is_file())
            self.assertTrue((materialized.stack_root / "init" / "01-create-n8n-db.sql").is_file())
            env_text = materialized.env_file.read_text(encoding="utf-8")
            compose_text = materialized.compose_file.read_text(encoding="utf-8")
            self.assertIn("SUPABASE_DB_PORT=5432", env_text)
            self.assertIn("SUPABASE_PUBLIC_PORT=54321", env_text)
            self.assertIn("SUPABASE_PUBLIC_URL=http://localhost:54321", env_text)
            self.assertIn('"${SUPABASE_PUBLIC_PORT:-54321}:8000"', compose_text)
            self.assertEqual(compose_text.count("pull_policy: missing"), 3)

    def test_materialize_dependency_compose_repairs_stale_directories_at_file_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_root = Path(tmpdir)
            stack_root = runtime_root / "dependency_compose" / "supabase" / "main"
            (stack_root / "kong.yml").mkdir(parents=True)
            (stack_root / "kong.yml" / "kong.yml").write_text("stale nested kong config\n", encoding="utf-8")
            (stack_root / "init" / "01-create-n8n-db.sql").mkdir(parents=True)
            (stack_root / "init" / "01-create-n8n-db.sql" / "01-create-n8n-db.sql").write_text(
                "stale nested n8n bootstrap\n",
                encoding="utf-8",
            )
            (stack_root / "init" / "02-bootstrap-gotrue-auth.sql").mkdir(parents=True)
            (stack_root / "init" / "02-bootstrap-gotrue-auth.sql" / "02-bootstrap-gotrue-auth.sql").write_text(
                "stale nested auth bootstrap\n",
                encoding="utf-8",
            )

            materialized = materialize_dependency_compose(
                runtime_root=runtime_root,
                dependency_name="supabase",
                project_name="Main",
                compose_project_name="envctl-supabase-main",
                env_values=supabase_managed_env(db_port=5432, public_port=54321, env={}),
            )

            self.assertTrue((materialized.stack_root / "kong.yml").is_file())
            self.assertFalse((materialized.stack_root / "kong.yml" / "kong.yml").exists())
            self.assertTrue((materialized.stack_root / "init" / "01-create-n8n-db.sql").is_file())
            self.assertFalse(
                (materialized.stack_root / "init" / "01-create-n8n-db.sql" / "01-create-n8n-db.sql").exists()
            )
            self.assertTrue((materialized.stack_root / "init" / "02-bootstrap-gotrue-auth.sql").is_file())
            self.assertFalse(
                (materialized.stack_root / "init" / "02-bootstrap-gotrue-auth.sql" / "02-bootstrap-gotrue-auth.sql").exists()
            )


if __name__ == "__main__":
    unittest.main()
