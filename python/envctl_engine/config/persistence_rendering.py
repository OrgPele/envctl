from __future__ import annotations

from pathlib import Path

from envctl_engine.config import CONFIG_MANAGED_BLOCK_END, CONFIG_MANAGED_BLOCK_START
from envctl_engine.config.persistence_values import (
    ManagedConfigValues,
    _backend_uses_port_any,
    _component_enabled_any,
    _component_runs_any,
    _dependency_runs_any,
    _frontend_uses_port_any,
    managed_values_from_mapping,
    managed_values_to_mapping,
)
from envctl_engine.requirements.core import dependency_definitions


def render_managed_block(values: ManagedConfigValues) -> str:
    rendered = managed_values_to_mapping(values)
    defaults = managed_values_to_mapping(managed_values_from_mapping({}))
    lines = [CONFIG_MANAGED_BLOCK_START]
    section_groups = _managed_block_sections(values=values, rendered=rendered, defaults=defaults)
    wrote_any = False
    for section in section_groups:
        if not section:
            continue
        if wrote_any:
            lines.append("")
        for key in section:
            lines.append(f"{key}={rendered[key]}")
        wrote_any = True
    lines.append(CONFIG_MANAGED_BLOCK_END)
    return "\n".join(lines) + "\n"


def _managed_block_sections(
    *,
    values: ManagedConfigValues,
    rendered: dict[str, str],
    defaults: dict[str, str],
) -> list[list[str]]:
    def append_once(keys: list[str], key: str) -> None:
        if key not in keys:
            keys.append(key)

    sections: list[list[str]] = []
    sections.append(["ENVCTL_DEFAULT_MODE"])
    sections.append(["ENVCTL_PUBLIC_HOST", "ENVCTL_UI_VISUAL_HOST"])

    directory_keys: list[str] = []
    if _component_enabled_any(values, "backend") and rendered["BACKEND_DIR"] != defaults["BACKEND_DIR"]:
        append_once(directory_keys, "BACKEND_DIR")
    if _component_enabled_any(values, "frontend") and rendered["FRONTEND_DIR"] != defaults["FRONTEND_DIR"]:
        append_once(directory_keys, "FRONTEND_DIR")
    if (
        _component_runs_any(values, "backend")
        and rendered["ENVCTL_BACKEND_START_CMD"] != defaults["ENVCTL_BACKEND_START_CMD"]
    ):
        append_once(directory_keys, "ENVCTL_BACKEND_START_CMD")
    if (
        _component_runs_any(values, "frontend")
        and rendered["ENVCTL_FRONTEND_START_CMD"] != defaults["ENVCTL_FRONTEND_START_CMD"]
    ):
        append_once(directory_keys, "ENVCTL_FRONTEND_START_CMD")
    if (
        _component_enabled_any(values, "backend")
        and rendered["ENVCTL_BACKEND_TEST_CMD"] != defaults["ENVCTL_BACKEND_TEST_CMD"]
    ):
        append_once(directory_keys, "ENVCTL_BACKEND_TEST_CMD")
    if (
        _component_enabled_any(values, "frontend")
        and rendered["ENVCTL_FRONTEND_TEST_CMD"] != defaults["ENVCTL_FRONTEND_TEST_CMD"]
    ):
        append_once(directory_keys, "ENVCTL_FRONTEND_TEST_CMD")
    if (
        _component_enabled_any(values, "frontend")
        and rendered["ENVCTL_FRONTEND_TEST_PATH"] != defaults["ENVCTL_FRONTEND_TEST_PATH"]
    ):
        append_once(directory_keys, "ENVCTL_FRONTEND_TEST_PATH")
    sections.append(directory_keys)

    port_keys: list[str] = []
    if _backend_uses_port_any(values) and rendered["BACKEND_PORT_BASE"] != defaults["BACKEND_PORT_BASE"]:
        append_once(port_keys, "BACKEND_PORT_BASE")
    if _frontend_uses_port_any(values) and rendered["FRONTEND_PORT_BASE"] != defaults["FRONTEND_PORT_BASE"]:
        append_once(port_keys, "FRONTEND_PORT_BASE")
    for definition in dependency_definitions():
        if not _dependency_runs_any(values, definition.id):
            continue
        for resource in definition.resources:
            key = resource.config_port_keys[0]
            if rendered[key] != defaults[key]:
                append_once(port_keys, key)
    if port_keys and rendered["PORT_SPACING"] != defaults["PORT_SPACING"]:
        append_once(port_keys, "PORT_SPACING")
    sections.append(port_keys)

    main_keys = _profile_keys_for_mode(mode="main", values=values, rendered=rendered, defaults=defaults)
    trees_keys = _profile_keys_for_mode(mode="trees", values=values, rendered=rendered, defaults=defaults)
    sections.append(main_keys)
    sections.append(trees_keys)
    service_keys: list[str] = []
    if values.additional_services:
        service_keys.append("ENVCTL_ADDITIONAL_SERVICES")
    for service in values.additional_services:
        prefix = f"ENVCTL_SERVICE_{service.env_suffix}_"
        for key in (
            f"{prefix}DIR",
            f"{prefix}START_CMD",
            f"{prefix}MAIN_ENABLE",
            f"{prefix}TREES_ENABLE",
            f"{prefix}EXPECT_LISTENER",
            f"{prefix}PORT_BASE",
            f"{prefix}TEST_CMD",
            f"{prefix}HEALTH_URL",
            f"{prefix}PUBLIC_URL",
            f"{prefix}DEPENDS_ON",
            f"{prefix}START_ORDER",
            f"{prefix}CRITICAL",
            f"{prefix}ENABLE_IF_PATH",
        ):
            if key in rendered:
                append_once(service_keys, key)
    sections.append(service_keys)
    return sections


