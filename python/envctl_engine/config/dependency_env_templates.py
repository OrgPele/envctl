from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from envctl_engine.shared.dependency_compose_assets import (
    default_supabase_anon_key,
    default_supabase_service_role_key,
)

CONFIG_DEPENDENCY_ENV_START = "# >>> envctl shared launch env >>>"
CONFIG_DEPENDENCY_ENV_END = "# <<< envctl shared launch env <<<"
CONFIG_BACKEND_DEPENDENCY_ENV_START = "# >>> envctl backend launch env >>>"
CONFIG_BACKEND_DEPENDENCY_ENV_END = "# <<< envctl backend launch env <<<"
CONFIG_FRONTEND_DEPENDENCY_ENV_START = "# >>> envctl frontend launch env >>>"
CONFIG_FRONTEND_DEPENDENCY_ENV_END = "# <<< envctl frontend launch env <<<"
CONFIG_MAIN_BACKEND_DEPENDENCY_ENV_START = "# >>> envctl main backend launch env >>>"
CONFIG_MAIN_BACKEND_DEPENDENCY_ENV_END = "# <<< envctl main backend launch env <<<"
CONFIG_MAIN_FRONTEND_DEPENDENCY_ENV_START = "# >>> envctl main frontend launch env >>>"
CONFIG_MAIN_FRONTEND_DEPENDENCY_ENV_END = "# <<< envctl main frontend launch env <<<"
CONFIG_TREES_BACKEND_DEPENDENCY_ENV_START = "# >>> envctl trees backend launch env >>>"
CONFIG_TREES_BACKEND_DEPENDENCY_ENV_END = "# <<< envctl trees backend launch env <<<"
CONFIG_TREES_FRONTEND_DEPENDENCY_ENV_START = "# >>> envctl trees frontend launch env >>>"
CONFIG_TREES_FRONTEND_DEPENDENCY_ENV_END = "# <<< envctl trees frontend launch env <<<"
LEGACY_CONFIG_DEPENDENCY_ENV_START = "# >>> envctl dependency env >>>"
LEGACY_CONFIG_DEPENDENCY_ENV_END = "# <<< envctl dependency env <<<"
LEGACY_CONFIG_BACKEND_DEPENDENCY_ENV_START = "# >>> envctl backend dependency env >>>"
LEGACY_CONFIG_BACKEND_DEPENDENCY_ENV_END = "# <<< envctl backend dependency env <<<"
LEGACY_CONFIG_FRONTEND_DEPENDENCY_ENV_START = "# >>> envctl frontend dependency env >>>"
LEGACY_CONFIG_FRONTEND_DEPENDENCY_ENV_END = "# <<< envctl frontend dependency env <<<"
_GENERIC_SERVICE_SECTION_RE = re.compile(
    r"# >>> envctl service (?P<service>[a-z][a-z0-9-]*) launch env >>>"
)
_GENERIC_MODE_SERVICE_SECTION_RE = re.compile(
    r"# >>> envctl (?P<mode>main|trees) service (?P<service>[a-z][a-z0-9-]*) launch env >>>"
)


@dataclass(slots=True, frozen=True)
class DependencyEnvTemplateEntry:
    name: str
    template: str
    line_number: int


def parse_dependency_env_section(text: str) -> tuple[DependencyEnvTemplateEntry, ...]:
    entries, _present, errors = _extract_dependency_env_section(text)
    if errors:
        raise ValueError("; ".join(errors))
    return entries


def render_default_dependency_env_section() -> str:
    lines = [
        CONFIG_DEPENDENCY_ENV_START,
        "# Legacy shared launch env; prefer backend/frontend sections below.",
        CONFIG_DEPENDENCY_ENV_END,
    ]
    return "\n".join(lines) + "\n"


