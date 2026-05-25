from __future__ import annotations

import unittest
from pathlib import Path

from envctl_engine.shared.dependency_compose_assets import (
    DEFAULT_SUPABASE_JWT_SECRET,
    default_supabase_anon_key,
    default_supabase_service_role_key,
)
from envctl_engine.requirements.supabase_lifecycle.native_db_commands import (
    SupabaseNativeDbCommandBuilder,
    supabase_native_db_image,
)


class SupabaseNativeDbCommandTests(unittest.TestCase):
    def test_build_create_command_uses_default_auth_and_mount_contract(self) -> None:
        command = SupabaseNativeDbCommandBuilder(
            compose_root=Path("/repo/deps/supabase"),
            container_name="main-supabase-db-1",
            volume_name="main_supabase_db_data",
            db_port=5435,
            image="supabase/postgres:15.1.0.147",
            env={},
        ).build_create_command()

        self.assertEqual(command[:3], ["create", "--name", "main-supabase-db-1"])
        self.assertIn("POSTGRES_PASSWORD=supabase-db-password", command)
        self.assertIn(f"JWT_SECRET={DEFAULT_SUPABASE_JWT_SECRET}", command)
        self.assertIn(f"ANON_KEY={default_supabase_anon_key(secret=DEFAULT_SUPABASE_JWT_SECRET)}", command)
        self.assertIn(
            f"SERVICE_ROLE_KEY={default_supabase_service_role_key(secret=DEFAULT_SUPABASE_JWT_SECRET)}",
            command,
        )
        self.assertIn("5435:5432", command)
        self.assertIn("main_supabase_db_data:/var/lib/postgresql/data", command)
        self.assertIn(
            "/repo/deps/supabase/init/01-create-n8n-db.sql:"
            "/docker-entrypoint-initdb.d/01-create-n8n-db.sql:ro",
            command,
        )
        self.assertIn(
            "/repo/deps/supabase/init/02-bootstrap-gotrue-auth.sql:"
            "/docker-entrypoint-initdb.d/02-bootstrap-gotrue-auth.sql:ro",
            command,
        )
        self.assertEqual(command[-1], "supabase/postgres:15.1.0.147")

    def test_build_create_command_honors_explicit_env_values(self) -> None:
        command = SupabaseNativeDbCommandBuilder(
            compose_root=Path("/repo/deps/supabase"),
            container_name="main-supabase-db-1",
            volume_name="main_supabase_db_data",
            db_port=5435,
            image="custom/postgres:local",
            env={
                "SUPABASE_DB_PASSWORD": "secret-db",
                "SUPABASE_JWT_SECRET": "jwt",
                "SUPABASE_ANON_KEY": "anon",
                "SUPABASE_SERVICE_ROLE_KEY": "service",
            },
        ).build_create_command()

        self.assertIn("POSTGRES_PASSWORD=secret-db", command)
        self.assertIn("JWT_SECRET=jwt", command)
        self.assertIn("ANON_KEY=anon", command)
        self.assertIn("SERVICE_ROLE_KEY=service", command)
        self.assertEqual(command[-1], "custom/postgres:local")

    def test_supabase_native_db_image_honors_env_override(self) -> None:
        self.assertEqual(supabase_native_db_image({}), "supabase/postgres:15.1.0.147")
        self.assertEqual(
            supabase_native_db_image({"SUPABASE_DB_IMAGE": "custom/postgres:local"}),
            "custom/postgres:local",
        )


if __name__ == "__main__":
    unittest.main()
