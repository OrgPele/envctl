from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal, Mapping

from envctl_engine.actions.actions_test import (
    canonicalize_frontend_test_path,
    suggest_action_test_command,
    suggest_backend_test_command,
    suggest_frontend_test_command,
    suggest_frontend_test_path,
)
from envctl_engine.config.dependency_env_templates import (
    CONFIG_BACKEND_DEPENDENCY_ENV_END,
    CONFIG_BACKEND_DEPENDENCY_ENV_START,
    CONFIG_DEPENDENCY_ENV_END,
    CONFIG_DEPENDENCY_ENV_START,
    CONFIG_FRONTEND_DEPENDENCY_ENV_END,
    CONFIG_FRONTEND_DEPENDENCY_ENV_START,
    CONFIG_MAIN_BACKEND_DEPENDENCY_ENV_END,
    CONFIG_MAIN_BACKEND_DEPENDENCY_ENV_START,
    CONFIG_MAIN_FRONTEND_DEPENDENCY_ENV_END,
    CONFIG_MAIN_FRONTEND_DEPENDENCY_ENV_START,
    CONFIG_TREES_BACKEND_DEPENDENCY_ENV_END,
    CONFIG_TREES_BACKEND_DEPENDENCY_ENV_START,
    CONFIG_TREES_FRONTEND_DEPENDENCY_ENV_END,
    CONFIG_TREES_FRONTEND_DEPENDENCY_ENV_START,
    DependencyEnvTemplateEntry,
    LEGACY_CONFIG_BACKEND_DEPENDENCY_ENV_END,
    LEGACY_CONFIG_BACKEND_DEPENDENCY_ENV_START,
    LEGACY_CONFIG_DEPENDENCY_ENV_END,
    LEGACY_CONFIG_DEPENDENCY_ENV_START,
    LEGACY_CONFIG_FRONTEND_DEPENDENCY_ENV_END,
    LEGACY_CONFIG_FRONTEND_DEPENDENCY_ENV_START,
    _any_dependency_env_section_markers_present,
    _backend_dependency_env_section_bounds,
    _dependency_env_section_bounds,
    _extract_backend_dependency_env_section,
    _extract_dependency_env_section,
    _extract_frontend_dependency_env_section,
    _extract_generic_mode_service_dependency_env_sections,
    _extract_generic_service_dependency_env_sections,
    _extract_mode_service_dependency_env_section,
    _frontend_dependency_env_section_bounds,
    _strip_template_sections,
    ensure_dependency_env_section,
    parse_dependency_env_section,
    render_default_backend_dependency_env_section,
    render_default_dependency_env_section,
    render_default_dependency_env_sections,
    render_default_frontend_dependency_env_section,
    render_legacy_default_dependency_env_sections,
)
from envctl_engine.config.defaults import DEFAULTS, MANAGED_CONFIG_KEYS
from envctl_engine.config.models import (
    AppServiceConfig,
    EngineConfig,
    LocalConfigState,
    PortDefaults,
    StartupProfile,
    SupabaseAuthUserConfig,
)
from envctl_engine.config.profile_defaults import managed_dependency_default_enabled
from envctl_engine.config.service_parsing import (
    _parse_additional_services,
    _parse_json_object_value,
    _parse_supabase_auth_users,
    _service_env_suffix,
    _validate_additional_service_dependencies,
)
from envctl_engine.config.source_discovery import (
    CONFIG_PRIMARY_FILENAME,
    LEGACY_CONFIG_FILENAMES,
    control_root_from_generated_tree_shape as _control_root_from_generated_tree_shape,
    control_root_from_worktree_provenance as _control_root_from_worktree_provenance,
    discover_local_config_state,
    generated_worktree_control_root as _generated_worktree_control_root,
    parse_envctl_text as _parse_envctl_text,
    resolve_explicit_path as _resolve_explicit_path,
)
from envctl_engine.runtime.command_resolution import suggest_service_directory, suggest_service_start_command
from envctl_engine.shared.parsing import parse_bool, parse_int
from envctl_engine.shared.repo_roots import canonical_envctl_project_root

