from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(slots=True)
class MaterializedDependencyCompose:
    dependency_name: str
    stack_root: Path
    compose_file: Path
    env_file: Path
    compose_project_name: str
    asset_root: Path


def dependency_compose_assets_root() -> Path:
    module_path = Path(__file__).resolve()
    candidates = (
        module_path.parent / "assets" / "dependency_compose",
        module_path.parent.parent / "assets" / "dependency_compose",
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[1]


def dependency_compose_asset_dir(dependency_name: str) -> Path:
    return dependency_compose_assets_root() / str(dependency_name).strip().lower()


def materialize_dependency_compose(
    *,
    runtime_root: Path,
    dependency_name: str,
    project_name: str,
    compose_project_name: str,
    env_values: Mapping[str, str],
) -> MaterializedDependencyCompose:
    asset_root = dependency_compose_asset_dir(dependency_name)
    if not asset_root.is_dir():
        raise FileNotFoundError(f"missing envctl dependency compose asset: {dependency_name}")

    safe_project = _safe_name(project_name)
    stack_root = runtime_root / "dependency_compose" / str(dependency_name).strip().lower() / safe_project
    stack_root.mkdir(parents=True, exist_ok=True)
    _sync_asset_tree(asset_root, stack_root)

    env_file = stack_root / ".env"
    env_lines = [f"{key}={value}" for key, value in sorted(env_values.items())]
    env_file.write_text("\n".join(env_lines) + "\n", encoding="utf-8")

    compose_file = stack_root / "docker-compose.yml"
    return MaterializedDependencyCompose(
        dependency_name=str(dependency_name).strip().lower(),
        stack_root=stack_root,
        compose_file=compose_file,
        env_file=env_file,
        compose_project_name=compose_project_name,
        asset_root=asset_root,
    )


def supabase_managed_env(*, db_port: int, env: Mapping[str, str] | None = None) -> dict[str, str]:
    values = dict(env or {})
    db_password = (
        values.get("SUPABASE_DB_PASSWORD")
        or values.get("DB_PASSWORD")
        or "supabase-db-password"
    )
    public_url = values.get("SUPABASE_PUBLIC_URL") or f"http://localhost:{db_port}"
    return {
        "SUPABASE_DB_PORT": str(int(db_port)),
        "SUPABASE_DB_PASSWORD": db_password,
        "SUPABASE_PUBLIC_URL": public_url,
        "SUPABASE_JWT_SECRET": values.get("SUPABASE_JWT_SECRET", "supabase-local-jwt-secret"),
        "SUPABASE_ANON_KEY": values.get("SUPABASE_ANON_KEY", "local-anon-key"),
        "SUPABASE_SERVICE_ROLE_KEY": values.get("SUPABASE_SERVICE_ROLE_KEY", "local-service-role-key"),
        "SUPABASE_DB_IMAGE": values.get("SUPABASE_DB_IMAGE", "supabase/postgres:15.1.0.147"),
        "SUPABASE_AUTH_IMAGE": values.get("SUPABASE_AUTH_IMAGE", "supabase/gotrue:v2.150.0"),
        "SUPABASE_KONG_IMAGE": values.get("SUPABASE_KONG_IMAGE", "kong:2.8.1"),
    }


def _safe_name(value: str) -> str:
    text = str(value).strip()
    if not text:
        return "project"
    chars: list[str] = []
    previous_dash = False
    for ch in text.lower():
        if ch.isalnum():
            chars.append(ch)
            previous_dash = False
            continue
        if not previous_dash:
            chars.append("-")
            previous_dash = True
    return "".join(chars).strip("-") or "project"


def _sync_asset_tree(source: Path, destination: Path) -> None:
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
