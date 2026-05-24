from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping, cast

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
from envctl_engine.config.profile_defaults import default_profile_settings, managed_dependency_default_enabled
from envctl_engine.runtime.command_resolution import suggest_service_directory, suggest_service_start_command
from envctl_engine.shared.parsing import parse_bool, parse_int, strip_quotes
from envctl_engine.shared.repo_roots import canonical_envctl_project_root

CONFIG_MANAGED_BLOCK_START = "# >>> envctl managed startup config >>>"
CONFIG_MANAGED_BLOCK_END = "# <<< envctl managed startup config <<<"
CONFIG_PRIMARY_FILENAME = ".envctl"
LEGACY_CONFIG_FILENAMES = (".envctl.sh", ".supportopia-config")
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
    "_dependency_env_section_bounds",
    "_extract_backend_dependency_env_section",
    "_extract_dependency_env_section",
    "_extract_frontend_dependency_env_section",
    "_extract_generic_mode_service_dependency_env_sections",
    "_extract_generic_service_dependency_env_sections",
    "_extract_mode_service_dependency_env_section",
    "_frontend_dependency_env_section_bounds",
    "_parse_envctl_text",
    "_strip_template_sections",
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
_SERVICE_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_SUPABASE_AUTH_USER_SLUG_RE = _SERVICE_SLUG_RE
_RESERVED_SERVICE_NAMES = {
    "backend",
    "frontend",
    "postgres",
    "redis",
    "supabase",
    "n8n",
    "all",
    "services",
    "dependencies",
}


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _build_defaults() -> dict[str, str]:
    main_profile = default_profile_settings("main")
    trees_profile = default_profile_settings("trees")
    main_dependencies = cast(Mapping[str, bool], main_profile["dependencies"])
    trees_dependencies = cast(Mapping[str, bool], trees_profile["dependencies"])
    return {
        "ENVCTL_DEFAULT_MODE": "main",
        "BACKEND_DIR": "backend",
        "FRONTEND_DIR": "frontend",
        "ENVCTL_BACKEND_START_CMD": "",
        "ENVCTL_FRONTEND_START_CMD": "",
        "ENVCTL_BACKEND_TEST_CMD": "",
        "ENVCTL_FRONTEND_TEST_CMD": "",
        "ENVCTL_ACTION_TEST_CMD": "",
        "ENVCTL_FRONTEND_TEST_PATH": "",
        "ENVCTL_PLANNING_DIR": "todo/plans",
        "TREES_DIR_NAME": "trees",
        "RUN_SH_RUNTIME_DIR": "/tmp/envctl-runtime",
        "BACKEND_PORT_BASE": "8000",
        "FRONTEND_PORT_BASE": "9000",
        "PORT_SPACING": "20",
        "DB_PORT": "5432",
        "REDIS_PORT": "6379",
        "N8N_PORT_BASE": "5678",
        "POSTGRES_MAIN_ENABLE": _bool_text(bool(main_dependencies["postgres"])),
        "REDIS_ENABLE": _bool_text(bool(main_dependencies["redis"] or trees_dependencies["redis"])),
        "REDIS_MAIN_ENABLE": _bool_text(bool(main_dependencies["redis"])),
        "SUPABASE_MAIN_ENABLE": _bool_text(bool(main_dependencies["supabase"])),
        "N8N_ENABLE": _bool_text(bool(main_dependencies["n8n"] or trees_dependencies["n8n"])),
        "N8N_MAIN_ENABLE": _bool_text(bool(main_dependencies["n8n"])),
        "ENVCTL_STRICT_N8N_BOOTSTRAP": "false",
        "ENVCTL_PORT_AVAILABILITY_MODE": "auto",
        "ENVCTL_PLAN_STRICT_SELECTION": "false",
        "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "false",
        "ENVCTL_PLAN_AGENT_CLI": "codex",
        "ENVCTL_PLAN_AGENT_PRESET": "implement_task",
        "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "2",
        "ENVCTL_PLAN_AGENT_CODEX_GOAL_ENABLE": "true",
        "ENVCTL_PLAN_AGENT_CODEX_YOLO": "true",
        "ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE": "true",
        "ENVCTL_PLAN_AGENT_PR_REVIEW_COMMENTS_ENABLE": "true",
        "ENVCTL_PLAN_AGENT_SHELL": "zsh",
        "ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT": "true",
        "ENVCTL_PLAN_AGENT_CLI_CMD": "",
        "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "",
        "ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT": "cmux",
        "ENVCTL_PLAN_AGENT_SUPERSET_PROJECT": "",
        "ENVCTL_PLAN_AGENT_SUPERSET_WORKSPACE": "",
        "ENVCTL_PLAN_AGENT_SUPERSET_HOST": "",
        "ENVCTL_PLAN_AGENT_SUPERSET_LOCAL": "true",
        "ENVCTL_PLAN_AGENT_SUPERSET_OPEN": "true",
        "ENVCTL_RUNTIME_TRUTH_MODE": "auto",
        "ENVCTL_REQUIREMENTS_STRICT": "true",
        "ENVCTL_BACKEND_BOOTSTRAP_STRICT": "false",
        "ENVCTL_BACKEND_MIGRATIONS_ON_STARTUP": "false",
        "ENVCTL_STATE_COMPAT_MODE": "compat_read_write",
        "ENVCTL_PUBLIC_HOST": "localhost",
        "ENVCTL_UI_VISUAL_HOST": "localhost",
        "MAIN_STARTUP_ENABLE": _bool_text(bool(main_profile["startup_enable"])),
        "MAIN_BACKEND_ENABLE": _bool_text(bool(main_profile["backend_enable"])),
        "MAIN_BACKEND_EXPECT_LISTENER": "true",
        "MAIN_FRONTEND_ENABLE": _bool_text(bool(main_profile["frontend_enable"])),
        "MAIN_POSTGRES_ENABLE": _bool_text(bool(main_dependencies["postgres"])),
        "MAIN_REDIS_ENABLE": _bool_text(bool(main_dependencies["redis"])),
        "MAIN_SUPABASE_ENABLE": _bool_text(bool(main_dependencies["supabase"])),
        "MAIN_N8N_ENABLE": _bool_text(bool(main_dependencies["n8n"])),
        "TREES_STARTUP_ENABLE": _bool_text(bool(trees_profile["startup_enable"])),
        "TREES_BACKEND_ENABLE": _bool_text(bool(trees_profile["backend_enable"])),
        "TREES_BACKEND_EXPECT_LISTENER": "true",
        "TREES_FRONTEND_ENABLE": _bool_text(bool(trees_profile["frontend_enable"])),
        "TREES_POSTGRES_ENABLE": _bool_text(bool(trees_dependencies["postgres"])),
        "TREES_REDIS_ENABLE": _bool_text(bool(trees_dependencies["redis"])),
        "TREES_SUPABASE_ENABLE": _bool_text(bool(trees_dependencies["supabase"])),
        "TREES_N8N_ENABLE": _bool_text(bool(trees_dependencies["n8n"])),
    }


