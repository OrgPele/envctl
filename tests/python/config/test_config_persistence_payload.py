from __future__ import annotations

from envctl_engine.config.persistence_payload import ConfigPayloadHydrator
from envctl_engine.config.persistence_values import managed_values_from_mapping, managed_values_to_mapping


def test_config_payload_hydrator_applies_nested_sections_without_losing_base_values() -> None:
    base_values = managed_values_from_mapping(
        {
            "ENVCTL_DEFAULT_MODE": "main",
            "BACKEND_DIR": "api",
            "FRONTEND_DIR": "web",
            "ENVCTL_BACKEND_TEST_CMD": "pytest backend",
            "ENVCTL_PUBLIC_HOST": "203.0.113.7",
        }
    )

    values = ConfigPayloadHydrator(base_values=base_values).hydrate(
        {
            "default_mode": "trees",
            "directories": {
                "backend_entrypoint": "uvicorn app:app",
                "frontend_test_path": "tests/e2e",
            },
            "ports": {
                "backend": 8100,
                "spacing": 30,
            },
            "profiles": {
                "main": {
                    "startup_enabled": False,
                    "backend": True,
                },
            },
        }
    )

    rendered = managed_values_to_mapping(values)
    assert rendered["ENVCTL_DEFAULT_MODE"] == "trees"
    assert rendered["BACKEND_DIR"] == "api"
    assert rendered["FRONTEND_DIR"] == "web"
    assert rendered["ENVCTL_BACKEND_START_CMD"] == "uvicorn app:app"
    assert rendered["ENVCTL_BACKEND_TEST_CMD"] == "pytest backend"
    assert rendered["ENVCTL_FRONTEND_TEST_PATH"] == "tests/e2e"
    assert rendered["ENVCTL_PUBLIC_HOST"] == "203.0.113.7"
    assert rendered["BACKEND_PORT_BASE"] == "8100"
    assert rendered["PORT_SPACING"] == "30"
    assert rendered["MAIN_STARTUP_ENABLE"] == "false"
    assert rendered["MAIN_BACKEND_ENABLE"] == "true"


def test_config_payload_hydrator_accepts_flat_managed_key_payloads() -> None:
    values = ConfigPayloadHydrator().hydrate(
        {
            "ENVCTL_DEFAULT_MODE": "trees",
            "BACKEND_DIR": "services/api",
            "MAIN_FRONTEND_ENABLE": "false",
        }
    )

    rendered = managed_values_to_mapping(values)
    assert rendered["ENVCTL_DEFAULT_MODE"] == "trees"
    assert rendered["BACKEND_DIR"] == "services/api"
    assert rendered["MAIN_FRONTEND_ENABLE"] == "false"