CONFIG_MANAGED_BLOCK_START = "# >>> envctl managed startup config >>>"
CONFIG_MANAGED_BLOCK_END = "# <<< envctl managed startup config <<<"
__all__ = (
    "AppServiceConfig",
    "CONFIG_BACKEND_DEPENDENCY_ENV_END",
    "CONFIG_BACKEND_DEPENDENCY_ENV_START",
    "CONFIG_DEPENDENCY_ENV_END",
    "CONFIG_DEPENDENCY_ENV_START",
    "CONFIG_FRONTEND_DEPENDENCY_ENV_END",
    "CONFIG_FRONTEND_DEPENDENCY_ENV_START",
    "CONFIG_MAIN_BACKEND_DEPENDENCY_ENV_END",
    "CONFIG_MAIN_BACKEND_DEPENDENCY_ENV_START",
    "CONFIG_MAIN_FRONTEND_DEPENDENCY_ENV_END",
    "CONFIG_MAIN_FRONTEND_DEPENDENCY_ENV_START",
    "CONFIG_MANAGED_BLOCK_END",
    "CONFIG_MANAGED_BLOCK_START",
    "CONFIG_PRIMARY_FILENAME",
    "CONFIG_TREES_BACKEND_DEPENDENCY_ENV_END",
    "CONFIG_TREES_BACKEND_DEPENDENCY_ENV_START",
    "CONFIG_TREES_FRONTEND_DEPENDENCY_ENV_END",
    "CONFIG_TREES_FRONTEND_DEPENDENCY_ENV_START",
    "DEFAULTS",
    "DependencyEnvTemplateEntry",
    "EngineConfig",
    "LEGACY_CONFIG_BACKEND_DEPENDENCY_ENV_END",
    "LEGACY_CONFIG_BACKEND_DEPENDENCY_ENV_START",
    "LEGACY_CONFIG_DEPENDENCY_ENV_END",
    "LEGACY_CONFIG_DEPENDENCY_ENV_START",
    "LEGACY_CONFIG_FILENAMES",
    "LEGACY_CONFIG_FRONTEND_DEPENDENCY_ENV_END",
    "LEGACY_CONFIG_FRONTEND_DEPENDENCY_ENV_START",
    "LocalConfigState",
    "MANAGED_CONFIG_KEYS",
    "PortDefaults",
    "StartupProfile",
    "SupabaseAuthUserConfig",
    "_any_dependency_env_section_markers_present",
    "_backend_dependency_env_section_bounds",
    "_control_root_from_generated_tree_shape",
    "_control_root_from_worktree_provenance",
    "_dependency_env_section_bounds",
    "_extract_backend_dependency_env_section",
    "_extract_dependency_env_section",
    "_extract_frontend_dependency_env_section",
    "_extract_generic_mode_service_dependency_env_sections",
    "_extract_generic_service_dependency_env_sections",
    "_extract_mode_service_dependency_env_section",
    "_frontend_dependency_env_section_bounds",
    "_parse_additional_services",
    "_parse_envctl_text",
    "_parse_json_object_value",
    "_parse_supabase_auth_users",
    "_resolve_explicit_path",
    "_service_env_suffix",
    "_strip_template_sections",
    "_validate_additional_service_dependencies",
    "discover_local_config_state",
    "ensure_dependency_env_section",
    "load_config",
    "parse_dependency_env_section",
    "render_default_backend_dependency_env_section",
    "render_default_dependency_env_section",
    "render_default_dependency_env_sections",
    "render_default_frontend_dependency_env_section",
    "render_legacy_default_dependency_env_sections",
)
def _dependency_definitions():
    from envctl_engine.requirements.core import dependency_definitions

    return dependency_definitions()


