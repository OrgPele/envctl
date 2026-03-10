from __future__ import annotations

from typing import Literal

Mode = Literal["main", "trees"]
WizardPreset = Literal["standard", "apps_only", "disabled"]

_PROFILE_COMPONENT_DEFAULTS: dict[str, bool] = {
    "startup_enable": True,
    "backend_enable": True,
    "frontend_enable": True,
}

_BASELINE_DEPENDENCY_DEFAULTS: dict[Mode, dict[str, bool]] = {
    "main": {
        "postgres": False,
        "redis": False,
        "supabase": False,
        "n8n": False,
    },
    "trees": {
        "postgres": False,
        "redis": False,
        "supabase": False,
        "n8n": False,
    },
}

_STANDARD_PRESET_DEPENDENCIES: dict[Mode, dict[str, bool]] = {
    "main": {
        "postgres": True,
        "redis": True,
        "supabase": False,
        "n8n": False,
    },
    "trees": {
        "postgres": True,
        "redis": True,
        "supabase": False,
        "n8n": True,
    },
}


def default_profile_settings(mode: str) -> dict[str, object]:
    normalized = _normalize_mode(mode)
    return {
        **_PROFILE_COMPONENT_DEFAULTS,
        "dependencies": dict(_BASELINE_DEPENDENCY_DEFAULTS[normalized]),
    }


def wizard_preset_settings(mode: str, preset: str) -> dict[str, object]:
    normalized_mode = _normalize_mode(mode)
    normalized_preset = _normalize_preset(preset)
    if normalized_preset == "apps_only":
        dependencies = {dependency_id: False for dependency_id in _BASELINE_DEPENDENCY_DEFAULTS[normalized_mode]}
    else:
        dependencies = dict(_STANDARD_PRESET_DEPENDENCIES[normalized_mode])
    return {
        "startup_enable": normalized_preset != "disabled",
        "backend_enable": True,
        "frontend_enable": True,
        "dependencies": dependencies,
    }


def dependency_default_enabled(dependency_id: str, mode: str) -> bool:
    normalized_mode = _normalize_mode(mode)
    normalized_dependency_id = str(dependency_id).strip().lower()
    return bool(_BASELINE_DEPENDENCY_DEFAULTS[normalized_mode].get(normalized_dependency_id, False))


def _normalize_mode(mode: str) -> Mode:
    normalized = str(mode).strip().lower()
    return "trees" if normalized == "trees" else "main"


def _normalize_preset(preset: str) -> WizardPreset:
    normalized = str(preset).strip().lower()
    if normalized == "apps_only":
        return "apps_only"
    if normalized == "disabled":
        return "disabled"
    return "standard"