def render_default_backend_dependency_env_section() -> str:
    lines = [
        CONFIG_BACKEND_DEPENDENCY_ENV_START,
        "DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}  # generic DB URL; e.g. postgresql://user:pass@host:5432/dbname",
        "REDIS_URL=${ENVCTL_SOURCE_REDIS_URL}  # Redis URL; e.g. redis://host:6379/0",
        "N8N_URL=${ENVCTL_SOURCE_N8N_URL}  # n8n base URL; e.g. http://localhost:5678",
        "SUPABASE_URL=${ENVCTL_SOURCE_SUPABASE_URL}  # Supabase base URL; e.g. http://localhost:54321",
        "SUPABASE_JWKS_URL=${ENVCTL_SOURCE_SUPABASE_JWKS_URL}  # backend-only JWT verification JWKS URL",
        "SUPABASE_JWT_SECRET=${ENVCTL_SOURCE_SUPABASE_JWT_SECRET}  # backend-only local JWT secret",
        "SUPABASE_SERVICE_ROLE_KEY=${ENVCTL_SOURCE_SUPABASE_SERVICE_ROLE_KEY}  # backend-only Admin API key",
        "SQLALCHEMY_DATABASE_URL=${ENVCTL_SOURCE_SQLALCHEMY_DATABASE_URL}  # SQLAlchemy sync URL; e.g. postgresql+psycopg://user:pass@host:5432/dbname",
        "ASYNC_DATABASE_URL=${ENVCTL_SOURCE_ASYNC_DATABASE_URL}  # SQLAlchemy async URL; e.g. postgresql+asyncpg://user:pass@host:5432/dbname",
        "# APP_DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}  # extra backend alias example",
        CONFIG_BACKEND_DEPENDENCY_ENV_END,
    ]
    return "\n".join(lines) + "\n"


def render_default_frontend_dependency_env_section() -> str:
    lines = [
        CONFIG_FRONTEND_DEPENDENCY_ENV_START,
        "# VITE_SUPABASE_URL=${ENVCTL_SOURCE_SUPABASE_URL}  # frontend-only Supabase URL",
        "# VITE_SUPABASE_ANON_KEY=${ENVCTL_SOURCE_SUPABASE_ANON_KEY}  # frontend-safe Supabase anon key",
        CONFIG_FRONTEND_DEPENDENCY_ENV_END,
    ]
    return "\n".join(lines) + "\n"


def render_default_dependency_env_sections() -> str:
    prelude = (
        "# Managed dependency startup parallelism can be configured here too.",
        "# Linux defaults to parallel startup. macOS defaults to sequential startup",
        "# to avoid Docker Desktop port-publish stalls. Override either default with:",
        "# ENVCTL_REQUIREMENTS_PARALLEL=true",
        "# ENVCTL_REQUIREMENTS_PARALLEL_MAX=4",
        "",
        "# External dependency mode can be configured in this same .envctl file.",
        "# Default mode is managed: envctl starts enabled dependencies and projects localhost values.",
        "# Main mode auto-uses an external dependency when that dependency's own env vars exist",
        "# in shell env, .envctl, project root .env, backend .env, or frontend .env,",
        "# unless that dependency is already configured as managed/enabled.",
        "# Trees mode defaults to managed/internal dependencies unless external mode is explicit.",
        "# For one-off main runs that should ignore external env auto-detection, use",
        "# `envctl --main --managed-deps` or the alias `envctl --main --no-external-deps`.",
        "# To use externally running services, enable one or more external dependencies:",
        "# ENVCTL_EXTERNAL_DEPENDENCIES=supabase,redis,postgres,n8n",
        "# Or use one dependency at a time:",
        "# ENVCTL_DEPENDENCY_SUPABASE_MODE=external",
        "# ENVCTL_DEPENDENCY_REDIS_MODE=external",
        "# ENVCTL_DEPENDENCY_POSTGRES_MODE=external",
        "# ENVCTL_DEPENDENCY_N8N_MODE=external",
        "# External Supabase requires SUPABASE_URL or SUPABASE_PUBLIC_URL plus SUPABASE_ANON_KEY",
        "# or the frontend-safe VITE_SUPABASE_ANON_KEY alias.",
        "# External dependencies are actively probed at startup. Set",
        "# ENVCTL_EXTERNAL_DEPENDENCY_PROBE=false only when the dependency is reachable",
        "# from launched services but intentionally unreachable from the envctl host.",
        "# SUPABASE_URL=http://localhost:54321",
        "# SUPABASE_ANON_KEY=<external anon key>",
        "# SUPABASE_SERVICE_ROLE_KEY=<external service-role key; backend only>",
        "# SUPABASE_JWT_SECRET=<external JWT secret; backend only>",
        "# SUPABASE_JWKS_URL=${SUPABASE_URL}/auth/v1/.well-known/jwks.json",
        "# DATABASE_URL=postgresql+asyncpg://postgres:<password>@localhost:5432/postgres",
        "# REDIS_URL=redis://localhost:6379/0",
        "# N8N_URL=http://localhost:5678",
        "# Local managed Supabase defaults are local-only secrets:",
        "# SUPABASE_DB_PASSWORD=supabase-db-password",
        "# SUPABASE_JWT_SECRET=supabase-local-jwt-secret",
        "# SUPABASE_ANON_KEY=" + default_supabase_anon_key(),
        "# SUPABASE_SERVICE_ROLE_KEY=" + default_supabase_service_role_key(),
        "",
        "# Launch env templates for services started by envctl.",
        "# Backend goes only to the backend process. Frontend goes only to the frontend process.",
    )
    sections = (
        render_default_backend_dependency_env_section().rstrip("\n"),
        render_default_frontend_dependency_env_section().rstrip("\n"),
    )
    return "\n".join(prelude) + "\n\n" + "\n\n".join(sections) + "\n"