DEFAULTS: dict[str, str] = _build_defaults()

_MANAGED_DEPENDENCY_PORT_KEYS: tuple[str, ...] = (
    "DB_PORT",
    "REDIS_PORT",
    "N8N_PORT_BASE",
)

_MANAGED_DEPENDENCY_ENABLE_KEYS: tuple[str, ...] = (
    "MAIN_POSTGRES_ENABLE",
    "MAIN_REDIS_ENABLE",
    "MAIN_SUPABASE_ENABLE",
    "MAIN_N8N_ENABLE",
    "TREES_POSTGRES_ENABLE",
    "TREES_REDIS_ENABLE",
    "TREES_SUPABASE_ENABLE",
    "TREES_N8N_ENABLE",
)

MANAGED_CONFIG_KEYS: tuple[str, ...] = (
    "ENVCTL_DEFAULT_MODE",
    "BACKEND_DIR",
    "FRONTEND_DIR",
    "ENVCTL_BACKEND_START_CMD",
    "ENVCTL_FRONTEND_START_CMD",
    "ENVCTL_BACKEND_TEST_CMD",
    "ENVCTL_FRONTEND_TEST_CMD",
    "ENVCTL_FRONTEND_TEST_PATH",
    "ENVCTL_PUBLIC_HOST",
    "ENVCTL_UI_VISUAL_HOST",
    "BACKEND_PORT_BASE",
    "FRONTEND_PORT_BASE",
    *_MANAGED_DEPENDENCY_PORT_KEYS,
    "PORT_SPACING",
    "MAIN_STARTUP_ENABLE",
    "MAIN_BACKEND_ENABLE",
    "MAIN_BACKEND_EXPECT_LISTENER",
    "MAIN_FRONTEND_ENABLE",
    *_MANAGED_DEPENDENCY_ENABLE_KEYS,
    "TREES_STARTUP_ENABLE",
    "TREES_BACKEND_ENABLE",
    "TREES_BACKEND_EXPECT_LISTENER",
    "TREES_FRONTEND_ENABLE",
)


@dataclass(slots=True, init=False)
class StartupProfile:
    startup_enable: bool
    backend_enable: bool
    frontend_enable: bool
    dependencies: dict[str, bool]

    def __init__(
        self,
        startup_enable: bool,
        backend_enable: bool,
        frontend_enable: bool,
        postgres_enable: bool | None = None,
        redis_enable: bool | None = None,
        supabase_enable: bool | None = None,
        n8n_enable: bool | None = None,
        *,
        dependencies: dict[str, bool] | None = None,
    ) -> None:
        self.startup_enable = bool(startup_enable)
        self.backend_enable = bool(backend_enable)
        self.frontend_enable = bool(frontend_enable)
        if dependencies is not None:
            self.dependencies = {str(key).strip().lower(): bool(value) for key, value in dependencies.items()}
        else:
            self.dependencies = {
                "postgres": bool(postgres_enable),
                "redis": bool(redis_enable),
                "supabase": bool(supabase_enable),
                "n8n": bool(n8n_enable),
            }

    def dependency_enabled(self, dependency_id: str) -> bool:
        return bool(self.dependencies.get(str(dependency_id).strip().lower(), False))

    @property
    def postgres_enable(self) -> bool:
        return self.dependency_enabled("postgres")

    @postgres_enable.setter
    def postgres_enable(self, value: bool) -> None:
        self.dependencies["postgres"] = bool(value)

    @property
    def redis_enable(self) -> bool:
        return self.dependency_enabled("redis")

    @redis_enable.setter
    def redis_enable(self, value: bool) -> None:
        self.dependencies["redis"] = bool(value)

    @property
    def supabase_enable(self) -> bool:
        return self.dependency_enabled("supabase")

    @supabase_enable.setter
    def supabase_enable(self, value: bool) -> None:
        self.dependencies["supabase"] = bool(value)

    @property
    def n8n_enable(self) -> bool:
        return self.dependency_enabled("n8n")

    @n8n_enable.setter
    def n8n_enable(self, value: bool) -> None:
        self.dependencies["n8n"] = bool(value)


