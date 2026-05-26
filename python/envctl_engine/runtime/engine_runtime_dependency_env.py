from __future__ import annotations

import re
from typing import Any, Mapping

from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.requirements.external import external_dependency_project_env
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RequirementsResult


_ENV_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TEMPLATE_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def service_env_overlays(
    runtime: Any,
    *,
    service_name: str,
    base_env: Mapping[str, str],
) -> dict[str, str]:
    normalized_service = str(service_name or "").strip().upper().replace("-", "_")
    if not normalized_service:
        return {}
    prefix = f"ENVCTL_{normalized_service}_ENV__"
    raw_sources: list[Mapping[object, object]] = []
    config_raw = getattr(getattr(runtime, "config", None), "raw", None)
    if isinstance(config_raw, Mapping):
        raw_sources.append(config_raw)
    runtime_env = getattr(runtime, "env", None)
    if isinstance(runtime_env, Mapping):
        raw_sources.append(runtime_env)
    source_env = dict(base_env)
    source_env.update(source_alias_env(source_env))
    overlays: dict[str, str] = {}
    for source in raw_sources:
        for key, value in source.items():
            name = str(key)
            if not name.startswith(prefix):
                continue
            target = name[len(prefix) :].strip()
            if not _ENV_VAR_NAME_RE.fullmatch(target):
                raise RuntimeError(f"service env overlay {name} must target a valid env var name")
            overlays[target] = _render_overlay_template(
                str(value),
                target=target,
                source_env={**source_env, **overlays},
            )
    return overlays


