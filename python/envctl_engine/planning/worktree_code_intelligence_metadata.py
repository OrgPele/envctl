from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from envctl_engine.planning.worktree_code_intelligence_models import (
    WORKTREE_CODE_INTELLIGENCE_PATH,
    WORKTREE_CODE_INTELLIGENCE_SCHEMA_VERSION,
    WorktreeCodeIntelligenceIdentity,
)


def write_worktree_code_intelligence_metadata(
    *,
    target: Path,
    identity: WorktreeCodeIntelligenceIdentity,
    copied_files: Mapping[str, bool],
    codegraph_result: Mapping[str, object],
    cgc_database: str,
    cgc_result: Mapping[str, object],
) -> None:
    if not target.is_dir():
        return
    payload: dict[str, object] = {
        "schema_version": WORKTREE_CODE_INTELLIGENCE_SCHEMA_VERSION,
        "serena_project_name": identity.serena_project_name,
        "cgc_context": identity.cgc_context,
        "cgc_active_context": identity.cgc_context,
        "worktree_name": identity.worktree_name,
        "feature": identity.feature,
        "iteration": identity.iteration,
        "files": dict(copied_files),
        "cgc_database": cgc_database,
    }
    payload.update(dict(codegraph_result))
    payload.update(dict(cgc_result))
    path = target / WORKTREE_CODE_INTELLIGENCE_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return