@dataclass(slots=True, init=False)
class PortDefaults:
    backend_port_base: int
    frontend_port_base: int
    dependency_ports: dict[str, dict[str, int]]
    port_spacing: int

    def __init__(
        self,
        backend_port_base: int,
        frontend_port_base: int,
        db_port_base: int | None = None,
        redis_port_base: int | None = None,
        n8n_port_base: int | None = None,
        port_spacing: int = 20,
        *,
        dependency_ports: dict[str, dict[str, int]] | None = None,
    ) -> None:
        self.backend_port_base = int(backend_port_base)
        self.frontend_port_base = int(frontend_port_base)
        self.port_spacing = int(port_spacing)
        if dependency_ports is not None:
            self.dependency_ports = {
                str(key).strip().lower(): {str(resource): int(value) for resource, value in resource_map.items()}
                for key, resource_map in dependency_ports.items()
            }
        else:
            self.dependency_ports = {
                "postgres": {"primary": int(db_port_base or 5432)},
                "redis": {"primary": int(redis_port_base or 6379)},
                "supabase": {"db": int(db_port_base or 5432), "api": 54321},
                "n8n": {"primary": int(n8n_port_base or 5678)},
            }

    def dependency_port(self, dependency_id: str, resource_name: str = "primary") -> int:
        component = self.dependency_ports.get(str(dependency_id).strip().lower(), {})
        return int(component.get(resource_name, 0) or 0)

    @property
    def db_port_base(self) -> int:
        return self.dependency_port("postgres")

    @property
    def redis_port_base(self) -> int:
        return self.dependency_port("redis")

    @property
    def n8n_port_base(self) -> int:
        return self.dependency_port("n8n")


@dataclass(slots=True)
class AppServiceConfig:
    name: str
    env_suffix: str
    enabled_main: bool
    enabled_trees: bool
    dir_name: str
    start_cmd: str
    test_cmd: str = ""
    port_base: int | None = None
    expect_listener: bool = True
    health_url_template: str = ""
    public_url_template: str = ""
    startup_group: str = "app"
    depends_on: tuple[str, ...] = ()
    start_order: int = 100
    critical: bool = True
    enable_if_path: str = ""

    def enabled_for_mode(self, mode: str) -> bool:
        return self.enabled_trees if str(mode).strip().lower() == "trees" else self.enabled_main

    def enabled_for_project_root(self, mode: str, project_root: Path | str | None) -> bool:
        if not self.enabled_for_mode(mode):
            return False
        if not self.enable_if_path:
            return True
        if project_root is None:
            return False
        root = Path(project_root).expanduser().resolve(strict=False)
        candidate = (root / self.enable_if_path).resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError:
            return False
        return candidate.exists()


@dataclass(slots=True)
class SupabaseAuthUserConfig:
    name: str
    env_suffix: str
    email: str
    password: str | None = None
    auto_confirm: bool = True
    user_metadata: dict[str, object] | None = None
    app_metadata: dict[str, object] | None = None
    enabled_main: bool = True
    enabled_trees: bool = True
    delete_on_blast: bool = False
    expose_password: bool = True

    def enabled_for_mode(self, mode: str) -> bool:
        return self.enabled_trees if str(mode).strip().lower() == "trees" else self.enabled_main


@dataclass(slots=True)
class LocalConfigState:
    base_dir: Path
    config_file_path: Path
    config_file_exists: bool
    config_source: Literal["envctl", "legacy_prefill", "defaults"]
    active_source_path: Path | None
    legacy_source_path: Path | None
    explicit_path: Path | None
    parsed_values: dict[str, str]
    file_text: str
    dependency_env_templates: tuple["DependencyEnvTemplateEntry", ...] = ()
    dependency_env_section_present: bool = False
    dependency_env_template_errors: tuple[str, ...] = ()
    backend_dependency_env_templates: tuple["DependencyEnvTemplateEntry", ...] = ()
    backend_dependency_env_section_present: bool = False
    backend_dependency_env_template_errors: tuple[str, ...] = ()
    frontend_dependency_env_templates: tuple["DependencyEnvTemplateEntry", ...] = ()
    frontend_dependency_env_section_present: bool = False
    frontend_dependency_env_template_errors: tuple[str, ...] = ()
    main_backend_dependency_env_templates: tuple["DependencyEnvTemplateEntry", ...] = ()
    main_backend_dependency_env_section_present: bool = False
    main_backend_dependency_env_template_errors: tuple[str, ...] = ()
    main_frontend_dependency_env_templates: tuple["DependencyEnvTemplateEntry", ...] = ()
    main_frontend_dependency_env_section_present: bool = False
    main_frontend_dependency_env_template_errors: tuple[str, ...] = ()
    trees_backend_dependency_env_templates: tuple["DependencyEnvTemplateEntry", ...] = ()
    trees_backend_dependency_env_section_present: bool = False
    trees_backend_dependency_env_template_errors: tuple[str, ...] = ()
    trees_frontend_dependency_env_templates: tuple["DependencyEnvTemplateEntry", ...] = ()
    trees_frontend_dependency_env_section_present: bool = False
    trees_frontend_dependency_env_template_errors: tuple[str, ...] = ()
    service_dependency_env_templates: dict[str, tuple["DependencyEnvTemplateEntry", ...]] | None = None
    service_dependency_env_section_present: dict[str, bool] | None = None
    service_dependency_env_template_errors: dict[str, tuple[str, ...]] | None = None
    mode_service_dependency_env_templates: dict[tuple[str, str], tuple["DependencyEnvTemplateEntry", ...]] | None = None
    mode_service_dependency_env_section_present: dict[tuple[str, str], bool] | None = None
    mode_service_dependency_env_template_errors: dict[tuple[str, str], tuple[str, ...]] | None = None


