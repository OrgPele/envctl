from __future__ import annotations

import re
from typing import Any, Mapping

from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import PortPlan, RequirementsResult
from envctl_engine.requirements.orchestrator import RequirementOutcome


_ENV_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TEMPLATE_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def skipped_requirement(service_name: str, plan: PortPlan) -> RequirementOutcome:
    return RequirementOutcome(
        service_name=service_name,
        success=True,
        requested_port=plan.requested,
        final_port=plan.final,
        retries=0,
    )


def requirements_ready(runtime: Any, result: RequirementsResult) -> bool:
    if not runtime.config.requirements_strict:
        return True
    for definition in dependency_definitions():
        component = result.component(definition.id)
        enabled = bool(component.get("enabled"))
        success = bool(component.get("success"))
        if enabled and not success:
            return False
    return True


def validate_mode_toggles(runtime: Any, mode: str, *, route: Route | None = None) -> None:
    normalized_mode = str(mode).strip().lower()
    config = runtime.config
    startup_enabled = (
        config.startup_enabled_for_mode(normalized_mode) if hasattr(config, "startup_enabled_for_mode") else True
    )
    if not startup_enabled:
        if _route_requires_enabled_mode(route):
            raise RuntimeError(
                f"envctl runs are disabled for {normalized_mode} in .envctl. Run 'envctl config' to enable them."
            )
        return
    if normalized_mode == "main":
        _ = main_requirements_mode(route)
        profile = (
            config.profile_for_mode("main")
            if hasattr(config, "profile_for_mode")
            else SimpleProfile(
                startup_enable=True,
                backend_enable=True,
                frontend_enable=True,
                postgres_enable=bool(getattr(config, "postgres_main_enable", True)),
                redis_enable=bool(getattr(config, "redis_main_enable", getattr(config, "redis_enable", True))),
                supabase_enable=bool(getattr(config, "supabase_main_enable", False)),
                n8n_enable=bool(getattr(config, "n8n_main_enable", False)),
            )
        )
        effective_main = effective_main_requirement_flags(runtime, route)
        postgres_enabled = effective_main["postgres"]
        supabase_enabled = effective_main["supabase"]
        enabled_count = sum(
            1
            for enabled in (
                profile.backend_enable,
                profile.frontend_enable,
                postgres_enabled,
                effective_main["redis"],
                supabase_enabled,
                effective_main["n8n"],
            )
            if enabled
        )
    else:
        profile = (
            config.profile_for_mode(normalized_mode)
            if hasattr(config, "profile_for_mode")
            else SimpleProfile(
                startup_enable=True,
                backend_enable=True,
                frontend_enable=True,
                postgres_enable=True,
                redis_enable=bool(getattr(config, "redis_enable", True)),
                supabase_enable=False,
                n8n_enable=bool(getattr(config, "n8n_enable", True)),
            )
        )
        postgres_enabled = profile.postgres_enable
        supabase_enabled = profile.supabase_enable
        enabled_count = sum(
            1
            for enabled in (
                profile.backend_enable,
                profile.frontend_enable,
                profile.postgres_enable,
                profile.redis_enable,
                profile.supabase_enable,
                profile.n8n_enable,
            )
            if enabled
        )
    if enabled_count < 1:
        raise RuntimeError(f"Invalid {normalized_mode} startup configuration: at least one component must be enabled.")
    if postgres_enabled and supabase_enabled:
        raise RuntimeError(
            f"Invalid {normalized_mode} requirements configuration: postgres and supabase cannot both be enabled."
        )


def _route_requires_enabled_mode(route: Route | None) -> bool:
    if route is None:
        return True
    command = str(route.command).strip().lower()
    if command in {"restart", "resume"}:
        return True
    if command == "start":
        return not _route_is_implicit_start(route)
    return False


def _route_is_implicit_start(route: Route | None) -> bool:
    if route is None or str(route.command).strip().lower() != "start":
        return False
    raw_args = [str(token).strip() for token in getattr(route, "raw_args", []) if str(token).strip()]
    if not raw_args:
        return True
    index = 0
    while index < len(raw_args):
        token = raw_args[index]
        lowered = token.lower()
        if lowered == "start":
            return False
        if lowered in {"--command", "--action"}:
            next_token = raw_args[index + 1].lower() if index + 1 < len(raw_args) else ""
            if next_token == "start":
                return False
            index += 2
            continue
        if lowered.startswith("--command=") or lowered.startswith("--action="):
            if lowered.split("=", 1)[1].strip() == "start":
                return False
        index += 1
    return True