def _profile_keys_for_mode(
    *,
    mode: str,
    values: ManagedConfigValues,
    rendered: dict[str, str],
    defaults: dict[str, str],
) -> list[str]:
    prefix = mode.upper()
    keys: list[str] = []
    for key in (
        f"{prefix}_STARTUP_ENABLE",
        f"{prefix}_BACKEND_ENABLE",
        f"{prefix}_BACKEND_EXPECT_LISTENER",
        f"{prefix}_FRONTEND_ENABLE",
    ):
        if rendered[key] != defaults[key]:
            keys.append(key)
    for definition in dependency_definitions():
        key = definition.enable_keys_for_mode(mode)[0]
        if rendered[key] != defaults[key]:
            keys.append(key)
    return keys


def merge_managed_block(existing_text: str, block_text: str) -> str:
    text = existing_text or ""
    start = text.find(CONFIG_MANAGED_BLOCK_START)
    end = text.find(CONFIG_MANAGED_BLOCK_END)
    if start != -1 and end != -1 and end >= start:
        end += len(CONFIG_MANAGED_BLOCK_END)
        suffix = text[end:]
        if suffix.startswith("\n"):
            suffix = suffix[1:]
        prefix = text[:start].rstrip("\n")
        parts = [part for part in (prefix, block_text.rstrip("\n"), suffix.rstrip("\n")) if part]
        return "\n\n".join(parts) + "\n"
    stripped = text.rstrip("\n")
    if not stripped:
        return block_text
    return stripped + "\n\n" + block_text


def config_review_text(
    *, path: Path, values: ManagedConfigValues, source_label: str, ignore_warning: str | None = None
) -> str:
    summary = [
        f"Path: {path}",
        f"Source: {source_label}",
        "CLI/env overrides still apply above this file.",
        "",
        render_managed_block(values).rstrip("\n"),
    ]
    if ignore_warning:
        summary.extend(["", f"Ignore warning: {ignore_warning}"])
    return "\n".join(summary)