@dataclass(slots=True)
class EngineConfig:
    base_dir: Path
    execution_root: Path
    backend_dir_name: str
    frontend_dir_name: str
    backend_start_cmd: str
    frontend_start_cmd: str
    backend_test_cmd: str
    frontend_test_cmd: str
    action_test_cmd: str
    frontend_test_path: str
    runtime_dir: Path
    runtime_scope_id: str
    runtime_scope_dir: Path
    planning_dir: Path
    trees_dir_name: str
    default_mode: str
    backend_port_base: int
    frontend_port_base: int
    port_spacing: int
    db_port_base: int
    redis_port_base: int
    n8n_port_base: int
    postgres_main_enable: bool
    redis_enable: bool
    redis_main_enable: bool
    supabase_main_enable: bool
    n8n_enable: bool
    n8n_main_enable: bool
    strict_n8n_bootstrap: bool
    port_availability_mode: str
    plan_strict_selection: bool
    plan_agent_terminals_enable: bool
    plan_agent_cli: str
    plan_agent_preset: str
    plan_agent_codex_cycles: int
    plan_agent_codex_goal_enable: bool
    plan_agent_codex_yolo: bool
    plan_agent_browser_e2e_enable: bool
    plan_agent_pr_review_comments_enable: bool
    plan_agent_shell: str
    plan_agent_require_cmux_context: bool
    plan_agent_cli_cmd: str
    plan_agent_cmux_workspace: str
    plan_agent_surface_transport: str
    plan_agent_superset_project: str
    plan_agent_superset_workspace: str
    plan_agent_superset_host: str
    plan_agent_superset_local: bool
    plan_agent_superset_open: bool
    runtime_truth_mode: str
    requirements_strict: bool
    main_profile: StartupProfile
    trees_profile: StartupProfile
    main_backend_expect_listener: bool
    trees_backend_expect_listener: bool
    port_defaults: PortDefaults
    config_file_path: Path
    config_file_exists: bool
    config_source: Literal["envctl", "legacy_prefill", "defaults"]
    raw: dict[str, str]
    explicit_keys: tuple[str, ...] = ()
    dependency_env_templates: tuple["DependencyEnvTemplateEntry", ...] = ()
    dependency_env_section_present: bool = False
    dependency_env_template_errors: tuple[str, ...] = ()
    backend_dependency_env_templates: tuple["DependencyEnvTemplateEntry", ...] = ()
    backend_dependency_env_section_present: bool = False
    backend_dependency_env_template_errors: tuple[str, ...] = ()
    frontend_dependency_env_templates: tuple["DependencyEnvTemplateEntry", ...] = ()
    frontend_dependency_env_section_present: bool = False
    frontend_dependency_env_template_errors: tuple[str, ...] = ()
    main_backend_dependency_env_templates: tuple["DependencyEnvTemplateEntry", ...] = ()
    main_backend_dependency_env_section_present: bool = False
    main_backend_dependency_env_template_errors: tuple[str, ...] = ()
    main_frontend_dependency_env_templates: tuple["DependencyEnvTemplateEntry", ...] = ()
    main_frontend_dependency_env_section_present: bool = False
    main_frontend_dependency_env_template_errors: tuple[str, ...] = ()
    trees_backend_dependency_env_templates: tuple["DependencyEnvTemplateEntry", ...] = ()
    trees_backend_dependency_env_section_present: bool = False
    trees_backend_dependency_env_template_errors: tuple[str, ...] = ()
    trees_frontend_dependency_env_templates: tuple["DependencyEnvTemplateEntry", ...] = ()
    trees_frontend_dependency_env_section_present: bool = False
    trees_frontend_dependency_env_template_errors: tuple[str, ...] = ()
    additional_services: tuple[AppServiceConfig, ...] = ()
    additional_service_errors: tuple[str, ...] = ()
    supabase_auth_users: tuple[SupabaseAuthUserConfig, ...] = ()
    supabase_auth_user_errors: tuple[str, ...] = ()
    supabase_auth_users_strict: bool = True
    service_dependency_env_templates: dict[str, tuple["DependencyEnvTemplateEntry", ...]] | None = None
    service_dependency_env_section_present: dict[str, bool] | None = None
    service_dependency_env_template_errors: dict[str, tuple[str, ...]] | None = None
    mode_service_dependency_env_templates: dict[tuple[str, str], tuple["DependencyEnvTemplateEntry", ...]] | None = None
    mode_service_dependency_env_section_present: dict[tuple[str, str], bool] | None = None
    mode_service_dependency_env_template_errors: dict[tuple[str, str], tuple[str, ...]] | None = None

    def profile_for_mode(self, mode: str) -> StartupProfile:
        return self.trees_profile if str(mode).strip().lower() == "trees" else self.main_profile

    def startup_enabled_for_mode(self, mode: str) -> bool:
        return self.profile_for_mode(mode).startup_enable

    def service_enabled_for_mode(self, mode: str, service_name: str) -> bool:
        if not self.startup_enabled_for_mode(mode):
            return False
        profile = self.profile_for_mode(mode)
        normalized = str(service_name).strip().lower()
        if normalized == "backend":
            return profile.backend_enable
        if normalized == "frontend":
            return profile.frontend_enable
        service = self.app_service_by_name(normalized)
        if service is not None:
            return service.enabled_for_mode(mode)
        return False

    def app_service_names(self) -> tuple[str, ...]:
        return tuple(service.name for service in self.additional_services)

    def app_service_by_name(self, name: str) -> AppServiceConfig | None:
        normalized = str(name).strip().lower()
        for service in self.additional_services:
            if service.name == normalized:
                return service
        return None

    def app_service_enabled_for_project_root(
        self, mode: str, service_name: str, project_root: Path | str | None
    ) -> bool:
        if not self.startup_enabled_for_mode(mode):
            return False
        service = self.app_service_by_name(service_name)
        if service is None:
            return False
        return service.enabled_for_project_root(mode, project_root)

    def all_app_service_names_for_mode(
        self, mode: str, project_root: Path | str | None = None
    ) -> tuple[str, ...]:
        names: list[str] = []
        for service_name in ("backend", "frontend"):
            if self.service_enabled_for_mode(mode, service_name):
                names.append(service_name)
        for service in self.additional_services:
            if service.enabled_for_project_root(mode, project_root):
                names.append(service.name)
        return tuple(names)

    def requirement_enabled_for_mode(self, mode: str, requirement_name: str) -> bool:
        if not self.startup_enabled_for_mode(mode):
            return False
        profile = self.profile_for_mode(mode)
        return profile.dependency_enabled(str(requirement_name).strip().lower())

    def backend_expects_listener_for_mode(self, mode: str) -> bool:
        normalized = str(mode).strip().lower()
        if normalized == "trees":
            return bool(self.trees_backend_expect_listener)
        return bool(self.main_backend_expect_listener)


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


