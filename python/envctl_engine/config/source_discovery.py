from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from envctl_engine.config.dependency_env_templates import (
    DependencyEnvTemplateEntry,
    _extract_backend_dependency_env_section,
    _extract_dependency_env_section,
    _extract_frontend_dependency_env_section,
    _extract_generic_mode_service_dependency_env_sections,
    _extract_generic_service_dependency_env_sections,
    _extract_mode_service_dependency_env_section,
    _strip_template_sections,
)
from envctl_engine.config.defaults import DEFAULTS
from envctl_engine.config.models import LocalConfigState
from envctl_engine.shared.parsing import strip_quotes

CONFIG_PRIMARY_FILENAME = ".envctl"
LEGACY_CONFIG_FILENAMES = (".envctl.sh", ".supportopia-config")


def generated_worktree_control_root(
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
        provenance_root = control_root_from_worktree_provenance(resolved)
        if provenance_root is not None:
            return provenance_root
        shaped_root = control_root_from_generated_tree_shape(resolved, trees_dir_name=trees_dir_name)
        if shaped_root is not None:
            return shaped_root
    return None


def control_root_from_worktree_provenance(worktree_root: Path) -> Path | None:
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


def control_root_from_generated_tree_shape(path: Path, *, trees_dir_name: str) -> Path | None:
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


def discover_local_config_state(base_dir: Path, explicit_path: str | None = None) -> LocalConfigState:
    base_dir = Path(base_dir).resolve()
    resolved_explicit = resolve_explicit_path(base_dir, explicit_path)
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

    source_sections = _read_local_config_source(active_source_path)
    return LocalConfigState(
        base_dir=base_dir,
        config_file_path=file_path,
        config_file_exists=file_exists,
        config_source=source,
        active_source_path=active_source_path,
        legacy_source_path=legacy_source_path,
        explicit_path=resolved_explicit,
        parsed_values=source_sections.parsed_values,
        file_text=source_sections.file_text,
        dependency_env_templates=source_sections.dependency_env_templates,
        dependency_env_section_present=source_sections.dependency_env_section_present,
        dependency_env_template_errors=source_sections.dependency_env_template_errors,
        backend_dependency_env_templates=source_sections.backend_dependency_env_templates,
        backend_dependency_env_section_present=source_sections.backend_dependency_env_section_present,
        backend_dependency_env_template_errors=source_sections.backend_dependency_env_template_errors,
        frontend_dependency_env_templates=source_sections.frontend_dependency_env_templates,
        frontend_dependency_env_section_present=source_sections.frontend_dependency_env_section_present,
        frontend_dependency_env_template_errors=source_sections.frontend_dependency_env_template_errors,
        main_backend_dependency_env_templates=source_sections.main_backend_dependency_env_templates,
        main_backend_dependency_env_section_present=source_sections.main_backend_dependency_env_section_present,
        main_backend_dependency_env_template_errors=source_sections.main_backend_dependency_env_template_errors,
        main_frontend_dependency_env_templates=source_sections.main_frontend_dependency_env_templates,
        main_frontend_dependency_env_section_present=source_sections.main_frontend_dependency_env_section_present,
        main_frontend_dependency_env_template_errors=source_sections.main_frontend_dependency_env_template_errors,
        trees_backend_dependency_env_templates=source_sections.trees_backend_dependency_env_templates,
        trees_backend_dependency_env_section_present=source_sections.trees_backend_dependency_env_section_present,
        trees_backend_dependency_env_template_errors=source_sections.trees_backend_dependency_env_template_errors,
        trees_frontend_dependency_env_templates=source_sections.trees_frontend_dependency_env_templates,
        trees_frontend_dependency_env_section_present=source_sections.trees_frontend_dependency_env_section_present,
        trees_frontend_dependency_env_template_errors=source_sections.trees_frontend_dependency_env_template_errors,
        service_dependency_env_templates=source_sections.service_dependency_env_templates,
        service_dependency_env_section_present=source_sections.service_dependency_env_section_present,
        service_dependency_env_template_errors=source_sections.service_dependency_env_template_errors,
        mode_service_dependency_env_templates=source_sections.mode_service_dependency_env_templates,
        mode_service_dependency_env_section_present=source_sections.mode_service_dependency_env_section_present,
        mode_service_dependency_env_template_errors=source_sections.mode_service_dependency_env_template_errors,
    )


class _LocalConfigSourceSections:
    def __init__(self, file_text: str = "") -> None:
        self.file_text = file_text
        self.parsed_values: dict[str, str] = parse_envctl_text(file_text)
        self.dependency_env_templates: tuple[DependencyEnvTemplateEntry, ...] = ()
        self.dependency_env_section_present = False
        self.dependency_env_template_errors: tuple[str, ...] = ()
        self.backend_dependency_env_templates: tuple[DependencyEnvTemplateEntry, ...] = ()
        self.backend_dependency_env_section_present = False
        self.backend_dependency_env_template_errors: tuple[str, ...] = ()
        self.frontend_dependency_env_templates: tuple[DependencyEnvTemplateEntry, ...] = ()
        self.frontend_dependency_env_section_present = False
        self.frontend_dependency_env_template_errors: tuple[str, ...] = ()
        self.main_backend_dependency_env_templates: tuple[DependencyEnvTemplateEntry, ...] = ()
        self.main_backend_dependency_env_section_present = False
        self.main_backend_dependency_env_template_errors: tuple[str, ...] = ()
        self.main_frontend_dependency_env_templates: tuple[DependencyEnvTemplateEntry, ...] = ()
        self.main_frontend_dependency_env_section_present = False
        self.main_frontend_dependency_env_template_errors: tuple[str, ...] = ()
        self.trees_backend_dependency_env_templates: tuple[DependencyEnvTemplateEntry, ...] = ()
        self.trees_backend_dependency_env_section_present = False
        self.trees_backend_dependency_env_template_errors: tuple[str, ...] = ()
        self.trees_frontend_dependency_env_templates: tuple[DependencyEnvTemplateEntry, ...] = ()
        self.trees_frontend_dependency_env_section_present = False
        self.trees_frontend_dependency_env_template_errors: tuple[str, ...] = ()
        self.service_dependency_env_templates: dict[str, tuple[DependencyEnvTemplateEntry, ...]] = {}
        self.service_dependency_env_section_present: dict[str, bool] = {}
        self.service_dependency_env_template_errors: dict[str, tuple[str, ...]] = {}
        self.mode_service_dependency_env_templates: dict[tuple[str, str], tuple[DependencyEnvTemplateEntry, ...]] = {}
        self.mode_service_dependency_env_section_present: dict[tuple[str, str], bool] = {}
        self.mode_service_dependency_env_template_errors: dict[tuple[str, str], tuple[str, ...]] = {}

    def extract_dependency_sections(self) -> None:
        (
            self.dependency_env_templates,
            self.dependency_env_section_present,
            self.dependency_env_template_errors,
        ) = _extract_dependency_env_section(self.file_text)
        (
            self.backend_dependency_env_templates,
            self.backend_dependency_env_section_present,
            self.backend_dependency_env_template_errors,
        ) = _extract_backend_dependency_env_section(self.file_text)
        (
            self.frontend_dependency_env_templates,
            self.frontend_dependency_env_section_present,
            self.frontend_dependency_env_template_errors,
        ) = _extract_frontend_dependency_env_section(self.file_text)
        (
            self.main_backend_dependency_env_templates,
            self.main_backend_dependency_env_section_present,
            self.main_backend_dependency_env_template_errors,
        ) = _extract_mode_service_dependency_env_section(self.file_text, mode="main", service_name="backend")
        (
            self.main_frontend_dependency_env_templates,
            self.main_frontend_dependency_env_section_present,
            self.main_frontend_dependency_env_template_errors,
        ) = _extract_mode_service_dependency_env_section(self.file_text, mode="main", service_name="frontend")
        (
            self.trees_backend_dependency_env_templates,
            self.trees_backend_dependency_env_section_present,
            self.trees_backend_dependency_env_template_errors,
        ) = _extract_mode_service_dependency_env_section(self.file_text, mode="trees", service_name="backend")
        (
            self.trees_frontend_dependency_env_templates,
            self.trees_frontend_dependency_env_section_present,
            self.trees_frontend_dependency_env_template_errors,
        ) = _extract_mode_service_dependency_env_section(self.file_text, mode="trees", service_name="frontend")
        (
            self.service_dependency_env_templates,
            self.service_dependency_env_section_present,
            self.service_dependency_env_template_errors,
        ) = _extract_generic_service_dependency_env_sections(self.file_text)
        (
            self.mode_service_dependency_env_templates,
            self.mode_service_dependency_env_section_present,
            self.mode_service_dependency_env_template_errors,
        ) = _extract_generic_mode_service_dependency_env_sections(self.file_text)


def _read_local_config_source(active_source_path: Path | None) -> _LocalConfigSourceSections:
    if active_source_path is None or not active_source_path.is_file():
        return _LocalConfigSourceSections()
    try:
        file_text = active_source_path.read_text(encoding="utf-8")
    except OSError:
        return _LocalConfigSourceSections()
    sections = _LocalConfigSourceSections(file_text)
    sections.extract_dependency_sections()
    return sections


def resolve_explicit_path(base_dir: Path, explicit_path: str | None) -> Path | None:
    if not explicit_path:
        return None
    path = Path(explicit_path).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def parse_envctl_text(text: str) -> dict[str, str]:
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
