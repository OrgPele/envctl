from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree
from envctl_engine.planning.worktree_code_intelligence_models import (
    WORKTREE_CGC_INDEX_MODE_DISABLED,
    WORKTREE_CODE_INTELLIGENCE_PATH,
)


@dataclass(frozen=True, slots=True)
class CodeIntelligencePromptBuilder:
    worktree: CreatedPlanWorktree | None = None

    def prompt_section(self) -> str:
        metadata = _worktree_code_intelligence_metadata(self.worktree)
        if not metadata:
            return ""
        serena_line = _serena_prompt_line(metadata)
        cgc_line = _cgc_prompt_line(metadata)
        if not serena_line and not cgc_line:
            return ""
        lines = [
            "## Worktree code intelligence",
            "Use these shortcuts only when they fit the question; use `rg` for exact strings such as flags, "
            "env keys, log messages, docs prose, and error text.",
        ]
        if serena_line:
            lines.append(f"- {serena_line}")
        if cgc_line:
            lines.append(f"- {cgc_line}")
        return "\n".join(lines)


def _append_code_intelligence_context_for_preset(
    *,
    preset: str,
    prompt_text: str,
    worktree: CreatedPlanWorktree | None = None,
) -> str:
    _ = preset
    context = _code_intelligence_prompt_section(worktree=worktree)
    if not context:
        return prompt_text
    return f"{prompt_text.rstrip()}\n\n{context}\n"


def _code_intelligence_prompt_section(*, worktree: CreatedPlanWorktree | None = None) -> str:
    return CodeIntelligencePromptBuilder(worktree=worktree).prompt_section()


def _worktree_code_intelligence_metadata(
    worktree: CreatedPlanWorktree | None,
) -> Mapping[str, object] | None:
    if worktree is None:
        return None
    try:
        path = Path(worktree.root).expanduser() / WORKTREE_CODE_INTELLIGENCE_PATH
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, Mapping):
        return None
    return payload


def _serena_prompt_line(metadata: Mapping[str, object]) -> str:
    if not _metadata_file_enabled(metadata, ".serena/project.yml"):
        return ""
    project_name = _string_value(metadata.get("serena_project_name"))
    if project_name:
        return (
            f"Serena project `{project_name}` is configured. Use Serena for symbol definitions, references, "
            "call paths, and semantic edits."
        )
    return "Serena is configured. Use it for symbol definitions, references, call paths, and semantic edits."


def _cgc_prompt_line(metadata: Mapping[str, object]) -> str:
    context = _active_cgc_context(metadata)
    if not context:
        return ""
    return (
        f"CodeGraphContext (`cgc`) context `{context}` is available. Use it for repo-wide ownership, "
        "coupling, impact, hotspot, and dead-code questions; use exact source reads for line-level edits. "
        "Do not use the legacy `codegraph` CLI or `.codegraph/` indexes for this envctl-managed context."
    )


def _active_cgc_context(metadata: Mapping[str, object]) -> str:
    mode = _string_value(metadata.get("cgc_index_mode")).casefold()
    skipped_reason = _string_value(metadata.get("cgc_index_skipped_reason")).casefold()
    if mode == WORKTREE_CGC_INDEX_MODE_DISABLED or skipped_reason in {"disabled", "cgc_not_available"}:
        return ""
    if not (_truthy(metadata.get("cgc_index_succeeded")) or skipped_reason == "source_context_reused"):
        return ""
    return _string_value(metadata.get("cgc_active_context")) or _string_value(metadata.get("cgc_context"))


def _metadata_file_enabled(metadata: Mapping[str, object], name: str) -> bool:
    files = metadata.get("files")
    if not isinstance(files, Mapping):
        return False
    return _truthy(files.get(name))


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _string_value(value: object) -> str:
    return str(value or "").strip()


__all__ = tuple(name for name in globals() if not name.startswith("__"))