def _generated_worktree_control_root(
    *,
    requested_root: Path,
    execution_root: Path,
    trees_dir_name: str,
) -> Path | None:
    for candidate in (execution_root, requested_root):
        resolved = Path(candidate).expanduser()
        if resolved.is_file():
            resolved = resolved.parent
        resolved = resolved.resolve()
        provenance_root = _control_root_from_worktree_provenance(resolved)
        if provenance_root is not None:
            return provenance_root
        shaped_root = _control_root_from_generated_tree_shape(resolved, trees_dir_name=trees_dir_name)
        if shaped_root is not None:
            return shaped_root
    return None


def _control_root_from_worktree_provenance(worktree_root: Path) -> Path | None:
    path = worktree_root / ".envctl-state" / "worktree-provenance.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    raw_root = str(payload.get("created_from_repo", "") or "").strip()
    if not raw_root:
        return None
    root = Path(raw_root).expanduser().resolve()
    if (root / CONFIG_PRIMARY_FILENAME).is_file():
        return root
    return None


def _control_root_from_generated_tree_shape(path: Path, *, trees_dir_name: str) -> Path | None:
    normalized_trees = str(trees_dir_name or DEFAULTS["TREES_DIR_NAME"]).strip().rstrip("/") or "trees"
    current = path.resolve()
    while current.parent != current:
        if current.parent.name and current.parent.parent.name == Path(normalized_trees).name:
            repo_root = current.parent.parent.parent
            if (repo_root / CONFIG_PRIMARY_FILENAME).is_file():
                return repo_root.resolve()
        if (current / ".git").is_dir() or (current / ".git").is_file():
            return None
        current = current.parent
    return None


