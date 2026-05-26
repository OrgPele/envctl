from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


WORKTREE_CODE_INTELLIGENCE_SCHEMA_VERSION = 1
WORKTREE_CODE_INTELLIGENCE_PATH = Path(".envctl-state") / "code-intelligence.json"
WORKTREE_CGC_DATABASE_DEFAULT = "kuzudb"

WORKTREE_CGC_INDEX_MODE_AUTO = "auto"
WORKTREE_CGC_INDEX_MODE_DISABLED = "disabled"
WORKTREE_CGC_INDEX_MODE_ENABLED = "enabled"


@dataclass(frozen=True)
class WorktreeCodeIntelligenceIdentity:
    worktree_name: str
    feature: str
    iteration: str
    cgc_context: str
    serena_project_name: str
