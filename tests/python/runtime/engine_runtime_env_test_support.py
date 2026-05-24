from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_router import parse_route  # noqa: E402
from envctl_engine.requirements.external import dependency_external_mode  # noqa: E402
from envctl_engine.shared.dependency_compose_assets import (  # noqa: E402
    DEFAULT_SUPABASE_JWT_SECRET,
    default_supabase_anon_key,
    default_supabase_service_role_key,
)
from envctl_engine.runtime.engine_runtime_env import (  # noqa: E402
    _route_is_implicit_start,
    effective_main_requirement_flags,
    main_requirements_mode,
    project_service_env,
    project_service_env_internal,
    requirement_enabled_for_mode,
    requirements_ready,
    resolve_dependency_env_templates,
    runtime_env_overrides,
    service_env_overlays,
    service_enabled_for_mode,
    validate_mode_toggles,
)
from envctl_engine.state.models import PortPlan, RequirementsResult  # noqa: E402


class EngineRuntimeEnvTestCase(unittest.TestCase):
    pass


__all__ = [
    "DEFAULT_SUPABASE_JWT_SECRET",
    "EngineRuntimeEnvTestCase",
    "Path",
    "PortPlan",
    "RequirementsResult",
    "SimpleNamespace",
    "_route_is_implicit_start",
    "default_supabase_anon_key",
    "default_supabase_service_role_key",
    "dependency_external_mode",
    "effective_main_requirement_flags",
    "main_requirements_mode",
    "parse_route",
    "project_service_env",
    "project_service_env_internal",
    "requirement_enabled_for_mode",
    "requirements_ready",
    "resolve_dependency_env_templates",
    "runtime_env_overrides",
    "service_enabled_for_mode",
    "service_env_overlays",
    "tempfile",
    "validate_mode_toggles",
]