def load_config(env: Mapping[str, str] | None = None) -> EngineConfig:
    env = env or {}
    requested_root = Path(env.get("RUN_REPO_ROOT") or Path.cwd())
    execution_root = Path(env.get("ENVCTL_EXECUTION_ROOT") or requested_root).expanduser()
    if execution_root.is_file():
        execution_root = execution_root.parent
    execution_root = execution_root.resolve()
    base_dir = canonical_envctl_project_root(requested_root)
    generated_root = _generated_worktree_control_root(
        requested_root=requested_root,
        execution_root=execution_root,
        trees_dir_name=str(env.get("TREES_DIR_NAME") or DEFAULTS["TREES_DIR_NAME"]),
    )
    if generated_root is not None:
        base_dir = generated_root
    local_state = discover_local_config_state(base_dir, env.get("ENVCTL_CONFIG_FILE"))

    resolved: dict[str, str] = dict(DEFAULTS)
    for key, value in local_state.parsed_values.items():
        if key not in env:
            resolved[key] = value
    for key, value in env.items():
        resolved[key] = value
    explicit_values: dict[str, str] = dict(local_state.parsed_values)
    explicit_values.update(env)
    visual_host_fallback = str(resolved.get("ENVCTL_PUBLIC_HOST") or "localhost").strip() or "localhost"
    if "ENVCTL_UI_VISUAL_HOST" not in explicit_values:
        resolved["ENVCTL_UI_VISUAL_HOST"] = visual_host_fallback
    elif not str(resolved.get("ENVCTL_UI_VISUAL_HOST") or "").strip():
        resolved["ENVCTL_UI_VISUAL_HOST"] = visual_host_fallback
    _apply_plan_agent_aliases(resolved, explicit_values=explicit_values)
    explicit_keys = set(explicit_values)
    aliased_explicit_values = dict(explicit_values)
    _apply_plan_agent_aliases(aliased_explicit_values, explicit_values=explicit_values)
    explicit_keys.update(aliased_explicit_values)

    default_mode = resolved.get("ENVCTL_DEFAULT_MODE", "main").strip().lower()
    if default_mode not in {"main", "trees"}:
        default_mode = "main"

    runtime_dir = _resolve_path(base_dir, resolved.get("RUN_SH_RUNTIME_DIR", DEFAULTS["RUN_SH_RUNTIME_DIR"]))
    planning_dir = _resolve_planning_dir(
        base_dir=base_dir,
        execution_root=execution_root,
        raw=resolved.get("ENVCTL_PLANNING_DIR", DEFAULTS["ENVCTL_PLANNING_DIR"]),
    )
    runtime_scope_id = _runtime_scope_id(base_dir=base_dir, env=env, resolved=resolved)
    runtime_scope_dir = runtime_dir / "python-engine" / runtime_scope_id

    runtime_dir.mkdir(parents=True, exist_ok=True)
    runtime_scope_dir.mkdir(parents=True, exist_ok=True)

    dependency_ports: dict[str, dict[str, int]] = {}
    for definition in _dependency_definitions():
        resources: dict[str, int] = {}
        for resource in definition.resources:
            default_value = 0
            if resource.config_port_keys:
                default_value = _default_port_value(resource.config_port_keys[0])
            raw_value = None
            for key in resource.config_port_keys:
                if key in resolved:
                    raw_value = resolved.get(key)
                    break
            resources[resource.name] = parse_int(raw_value, default_value)
        dependency_ports[definition.id] = resources
    port_defaults = PortDefaults(
        backend_port_base=parse_int(resolved.get("BACKEND_PORT_BASE"), 8000),
        frontend_port_base=parse_int(resolved.get("FRONTEND_PORT_BASE"), 9000),
        dependency_ports=dependency_ports,
        port_spacing=parse_int(resolved.get("PORT_SPACING"), 20),
    )

    use_managed_dependency_defaults = local_state.config_file_exists
    main_profile = _startup_profile_from_resolved(
        resolved,
        explicit_values=explicit_values,
        mode="main",
        use_managed_dependency_defaults=use_managed_dependency_defaults,
    )
    trees_profile = _startup_profile_from_resolved(
        resolved,
        explicit_values=explicit_values,
        mode="trees",
        use_managed_dependency_defaults=use_managed_dependency_defaults,
    )
    if "REDIS_ENABLE" in explicit_values and not parse_bool(explicit_values.get("REDIS_ENABLE"), True):
        main_profile.redis_enable = False
        trees_profile.redis_enable = False
    if "N8N_ENABLE" in explicit_values and not parse_bool(explicit_values.get("N8N_ENABLE"), True):
        main_profile.n8n_enable = False
        trees_profile.n8n_enable = False
    _apply_dependency_env_template_inferences(
        main_profile,
        mode="main",
        explicit_values=explicit_values,
        local_state=local_state,
    )
    _apply_dependency_env_template_inferences(
        trees_profile,
        mode="trees",
        explicit_values=explicit_values,
        local_state=local_state,
    )

    redis_enabled_any = main_profile.redis_enable or trees_profile.redis_enable
    n8n_enabled_any = main_profile.n8n_enable or trees_profile.n8n_enable
    main_backend_expect_listener = parse_bool(resolved.get("MAIN_BACKEND_EXPECT_LISTENER"), True)
    trees_backend_expect_listener = parse_bool(resolved.get("TREES_BACKEND_EXPECT_LISTENER"), True)
    plan_agent_cmux_workspace = str(resolved.get("ENVCTL_PLAN_AGENT_CMUX_WORKSPACE", "") or "").strip()
    plan_agent_superset_project = str(resolved.get("ENVCTL_PLAN_AGENT_SUPERSET_PROJECT", "") or "").strip()
    plan_agent_superset_workspace = str(resolved.get("ENVCTL_PLAN_AGENT_SUPERSET_WORKSPACE", "") or "").strip()
    plan_agent_terminals_enable = parse_bool(resolved.get("ENVCTL_PLAN_AGENT_TERMINALS_ENABLE"), False) or bool(
        plan_agent_cmux_workspace
    ) or bool(plan_agent_superset_project or plan_agent_superset_workspace)
    additional_services, additional_service_errors = _parse_additional_services(resolved)
    supabase_auth_users, supabase_auth_user_errors = _parse_supabase_auth_users(resolved)

    return EngineConfig(
        base_dir=base_dir,
        execution_root=execution_root,
        backend_dir_name=_resolved_backend_dir_name(
            base_dir=execution_root, resolved=resolved, explicit_values=explicit_values
        ),
        frontend_dir_name=_resolved_frontend_dir_name(
            base_dir=execution_root, resolved=resolved, explicit_values=explicit_values
        ),
        runtime_dir=runtime_dir,
        backend_start_cmd=_resolved_backend_start_cmd(base_dir=execution_root, resolved=resolved),
        frontend_start_cmd=_resolved_frontend_start_cmd(base_dir=execution_root, resolved=resolved),
        backend_test_cmd=_resolved_backend_test_cmd(base_dir=execution_root, resolved=resolved),
        frontend_test_cmd=_resolved_frontend_test_cmd(base_dir=execution_root, resolved=resolved),
        action_test_cmd=_resolved_action_test_cmd(base_dir=execution_root, resolved=resolved),
        frontend_test_path=_resolved_frontend_test_path(base_dir=execution_root, resolved=resolved),
        runtime_scope_id=runtime_scope_id,
        runtime_scope_dir=runtime_scope_dir,
        planning_dir=planning_dir,
        trees_dir_name=resolved.get("TREES_DIR_NAME", DEFAULTS["TREES_DIR_NAME"]),
        default_mode=default_mode,
        backend_port_base=port_defaults.backend_port_base,
        frontend_port_base=port_defaults.frontend_port_base,
        port_spacing=port_defaults.port_spacing,
        db_port_base=port_defaults.db_port_base,
        redis_port_base=port_defaults.redis_port_base,
        n8n_port_base=port_defaults.n8n_port_base,
        postgres_main_enable=main_profile.postgres_enable,
        redis_enable=redis_enabled_any,
        redis_main_enable=main_profile.redis_enable,
        supabase_main_enable=main_profile.supabase_enable,
        n8n_enable=n8n_enabled_any,
        n8n_main_enable=main_profile.n8n_enable,
        strict_n8n_bootstrap=parse_bool(resolved.get("ENVCTL_STRICT_N8N_BOOTSTRAP"), False),
        port_availability_mode=_parse_port_availability_mode(
            resolved.get("ENVCTL_PORT_AVAILABILITY_MODE"),
            DEFAULTS["ENVCTL_PORT_AVAILABILITY_MODE"],
        ),
        plan_strict_selection=parse_bool(resolved.get("ENVCTL_PLAN_STRICT_SELECTION"), False),
        plan_agent_terminals_enable=plan_agent_terminals_enable,
        plan_agent_cli=str(resolved.get("ENVCTL_PLAN_AGENT_CLI", "codex") or "codex").strip().lower() or "codex",
        plan_agent_preset=str(resolved.get("ENVCTL_PLAN_AGENT_PRESET", "implement_task") or "implement_task").strip()
        or "implement_task",
        plan_agent_codex_cycles=max(parse_int(resolved.get("ENVCTL_PLAN_AGENT_CODEX_CYCLES"), 0), 0),
        plan_agent_codex_goal_enable=parse_bool(
            resolved.get("ENVCTL_PLAN_AGENT_CODEX_GOAL_ENABLE"),
            True,
        ),
        plan_agent_codex_yolo=parse_bool(
            resolved.get("ENVCTL_PLAN_AGENT_CODEX_YOLO"),
            True,
        ),
        plan_agent_browser_e2e_enable=parse_bool(
            resolved.get("ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE"),
            True,
        ),
        plan_agent_pr_review_comments_enable=parse_bool(
            resolved.get("ENVCTL_PLAN_AGENT_PR_REVIEW_COMMENTS_ENABLE"),
            True,
        ),
        plan_agent_shell=str(resolved.get("ENVCTL_PLAN_AGENT_SHELL", "zsh") or "zsh").strip() or "zsh",
        plan_agent_require_cmux_context=parse_bool(resolved.get("ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT"), True),
        plan_agent_cli_cmd=str(resolved.get("ENVCTL_PLAN_AGENT_CLI_CMD", "") or "").strip(),
        plan_agent_cmux_workspace=plan_agent_cmux_workspace,
        plan_agent_surface_transport=(
            str(resolved.get("ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT", "cmux") or "cmux").strip().lower()
            or "cmux"
        ),
        plan_agent_superset_project=plan_agent_superset_project,
        plan_agent_superset_workspace=plan_agent_superset_workspace,
        plan_agent_superset_host=str(resolved.get("ENVCTL_PLAN_AGENT_SUPERSET_HOST", "") or "").strip(),
        plan_agent_superset_local=parse_bool(resolved.get("ENVCTL_PLAN_AGENT_SUPERSET_LOCAL"), True),
        plan_agent_superset_open=parse_bool(resolved.get("ENVCTL_PLAN_AGENT_SUPERSET_OPEN"), True),
        runtime_truth_mode=_parse_runtime_truth_mode(
            resolved.get("ENVCTL_RUNTIME_TRUTH_MODE"),
            DEFAULTS["ENVCTL_RUNTIME_TRUTH_MODE"],
        ),
        requirements_strict=parse_bool(resolved.get("ENVCTL_REQUIREMENTS_STRICT"), True),
        main_profile=main_profile,
        trees_profile=trees_profile,
        main_backend_expect_listener=main_backend_expect_listener,
        trees_backend_expect_listener=trees_backend_expect_listener,
        port_defaults=port_defaults,
        config_file_path=local_state.config_file_path,
        config_file_exists=local_state.config_file_exists,
        config_source=local_state.config_source,
        raw=resolved,
        explicit_keys=tuple(sorted(explicit_keys)),
        dependency_env_templates=local_state.dependency_env_templates,
        dependency_env_section_present=local_state.dependency_env_section_present,
        dependency_env_template_errors=local_state.dependency_env_template_errors,
        backend_dependency_env_templates=local_state.backend_dependency_env_templates,
        backend_dependency_env_section_present=local_state.backend_dependency_env_section_present,
        backend_dependency_env_template_errors=local_state.backend_dependency_env_template_errors,
        frontend_dependency_env_templates=local_state.frontend_dependency_env_templates,
        frontend_dependency_env_section_present=local_state.frontend_dependency_env_section_present,
        frontend_dependency_env_template_errors=local_state.frontend_dependency_env_template_errors,
        main_backend_dependency_env_templates=local_state.main_backend_dependency_env_templates,
        main_backend_dependency_env_section_present=local_state.main_backend_dependency_env_section_present,
        main_backend_dependency_env_template_errors=local_state.main_backend_dependency_env_template_errors,
        main_frontend_dependency_env_templates=local_state.main_frontend_dependency_env_templates,
        main_frontend_dependency_env_section_present=local_state.main_frontend_dependency_env_section_present,
        main_frontend_dependency_env_template_errors=local_state.main_frontend_dependency_env_template_errors,
        trees_backend_dependency_env_templates=local_state.trees_backend_dependency_env_templates,
        trees_backend_dependency_env_section_present=local_state.trees_backend_dependency_env_section_present,
        trees_backend_dependency_env_template_errors=local_state.trees_backend_dependency_env_template_errors,
        trees_frontend_dependency_env_templates=local_state.trees_frontend_dependency_env_templates,
        trees_frontend_dependency_env_section_present=local_state.trees_frontend_dependency_env_section_present,
        trees_frontend_dependency_env_template_errors=local_state.trees_frontend_dependency_env_template_errors,
        additional_services=additional_services,
        additional_service_errors=additional_service_errors,
        supabase_auth_users=supabase_auth_users,
        supabase_auth_user_errors=supabase_auth_user_errors,
        supabase_auth_users_strict=parse_bool(resolved.get("ENVCTL_SUPABASE_AUTH_USERS_STRICT"), True),
        service_dependency_env_templates=dict(local_state.service_dependency_env_templates or {}),
        service_dependency_env_section_present=dict(local_state.service_dependency_env_section_present or {}),
        service_dependency_env_template_errors=dict(local_state.service_dependency_env_template_errors or {}),
        mode_service_dependency_env_templates=dict(local_state.mode_service_dependency_env_templates or {}),
        mode_service_dependency_env_section_present=dict(local_state.mode_service_dependency_env_section_present or {}),
        mode_service_dependency_env_template_errors=dict(local_state.mode_service_dependency_env_template_errors or {}),
    )


