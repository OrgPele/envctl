from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import re

from ....actions.actions_test import (
    suggest_backend_test_command,
    suggest_frontend_test_command,
    suggest_frontend_test_path,
)
from ....config import AppServiceConfig, LocalConfigState, StartupProfile
from ....config.persistence import ManagedConfigValues, managed_values_from_local_state
from ....requirements.core import dependency_definitions
from ....runtime.command_resolution import suggest_service_directory, suggest_service_start_command
from envctl_engine.shared.parsing import parse_bool
from envctl_engine.ui.textual.list_row_styles import selectable_list_row_css

_SERVICE_FIELDS: tuple[tuple[str, str], ...] = (
    ("backend_enable", "Backend"),
    ("frontend_enable", "Frontend"),
)

_SERVICE_STARTUP_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("startup_enable", "main", "Main - start this service with envctl"),
    ("startup_enable", "trees", "Trees - start this service with envctl"),
    ("backend_expect_listener", "main", "Main - wait for a listener/port before continuing"),
    ("backend_expect_listener", "trees", "Trees - wait for a listener/port before continuing"),
)

_COMPONENT_FIELDS: tuple[tuple[str, str], ...] = (
    *tuple((definition.id, definition.display_name.title()) for definition in dependency_definitions()),
)

_DIRECTORY_FIELDS: tuple[tuple[str, str], ...] = (
    ("backend_dir_name", "Backend directory"),
    ("frontend_dir_name", "Frontend directory"),
    ("frontend_test_path", "Frontend tests directory"),
)

_COMMAND_FIELDS: tuple[tuple[str, str], ...] = (
    ("backend_start_cmd", "Backend entrypoint"),
    ("frontend_start_cmd", "Frontend entrypoint"),
    ("backend_test_cmd", "Backend test command"),
    ("frontend_test_cmd", "Frontend test command"),
)

_PORT_FIELDS: tuple[tuple[str, str], ...] = (
    ("backend_port_base", "Backend base port"),
    ("frontend_port_base", "Frontend base port"),
    ("db_port_base", "Database base port"),
    ("redis_port_base", "Redis base port"),
    ("n8n_port_base", "n8n base port"),
    ("port_spacing", "Port spacing"),
)

_ADDITIONAL_SERVICE_FIELDS: tuple[tuple[str, str], ...] = (
    ("slug", "Service slug"),
    ("dir_name", "Service directory"),
    ("start_cmd", "Start command"),
    ("port_base", "Base port"),
    ("listener_expected", "Wait for listener"),
    ("enabled_main", "Enable in main"),
    ("enabled_trees", "Enable in trees"),
    ("test_cmd", "Test command"),
    ("public_url", "Public URL template"),
    ("health_url", "Health URL template"),
    ("depends_on", "Dependencies"),
    ("start_order", "Start order"),
    ("critical", "Critical"),
)

_STEP_TITLES = {
    "welcome": "Welcome / Source",
    "default_mode": "Default Mode",
    "components": "Components",
    "service_startup": "Long-Running Service",
    "additional_services": "Additional App Services",
    "directories": "Directories",
    "commands": "Entrypoints / Commands",
    "ports": "Ports",
    "review": "Review / Save",
}

_STEP_HELP_TEXT = {
    "welcome": (
        "This wizard saves the repo-local envctl run configuration. "
        "Existing services are not changed until a later command runs."
    ),
    "default_mode": "Pick which mode envctl should use by default when you do not pass --main or --trees.",
    "components": (
        "Choose which services and dependencies envctl should manage. Rows apply to Main + Trees until split. "
        "Press D to split the focused row into separate main and trees settings."
    ),
    "service_startup": (
        "This looks like a backend-only project. Choose whether envctl should keep it running automatically in "
        "main and trees. CLI tools usually should not stay running."
    ),
    "additional_services": (
        "Review advanced declarative app services managed through ENVCTL_ADDITIONAL_SERVICES and "
        "ENVCTL_SERVICE_<SUFFIX>_* keys."
    ),
    "directories": "Set only the directories needed by the components currently configured in main or trees.",
    "commands": (
        "Set only the entrypoints and test commands needed by the components currently configured in main or trees."
    ),
    "ports": "Set only the ports needed by the components currently configured in main or trees.",
    "review": "Review the generated managed .envctl block before saving it to the repository.",
}