def route_is_implicit_start(route: Route | None) -> bool:
    return _route_is_implicit_start(route)


def service_enabled_for_mode(runtime: Any, mode: str, service_name: str) -> bool:
    if hasattr(runtime.config, "startup_enabled_for_mode") and not runtime.config.startup_enabled_for_mode(mode):
        return False
    if hasattr(runtime.config, "service_enabled_for_mode"):
        return runtime.config.service_enabled_for_mode(mode, service_name)
    return str(service_name).strip().lower() in {"backend", "frontend"}


def requirement_enabled_for_mode(runtime: Any, mode: str, requirement_name: str, *, route: Route | None = None) -> bool:
    normalized_mode = str(mode).strip().lower()
    normalized_name = str(requirement_name).strip().lower()
    if route is not None and route.flags.get("launch_dependencies") is False:
        return False
    if normalized_mode == "trees" and effective_dependency_scope(route, normalized_mode) == "shared":
        normalized_mode = "main"
    if hasattr(runtime.config, "startup_enabled_for_mode") and not runtime.config.startup_enabled_for_mode(
        normalized_mode
    ):
        return False
    if normalized_mode == "main":
        effective_main = effective_main_requirement_flags(runtime, route)
        if normalized_name in effective_main:
            return effective_main[normalized_name]
    if hasattr(runtime.config, "requirement_enabled_for_mode"):
        return runtime.config.requirement_enabled_for_mode(normalized_mode, normalized_name)
    return True


def effective_dependency_scope(route: Route | None, mode: str) -> str:
    if route is None:
        return "isolated" if str(mode).strip().lower() == "trees" else "shared"
    if route is not None and route.flags.get("launch_dependencies") is False:
        return "none"
    explicit = route.flags.get("dependency_scope") if route is not None else None
    if explicit in {"shared", "isolated"}:
        return str(explicit)
    normalized_mode = str(mode).strip().lower()
    if normalized_mode == "trees":
        return "shared"
    return "shared"


class SimpleProfile:
    def __init__(
        self,
        *,
        startup_enable: bool,
        backend_enable: bool,
        frontend_enable: bool,
        postgres_enable: bool,
        redis_enable: bool,
        supabase_enable: bool,
        n8n_enable: bool,
    ) -> None:
        self.startup_enable = startup_enable
        self.backend_enable = backend_enable
        self.frontend_enable = frontend_enable
        self.postgres_enable = postgres_enable
        self.redis_enable = redis_enable
        self.supabase_enable = supabase_enable
        self.n8n_enable = n8n_enable


def project_service_env_internal(
    runtime: Any,
    context: Any,
    *,
    requirements: RequirementsResult,
    route: Route | None = None,
) -> dict[str, str]:
    env = {"ENVCTL_PROJECT_NAME": context.name}
    env.update(_dependency_projector_env(runtime, context, requirements=requirements, route=route))
    env.update(runtime_env_overrides(route))
    _apply_route_log_overrides(env, route)
    return env


def project_service_env(
    runtime: Any,
    context: Any,
    *,
    requirements: RequirementsResult,
    route: Route | None = None,
    service_name: str | None = None,
) -> dict[str, str]:
    env = {"ENVCTL_PROJECT_NAME": context.name}
    dependency_env = _dependency_projector_env(runtime, context, requirements=requirements, route=route)
    dependency_env.update(_app_service_projector_env(runtime, context))
    dependency_env.update(_source_alias_env(dependency_env))
    config = getattr(runtime, "config", None)
    mode = str(getattr(route, "mode", "") or "").strip().lower() if route is not None else ""
    scoped_dependency_env = _resolve_scoped_dependency_env(
        config,
        canonical_dependency_env=dependency_env,
        mode=mode,
        service_name=service_name,
    )
    if scoped_dependency_env is not None:
        env.update(scoped_dependency_env)
    else:
        env.update(dependency_env)
    env.update(runtime_env_overrides(route))
    _apply_route_log_overrides(env, route)
    return env


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
    raw_sources: list[Mapping[str, str]] = []
    config_raw = getattr(getattr(runtime, "config", None), "raw", None)
    if isinstance(config_raw, Mapping):
        raw_sources.append(config_raw)
    runtime_env = getattr(runtime, "env", None)
    if isinstance(runtime_env, Mapping):
        raw_sources.append(runtime_env)
    source_env = dict(base_env)
    source_env.update(_source_alias_env(source_env))
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