_POSTGRES_TEMPLATE_SOURCE_TOKENS = (
    "${ENVCTL_SOURCE_DATABASE_URL}",
    "${ENVCTL_SOURCE_SQLALCHEMY_DATABASE_URL}",
    "${ENVCTL_SOURCE_ASYNC_DATABASE_URL}",
    "${ENVCTL_SOURCE_DB_HOST}",
    "${ENVCTL_SOURCE_DB_PORT}",
    "${ENVCTL_SOURCE_DB_USER}",
    "${ENVCTL_SOURCE_DB_PASSWORD}",
    "${ENVCTL_SOURCE_DB_NAME}",
)
_REDIS_TEMPLATE_SOURCE_TOKENS = (
    "${ENVCTL_SOURCE_REDIS_URL}",
    "${ENVCTL_SOURCE_REDIS_PORT}",
)
_SUPABASE_TEMPLATE_SOURCE_TOKENS = (
    "${ENVCTL_SOURCE_SUPABASE_URL}",
    "${ENVCTL_SOURCE_SUPABASE_PUBLIC_URL}",
    "${ENVCTL_SOURCE_SUPABASE_PUBLIC_PORT}",
    "${ENVCTL_SOURCE_SUPABASE_API_PORT}",
    "${ENVCTL_SOURCE_SUPABASE_ANON_KEY}",
    "${ENVCTL_SOURCE_SUPABASE_SERVICE_ROLE_KEY}",
    "${ENVCTL_SOURCE_SUPABASE_JWT_SECRET}",
    "${ENVCTL_SOURCE_SUPABASE_JWKS_URL}",
    "${ENVCTL_SOURCE_SUPABASE_DB_PASSWORD}",
    "${ENVCTL_SOURCE_SUPABASE_DB_PORT}",
    "${ENVCTL_SOURCE_SUPABASE_TEST_USER_ID}",
    "${ENVCTL_SOURCE_SUPABASE_TEST_USER_EMAIL}",
    "${ENVCTL_SOURCE_SUPABASE_TEST_USER_PASSWORD}",
)
_SUPABASE_TEMPLATE_SOURCE_PREFIX_TOKENS = (
    "${ENVCTL_SOURCE_SUPABASE_USER_",
)


