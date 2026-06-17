from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from envctl_engine.config.dependency_env_templates import DependencyEnvTemplateEntry


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
    plan_agent_fullstack_pr_url_e2e_enable: bool
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
