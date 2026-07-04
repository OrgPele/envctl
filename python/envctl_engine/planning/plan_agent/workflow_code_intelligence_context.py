from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree
from envctl_engine.planning.worktree_code_intelligence_config import read_source_serena_project_name
from envctl_engine.planning.worktree_code_intelligence_models import (
    WORKTREE_CODEGRAPH_INDEX_MODE_DISABLED,
    WORKTREE_CODE_INTELLIGENCE_PATH,
)


@dataclass(frozen=True, slots=True)
class CodeIntelligencePromptBuilder:
    worktree: CreatedPlanWorktree | None = None

    def prompt_section(self) -> str:
        root = _worktree_root(self.worktree)
        metadata = _worktree_code_intelligence_metadata(self.worktree)
        serena_line = _serena_prompt_line(metadata, root=root) if metadata else ""
        codegraph_line = _codegraph_prompt_line(metadata, root=root) if metadata else ""
        envctl_source_line = _envctl_source_checkout_prompt_line(root)
        if not serena_line and not codegraph_line and not envctl_source_line:
            return ""
        lines = [
            "## Worktree code intelligence",
            "Use these shortcuts only when they fit the question; use `rg` for exact strings such as flags, "
            "env keys, log messages, docs prose, and error text.",
        ]
        if serena_line:
            lines.append(f"- {serena_line}")
        if codegraph_line:
            lines.append(f"- {codegraph_line}")
        if envctl_source_line:
            lines.append(f"- {envctl_source_line}")
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


def _serena_prompt_line(metadata: Mapping[str, object], *, root: Path | None = None) -> str:
    if not (
        _metadata_file_enabled(metadata, ".serena/project.yml", root=root)
        or _metadata_file_enabled(metadata, ".serena/project.local.yml", root=root)
    ):
        return ""
    project_name = _string_value(read_source_serena_project_name(root)) if root is not None else ""
    if not project_name:
        project_name = _string_value(metadata.get("serena_project_name"))
    if project_name:
        return (
            f"Serena project `{project_name}` is configured. Use Serena for symbol definitions, references, "
            "call paths, and semantic edits."
        )
    return "Serena is configured. Use it for symbol definitions, references, call paths, and semantic edits."


def _codegraph_prompt_line(metadata: Mapping[str, object], *, root: Path | None = None) -> str:
    if not _active_codegraph_index(metadata, root=root):
        return ""
    return (
        "CodeGraph index `.codegraph/` is available for this worktree. Use CodeGraph for broad repo "
        "structure, call paths, flows, and blast-radius questions; in Codex prefer the CodeGraph MCP tool "
        "when present, otherwise run `codegraph explore \"<question>\"` from the worktree root. Use Serena "
        "for exact diagnostics and edits."
    )


def _active_codegraph_index(metadata: Mapping[str, object], *, root: Path | None = None) -> bool:
    mode = _string_value(metadata.get("codegraph_index_mode")).casefold()
    skipped_reason = _string_value(metadata.get("codegraph_index_skipped_reason")).casefold()
    if mode == WORKTREE_CODEGRAPH_INDEX_MODE_DISABLED or skipped_reason in {"disabled", "codegraph_not_available"}:
        return False
    if not _truthy(metadata.get("codegraph_index_succeeded")):
        return False
    return _metadata_file_enabled(metadata, ".codegraph/codegraph.db", root=root)


def _metadata_file_enabled(metadata: Mapping[str, object], name: str, *, root: Path | None = None) -> bool:
    if root is not None:
        return (root / name).is_file()
    files = metadata.get("files")
    if isinstance(files, Mapping) and _truthy(files.get(name)):
        return True
    return False


def _envctl_source_checkout_prompt_line(root: Path | None) -> str:
    if root is None:
        return ""
    if not ((root / "bin" / "envctl").is_file() and (root / "python" / "envctl_engine").is_dir()):
        return ""
    return (
        "This is an envctl source checkout. For envctl self-validation, prefer "
        '`PATH="$PWD/.venv/bin:$PATH" envctl ...` or `ENVCTL_USE_REPO_WRAPPER=1 ./bin/envctl ...` '
        "so commands run this checkout instead of an installed envctl."
    )


def _worktree_root(worktree: CreatedPlanWorktree | None) -> Path | None:
    if worktree is None:
        return None
    try:
        return Path(worktree.root).expanduser()
    except TypeError:
        return None


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _string_value(value: object) -> str:
    return str(value or "").strip()


__all__ = tuple(name for name in globals() if not name.startswith("__"))