def _apply_dependency_env_template_inferences(
    profile: StartupProfile,
    *,
    mode: Literal["main", "trees"],
    explicit_values: Mapping[str, str],
    local_state: LocalConfigState,
) -> None:
    """Enable core dynamic dependencies needed by active launch env templates.

    A saved `.envctl` file can contain backend/frontend launch env templates without
    the older managed dependency toggles. In that shape the template is an active
    request for envctl-owned dynamic URLs, so keep PostgreSQL/Redis dynamic by
    default while still honoring explicit dependency enable/disable keys.
    """

    if not profile.startup_enable:
        return
    inferred = _core_dependencies_referenced_by_launch_env_templates(
        local_state,
        mode=mode,
        backend_enabled=profile.backend_enable,
        frontend_enabled=profile.frontend_enable,
    )
    supabase_can_be_enabled = "supabase" in inferred and not _dependency_toggle_explicit_for_mode(
        "supabase", mode=mode, explicit_values=explicit_values
    )
    for dependency_id in sorted(inferred):
        if _dependency_toggle_explicit_for_mode(dependency_id, mode=mode, explicit_values=explicit_values):
            continue
        if dependency_id == "postgres" and (profile.supabase_enable or supabase_can_be_enabled):
            continue
        profile.dependencies[dependency_id] = True