_TEXTUAL_ID_INVALID_CHARS = re.compile(r"[^A-Za-z0-9_-]+")

CONFIG_ROW_STYLES_CSS = selectable_list_row_css("config-row")


@dataclass(frozen=True, slots=True)
class AdditionalServiceFormResult:
    service: AppServiceConfig | None
    remove_current: bool = False
    error_message: str | None = None
    focus_field: str | None = None


def _port_input_id(field_name: str) -> str:
    return f"port-{_TEXTUAL_ID_INVALID_CHARS.sub('-', field_name).strip('-')}"


def _additional_service_input_id(field_name: str) -> str:
    return f"additional-service-{_TEXTUAL_ID_INVALID_CHARS.sub('-', field_name).strip('-')}"


def _directory_input_id(field_name: str) -> str:
    return f"directory-{_TEXTUAL_ID_INVALID_CHARS.sub('-', field_name).strip('-')}"


def _field_label_id(prefix: str, field_name: str) -> str:
    normalized = _TEXTUAL_ID_INVALID_CHARS.sub("-", field_name).strip("-")
    return f"{prefix}-label-{normalized}"


def _directory_error_id(field_name: str) -> str:
    normalized = _TEXTUAL_ID_INVALID_CHARS.sub("-", field_name).strip("-")
    return f"directory-error-{normalized}"


def _directory_hint_id(field_name: str) -> str:
    normalized = _TEXTUAL_ID_INVALID_CHARS.sub("-", field_name).strip("-")
    return f"directory-hint-{normalized}"


def _directory_field_name_from_input_id(input_id: str | None) -> str | None:
    normalized = str(input_id or "").strip()
    for field_name, _label in (*_DIRECTORY_FIELDS, *_COMMAND_FIELDS):
        if normalized == _directory_input_id(field_name):
            return field_name
    return None


def _resolve_directory_path(base_dir: Path, raw: str) -> Path:
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate
    return (base_dir / candidate).resolve()


def _directory_validation_message(base_dir: Path, label: str, raw: str) -> str | None:
    value = str(raw).strip()
    if not value:
        return f"{label} must not be empty."
    candidate = _resolve_directory_path(base_dir, value)
    if not candidate.exists():
        return f"Directory does not exist: {value}"
    if not candidate.is_dir():
        return f"Path is not a directory: {value}"
    return None


def _entrypoint_validation_message(label: str, raw: str) -> str | None:
    value = str(raw).strip()
    if not value:
        return f"{label} must not be empty."
    return None


def _field_placeholder(field_name: str) -> str:
    return {
        "additional_service_slug": "optional; e.g. voice-runtime",
        "additional_service_dir_name": "repo-relative; e.g. voice-runtime",
        "additional_service_start_cmd": "e.g. scripts/envctl/start-voice-runtime.sh {port}",
        "additional_service_port_base": "required when listener waiting is true; e.g. 8010",
        "additional_service_listener_expected": "true or false",
        "additional_service_enabled_main": "true or false",
        "additional_service_enabled_trees": "true or false",
        "additional_service_test_cmd": "optional; e.g. scripts/envctl/test-voice-runtime.sh",
        "additional_service_public_url": "optional; supports envctl template variables",
        "additional_service_health_url": "optional; supports envctl template variables",
        "additional_service_depends_on": "optional comma list; e.g. backend,redis",
        "additional_service_start_order": "integer; lower starts first within a dependency layer",
        "additional_service_critical": "true or false",
        "backend_start_cmd": "e.g. python -m uvicorn app.main:app --host 127.0.0.1 --port {port}",
        "frontend_start_cmd": "e.g. npm run dev -- --port {port} --host 127.0.0.1",
        "backend_test_cmd": "e.g. python -m pytest backend/tests",
        "frontend_test_cmd": "e.g. npm run test",
        "frontend_test_path": "optional; e.g. frontend/src",
    }.get(field_name, "")