def _parse_additional_services(resolved: Mapping[str, str]) -> tuple[tuple[AppServiceConfig, ...], tuple[str, ...]]:
    declared = [
        item.strip().lower()
        for item in str(resolved.get("ENVCTL_ADDITIONAL_SERVICES", "") or "").split(",")
        if item.strip()
    ]
    services: list[AppServiceConfig] = []
    errors: list[str] = []
    seen_names: set[str] = set()
    seen_suffixes: set[str] = set()
    for name in declared:
        suffix = _service_env_suffix(name)
        if not _SERVICE_SLUG_RE.fullmatch(name):
            errors.append(f"invalid service slug {name!r}: use lowercase letters, numbers, and hyphens")
            continue
        if name in _RESERVED_SERVICE_NAMES:
            errors.append(f"reserved service name {name!r} cannot be used as an additional app service")
            continue
        if name in seen_names:
            errors.append(f"duplicate service slug {name!r}")
            continue
        if suffix in seen_suffixes:
            errors.append(f"duplicate service env suffix {suffix!r}")
            continue
        prefix = f"ENVCTL_SERVICE_{suffix}_"
        enabled_default = parse_bool(resolved.get(f"{prefix}ENABLE"), True)
        enabled_main = parse_bool(resolved.get(f"{prefix}MAIN_ENABLE"), enabled_default)
        enabled_trees = parse_bool(resolved.get(f"{prefix}TREES_ENABLE"), enabled_default)
        start_cmd = str(resolved.get(f"{prefix}START_CMD", "") or "").strip()
        expect_listener = parse_bool(resolved.get(f"{prefix}EXPECT_LISTENER"), True)
        port_base_raw = str(resolved.get(f"{prefix}PORT_BASE", "") or "").strip()
        port_base = parse_int(port_base_raw, 0) if port_base_raw else None
        if (enabled_main or enabled_trees) and not start_cmd:
            errors.append(f"enabled service {name!r} requires {prefix}START_CMD")
            continue
        if (enabled_main or enabled_trees) and expect_listener and (port_base is None or port_base <= 0):
            errors.append(f"listener service {name!r} requires {prefix}PORT_BASE")
            continue
        seen_names.add(name)
        seen_suffixes.add(suffix)
        services.append(
            AppServiceConfig(
                name=name,
                env_suffix=suffix,
                enabled_main=enabled_main,
                enabled_trees=enabled_trees,
                dir_name=str(resolved.get(f"{prefix}DIR", "") or "").strip() or ".",
                start_cmd=start_cmd,
                test_cmd=str(resolved.get(f"{prefix}TEST_CMD", "") or "").strip(),
                port_base=port_base,
                expect_listener=expect_listener,
                health_url_template=str(resolved.get(f"{prefix}HEALTH_URL", "") or "").strip(),
                public_url_template=str(resolved.get(f"{prefix}PUBLIC_URL", "") or "").strip(),
                startup_group=str(resolved.get(f"{prefix}STARTUP_GROUP", "app") or "app").strip() or "app",
                depends_on=tuple(
                    item.strip().lower()
                    for item in str(resolved.get(f"{prefix}DEPENDS_ON", "") or "").split(",")
                    if item.strip()
                ),
                start_order=parse_int(resolved.get(f"{prefix}START_ORDER"), 100),
                critical=parse_bool(resolved.get(f"{prefix}CRITICAL"), True),
                enable_if_path=str(resolved.get(f"{prefix}ENABLE_IF_PATH", "") or "").strip(),
            )
        )
    dependency_errors = _validate_additional_service_dependencies(services)
    errors.extend(dependency_errors)
    if errors:
        return (), tuple(errors)
    return tuple(services), ()


def _parse_supabase_auth_users(
    resolved: Mapping[str, str],
) -> tuple[tuple[SupabaseAuthUserConfig, ...], tuple[str, ...]]:
    declared = [
        item.strip().lower()
        for item in str(resolved.get("ENVCTL_SUPABASE_AUTH_USERS", "") or "").split(",")
        if item.strip()
    ]
    users: list[SupabaseAuthUserConfig] = []
    errors: list[str] = []
    seen_names: set[str] = set()
    seen_suffixes: set[str] = set()
    for name in declared:
        suffix = _service_env_suffix(name)
        if not _SUPABASE_AUTH_USER_SLUG_RE.fullmatch(name):
            errors.append(f"invalid Supabase Auth user slug {name!r}: use lowercase letters, numbers, and hyphens")
            continue
        if name in seen_names:
            errors.append(f"duplicate Supabase Auth user slug {name!r}")
            continue
        if suffix in seen_suffixes:
            errors.append(f"duplicate Supabase Auth user env suffix {suffix!r}")
            continue
        prefix = f"ENVCTL_SUPABASE_USER_{suffix}_"
        enabled_default = parse_bool(resolved.get(f"{prefix}ENABLE"), True)
        enabled_main = parse_bool(resolved.get(f"{prefix}MAIN_ENABLE"), enabled_default)
        enabled_trees = parse_bool(resolved.get(f"{prefix}TREES_ENABLE"), enabled_default)
        email = str(resolved.get(f"{prefix}EMAIL", "") or "").strip()
        password = str(resolved.get(f"{prefix}PASSWORD", "") or "").strip() or None
        if (enabled_main or enabled_trees) and not email:
            errors.append(f"Supabase Auth user {name!r} requires {prefix}EMAIL")
        if (enabled_main or enabled_trees) and password is None:
            errors.append(f"Supabase Auth user {name!r} requires {prefix}PASSWORD or runtime password env")
        user_metadata, user_metadata_error = _parse_json_object_value(
            resolved.get(f"{prefix}USER_METADATA_JSON"),
            key=f"{prefix}USER_METADATA_JSON",
        )
        if user_metadata_error:
            errors.append(user_metadata_error)
        app_metadata, app_metadata_error = _parse_json_object_value(
            resolved.get(f"{prefix}APP_METADATA_JSON"),
            key=f"{prefix}APP_METADATA_JSON",
        )
        if app_metadata_error:
            errors.append(app_metadata_error)
        seen_names.add(name)
        seen_suffixes.add(suffix)
        users.append(
            SupabaseAuthUserConfig(
                name=name,
                env_suffix=suffix,
                email=email,
                password=password,
                auto_confirm=parse_bool(resolved.get(f"{prefix}AUTO_CONFIRM"), True),
                user_metadata=user_metadata,
                app_metadata=app_metadata,
                enabled_main=enabled_main,
                enabled_trees=enabled_trees,
                delete_on_blast=parse_bool(resolved.get(f"{prefix}DELETE_ON_BLAST"), False),
                expose_password=parse_bool(resolved.get(f"{prefix}EXPOSE_PASSWORD"), True),
            )
        )
    return tuple(users), tuple(errors)


