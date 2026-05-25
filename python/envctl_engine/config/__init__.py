from __future__ import annotations

from pathlib import Path
from typing import Mapping

from envctl_engine.config.command_defaults import (
    resolved_action_test_cmd as _resolved_action_test_cmd,
    resolved_backend_dir_name as _resolved_backend_dir_name,
    resolved_backend_start_cmd as _resolved_backend_start_cmd,
    resolved_backend_test_cmd as _resolved_backend_test_cmd,
    resolved_frontend_dir_name as _resolved_frontend_dir_name,
    resolved_frontend_start_cmd as _resolved_frontend_start_cmd,
    resolved_frontend_test_cmd as _resolved_frontend_test_cmd,
    resolved_frontend_test_path as _resolved_frontend_test_path,
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
from envctl_engine.config.load_support import (
    _apply_dependency_env_template_inferences,
    _apply_plan_agent_aliases,
    _default_port_value,
    _dependency_definitions,
    _parse_port_availability_mode,
    _parse_runtime_truth_mode,
    _resolve_path,
    _resolve_planning_dir,
    _runtime_scope_id,
    _startup_profile_from_resolved,
)
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
    "_resolved_action_test_cmd",
    "_resolved_backend_dir_name",
    "_resolved_backend_start_cmd",
    "_resolved_backend_test_cmd",
    "_resolved_frontend_dir_name",
    "_resolved_frontend_start_cmd",
    "_resolved_frontend_test_cmd",
    "_resolved_frontend_test_path",
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