def render_legacy_default_dependency_env_sections() -> str:
    prelude = (
        "# The shared section below applies to both backend and frontend launches.",
        "# The backend/frontend sections below it are service-specific.",
        "# For a given service, envctl emits only the vars defined in the sections that apply to that service.",
    )
    sections = (
        "\n".join(
            (
                LEGACY_CONFIG_DEPENDENCY_ENV_START,
                "# Primary database connection string for apps that expect a generic DB URL.",
                "# Usually looks like: postgresql://user:pass@host:5432/dbname",
                "DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}",
                "# Redis connection string for cache, queues, and pub/sub clients.",
                "# Usually looks like: redis://host:6379/0",
                "REDIS_URL=${ENVCTL_SOURCE_REDIS_URL}",
                "# Base HTTP URL for your local n8n instance.",
                "# Usually looks like: http://localhost:5678",
                "N8N_URL=${ENVCTL_SOURCE_N8N_URL}",
                "# Base HTTP URL for local Supabase APIs and Studio integrations.",
                "# Usually looks like: http://localhost:54321",
                "SUPABASE_URL=${ENVCTL_SOURCE_SUPABASE_URL}",
                "# SQLAlchemy sync driver URL, commonly used by sync app/database layers.",
                "# Usually looks like: postgresql+psycopg://user:pass@host:5432/dbname",
                "SQLALCHEMY_DATABASE_URL=${ENVCTL_SOURCE_SQLALCHEMY_DATABASE_URL}",
                "# SQLAlchemy async driver URL, commonly used by async Python services.",
                "# Usually looks like: postgresql+asyncpg://user:pass@host:5432/dbname",
                "ASYNC_DATABASE_URL=${ENVCTL_SOURCE_ASYNC_DATABASE_URL}",
                LEGACY_CONFIG_DEPENDENCY_ENV_END,
            )
        ),
        "\n".join(
            (
                LEGACY_CONFIG_BACKEND_DEPENDENCY_ENV_START,
                "# Add backend-only dependency aliases/templates here.",
                "# Example:",
                "# APP_DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}",
                LEGACY_CONFIG_BACKEND_DEPENDENCY_ENV_END,
            )
        ),
        "\n".join(
            (
                LEGACY_CONFIG_FRONTEND_DEPENDENCY_ENV_START,
                "# Add frontend-only dependency aliases/templates here.",
                "# Example:",
                "# VITE_SUPABASE_URL=${ENVCTL_SOURCE_SUPABASE_URL}",
                LEGACY_CONFIG_FRONTEND_DEPENDENCY_ENV_END,
            )
        ),
    )
    return "\n".join(prelude) + "\n\n" + "\n\n".join(sections) + "\n"


def ensure_dependency_env_section(text: str) -> str:
    existing = text or ""
    upgraded = _upgrade_legacy_default_dependency_env_sections(existing)
    if upgraded != existing:
        return upgraded
    if _any_dependency_env_section_markers_present(existing):
        return existing
    section = render_default_dependency_env_sections().rstrip("\n")
    stripped = existing.rstrip("\n")
    if not stripped:
        return section + "\n"
    return stripped + "\n\n" + section + "\n"


def _upgrade_legacy_default_dependency_env_sections(text: str) -> str:
    existing = text or ""
    legacy_block = render_legacy_default_dependency_env_sections().rstrip("\n")
    new_block = render_default_dependency_env_sections().rstrip("\n")
    if legacy_block in existing:
        return existing.replace(legacy_block, new_block, 1)
    return existing


def _dependency_env_section_markers_present(text: str) -> bool:
    return any(marker in text for marker in _dependency_env_markers())


def _backend_dependency_env_section_markers_present(text: str) -> bool:
    return any(marker in text for marker in _backend_dependency_env_markers())