def _wizard_steps(
    values: ManagedConfigValues,
    *,
    include_service_startup: bool,
    include_additional_services: bool = False,
) -> list[str]:
    steps = ["welcome", "default_mode", "components"]
    if include_service_startup:
        steps.append("service_startup")
    if include_additional_services or values.additional_services:
        steps.append("additional_services")
    if _visible_directory_fields(values):
        steps.append("directories")
    if _visible_command_fields(values):
        steps.append("commands")
    if _visible_port_fields(values):
        steps.append("ports")
    steps.append("review")
    return steps


def _copy_profile(profile: StartupProfile) -> StartupProfile:
    return StartupProfile(
        startup_enable=profile.startup_enable,
        backend_enable=profile.backend_enable,
        frontend_enable=profile.frontend_enable,
        dependencies=dict(profile.dependencies),
    )


def _clone_values(values: ManagedConfigValues) -> ManagedConfigValues:
    return ManagedConfigValues(
        default_mode=values.default_mode,
        main_profile=_copy_profile(values.main_profile),
        trees_profile=_copy_profile(values.trees_profile),
        port_defaults=type(values.port_defaults)(
            backend_port_base=values.port_defaults.backend_port_base,
            frontend_port_base=values.port_defaults.frontend_port_base,
            dependency_ports={
                key: dict(resource_map) for key, resource_map in values.port_defaults.dependency_ports.items()
            },
            port_spacing=values.port_defaults.port_spacing,
        ),
        main_backend_expect_listener=values.main_backend_expect_listener,
        trees_backend_expect_listener=values.trees_backend_expect_listener,
        backend_dir_name=values.backend_dir_name,
        frontend_dir_name=values.frontend_dir_name,
        backend_start_cmd=values.backend_start_cmd,
        frontend_start_cmd=values.frontend_start_cmd,
        backend_test_cmd=values.backend_test_cmd,
        frontend_test_cmd=values.frontend_test_cmd,
        action_test_cmd=values.action_test_cmd,
        frontend_test_path=values.frontend_test_path,
        public_host=values.public_host,
        ui_visual_host=values.ui_visual_host,
        additional_services=tuple(
            AppServiceConfig(
                name=service.name,
                env_suffix=service.env_suffix,
                enabled_main=service.enabled_main,
                enabled_trees=service.enabled_trees,
                dir_name=service.dir_name,
                start_cmd=service.start_cmd,
                test_cmd=service.test_cmd,
                port_base=service.port_base,
                expect_listener=service.expect_listener,
                health_url_template=service.health_url_template,
                public_url_template=service.public_url_template,
                enable_if_path=service.enable_if_path,
                startup_group=service.startup_group,
                depends_on=service.depends_on,
                start_order=service.start_order,
                critical=service.critical,
            )
            for service in values.additional_services
        ),
    )


def _additional_service_field_value(service: AppServiceConfig | None, field_name: str) -> str:
    if service is None:
        defaults = {
            "listener_expected": "true",
            "enabled_main": "false",
            "enabled_trees": "false",
            "start_order": "100",
            "critical": "true",
        }
        return defaults.get(field_name, "")
    if field_name == "slug":
        return service.name
    if field_name == "dir_name":
        return service.dir_name
    if field_name == "start_cmd":
        return service.start_cmd
    if field_name == "port_base":
        return "" if service.port_base is None else str(service.port_base)
    if field_name == "listener_expected":
        return "true" if service.expect_listener else "false"
    if field_name == "enabled_main":
        return "true" if service.enabled_main else "false"
    if field_name == "enabled_trees":
        return "true" if service.enabled_trees else "false"
    if field_name == "test_cmd":
        return service.test_cmd
    if field_name == "public_url":
        return service.public_url_template
    if field_name == "health_url":
        return service.health_url_template
    if field_name == "depends_on":
        return ",".join(service.depends_on)
    if field_name == "start_order":
        return str(service.start_order)
    if field_name == "critical":
        return "true" if service.critical else "false"
    return ""