def _core_dependencies_referenced_by_launch_env_templates(
    local_state: LocalConfigState,
    *,
    mode: Literal["main", "trees"],
    backend_enabled: bool,
    frontend_enabled: bool,
) -> set[str]:
    entries: list[DependencyEnvTemplateEntry] = []
    if backend_enabled:
        entries.extend(local_state.dependency_env_templates)
        entries.extend(local_state.backend_dependency_env_templates)
        if mode == "main":
            entries.extend(local_state.main_backend_dependency_env_templates)
        else:
            entries.extend(local_state.trees_backend_dependency_env_templates)
    if frontend_enabled:
        entries.extend(local_state.dependency_env_templates)
        entries.extend(local_state.frontend_dependency_env_templates)
        if mode == "main":
            entries.extend(local_state.main_frontend_dependency_env_templates)
        else:
            entries.extend(local_state.trees_frontend_dependency_env_templates)
    inferred: set[str] = set()
    for entry in entries:
        template = entry.template
        if any(token in template for token in _POSTGRES_TEMPLATE_SOURCE_TOKENS):
            inferred.add("postgres")
        if any(token in template for token in _REDIS_TEMPLATE_SOURCE_TOKENS):
            inferred.add("redis")
        if any(token in template for token in _SUPABASE_TEMPLATE_SOURCE_TOKENS) or any(
            token in template for token in _SUPABASE_TEMPLATE_SOURCE_PREFIX_TOKENS
        ):
            inferred.add("supabase")
    return inferred


def _dependency_toggle_explicit_for_mode(
    dependency_id: str,
    *,
    mode: Literal["main", "trees"],
    explicit_values: Mapping[str, str],
) -> bool:
    for definition in _dependency_definitions():
        if definition.id != dependency_id:
            continue
        return any(key in explicit_values for key in definition.enable_keys_for_mode(mode))
    return False