def _frontend_dependency_env_section_markers_present(text: str) -> bool:
    return any(marker in text for marker in _frontend_dependency_env_markers())


def _mode_service_dependency_env_section_markers_present(text: str) -> bool:
    return any(marker in text for marker in _mode_service_dependency_env_markers())


def _generic_service_dependency_env_section_markers_present(text: str) -> bool:
    return bool(_GENERIC_SERVICE_SECTION_RE.search(text) or _GENERIC_MODE_SERVICE_SECTION_RE.search(text))


def _any_dependency_env_section_markers_present(text: str) -> bool:
    return bool(
        _dependency_env_section_markers_present(text)
        or _backend_dependency_env_section_markers_present(text)
        or _frontend_dependency_env_section_markers_present(text)
        or _mode_service_dependency_env_section_markers_present(text)
        or _generic_service_dependency_env_section_markers_present(text)
    )


def _dependency_env_section_bounds(text: str) -> tuple[int, int] | None:
    return _template_section_bounds(text, CONFIG_DEPENDENCY_ENV_START, CONFIG_DEPENDENCY_ENV_END)


def _backend_dependency_env_section_bounds(text: str) -> tuple[int, int] | None:
    return _template_section_bounds(text, CONFIG_BACKEND_DEPENDENCY_ENV_START, CONFIG_BACKEND_DEPENDENCY_ENV_END)


def _frontend_dependency_env_section_bounds(text: str) -> tuple[int, int] | None:
    return _template_section_bounds(text, CONFIG_FRONTEND_DEPENDENCY_ENV_START, CONFIG_FRONTEND_DEPENDENCY_ENV_END)


def _template_section_bounds(text: str, start_marker: str, end_marker: str) -> tuple[int, int] | None:
    start = text.find(start_marker)
    if start == -1:
        return None
    end = text.find(end_marker, start)
    if end == -1:
        return None
    return start, end + len(end_marker)


def _extract_dependency_env_section(text: str) -> tuple[tuple[DependencyEnvTemplateEntry, ...], bool, tuple[str, ...]]:
    return _extract_template_section(
        text,
        marker_pairs=_dependency_env_marker_pairs(),
        section_label="shared launch env",
    )


def _extract_backend_dependency_env_section(
    text: str,
) -> tuple[tuple[DependencyEnvTemplateEntry, ...], bool, tuple[str, ...]]:
    return _extract_template_section(
        text,
        marker_pairs=_backend_dependency_env_marker_pairs(),
        section_label="backend launch env",
    )


def _extract_frontend_dependency_env_section(
    text: str,
) -> tuple[tuple[DependencyEnvTemplateEntry, ...], bool, tuple[str, ...]]:
    return _extract_template_section(
        text,
        marker_pairs=_frontend_dependency_env_marker_pairs(),
        section_label="frontend launch env",
    )


def _extract_mode_service_dependency_env_section(
    text: str,
    *,
    mode: Literal["main", "trees"],
    service_name: Literal["backend", "frontend"],
) -> tuple[tuple[DependencyEnvTemplateEntry, ...], bool, tuple[str, ...]]:
    return _extract_template_section(
        text,
        marker_pairs=_mode_service_dependency_env_marker_pairs(mode=mode, service_name=service_name),
        section_label=f"{mode} {service_name} launch env",
    )


def _extract_generic_service_dependency_env_sections(
    text: str,
) -> tuple[dict[str, tuple[DependencyEnvTemplateEntry, ...]], dict[str, bool], dict[str, tuple[str, ...]]]:
    templates: dict[str, tuple[DependencyEnvTemplateEntry, ...]] = {}
    present: dict[str, bool] = {}
    errors: dict[str, tuple[str, ...]] = {}
    for match in _GENERIC_SERVICE_SECTION_RE.finditer(text):
        service = match.group("service")
        end_marker = f"# <<< envctl service {service} launch env <<<"
        entries, section_present, section_errors = _extract_template_section(
            text,
            marker_pairs=((match.group(0), end_marker),),
            section_label=f"service {service} launch env",
        )
        present[service] = section_present
        templates[service] = entries
        errors[service] = section_errors
    return templates, present, errors