def _source_alias_env(env: Mapping[str, str]) -> dict[str, str]:
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


def _dependency_projector_env(
    runtime: Any,
    context: Any,
    *,
    requirements: RequirementsResult,
    route: Route | None = None,
) -> dict[str, str]:
    env: dict[str, str] = {}
    for definition in dependency_definitions():
        component = requirements.component(definition.id)
        if not bool(component.get("enabled", False)):
            continue
        if callable(definition.env_projector):
            env.update(
                definition.env_projector(runtime=runtime, context=context, requirements=requirements, route=route)
            )
    env.update(_supabase_auth_user_source_env(runtime, requirements=requirements))
    return env


def _app_service_projector_env(runtime: Any, context: Any) -> dict[str, str]:
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


def _apply_route_log_overrides(env: dict[str, str], route: Route | None) -> None:
    if route is not None:
        log_profile = route.flags.get("log_profile")
        log_level = route.flags.get("log_level")
        backend_log_profile = route.flags.get("backend_log_profile")
        backend_log_level = route.flags.get("backend_log_level")
        frontend_log_profile = route.flags.get("frontend_log_profile")
        frontend_log_level = route.flags.get("frontend_log_level")
        frontend_test_runner = route.flags.get("frontend_test_runner")
        if isinstance(log_profile, str):
            env["LOG_PROFILE_OVERRIDE"] = log_profile
            if not isinstance(backend_log_profile, str):
                env["BACKEND_LOG_PROFILE_OVERRIDE"] = log_profile
            if not isinstance(frontend_log_profile, str):
                env["FRONTEND_LOG_PROFILE_OVERRIDE"] = log_profile
        if isinstance(log_level, str):
            env["LOG_LEVEL_OVERRIDE"] = log_level
            if not isinstance(backend_log_level, str):
                env["BACKEND_LOG_LEVEL_OVERRIDE"] = log_level
            if not isinstance(frontend_log_level, str):
                env["FRONTEND_LOG_LEVEL_OVERRIDE"] = log_level
        if isinstance(backend_log_profile, str):
            env["BACKEND_LOG_PROFILE_OVERRIDE"] = backend_log_profile
        if isinstance(backend_log_level, str):
            env["BACKEND_LOG_LEVEL_OVERRIDE"] = backend_log_level
        if isinstance(frontend_log_profile, str):
            env["FRONTEND_LOG_PROFILE_OVERRIDE"] = frontend_log_profile
        if isinstance(frontend_log_level, str):
            env["FRONTEND_LOG_LEVEL_OVERRIDE"] = frontend_log_level
        if isinstance(frontend_test_runner, str):
            env["FRONTEND_TEST_RUNNER"] = frontend_test_runner


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