def _parse_json_object_value(raw: object, *, key: str) -> tuple[dict[str, object], str | None]:
    text = str(raw or "").strip()
    if not text:
        return {}, None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, f"{key} must be a JSON object: {exc.msg}"
    if not isinstance(payload, dict):
        return {}, f"{key} must be a JSON object"
    return dict(payload), None


def _validate_additional_service_dependencies(services: list[AppServiceConfig]) -> list[str]:
    from envctl_engine.requirements.core import dependency_ids

    errors: list[str] = []
    service_names = {service.name for service in services}
    allowed = {"backend", "frontend", *dependency_ids(), *service_names}
    graph: dict[str, set[str]] = {service.name: set() for service in services}
    for service in services:
        for dependency in service.depends_on:
            if dependency not in allowed:
                errors.append(
                    f"service {service.name!r} depends on unknown service or dependency {dependency!r}"
                )
                continue
            if dependency in service_names:
                graph[service.name].add(dependency)

    visiting: list[str] = []
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        if name in visiting:
            cycle = [*visiting[visiting.index(name) :], name]
            errors.append("additional service dependency cycle: " + " -> ".join(cycle))
            return
        visiting.append(name)
        for dependency in sorted(graph.get(name, set())):
            visit(dependency)
        visiting.pop()
        visited.add(name)

    for service in services:
        visit(service.name)
    return errors


def _service_env_suffix(service_name: str) -> str:
    return str(service_name).strip().upper().replace("-", "_")


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