def _extract_generic_mode_service_dependency_env_sections(
    text: str,
) -> tuple[
    dict[tuple[str, str], tuple[DependencyEnvTemplateEntry, ...]],
    dict[tuple[str, str], bool],
    dict[tuple[str, str], tuple[str, ...]],
]:
    templates: dict[tuple[str, str], tuple[DependencyEnvTemplateEntry, ...]] = {}
    present: dict[tuple[str, str], bool] = {}
    errors: dict[tuple[str, str], tuple[str, ...]] = {}
    for match in _GENERIC_MODE_SERVICE_SECTION_RE.finditer(text):
        mode = match.group("mode")
        service = match.group("service")
        key = (mode, service)
        end_marker = f"# <<< envctl {mode} service {service} launch env <<<"
        entries, section_present, section_errors = _extract_template_section(
            text,
            marker_pairs=((match.group(0), end_marker),),
            section_label=f"{mode} service {service} launch env",
        )
        present[key] = section_present
        templates[key] = entries
        errors[key] = section_errors
    return templates, present, errors


def _extract_template_section(
    text: str,
    *,
    marker_pairs: tuple[tuple[str, str], ...],
    section_label: str,
) -> tuple[tuple[DependencyEnvTemplateEntry, ...], bool, tuple[str, ...]]:
    start_present = any(start_marker in text for start_marker, _ in marker_pairs)
    end_present = any(end_marker in text for _, end_marker in marker_pairs)
    if start_present and not end_present:
        return (), True, (f"invalid {section_label} section: missing closing marker",)
    if end_present and not start_present:
        return (), True, (f"invalid {section_label} section: missing opening marker",)
    bounds = None
    chosen_markers: tuple[str, str] | None = None
    for start_marker, end_marker in marker_pairs:
        bounds = _template_section_bounds(text, start_marker, end_marker)
        if bounds is not None:
            chosen_markers = (start_marker, end_marker)
            break
    if bounds is None:
        return (), False, ()
    start, end = bounds
    assert chosen_markers is not None
    section_body = text[start + len(chosen_markers[0]) : end - len(chosen_markers[1])]
    entries: list[DependencyEnvTemplateEntry] = []
    errors: list[str] = []
    section_line_offset = text[: start + len(chosen_markers[0])].count("\n")
    for index, raw_line in enumerate(section_body.splitlines(), start=1):
        line_number = section_line_offset + index
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            errors.append(
                f"invalid {section_label} entry on line {line_number}: expected KEY=VALUE, got {raw_line.strip()!r}"
            )
            continue
        key, value = line.split("=", 1)
        name = key.strip()
        template = _strip_inline_template_comment(value.strip())
        if not name:
            errors.append(f"invalid {section_label} entry on line {line_number}: missing variable name")
            continue
        entries.append(DependencyEnvTemplateEntry(name=name, template=template, line_number=line_number))
    return tuple(entries), True, tuple(errors)


def _dependency_env_markers() -> tuple[str, ...]:
    return (
        CONFIG_DEPENDENCY_ENV_START,
        CONFIG_DEPENDENCY_ENV_END,
        LEGACY_CONFIG_DEPENDENCY_ENV_START,
        LEGACY_CONFIG_DEPENDENCY_ENV_END,
    )


def _backend_dependency_env_markers() -> tuple[str, ...]:
    return (
        CONFIG_BACKEND_DEPENDENCY_ENV_START,
        CONFIG_BACKEND_DEPENDENCY_ENV_END,
        LEGACY_CONFIG_BACKEND_DEPENDENCY_ENV_START,
        LEGACY_CONFIG_BACKEND_DEPENDENCY_ENV_END,
    )


def _frontend_dependency_env_markers() -> tuple[str, ...]:
    return (
        CONFIG_FRONTEND_DEPENDENCY_ENV_START,
        CONFIG_FRONTEND_DEPENDENCY_ENV_END,
        LEGACY_CONFIG_FRONTEND_DEPENDENCY_ENV_START,
        LEGACY_CONFIG_FRONTEND_DEPENDENCY_ENV_END,
    )


def _mode_service_dependency_env_markers() -> tuple[str, ...]:
    return (
        CONFIG_MAIN_BACKEND_DEPENDENCY_ENV_START,
        CONFIG_MAIN_BACKEND_DEPENDENCY_ENV_END,
        CONFIG_MAIN_FRONTEND_DEPENDENCY_ENV_START,
        CONFIG_MAIN_FRONTEND_DEPENDENCY_ENV_END,
        CONFIG_TREES_BACKEND_DEPENDENCY_ENV_START,
        CONFIG_TREES_BACKEND_DEPENDENCY_ENV_END,
        CONFIG_TREES_FRONTEND_DEPENDENCY_ENV_START,
        CONFIG_TREES_FRONTEND_DEPENDENCY_ENV_END,
    )