def _resolve_scoped_dependency_env(
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


def _supabase_auth_user_source_env(runtime: Any, *, requirements: RequirementsResult) -> dict[str, str]:
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


def runtime_env_overrides(route: Route | None) -> dict[str, str]:
    if route is None:
        return {}
    env: dict[str, str] = {}
    if bool(route.flags.get("fast")):
        env["RUN_SH_FAST_STARTUP"] = "true"
    if bool(route.flags.get("refresh_cache")):
        env["RUN_SH_REFRESH_CACHE"] = "true"
        env["RUN_SH_FAST_STARTUP"] = "true"
    if bool(route.flags.get("docker")):
        env["DOCKER_MODE"] = "true"
    if bool(route.flags.get("docker_temp")):
        env["DOCKER_TEMP_MODE"] = "true"
    if bool(route.flags.get("no_resume")):
        env["AUTO_RESUME"] = "false"
    parallel = route.flags.get("parallel_trees")
    if isinstance(parallel, bool):
        env["RUN_SH_OPT_PARALLEL_TREES"] = "true" if parallel else "false"
    parallel_max = route.flags.get("parallel_trees_max")
    if isinstance(parallel_max, str) and parallel_max.strip():
        env["RUN_SH_OPT_PARALLEL_TREES_MAX"] = parallel_max.strip()
    if bool(route.flags.get("debug_trace")):
        env["RUN_SH_DEBUG"] = "true"
    debug_log = route.flags.get("debug_trace_log")
    if isinstance(debug_log, str) and debug_log.strip():
        env["RUN_SH_DEBUG"] = "true"
        env["RUN_SH_DEBUG_LOG"] = debug_log.strip()
    if bool(route.flags.get("debug_trace_no_xtrace")):
        env["RUN_SH_DEBUG"] = "true"
        env["RUN_SH_DEBUG_XTRACE"] = "false"
    if bool(route.flags.get("debug_trace_no_stdio")):
        env["RUN_SH_DEBUG"] = "true"
        env["RUN_SH_DEBUG_STDIO"] = "false"
    if bool(route.flags.get("debug_trace_no_interactive")):
        env["RUN_SH_DEBUG"] = "true"
        env["RUN_SH_DEBUG_TRACE_INTERACTIVE"] = "false"
    if bool(route.flags.get("key_debug")):
        env["KEY_DEBUG"] = "true"
    if bool(route.flags.get("setup_worktree_existing")):
        env["SETUP_WORKTREE_EXISTING"] = "true"
    if bool(route.flags.get("setup_worktree_recreate")):
        env["SETUP_WORKTREE_RECREATE"] = "true"
    include_existing = route.flags.get("include_existing_worktrees")
    if isinstance(include_existing, list):
        values = [str(value).strip() for value in include_existing if str(value).strip()]
        if values:
            env["SETUP_INCLUDE_WORKTREES_RAW"] = ",".join(values)
    seed_from_base = route.flags.get("seed_requirements_from_base")
    if isinstance(seed_from_base, bool):
        env["SEED_REQUIREMENTS_FROM_BASE"] = "true" if seed_from_base else "false"
    stop_all_remove_volumes = route.flags.get("stop_all_remove_volumes")
    if isinstance(stop_all_remove_volumes, bool):
        env["RUN_SH_COMMAND_STOP_ALL_REMOVE_VOLUMES"] = "true" if stop_all_remove_volumes else "false"
    return env


def main_requirements_mode(route: Route | None) -> str | None:
    if route is None:
        return None
    local = bool(route.flags.get("main_services_local"))
    remote = bool(route.flags.get("main_services_remote"))
    if local and remote:
        raise RuntimeError(
            "Conflicting main requirements flags: use only one of --main-services-local or --main-services-remote."
        )
    if local:
        return "local"
    if remote:
        return "remote"
    return None


def effective_main_requirement_flags(runtime: Any, route: Route | None) -> dict[str, bool]:
    if hasattr(runtime.config, "requirement_enabled_for_mode"):
        values = {
            definition.id: runtime.config.requirement_enabled_for_mode("main", definition.id)
            for definition in dependency_definitions()
        }
    else:
        values = {
            "postgres": bool(getattr(runtime.config, "postgres_main_enable", True)),
            "redis": bool(getattr(runtime.config, "redis_main_enable", getattr(runtime.config, "redis_enable", True))),
            "supabase": bool(getattr(runtime.config, "supabase_main_enable", False)),
            "n8n": bool(getattr(runtime.config, "n8n_main_enable", False)),
        }

    mode = main_requirements_mode(route)
    if mode == "local":
        values["postgres"] = False
        values["redis"] = True
        values["supabase"] = True
        values["n8n"] = True
    elif mode == "remote":
        values["postgres"] = True
        values["supabase"] = False
        values["n8n"] = False
    values.update(
        {
            "postgres_main_enable": values["postgres"],
            "redis_main_enable": values["redis"],
            "supabase_main_enable": values["supabase"],
            "n8n_main_enable": values["n8n"],
        }
    )
    return values
