from __future__ import annotations

from typing import Mapping, cast

from envctl_engine.config.profile_defaults import default_profile_settings
from envctl_engine.shared.parsing import bool_text as _bool_text


def _build_defaults() -> dict[str, str]:
    main_profile = default_profile_settings("main")
    trees_profile = default_profile_settings("trees")
    main_dependencies = cast(Mapping[str, bool], main_profile["dependencies"])
    trees_dependencies = cast(Mapping[str, bool], trees_profile["dependencies"])
    return {
        "ENVCTL_DEFAULT_MODE": "main",
        "ENVCTL_DEFAULT_TREE_DEPENDENCY_SCOPE": "",
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
        "ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE": "false",
        "ENVCTL_PLAN_AGENT_FULLSTACK_PR_URL_E2E_ENABLE": "false",
        "ENVCTL_PLAN_AGENT_PR_REVIEW_COMMENTS_ENABLE": "false",
        "ENVCTL_SHIP_PR_LABEL_ENABLE": "false",
        "ENVCTL_SHIP_PR_LABEL": "deploy-app",
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
    "ENVCTL_DEFAULT_TREE_DEPENDENCY_SCOPE",
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
    "ENVCTL_PLAN_AGENT_FULLSTACK_PR_URL_E2E_ENABLE",
)
