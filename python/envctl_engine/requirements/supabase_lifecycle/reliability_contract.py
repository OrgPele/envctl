from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from envctl_engine.shared.dependency_compose_assets import dependency_compose_asset_dir


@dataclass(slots=True)
class SupabaseReliabilityContract:
    ok: bool
    fingerprint: str
    errors: list[str]
    compose_path: Path | None
    compatible_fingerprints: tuple[str, ...] = ()


def evaluate_supabase_reliability_contract(project_root: Path) -> SupabaseReliabilityContract:
    compose_root = project_root / "supabase"
    compose_path = compose_root / "docker-compose.yml"
    if not compose_path.is_file():
        return SupabaseReliabilityContract(
            ok=False,
            fingerprint="missing",
            errors=["missing supabase compose file: supabase/docker-compose.yml"],
            compose_path=compose_path,
        )

    try:
        compose_text = compose_path.read_text(encoding="utf-8")
    except OSError as exc:
        return SupabaseReliabilityContract(
            ok=False,
            fingerprint="unreadable",
            errors=[f"failed reading supabase compose file: {exc}"],
            compose_path=compose_path,
        )

    errors: list[str] = []

    if _has_static_network_name(compose_text):
        errors.append("supabase compose defines static network name; use project-scoped network names instead")

    if not _contains_search_path_contract(compose_text):
        errors.append("missing GOTRUE_DB_DATABASE_URL search_path contract (?search_path=auth,public)")
    if not _contains_auth_namespace_var(compose_text, "GOTRUE_DB_NAMESPACE"):
        errors.append("missing GOTRUE_DB_NAMESPACE=auth")
    if not _contains_auth_namespace_var(compose_text, "DB_NAMESPACE"):
        errors.append("missing DB_NAMESPACE=auth")

    if "02-bootstrap-gotrue-auth.sql" not in compose_text:
        errors.append("missing mount for 02-bootstrap-gotrue-auth.sql")
    if "01-create-n8n-db.sql" not in compose_text:
        errors.append("missing mount for 01-create-n8n-db.sql")
    if "kong.yml" not in compose_text:
        errors.append("missing mount for kong.yml")

    errors.extend(_unsafe_mount_path_errors(compose_text))

    fingerprint = _fingerprint_contract_inputs(compose_root, compose_text=compose_text)
    return SupabaseReliabilityContract(
        ok=not errors,
        fingerprint=fingerprint,
        errors=errors,
        compose_path=compose_path,
        compatible_fingerprints=_compatible_contract_fingerprints(
            compose_root,
            compose_text=compose_text,
            canonical_fingerprint=fingerprint,
        ),
    )