def build_additional_service_from_input_values(
    field_value: Callable[[str], str],
    *,
    existing_service: AppServiceConfig | None = None,
) -> AdditionalServiceFormResult:
    raw_name = field_value("slug").lower()
    if not raw_name:
        return AdditionalServiceFormResult(service=None, remove_current=True)

    port_raw = field_value("port_base")
    if port_raw:
        if not port_raw.isdigit() or int(port_raw) < 1:
            return AdditionalServiceFormResult(
                service=None,
                error_message="Base port must be a positive integer.",
                focus_field="port_base",
            )
        port_base: int | None = int(port_raw)
    else:
        port_base = None

    start_order_raw = field_value("start_order") or "100"
    if not start_order_raw.isdigit():
        return AdditionalServiceFormResult(
            service=None,
            error_message="Start order must be a non-negative integer.",
            focus_field="start_order",
        )

    service = AppServiceConfig(
        name=raw_name,
        env_suffix=raw_name.upper().replace("-", "_"),
        enabled_main=parse_bool(field_value("enabled_main"), False),
        enabled_trees=parse_bool(field_value("enabled_trees"), False),
        dir_name=field_value("dir_name"),
        start_cmd=field_value("start_cmd"),
        test_cmd=field_value("test_cmd"),
        port_base=port_base,
        expect_listener=parse_bool(field_value("listener_expected"), True),
        public_url_template=field_value("public_url"),
        health_url_template=field_value("health_url"),
        startup_group=existing_service.startup_group if existing_service is not None else "app",
        depends_on=tuple(item.strip().lower() for item in field_value("depends_on").split(",") if item.strip()),
        start_order=int(start_order_raw),
        critical=parse_bool(field_value("critical"), True),
        enable_if_path=existing_service.enable_if_path if existing_service is not None else "",
    )
    return AdditionalServiceFormResult(service=service)


def _hydrate_wizard_values(values: ManagedConfigValues, *, base_dir: Path) -> ManagedConfigValues:
    hydrated = _clone_values(values)
    baseline_defaults = managed_values_from_local_state(
        LocalConfigState(
            base_dir=base_dir,
            config_file_path=base_dir / ".envctl",
            config_file_exists=False,
            config_source="defaults",
            active_source_path=None,
            legacy_source_path=None,
            explicit_path=None,
            parsed_values={},
            file_text="",
        )
    )
    backend_suggested = str(suggest_service_directory(service_name="backend", project_root=base_dir) or "").strip()
    frontend_suggested = str(suggest_service_directory(service_name="frontend", project_root=base_dir) or "").strip()
    if _should_hydrate_directory_value(
        current_value=hydrated.backend_dir_name,
        baseline_value=baseline_defaults.backend_dir_name,
        base_dir=base_dir,
        conventional_default="backend",
        suggested_value=backend_suggested,
    ):
        hydrated.backend_dir_name = backend_suggested
    if _should_hydrate_directory_value(
        current_value=hydrated.frontend_dir_name,
        baseline_value=baseline_defaults.frontend_dir_name,
        base_dir=base_dir,
        conventional_default="frontend",
        suggested_value=frontend_suggested,
    ):
        hydrated.frontend_dir_name = frontend_suggested
    if not str(hydrated.backend_start_cmd).strip():
        hydrated.backend_start_cmd = str(
            suggest_service_start_command(service_name="backend", project_root=base_dir) or ""
        ).strip()
    if not str(hydrated.frontend_start_cmd).strip():
        hydrated.frontend_start_cmd = str(
            suggest_service_start_command(service_name="frontend", project_root=base_dir) or ""
        ).strip()
    if not str(hydrated.backend_test_cmd).strip():
        hydrated.backend_test_cmd = str(suggest_backend_test_command(base_dir) or "").strip()
    if not str(hydrated.frontend_test_cmd).strip():
        hydrated.frontend_test_cmd = str(suggest_frontend_test_command(base_dir) or "").strip()
    if not str(hydrated.frontend_test_path).strip():
        hydrated.frontend_test_path = str(suggest_frontend_test_path(base_dir) or "").strip()
    return hydrated