def _apply_plan_agent_aliases(resolved: dict[str, str], *, explicit_values: Mapping[str, str]) -> None:
    if "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE" not in explicit_values and "CMUX" in explicit_values:
        resolved["ENVCTL_PLAN_AGENT_TERMINALS_ENABLE"] = str(explicit_values.get("CMUX", ""))
    if "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE" not in explicit_values and "CMUX_WORKSPACE" in explicit_values:
        resolved["ENVCTL_PLAN_AGENT_CMUX_WORKSPACE"] = str(explicit_values.get("CMUX_WORKSPACE", ""))
    if "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE" not in explicit_values and "SUPERSET" in explicit_values:
        resolved["ENVCTL_PLAN_AGENT_TERMINALS_ENABLE"] = str(explicit_values.get("SUPERSET", ""))
    if "ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT" not in explicit_values and "SUPERSET" in explicit_values:
        if parse_bool(explicit_values.get("SUPERSET"), False):
            resolved["ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT"] = "superset"
    if "ENVCTL_PLAN_AGENT_SUPERSET_PROJECT" not in explicit_values and "SUPERSET_PROJECT" in explicit_values:
        resolved["ENVCTL_PLAN_AGENT_SUPERSET_PROJECT"] = str(explicit_values.get("SUPERSET_PROJECT", ""))
    if "ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT" not in explicit_values and (
        "SUPERSET_PROJECT" in explicit_values or "ENVCTL_PLAN_AGENT_SUPERSET_PROJECT" in explicit_values
    ):
        resolved["ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT"] = "superset"
    if "ENVCTL_PLAN_AGENT_SUPERSET_WORKSPACE" not in explicit_values and "SUPERSET_WORKSPACE" in explicit_values:
        resolved["ENVCTL_PLAN_AGENT_SUPERSET_WORKSPACE"] = str(explicit_values.get("SUPERSET_WORKSPACE", ""))
    if "ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT" not in explicit_values and (
        "SUPERSET_WORKSPACE" in explicit_values or "ENVCTL_PLAN_AGENT_SUPERSET_WORKSPACE" in explicit_values
    ):
        resolved["ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT"] = "superset"
    if "ENVCTL_PLAN_AGENT_CODEX_CYCLES" not in explicit_values and "CYCLES" in explicit_values:
        resolved["ENVCTL_PLAN_AGENT_CODEX_CYCLES"] = str(explicit_values.get("CYCLES", ""))


def _resolved_backend_start_cmd(*, base_dir: Path, resolved: Mapping[str, str]) -> str:
    raw = str(resolved.get("ENVCTL_BACKEND_START_CMD", "") or "").strip()
    if raw:
        return raw
    suggested = suggest_service_start_command(service_name="backend", project_root=base_dir)
    return str(suggested or "").strip()


def _resolved_backend_dir_name(
    *, base_dir: Path, resolved: Mapping[str, str], explicit_values: Mapping[str, str]
) -> str:
    if "BACKEND_DIR" in explicit_values:
        return str(resolved.get("BACKEND_DIR") or "").strip()
    suggested = suggest_service_directory(service_name="backend", project_root=base_dir)
    return str(suggested or "backend").strip()


def _resolved_frontend_start_cmd(*, base_dir: Path, resolved: Mapping[str, str]) -> str:
    raw = str(resolved.get("ENVCTL_FRONTEND_START_CMD", "") or "").strip()
    if raw:
        return raw
    suggested = suggest_service_start_command(service_name="frontend", project_root=base_dir)
    return str(suggested or "").strip()


def _resolved_frontend_dir_name(
    *, base_dir: Path, resolved: Mapping[str, str], explicit_values: Mapping[str, str]
) -> str:
    if "FRONTEND_DIR" in explicit_values:
        return str(resolved.get("FRONTEND_DIR") or "").strip()
    suggested = suggest_service_directory(service_name="frontend", project_root=base_dir)
    return str(suggested or "frontend").strip()


def _resolved_action_test_cmd(*, base_dir: Path, resolved: Mapping[str, str]) -> str:
    raw = str(resolved.get("ENVCTL_ACTION_TEST_CMD", "") or "").strip()
    if raw:
        return raw
    suggested = suggest_action_test_command(base_dir)
    return str(suggested or "").strip()


def _resolved_backend_test_cmd(*, base_dir: Path, resolved: Mapping[str, str]) -> str:
    raw = str(resolved.get("ENVCTL_BACKEND_TEST_CMD", "") or "").strip()
    if raw:
        return raw
    shared = str(resolved.get("ENVCTL_ACTION_TEST_CMD", "") or "").strip()
    if shared:
        return shared
    suggested = suggest_backend_test_command(base_dir)
    return str(suggested or "").strip()