def source_alias_env(env: Mapping[str, str]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for key, value in env.items():
        name = str(key).strip()
        if not _ENV_VAR_NAME_RE.fullmatch(name):
            continue
        if name.startswith("ENVCTL_SOURCE_"):
            continue
        text = str(value)
        if text:
            aliases[f"ENVCTL_SOURCE_{name}"] = text
    return aliases


def _render_overlay_template(template: str, *, target: str, source_env: Mapping[str, str]) -> str:
    rendered = template
    sanitized = _TEMPLATE_VAR_RE.sub("", rendered)
    if "${" in sanitized:
        raise RuntimeError(f"service env overlay {target} has malformed placeholder syntax")
    for match in _TEMPLATE_VAR_RE.finditer(template):
        placeholder = str(match.group(1)).strip()
        if not _ENV_VAR_NAME_RE.fullmatch(placeholder):
            raise RuntimeError(f"service env overlay {target} has invalid placeholder {match.group(0)!r}")
        if placeholder not in source_env:
            raise RuntimeError(f"service env overlay {target} references unknown variable {placeholder}")
        rendered = rendered.replace(f"${{{placeholder}}}", str(source_env[placeholder]))
    return rendered


def dependency_projector_env(
    runtime: Any,
    context: Any,
    *,
    requirements: RequirementsResult,
    route: Route | None = None,
) -> dict[str, str]:
    env: dict[str, str] = {}
    project_disabled_launch_env = route is not None and route.flags.get("launch_dependencies") is False
    for definition in dependency_definitions():
        component = requirements.component(definition.id)
        if not bool(component.get("enabled", False)):
            if not project_disabled_launch_env or not _disabled_dependency_has_projectable_resources(
                definition, component=component, context=context
            ):
                continue
        if bool(component.get("external")) or str(component.get("runtime_status") or "").strip().lower() == "external":
            env.update(external_dependency_project_env(runtime, definition.id))
            continue
        if callable(definition.env_projector):
            env.update(
                definition.env_projector(runtime=runtime, context=context, requirements=requirements, route=route)
            )
    env.update(supabase_auth_user_source_env(runtime, requirements=requirements))
    return env


def _disabled_dependency_has_projectable_resources(
    definition: Any, *, component: Mapping[str, Any], context: Any
) -> bool:
    if _positive_int(component.get("final")):
        return True
    resources = component.get("resources")
    if isinstance(resources, Mapping) and any(_positive_int(value) for value in resources.values()):
        return True
    ports = getattr(context, "ports", {})
    if not isinstance(ports, Mapping):
        return False
    for resource in getattr(definition, "resources", ()) or ():
        plan = ports.get(getattr(resource, "legacy_port_key", ""))
        if _positive_int(getattr(plan, "final", None)):
            return True
    return False


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and value > 0


def app_service_projector_env(runtime: Any, context: Any) -> dict[str, str]:
    env: dict[str, str] = {}
    ports = getattr(context, "ports", {})
    if not isinstance(ports, dict):
        return env
    for service_name, plan in ports.items():
        normalized = str(service_name).strip().lower()
        if normalized == "backend":
            _add_service_source_env(env, suffix="BACKEND", port=getattr(plan, "final", None))
            continue
        if normalized == "frontend":
            _add_service_source_env(env, suffix="FRONTEND", port=getattr(plan, "final", None))
            continue
        service = None
        lookup = getattr(getattr(runtime, "config", None), "app_service_by_name", None)
        if callable(lookup):
            service = lookup(normalized)
        suffix = str(getattr(service, "env_suffix", "") or "").strip() or normalized.upper().replace("-", "_")
        _add_service_source_env(
            env,
            suffix=f"SERVICE_{suffix}",
            port=getattr(plan, "final", None),
            public_url_template=str(getattr(service, "public_url_template", "") or ""),
            health_url_template=str(getattr(service, "health_url_template", "") or ""),
        )
    return env


def _add_service_source_env(
    env: dict[str, str],
    *,
    suffix: str,
    port: object,
    public_url_template: str = "",
    health_url_template: str = "",
) -> None:
    if not isinstance(port, int) or port <= 0:
        return
    host = "localhost"
    env[f"{suffix}_HOST"] = host
    env[f"{suffix}_PORT"] = str(port)
    env[f"{suffix}_URL"] = f"http://{host}:{port}"
    if public_url_template:
        env[f"{suffix}_PUBLIC_URL"] = _render_service_source_template(public_url_template, env)
    else:
        env[f"{suffix}_PUBLIC_URL"] = env[f"{suffix}_URL"]
    if health_url_template:
        env[f"{suffix}_HEALTH_URL"] = _render_service_source_template(health_url_template, env)


def _render_service_source_template(template: str, env: dict[str, str]) -> str:
    rendered = template
    source_env = {f"ENVCTL_SOURCE_{key}": value for key, value in env.items()}
    for key, value in source_env.items():
        rendered = rendered.replace(f"${{{key}}}", value)
    return rendered


def resolve_dependency_env_templates(
    entries: tuple[object, ...],
    *,
    canonical_dependency_env: dict[str, str],
    resolved_env_base: dict[str, str] | None = None,
    frontend_context: bool = False,
) -> dict[str, str]:
    source_env = {
        f"ENVCTL_SOURCE_{key}": str(value)
        for key, value in canonical_dependency_env.items()
        if isinstance(value, str) and value.strip()
    }
    resolved: dict[str, str] = dict(resolved_env_base or {})
    seen_names: set[str] = set()
    for entry in entries:
        name = str(getattr(entry, "name", "")).strip()
        template = str(getattr(entry, "template", ""))
        line_number = int(getattr(entry, "line_number", 0) or 0)
        _validate_dependency_env_entry(name, line_number=line_number, seen_names=seen_names)
        if name in resolved:
            raise RuntimeError(f"duplicate launch env key {name} in .envctl launch env section")
        placeholders, skip_line = _collect_dependency_template_placeholders(
            name=name,
            template=template,
            line_number=line_number,
            source_env=source_env,
            resolved_env=resolved,
            frontend_context=frontend_context,
        )
        if skip_line:
            continue
        rendered = template
        for placeholder in placeholders:
            rendered = rendered.replace(
                f"${{{placeholder}}}", _resolve_dependency_placeholder(placeholder, source_env, resolved)
            )
        resolved[name] = rendered
    return resolved


def resolve_scoped_dependency_env(
    config: Any,
    *,
    canonical_dependency_env: dict[str, str],
    mode: str,
    service_name: str | None,
) -> dict[str, str] | None:
    sections = _dependency_template_sections_for_service(config, mode=mode, service_name=service_name)
    if not sections:
        if _any_dependency_template_section_present(config):
            return {}
        return None
    frontend_context = str(service_name or "").strip().lower() == "frontend"
    resolved: dict[str, str] = {}
    for section_label, entries, errors in sections:
        if errors:
            raise RuntimeError(f"Invalid .envctl {section_label} section: " + "; ".join(errors))
        if _section_overrides_existing_keys(entries, resolved):
            resolved = {key: value for key, value in resolved.items() if key not in _section_entry_names(entries)}
        resolved = resolve_dependency_env_templates(
            entries,
            canonical_dependency_env=canonical_dependency_env,
            resolved_env_base=resolved,
            frontend_context=frontend_context,
        )
    return resolved


def _section_entry_names(entries: tuple[object, ...]) -> set[str]:
    return {str(getattr(entry, "name", "")).strip() for entry in entries if str(getattr(entry, "name", "")).strip()}


def _section_overrides_existing_keys(entries: tuple[object, ...], resolved: dict[str, str]) -> bool:
    return bool(_section_entry_names(entries).intersection(resolved))


def _dependency_template_sections_for_service(
    config: Any,
    *,
    mode: str,
    service_name: str | None,
) -> list[tuple[str, tuple[object, ...], tuple[str, ...]]]:
    sections: list[tuple[str, tuple[object, ...], tuple[str, ...]]] = []
    if bool(getattr(config, "dependency_env_section_present", False)):
        sections.append(
            (
                "shared launch env",
                tuple(getattr(config, "dependency_env_templates", ())),
                tuple(getattr(config, "dependency_env_template_errors", ())),
            )
        )
    normalized_service = str(service_name or "").strip().lower()
    if normalized_service == "backend" and bool(getattr(config, "backend_dependency_env_section_present", False)):
        sections.append(
            (
                "backend launch env",
                tuple(getattr(config, "backend_dependency_env_templates", ())),
                tuple(getattr(config, "backend_dependency_env_template_errors", ())),
            )
        )
    if normalized_service == "frontend" and bool(getattr(config, "frontend_dependency_env_section_present", False)):
        sections.append(
            (
                "frontend launch env",
                tuple(getattr(config, "frontend_dependency_env_templates", ())),
                tuple(getattr(config, "frontend_dependency_env_template_errors", ())),
            )
        )
    normalized_mode = "trees" if str(mode).strip().lower() == "trees" else "main"
    mode_service_prefix = f"{normalized_mode}_{normalized_service}"
    if normalized_service in {"backend", "frontend"} and bool(
        getattr(config, f"{mode_service_prefix}_dependency_env_section_present", False)
    ):
        sections.append(
            (
                f"{normalized_mode} {normalized_service} launch env",
                tuple(getattr(config, f"{mode_service_prefix}_dependency_env_templates", ())),
                tuple(getattr(config, f"{mode_service_prefix}_dependency_env_template_errors", ())),
            )
        )
    service_present = getattr(config, "service_dependency_env_section_present", {})
    service_templates = getattr(config, "service_dependency_env_templates", {})
    service_errors = getattr(config, "service_dependency_env_template_errors", {})
    if isinstance(service_present, dict) and bool(service_present.get(normalized_service)):
        sections.append(
            (
                f"service {normalized_service} launch env",
                tuple(service_templates.get(normalized_service, ())) if isinstance(service_templates, dict) else (),
                tuple(service_errors.get(normalized_service, ())) if isinstance(service_errors, dict) else (),
            )
        )
    mode_service_present = getattr(config, "mode_service_dependency_env_section_present", {})
    mode_service_templates = getattr(config, "mode_service_dependency_env_templates", {})
    mode_service_errors = getattr(config, "mode_service_dependency_env_template_errors", {})
    mode_key = (normalized_mode, normalized_service)
    if isinstance(mode_service_present, dict) and bool(mode_service_present.get(mode_key)):
        sections.append(
            (
                f"{normalized_mode} service {normalized_service} launch env",
                tuple(mode_service_templates.get(mode_key, ())) if isinstance(mode_service_templates, dict) else (),
                tuple(mode_service_errors.get(mode_key, ())) if isinstance(mode_service_errors, dict) else (),
            )
        )
    return sections


def _any_dependency_template_section_present(config: Any) -> bool:
    return bool(
        getattr(config, "dependency_env_section_present", False)
        or getattr(config, "backend_dependency_env_section_present", False)
        or getattr(config, "frontend_dependency_env_section_present", False)
        or getattr(config, "main_backend_dependency_env_section_present", False)
        or getattr(config, "main_frontend_dependency_env_section_present", False)
        or getattr(config, "trees_backend_dependency_env_section_present", False)
        or getattr(config, "trees_frontend_dependency_env_section_present", False)
        or bool(getattr(config, "service_dependency_env_section_present", {}) or {})
        or bool(getattr(config, "mode_service_dependency_env_section_present", {}) or {})
    )


def _validate_dependency_env_entry(name: str, *, line_number: int, seen_names: set[str]) -> None:
    if not _ENV_VAR_NAME_RE.fullmatch(name):
        raise RuntimeError(f"launch env entry {name or '<empty>'} on line {line_number} must use a valid env var name")
    if name.startswith("ENVCTL_SOURCE_"):
        raise RuntimeError(f"launch env entry {name} on line {line_number} uses reserved prefix ENVCTL_SOURCE_")
    if name in seen_names:
        raise RuntimeError(f"duplicate launch env key {name} in .envctl launch env section")
    seen_names.add(name)


def _collect_dependency_template_placeholders(
    *,
    name: str,
    template: str,
    line_number: int,
    source_env: dict[str, str],
    resolved_env: dict[str, str],
    frontend_context: bool,
) -> tuple[list[str], bool]:
    sanitized = _TEMPLATE_VAR_RE.sub("", template)
    if "${" in sanitized:
        raise RuntimeError(f"launch env entry {name} on line {line_number} has malformed placeholder syntax")
    placeholders: list[str] = []
    skip_line = False
    for match in _TEMPLATE_VAR_RE.finditer(template):
        placeholder = str(match.group(1)).strip()
        if not _ENV_VAR_NAME_RE.fullmatch(placeholder):
            raise RuntimeError(
                f"launch env entry {name} on line {line_number} has invalid placeholder {match.group(0)!r}"
            )
        if placeholder.startswith("ENVCTL_SOURCE_") and placeholder not in source_env:
            skip_line = True
            break
        if not placeholder.startswith("ENVCTL_SOURCE_") and placeholder not in resolved_env:
            raise RuntimeError(
                f"launch env entry {name} on line {line_number} references unknown variable {placeholder}"
            )
        if _frontend_service_role_source_forbidden(
            name=name,
            placeholder=placeholder,
            frontend_context=frontend_context,
        ):
            raise RuntimeError(
                f"launch env entry {name} on line {line_number} cannot project SUPABASE_SERVICE_ROLE_KEY to frontend"
            )
        placeholders.append(placeholder)
    return placeholders, skip_line


def _frontend_service_role_source_forbidden(*, name: str, placeholder: str, frontend_context: bool) -> bool:
    if placeholder != "ENVCTL_SOURCE_SUPABASE_SERVICE_ROLE_KEY":
        return False
    return frontend_context or name.startswith("VITE_")


def supabase_auth_user_source_env(runtime: Any, *, requirements: RequirementsResult) -> dict[str, str]:
    component = requirements.component("supabase")
    raw_users = component.get("auth_users")
    if not isinstance(raw_users, dict):
        return {}
    configured = tuple(getattr(getattr(runtime, "config", None), "supabase_auth_users", ()) or ())
    by_name = {str(getattr(user, "name", "") or "").strip(): user for user in configured}
    env: dict[str, str] = {}
    first_suffix: str | None = None
    for slug, payload in raw_users.items():
        name = str(slug).strip()
        if not isinstance(payload, dict) or not name:
            continue
        user = by_name.get(name)
        suffix = str(getattr(user, "env_suffix", "") or name.upper().replace("-", "_")).strip()
        if not suffix:
            continue
        user_id = str(payload.get("id", "") or "").strip()
        email = str(payload.get("email", "") or getattr(user, "email", "") or "").strip()
        if user_id:
            env[f"SUPABASE_USER_{suffix}_ID"] = user_id
        if email:
            env[f"SUPABASE_USER_{suffix}_EMAIL"] = email
        password = str(getattr(user, "password", "") or "").strip()
        if password and bool(getattr(user, "expose_password", True)):
            env[f"SUPABASE_USER_{suffix}_PASSWORD"] = password
        if first_suffix is None and (user_id or email):
            first_suffix = suffix
    if first_suffix:
        for key in ("ID", "EMAIL", "PASSWORD"):
            source_key = f"SUPABASE_USER_{first_suffix}_{key}"
            if source_key in env:
                env[f"SUPABASE_TEST_USER_{key}"] = env[source_key]
    return env


def _resolve_dependency_placeholder(
    placeholder: str,
    source_env: dict[str, str],
    resolved_env: dict[str, str],
) -> str:
    if placeholder in source_env:
        return source_env[placeholder]
    return resolved_env[placeholder]


_source_alias_env = source_alias_env
_dependency_projector_env = dependency_projector_env
_app_service_projector_env = app_service_projector_env
_resolve_scoped_dependency_env = resolve_scoped_dependency_env
_supabase_auth_user_source_env = supabase_auth_user_source_env