def read_fingerprint(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = payload.get("fingerprint")
    return str(value) if isinstance(value, str) and value.strip() else None


def write_fingerprint(path: Path, *, fingerprint: str, project_root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fingerprint": fingerprint,
        "project_root": str(project_root),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def evaluate_managed_supabase_reliability_contract() -> SupabaseReliabilityContract:
    compose_root = dependency_compose_asset_dir("supabase")
    compose_path = compose_root / "docker-compose.yml"
    if not compose_path.is_file():
        return SupabaseReliabilityContract(
            ok=False,
            fingerprint="missing",
            errors=[f"missing envctl managed supabase compose file: {compose_path}"],
            compose_path=compose_path,
        )
    try:
        compose_text = compose_path.read_text(encoding="utf-8")
    except OSError as exc:
        return SupabaseReliabilityContract(
            ok=False,
            fingerprint="unreadable",
            errors=[f"failed reading envctl managed supabase compose file: {exc}"],
            compose_path=compose_path,
        )
    errors: list[str] = []
    if _has_static_network_name(compose_text):
        errors.append("supabase compose defines static network name; use project-scoped network names instead")
    if not _contains_search_path_contract(compose_text):
        errors.append("missing GOTRUE_DB_DATABASE_URL search_path contract (?search_path=auth,public)")
    if not _contains_auth_namespace_var(compose_text, "GOTRUE_DB_NAMESPACE"):
        errors.append("missing GOTRUE_DB_NAMESPACE=auth")
    if not _contains_auth_namespace_var(compose_text, "DB_NAMESPACE"):
        errors.append("missing DB_NAMESPACE=auth")
    if "02-bootstrap-gotrue-auth.sql" not in compose_text:
        errors.append("missing mount for 02-bootstrap-gotrue-auth.sql")
    if "01-create-n8n-db.sql" not in compose_text:
        errors.append("missing mount for 01-create-n8n-db.sql")
    if "kong.yml" not in compose_text:
        errors.append("missing mount for kong.yml")
    errors.extend(_unsafe_mount_path_errors(compose_text))
    fingerprint = _fingerprint_contract_inputs(compose_root, compose_text=compose_text)
    return SupabaseReliabilityContract(
        ok=not errors,
        fingerprint=fingerprint,
        errors=errors,
        compose_path=compose_path,
        compatible_fingerprints=_compatible_contract_fingerprints(
            compose_root,
            compose_text=compose_text,
            canonical_fingerprint=fingerprint,
        ),
    )


def _fingerprint_contract_inputs(compose_root: Path, *, compose_text: str) -> str:
    return _fingerprint_contract_hash(compose_root, compose_text=_fingerprint_relevant_compose_text(compose_text))


def _fingerprint_contract_hash(compose_root: Path, *, compose_text: str) -> str:
    hasher = hashlib.sha256()
    hasher.update(compose_text.encode("utf-8"))
    for rel in (
        Path("kong.yml"),
        Path("init/01-create-n8n-db.sql"),
        Path("init/02-bootstrap-gotrue-auth.sql"),
    ):
        path = compose_root / rel
        hasher.update(str(rel).encode("utf-8"))
        if path.is_file():
            try:
                hasher.update(path.read_bytes())
            except OSError:
                hasher.update(b"<unreadable>")
        else:
            hasher.update(b"<missing>")
    return hasher.hexdigest()


def _compatible_contract_fingerprints(
    compose_root: Path,
    *,
    compose_text: str,
    canonical_fingerprint: str,
) -> tuple[str, ...]:
    candidates: list[str] = []
    for candidate_text in (
        compose_text,
        _fingerprint_relevant_compose_text_legacy_pull_policy_only(compose_text),
        _legacy_managed_supabase_healthcheck_text(compose_text),
        _fingerprint_relevant_compose_text_legacy_pull_policy_only(
            _legacy_managed_supabase_healthcheck_text(compose_text)
        ),
    ):
        candidate = _fingerprint_contract_hash(compose_root, compose_text=candidate_text)
        if candidate != canonical_fingerprint and candidate not in candidates:
            candidates.append(candidate)
    return tuple(candidates)


def _fingerprint_relevant_compose_text(compose_text: str) -> str:
    lines = []
    skip_indent: int | None = None
    for line in compose_text.splitlines():
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if skip_indent is not None:
            if stripped and indent > skip_indent:
                continue
            skip_indent = None
        if stripped.startswith("pull_policy:"):
            continue
        if stripped == "healthcheck:" or stripped.startswith("healthcheck: "):
            skip_indent = indent
            continue
        lines.append(line.rstrip())
    return "\n".join(lines) + "\n"


def _fingerprint_relevant_compose_text_legacy_pull_policy_only(compose_text: str) -> str:
    lines = []
    for line in compose_text.splitlines():
        if line.strip().startswith("pull_policy:"):
            continue
        lines.append(line.rstrip())
    return "\n".join(lines) + "\n"


def _legacy_managed_supabase_healthcheck_text(compose_text: str) -> str:
    return (
        compose_text.replace("interval: 1s", "interval: 10s")
        .replace("timeout: 2s", "timeout: 5s")
        .replace("retries: 30", "retries: 10")
    )


def _contains_search_path_contract(compose_text: str) -> bool:
    pattern = re.compile(r"GOTRUE_DB_DATABASE_URL\s*[:=]\s*['\"]?[^'\"\n]*search_path=auth,public", re.IGNORECASE)
    return bool(pattern.search(compose_text))


def _contains_auth_namespace_var(compose_text: str, key: str) -> bool:
    pattern = re.compile(rf"{re.escape(key)}\s*[:=]\s*['\"]?auth(?:['\"]|\s|$)", re.IGNORECASE)
    return bool(pattern.search(compose_text))


def _has_static_network_name(compose_text: str) -> bool:
    lines = compose_text.splitlines()
    in_networks = False
    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not in_networks:
            if stripped == "networks:":
                in_networks = True
            continue
        if line and not line.startswith((" ", "\t")):
            break
        if re.search(r"^\s*name\s*:\s*[^$].+", line):
            return True
    return False


def _unsafe_mount_path_errors(compose_text: str) -> list[str]:
    errors: list[str] = []
    for marker in ("kong.yml", "01-create-n8n-db.sql", "02-bootstrap-gotrue-auth.sql"):
        for line in compose_text.splitlines():
            if marker not in line:
                continue
            mount = _extract_mount_source(line)
            if mount is None:
                continue
            if mount.startswith("/"):
                errors.append(f"unsafe absolute mount for {marker}: {mount}")
    return errors


def _extract_mount_source(line: str) -> str | None:
    # Matches compose short syntax: - ./path/file:/container/path[:mode]
    match = re.search(r"^\s*-\s*([^:\s]+):", line)
    if not match:
        return None
    return match.group(1).strip()