def discover_local_config_state(base_dir: Path, explicit_path: str | None = None) -> LocalConfigState:
    base_dir = Path(base_dir).resolve()
    resolved_explicit = _resolve_explicit_path(base_dir, explicit_path)
    primary_path = base_dir / CONFIG_PRIMARY_FILENAME
    file_path = primary_path
    file_exists = primary_path.is_file()
    source: Literal["envctl", "legacy_prefill", "defaults"] = "envctl" if file_exists else "defaults"
    active_source_path: Path | None = primary_path if file_exists else None
    legacy_source_path: Path | None = None

    if resolved_explicit is not None and resolved_explicit.is_file():
        active_source_path = resolved_explicit
        if resolved_explicit.name == CONFIG_PRIMARY_FILENAME:
            file_path = resolved_explicit
            file_exists = True
            source = "envctl"
        else:
            file_exists = primary_path.is_file()
            source = "legacy_prefill" if not file_exists else "envctl"
            legacy_source_path = resolved_explicit
    elif file_exists:
        source = "envctl"
    else:
        for candidate_name in LEGACY_CONFIG_FILENAMES:
            candidate = base_dir / candidate_name
            if candidate.is_file():
                active_source_path = candidate
                legacy_source_path = candidate
                source = "legacy_prefill"
                break

    file_text = ""
    parsed_values: dict[str, str] = {}
    dependency_env_templates: tuple[DependencyEnvTemplateEntry, ...] = ()
    dependency_env_section_present = False
    dependency_env_template_errors: tuple[str, ...] = ()
    backend_dependency_env_templates: tuple[DependencyEnvTemplateEntry, ...] = ()
    backend_dependency_env_section_present = False
    backend_dependency_env_template_errors: tuple[str, ...] = ()
    frontend_dependency_env_templates: tuple[DependencyEnvTemplateEntry, ...] = ()
    frontend_dependency_env_section_present = False
    frontend_dependency_env_template_errors: tuple[str, ...] = ()
    main_backend_dependency_env_templates: tuple[DependencyEnvTemplateEntry, ...] = ()
    main_backend_dependency_env_section_present = False
    main_backend_dependency_env_template_errors: tuple[str, ...] = ()
    main_frontend_dependency_env_templates: tuple[DependencyEnvTemplateEntry, ...] = ()
    main_frontend_dependency_env_section_present = False
    main_frontend_dependency_env_template_errors: tuple[str, ...] = ()
    trees_backend_dependency_env_templates: tuple[DependencyEnvTemplateEntry, ...] = ()
    trees_backend_dependency_env_section_present = False
    trees_backend_dependency_env_template_errors: tuple[str, ...] = ()
    trees_frontend_dependency_env_templates: tuple[DependencyEnvTemplateEntry, ...] = ()
    trees_frontend_dependency_env_section_present = False
    trees_frontend_dependency_env_template_errors: tuple[str, ...] = ()
    service_dependency_env_templates: dict[str, tuple[DependencyEnvTemplateEntry, ...]] = {}
    service_dependency_env_section_present: dict[str, bool] = {}
    service_dependency_env_template_errors: dict[str, tuple[str, ...]] = {}
    mode_service_dependency_env_templates: dict[tuple[str, str], tuple[DependencyEnvTemplateEntry, ...]] = {}
    mode_service_dependency_env_section_present: dict[tuple[str, str], bool] = {}
    mode_service_dependency_env_template_errors: dict[tuple[str, str], tuple[str, ...]] = {}
    if active_source_path is not None and active_source_path.is_file():
        try:
            file_text = active_source_path.read_text(encoding="utf-8")
        except OSError:
            file_text = ""
        parsed_values = _parse_envctl_text(file_text)
        (
            dependency_env_templates,
            dependency_env_section_present,
            dependency_env_template_errors,
        ) = _extract_dependency_env_section(file_text)
        (
            backend_dependency_env_templates,
            backend_dependency_env_section_present,
            backend_dependency_env_template_errors,
        ) = _extract_backend_dependency_env_section(file_text)
        (
            frontend_dependency_env_templates,
            frontend_dependency_env_section_present,
            frontend_dependency_env_template_errors,
        ) = _extract_frontend_dependency_env_section(file_text)
        (
            main_backend_dependency_env_templates,
            main_backend_dependency_env_section_present,
            main_backend_dependency_env_template_errors,
        ) = _extract_mode_service_dependency_env_section(file_text, mode="main", service_name="backend")
        (
            main_frontend_dependency_env_templates,
            main_frontend_dependency_env_section_present,
            main_frontend_dependency_env_template_errors,
        ) = _extract_mode_service_dependency_env_section(file_text, mode="main", service_name="frontend")
        (
            trees_backend_dependency_env_templates,
            trees_backend_dependency_env_section_present,
            trees_backend_dependency_env_template_errors,
        ) = _extract_mode_service_dependency_env_section(file_text, mode="trees", service_name="backend")
        (
            trees_frontend_dependency_env_templates,
            trees_frontend_dependency_env_section_present,
            trees_frontend_dependency_env_template_errors,
        ) = _extract_mode_service_dependency_env_section(file_text, mode="trees", service_name="frontend")
        (
            service_dependency_env_templates,
            service_dependency_env_section_present,
            service_dependency_env_template_errors,
        ) = _extract_generic_service_dependency_env_sections(file_text)
        (
            mode_service_dependency_env_templates,
            mode_service_dependency_env_section_present,
            mode_service_dependency_env_template_errors,
        ) = _extract_generic_mode_service_dependency_env_sections(file_text)

    return LocalConfigState(
        base_dir=base_dir,
        config_file_path=file_path,
        config_file_exists=file_exists,
        config_source=source,
        active_source_path=active_source_path,
        legacy_source_path=legacy_source_path,
        explicit_path=resolved_explicit,
        parsed_values=parsed_values,
        file_text=file_text,
        dependency_env_templates=dependency_env_templates,
        dependency_env_section_present=dependency_env_section_present,
        dependency_env_template_errors=dependency_env_template_errors,
        backend_dependency_env_templates=backend_dependency_env_templates,
        backend_dependency_env_section_present=backend_dependency_env_section_present,
        backend_dependency_env_template_errors=backend_dependency_env_template_errors,
        frontend_dependency_env_templates=frontend_dependency_env_templates,
        frontend_dependency_env_section_present=frontend_dependency_env_section_present,
        frontend_dependency_env_template_errors=frontend_dependency_env_template_errors,
        main_backend_dependency_env_templates=main_backend_dependency_env_templates,
        main_backend_dependency_env_section_present=main_backend_dependency_env_section_present,
        main_backend_dependency_env_template_errors=main_backend_dependency_env_template_errors,
        main_frontend_dependency_env_templates=main_frontend_dependency_env_templates,
        main_frontend_dependency_env_section_present=main_frontend_dependency_env_section_present,
        main_frontend_dependency_env_template_errors=main_frontend_dependency_env_template_errors,
        trees_backend_dependency_env_templates=trees_backend_dependency_env_templates,
        trees_backend_dependency_env_section_present=trees_backend_dependency_env_section_present,
        trees_backend_dependency_env_template_errors=trees_backend_dependency_env_template_errors,
        trees_frontend_dependency_env_templates=trees_frontend_dependency_env_templates,
        trees_frontend_dependency_env_section_present=trees_frontend_dependency_env_section_present,
        trees_frontend_dependency_env_template_errors=trees_frontend_dependency_env_template_errors,
        service_dependency_env_templates=service_dependency_env_templates,
        service_dependency_env_section_present=service_dependency_env_section_present,
        service_dependency_env_template_errors=service_dependency_env_template_errors,
        mode_service_dependency_env_templates=mode_service_dependency_env_templates,
        mode_service_dependency_env_section_present=mode_service_dependency_env_section_present,
        mode_service_dependency_env_template_errors=mode_service_dependency_env_template_errors,
    )


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


def _resolve_explicit_path(base_dir: Path, explicit_path: str | None) -> Path | None:
    if not explicit_path:
        return None
    path = Path(explicit_path).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def _parse_envctl_text(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in _strip_template_sections(text).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = strip_quotes(value.strip())
    return parsed


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
