from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from envctl_engine.shared.dependency_compose_assets import (
    DEFAULT_SUPABASE_JWT_SECRET,
    default_supabase_anon_key,
    default_supabase_service_role_key,
)

DEFAULT_SUPABASE_DB_IMAGE = "supabase/postgres:15.1.0.147"


def supabase_native_db_image(env: Mapping[str, str] | None) -> str:
    return (env or {}).get("SUPABASE_DB_IMAGE") or DEFAULT_SUPABASE_DB_IMAGE


@dataclass(frozen=True, slots=True)
class SupabaseNativeDbCommandBuilder:
    compose_root: Path
    container_name: str
    volume_name: str
    db_port: int
    image: str
    env: Mapping[str, str] | None

    def build_create_command(self) -> list[str]:
        env_values = self.env or {}
        jwt_secret = env_values.get("SUPABASE_JWT_SECRET") or DEFAULT_SUPABASE_JWT_SECRET
        anon_key = env_values.get("SUPABASE_ANON_KEY") or default_supabase_anon_key(secret=jwt_secret)
        service_role_key = env_values.get("SUPABASE_SERVICE_ROLE_KEY") or default_supabase_service_role_key(
            secret=jwt_secret
        )
        return [
            "create",
            "--name",
            self.container_name,
            "-e",
            f"POSTGRES_PASSWORD={env_values.get('SUPABASE_DB_PASSWORD', 'supabase-db-password')}",
            "-e",
            "POSTGRES_DB=postgres",
            "-e",
            "POSTGRES_USER=postgres",
            "-e",
            f"JWT_SECRET={jwt_secret}",
            "-e",
            f"ANON_KEY={anon_key}",
            "-e",
            f"SERVICE_ROLE_KEY={service_role_key}",
            "-p",
            f"{self.db_port}:5432",
            "-v",
            f"{self.volume_name}:/var/lib/postgresql/data",
            "-v",
            (
                f"{self.compose_root / 'init' / '01-create-n8n-db.sql'}:"
                "/docker-entrypoint-initdb.d/01-create-n8n-db.sql:ro"
            ),
            "-v",
            (
                f"{self.compose_root / 'init' / '02-bootstrap-gotrue-auth.sql'}:"
                "/docker-entrypoint-initdb.d/02-bootstrap-gotrue-auth.sql:ro"
            ),
            self.image,
        ]