def _dependency_env_marker_pairs() -> tuple[tuple[str, str], ...]:
    return (
        (CONFIG_DEPENDENCY_ENV_START, CONFIG_DEPENDENCY_ENV_END),
        (LEGACY_CONFIG_DEPENDENCY_ENV_START, LEGACY_CONFIG_DEPENDENCY_ENV_END),
    )


def _backend_dependency_env_marker_pairs() -> tuple[tuple[str, str], ...]:
    return (
        (CONFIG_BACKEND_DEPENDENCY_ENV_START, CONFIG_BACKEND_DEPENDENCY_ENV_END),
        (LEGACY_CONFIG_BACKEND_DEPENDENCY_ENV_START, LEGACY_CONFIG_BACKEND_DEPENDENCY_ENV_END),
    )


def _frontend_dependency_env_marker_pairs() -> tuple[tuple[str, str], ...]:
    return (
        (CONFIG_FRONTEND_DEPENDENCY_ENV_START, CONFIG_FRONTEND_DEPENDENCY_ENV_END),
        (LEGACY_CONFIG_FRONTEND_DEPENDENCY_ENV_START, LEGACY_CONFIG_FRONTEND_DEPENDENCY_ENV_END),
    )


def _mode_service_dependency_env_marker_pairs(
    *,
    mode: Literal["main", "trees"],
    service_name: Literal["backend", "frontend"],
) -> tuple[tuple[str, str], ...]:
    marker_map = {
        ("main", "backend"): (CONFIG_MAIN_BACKEND_DEPENDENCY_ENV_START, CONFIG_MAIN_BACKEND_DEPENDENCY_ENV_END),
        ("main", "frontend"): (CONFIG_MAIN_FRONTEND_DEPENDENCY_ENV_START, CONFIG_MAIN_FRONTEND_DEPENDENCY_ENV_END),
        ("trees", "backend"): (CONFIG_TREES_BACKEND_DEPENDENCY_ENV_START, CONFIG_TREES_BACKEND_DEPENDENCY_ENV_END),
        ("trees", "frontend"): (CONFIG_TREES_FRONTEND_DEPENDENCY_ENV_START, CONFIG_TREES_FRONTEND_DEPENDENCY_ENV_END),
    }
    return (marker_map[(mode, service_name)],)


def _strip_template_sections(text: str) -> str:
    stripped = text
    stripped = _strip_generic_template_sections(stripped)
    for start_marker, end_marker in (
        *_dependency_env_marker_pairs(),
        *_backend_dependency_env_marker_pairs(),
        *_frontend_dependency_env_marker_pairs(),
        *_mode_service_dependency_env_marker_pairs(mode="main", service_name="backend"),
        *_mode_service_dependency_env_marker_pairs(mode="main", service_name="frontend"),
        *_mode_service_dependency_env_marker_pairs(mode="trees", service_name="backend"),
        *_mode_service_dependency_env_marker_pairs(mode="trees", service_name="frontend"),
    ):
        while True:
            bounds = _template_section_bounds(stripped, start_marker, end_marker)
            if bounds is None:
                break
            start, end = bounds
            stripped = stripped[:start] + stripped[end:]
    return stripped


def _strip_generic_template_sections(text: str) -> str:
    stripped = text
    changed = True
    while changed:
        changed = False
        for pattern, end_builder in (
            (_GENERIC_MODE_SERVICE_SECTION_RE, _generic_mode_service_end_marker),
            (_GENERIC_SERVICE_SECTION_RE, _generic_service_end_marker),
        ):
            match = pattern.search(stripped)
            if match is None:
                continue
            end_marker = end_builder(match)
            bounds = _template_section_bounds(stripped, match.group(0), end_marker)
            if bounds is None:
                continue
            start, end = bounds
            stripped = stripped[:start] + stripped[end:]
            changed = True
            break
    return stripped


def _generic_mode_service_end_marker(match: re.Match[str]) -> str:
    return f"# <<< envctl {match.group('mode')} service {match.group('service')} launch env <<<"


def _generic_service_end_marker(match: re.Match[str]) -> str:
    return f"# <<< envctl service {match.group('service')} launch env <<<"


def _strip_inline_template_comment(value: str) -> str:
    hash_index = value.find("#")
    while hash_index != -1:
        if hash_index > 0 and value[hash_index - 1].isspace():
            return value[:hash_index].rstrip()
        hash_index = value.find("#", hash_index + 1)
    return value
