from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from envctl_engine.planning.worktree_code_intelligence_models import (
    WORKTREE_CGC_DATABASE_DEFAULT,
    WORKTREE_CGC_INDEX_MODE_AUTO,
    WORKTREE_CGC_INDEX_MODE_DISABLED,
    WORKTREE_CGC_INDEX_MODE_ENABLED,
    WorktreeCodeIntelligenceIdentity,
)


WORKTREE_CODE_INTELLIGENCE_DISABLED_VALUES = frozenset(("disabled", "disable", "off", "false", "0", "no"))
WORKTREE_CODE_INTELLIGENCE_ENABLED_VALUES = frozenset(("auto", "enabled", "enable", "on", "true", "1", "yes"))
WORKTREE_CGC_INDEX_DISABLED_VALUES = frozenset(("disabled", "disable", "off", "false", "0", "no"))
WORKTREE_CGC_INDEX_ENABLED_VALUES = frozenset(("enabled", "enable", "on", "true", "1", "yes"))
WORKTREE_CGC_INDEX_AUTO_VALUES = frozenset(("auto",))


def worktree_code_intelligence_enabled(runtime: Any) -> bool:
    raw = str(
        runtime.env.get("ENVCTL_WORKTREE_CODE_INTELLIGENCE")
        or runtime.config.raw.get("ENVCTL_WORKTREE_CODE_INTELLIGENCE")
        or "auto"
    ).strip().lower()
    if raw in WORKTREE_CODE_INTELLIGENCE_ENABLED_VALUES:
        return True
    if raw in WORKTREE_CODE_INTELLIGENCE_DISABLED_VALUES:
        return False
    raise RuntimeError(
        "Invalid ENVCTL_WORKTREE_CODE_INTELLIGENCE value. "
        "Use auto/on/true or off/false."
    )


def worktree_cgc_index_mode(runtime: Any) -> str:
    raw_value = runtime.env.get("ENVCTL_WORKTREE_CGC_INDEX")
    if raw_value is None or str(raw_value).strip() == "":
        raw_value = runtime.config.raw.get("ENVCTL_WORKTREE_CGC_INDEX")
    if raw_value is None or str(raw_value).strip() == "":
        return WORKTREE_CGC_INDEX_MODE_DISABLED
    raw = str(raw_value).strip().lower()
    if raw in WORKTREE_CGC_INDEX_ENABLED_VALUES:
        return WORKTREE_CGC_INDEX_MODE_ENABLED
    if raw in WORKTREE_CGC_INDEX_DISABLED_VALUES:
        return WORKTREE_CGC_INDEX_MODE_DISABLED
    if raw in WORKTREE_CGC_INDEX_AUTO_VALUES:
        repo_root = runtime.config.base_dir
        if (repo_root / ".cgcignore").is_file() or (repo_root / ".codegraphcontext").exists():
            return WORKTREE_CGC_INDEX_MODE_AUTO
        return WORKTREE_CGC_INDEX_MODE_DISABLED
    raise RuntimeError(
        "Invalid ENVCTL_WORKTREE_CGC_INDEX value. "
        "Use auto/on/true to enable CGC graph tooling or off/false to disable it."
    )


def worktree_code_intelligence_identity(
    runtime: Any,
    *,
    target: Path,
    trees_root_for_worktree: Callable[[Any, Path], Path],
) -> WorktreeCodeIntelligenceIdentity:
    source_project = (
        read_source_serena_project_name(runtime.config.base_dir)
        or runtime.config.base_dir.name
        or "project"
    )
    worktree_name, feature, iteration = worktree_identity_parts(
        runtime,
        target=target,
        trees_root_for_worktree=trees_root_for_worktree,
    )
    serena_template = worktree_template_value(
        runtime,
        env_key="ENVCTL_WORKTREE_SERENA_PROJECT_TEMPLATE",
        default="{project}-{worktree}",
    )
    cgc_template = worktree_template_value(
        runtime,
        env_key="ENVCTL_WORKTREE_CGC_CONTEXT_TEMPLATE",
        default="{project}-{worktree}",
    )
    serena_project = render_worktree_identity_template(
        serena_template,
        project=sanitize_worktree_identity(source_project, lowercase=True),
        worktree=worktree_name,
        feature=feature,
        iteration=iteration,
    )
    cgc_context = render_worktree_identity_template(
        cgc_template,
        project=sanitize_worktree_identity(source_project, titlecase=True),
        worktree=worktree_name,
        feature=feature,
        iteration=iteration,
    )
    return WorktreeCodeIntelligenceIdentity(
        worktree_name=worktree_name,
        feature=feature,
        iteration=iteration,
        serena_project_name=serena_project,
        cgc_context=cgc_context,
    )