def _resolved_frontend_test_cmd(*, base_dir: Path, resolved: Mapping[str, str]) -> str:
    raw = str(resolved.get("ENVCTL_FRONTEND_TEST_CMD", "") or "").strip()
    if raw:
        return raw
    shared = str(resolved.get("ENVCTL_ACTION_TEST_CMD", "") or "").strip()
    if shared:
        return shared
    suggested = suggest_frontend_test_command(base_dir)
    return str(suggested or "").strip()


def _resolved_frontend_test_path(*, base_dir: Path, resolved: Mapping[str, str]) -> str:
    raw = str(resolved.get("ENVCTL_FRONTEND_TEST_PATH", "") or "").strip()
    if raw:
        return str(
            canonicalize_frontend_test_path(
                raw,
                project_root=base_dir,
                frontend_dir_name=str(resolved.get("FRONTEND_DIR", "") or "").strip(),
            )
            or raw
        ).strip()
    suggested = suggest_frontend_test_path(base_dir)
    return str(suggested or "").strip()


def _startup_profile_from_resolved(
    resolved: Mapping[str, str],
    *,
    explicit_values: Mapping[str, str],
    mode: Literal["main", "trees"],
    use_managed_dependency_defaults: bool = False,
) -> StartupProfile:
    prefix = "MAIN" if mode == "main" else "TREES"

    def profile_bool(key: str, default: bool) -> bool:
        if key in explicit_values:
            return parse_bool(resolved.get(key), default)
        return default

    dependencies: dict[str, bool] = {}
    for definition in _dependency_definitions():
        if use_managed_dependency_defaults:
            default = managed_dependency_default_enabled(definition.id, mode)
        else:
            default = definition.enabled_by_default(mode)
        value = default
        for key in definition.enable_keys_for_mode(mode):
            if key not in explicit_values:
                continue
            value = parse_bool(resolved.get(key), default)
            break
        dependencies[definition.id] = value
    postgres_key = f"{prefix}_POSTGRES_ENABLE"
    supabase_key = f"{prefix}_SUPABASE_ENABLE"
    if (
        supabase_key in explicit_values
        and parse_bool(resolved.get(supabase_key), False)
        and postgres_key not in explicit_values
    ):
        dependencies["postgres"] = False
    if (
        postgres_key in explicit_values
        and parse_bool(resolved.get(postgres_key), False)
        and supabase_key not in explicit_values
    ):
        dependencies["supabase"] = False
    return StartupProfile(
        startup_enable=profile_bool(f"{prefix}_STARTUP_ENABLE", True),
        backend_enable=profile_bool(f"{prefix}_BACKEND_ENABLE", True),
        frontend_enable=profile_bool(f"{prefix}_FRONTEND_ENABLE", True),
        dependencies=dependencies,
    )


def _default_port_value(key: str) -> int:
    defaults = {
        "DB_PORT": 5432,
        "REDIS_PORT": 6379,
        "N8N_PORT_BASE": 5678,
        "SUPABASE_PUBLIC_PORT": 54321,
        "SUPABASE_API_PORT": 54321,
    }
    return defaults.get(key, 0)


def _runtime_scope_id(*, base_dir: Path, env: Mapping[str, str], resolved: Mapping[str, str]) -> str:
    explicit = (env.get("ENVCTL_RUNTIME_SCOPE_ID") or resolved.get("ENVCTL_RUNTIME_SCOPE_ID") or "").strip()
    if explicit:
        normalized = "".join(ch for ch in explicit.lower() if ch.isalnum() or ch in {"-", "_"})
        return normalized or "repo"
    digest = hashlib.sha256(str(base_dir).encode("utf-8")).hexdigest()[:12]
    return f"repo-{digest}"


def _resolve_path(base_dir: Path, raw: str) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _resolve_planning_dir(*, base_dir: Path, execution_root: Path, raw: str) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    base_candidate = (base_dir / path).resolve()
    execution_candidate = (execution_root / path).resolve()
    if execution_root.resolve() != base_dir.resolve() and execution_candidate.is_dir():
        return execution_candidate
    return base_candidate


def _parse_port_availability_mode(value: str | None, default: str) -> str:
    if value is None:
        return default
    normalized = value.strip().lower()
    allowed = {"auto", "socket_bind", "listener_query", "lock_only"}
    if normalized in allowed:
        return normalized
    return default


def _parse_runtime_truth_mode(value: str | None, default: str) -> str:
    if value is None:
        return default
    normalized = value.strip().lower()
    allowed = {"auto", "strict", "best_effort"}
    if normalized in allowed:
        return normalized
    return default