def _should_hydrate_directory_value(
    *,
    current_value: str,
    baseline_value: str,
    base_dir: Path,
    conventional_default: str,
    suggested_value: str,
) -> bool:
    current = str(current_value or "").strip()
    if not current:
        return True
    if current == str(baseline_value or "").strip():
        return True
    if current != conventional_default or not suggested_value or suggested_value == current:
        return False
    return not (base_dir / current).exists()


def _visible_directory_fields(values: ManagedConfigValues) -> tuple[tuple[str, str], ...]:
    profiles = [values.main_profile, values.trees_profile]
    visible: list[tuple[str, str]] = []
    if any(profile.backend_enable for profile in profiles):
        visible.append(("backend_dir_name", "Backend directory"))
    if any(profile.frontend_enable for profile in profiles):
        visible.append(("frontend_dir_name", "Frontend directory"))
        visible.append(("frontend_test_path", "Frontend tests directory"))
    return tuple(visible)


def _visible_command_fields(values: ManagedConfigValues) -> tuple[tuple[str, str], ...]:
    profiles = [values.main_profile, values.trees_profile]
    visible: list[tuple[str, str]] = []
    backend_runs = any(profile.startup_enable and profile.backend_enable for profile in profiles)
    frontend_runs = any(profile.startup_enable and profile.frontend_enable for profile in profiles)
    if any(profile.backend_enable for profile in profiles):
        if backend_runs:
            visible.append(("backend_start_cmd", "Backend entrypoint"))
        visible.append(("backend_test_cmd", "Backend test command"))
    if any(profile.frontend_enable for profile in profiles):
        if frontend_runs:
            visible.append(("frontend_start_cmd", "Frontend entrypoint"))
        visible.append(("frontend_test_cmd", "Frontend test command"))
    return tuple(visible)


def _visible_port_fields(values: ManagedConfigValues) -> tuple[tuple[str, str], ...]:
    backend_uses_port = (
        values.main_profile.startup_enable
        and values.main_profile.backend_enable
        and values.main_backend_expect_listener
    ) or (
        values.trees_profile.startup_enable
        and values.trees_profile.backend_enable
        and values.trees_backend_expect_listener
    )
    frontend_uses_port = any(
        profile.startup_enable and profile.frontend_enable for profile in (values.main_profile, values.trees_profile)
    )
    running_dependencies = {
        definition.id
        for definition in dependency_definitions()
        if any(
            profile.startup_enable and profile.dependency_enabled(definition.id)
            for profile in (values.main_profile, values.trees_profile)
        )
    }
    visible: list[tuple[str, str]] = []
    if backend_uses_port:
        visible.append(("backend_port_base", "Backend base port"))
    if frontend_uses_port:
        visible.append(("frontend_port_base", "Frontend base port"))
    if running_dependencies & {"postgres", "supabase"}:
        visible.append(("db_port_base", "Database base port"))
    if "redis" in running_dependencies:
        visible.append(("redis_port_base", "Redis base port"))
    if "n8n" in running_dependencies:
        visible.append(("n8n_port_base", "n8n base port"))
    if visible:
        visible.append(("port_spacing", "Port spacing"))
    return tuple(visible)