def read_source_serena_project_name(repo_root: Path) -> str:
    path = repo_root / ".serena" / "project.yml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r"^project_name:\s*[\"']?(.*?)[\"']?\s*$", text, flags=re.MULTILINE)
    return str(match.group(1)).strip() if match else ""


def worktree_identity_parts(
    runtime: Any,
    *,
    target: Path,
    trees_root_for_worktree: Callable[[Any, Path], Path],
) -> tuple[str, str, str]:
    trees_root = trees_root_for_worktree(runtime, target)
    try:
        relative = target.resolve().relative_to(trees_root.resolve())
    except ValueError:
        relative = Path(target.name)
    parts = list(relative.parts)
    if not parts:
        parts = [target.name]
    iteration = sanitize_worktree_identity(parts[-1])
    feature_raw = "_".join(parts[:-1]) if len(parts) > 1 else parts[0]
    feature = sanitize_worktree_identity(feature_raw)
    worktree_name = sanitize_worktree_identity(f"{feature}-{iteration}")
    return worktree_name, feature, iteration


def worktree_template_value(runtime: Any, *, env_key: str, default: str) -> str:
    raw = runtime.env.get(env_key) or runtime.config.raw.get(env_key) or default
    value = str(raw).strip()
    return value or default


def render_worktree_identity_template(
    template: str,
    *,
    project: str,
    worktree: str,
    feature: str,
    iteration: str,
) -> str:
    values = {
        "project": project,
        "worktree": worktree,
        "feature": feature,
        "iteration": iteration,
    }
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)
    return sanitize_worktree_identity(rendered) or worktree


def sanitize_worktree_identity(raw: str, *, lowercase: bool = False, titlecase: bool = False, limit: int = 96) -> str:
    text = str(raw or "").strip()
    if lowercase:
        text = text.lower()
    text = text.replace("/", "_").replace("\\", "_").replace(".", "-")
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", text)
    text = re.sub(r"_+", "_", text)
    text = re.sub(r"-+", "-", text)
    text = text.strip("_-")
    if titlecase:
        pieces = re.split(r"([_-])", text)
        text = "".join(piece[:1].upper() + piece[1:] if piece not in {"_", "-"} else piece for piece in pieces)
    if len(text) > limit:
        text = text[:limit].rstrip("_-")
    return text or "worktree"


def worktree_cgc_database(runtime: Any) -> str:
    for raw in (
        runtime.env.get("ENVCTL_WORKTREE_CGC_DATABASE"),
        runtime.config.raw.get("ENVCTL_WORKTREE_CGC_DATABASE"),
    ):
        value = str(raw or "").strip()
        if value:
            return sanitize_worktree_identity(value)
    return WORKTREE_CGC_DATABASE_DEFAULT


def source_cgc_context(runtime: Any) -> str:
    for raw in (
        runtime.env.get("ENVCTL_WORKTREE_CGC_SOURCE_CONTEXT"),
        runtime.config.raw.get("ENVCTL_WORKTREE_CGC_SOURCE_CONTEXT"),
    ):
        value = str(raw or "").strip()
        if value:
            return sanitize_worktree_identity(value)
    source_project = (
        read_source_serena_project_name(runtime.config.base_dir)
        or runtime.config.base_dir.name
        or "project"
    )
    return sanitize_worktree_identity(source_project, titlecase=True)
