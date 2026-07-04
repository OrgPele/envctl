from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from envctl_engine.planning.worktree_code_intelligence_cgc import (
    cgc_context_already_exists as _cgc_context_already_exists,
    index_worktree_with_cgc as _index_worktree_with_cgc,
    reuse_or_index_worktree_with_cgc as _reuse_or_index_worktree_with_cgc,
    short_command_output as _short_command_output,
)
from envctl_engine.planning.worktree_code_intelligence_codegraph import (
    disabled_codegraph_metadata as _disabled_codegraph_metadata,
    index_worktree_with_codegraph as _index_worktree_with_codegraph,
)
from envctl_engine.planning.worktree_code_intelligence_config import (
    WORKTREE_CGC_INDEX_AUTO_VALUES as _WORKTREE_CGC_INDEX_AUTO_VALUES,
    WORKTREE_CGC_INDEX_DISABLED_VALUES as _WORKTREE_CGC_INDEX_DISABLED_VALUES,
    WORKTREE_CGC_INDEX_ENABLED_VALUES as _WORKTREE_CGC_INDEX_ENABLED_VALUES,
    WORKTREE_CODE_INTELLIGENCE_DISABLED_VALUES as _WORKTREE_CODE_INTELLIGENCE_DISABLED_VALUES,
    WORKTREE_CODE_INTELLIGENCE_ENABLED_VALUES as _WORKTREE_CODE_INTELLIGENCE_ENABLED_VALUES,
    read_source_serena_project_name as _read_source_serena_project_name,
    render_worktree_identity_template as _render_worktree_identity_template,
    sanitize_worktree_identity as _sanitize_worktree_identity,
    source_cgc_context as _source_cgc_context,
    worktree_cgc_database as _worktree_cgc_database,
    worktree_cgc_index_mode as _worktree_cgc_index_mode,
    worktree_codegraph_index_mode as _worktree_codegraph_index_mode,
    worktree_code_intelligence_enabled as _worktree_code_intelligence_enabled,
    worktree_code_intelligence_identity as _worktree_code_intelligence_identity,
    worktree_identity_parts as _worktree_identity_parts,
    worktree_template_value as _worktree_template_value,
)
from envctl_engine.planning.worktree_code_intelligence_files import (
    copy_worktree_code_intelligence_file as _copy_worktree_code_intelligence_file,
    copy_worktree_serena_project_file as _copy_worktree_serena_project_file,
    ensure_worktree_git_excludes as _ensure_worktree_git_excludes,
    rewrite_serena_project_name as _rewrite_serena_project_name,
    write_worktree_serena_project_local_file as _write_worktree_serena_project_local_file,
)
from envctl_engine.planning.worktree_code_intelligence_metadata import (
    write_worktree_code_intelligence_metadata as _write_worktree_code_intelligence_metadata,
)
from envctl_engine.planning.worktree_code_intelligence_models import (
    WORKTREE_CGC_DATABASE_DEFAULT,
    WORKTREE_CGC_INDEX_MODE_AUTO as _WORKTREE_CGC_INDEX_MODE_AUTO,
    WORKTREE_CGC_INDEX_MODE_DISABLED as _WORKTREE_CGC_INDEX_MODE_DISABLED,
    WORKTREE_CGC_INDEX_MODE_ENABLED as _WORKTREE_CGC_INDEX_MODE_ENABLED,
    WORKTREE_CODEGRAPH_INDEX_MODE_DISABLED as _WORKTREE_CODEGRAPH_INDEX_MODE_DISABLED,
    WORKTREE_CODE_INTELLIGENCE_PATH,
    WORKTREE_CODE_INTELLIGENCE_SCHEMA_VERSION,
    WorktreeCodeIntelligenceIdentity,
)


__all__ = [
    "WORKTREE_CGC_DATABASE_DEFAULT",
    "WORKTREE_CODE_INTELLIGENCE_PATH",
    "WORKTREE_CODE_INTELLIGENCE_SCHEMA_VERSION",
    "WorktreeCodeIntelligenceIdentity",
    "_WORKTREE_CGC_INDEX_AUTO_VALUES",
    "_WORKTREE_CGC_INDEX_DISABLED_VALUES",
    "_WORKTREE_CGC_INDEX_ENABLED_VALUES",
    "_WORKTREE_CGC_INDEX_MODE_AUTO",
    "_WORKTREE_CGC_INDEX_MODE_DISABLED",
    "_WORKTREE_CGC_INDEX_MODE_ENABLED",
    "_WORKTREE_CODEGRAPH_INDEX_MODE_DISABLED",
    "_WORKTREE_CODE_INTELLIGENCE_DISABLED_VALUES",
    "_WORKTREE_CODE_INTELLIGENCE_ENABLED_VALUES",
    "_cgc_context_already_exists",
    "_copy_worktree_code_intelligence_file",
    "_copy_worktree_serena_project_file",
    "_disabled_codegraph_metadata",
    "_ensure_worktree_git_excludes",
    "_index_worktree_with_codegraph",
    "_index_worktree_with_cgc",
    "_read_source_serena_project_name",
    "_render_worktree_identity_template",
    "_reuse_or_index_worktree_with_cgc",
    "_rewrite_serena_project_name",
    "_sanitize_worktree_identity",
    "_short_command_output",
    "_source_cgc_context",
    "_worktree_cgc_database",
    "_worktree_cgc_index_mode",
    "_worktree_codegraph_index_mode",
    "_worktree_code_intelligence_enabled",
    "_worktree_code_intelligence_identity",
    "_worktree_identity_parts",
    "_worktree_template_value",
    "_write_worktree_code_intelligence_metadata",
    "_write_worktree_serena_project_local_file",
    "prepare_worktree_code_intelligence",
]


def prepare_worktree_code_intelligence(
    self: Any,
    *,
    target: Path,
    trees_root_for_worktree: Callable[[Any, Path], Path],
) -> None:
    if not target.is_dir() or not _worktree_code_intelligence_enabled(self):
        return
    identity = _worktree_code_intelligence_identity(
        self,
        target=target,
        trees_root_for_worktree=trees_root_for_worktree,
    )
    _ensure_worktree_git_excludes(root=target, patterns=(".envctl-state/",))
    copied_files: dict[str, bool] = {}
    codegraph_result = _disabled_codegraph_metadata()
    cgc_result: dict[str, object] = {
        "cgc_index_mode": _WORKTREE_CGC_INDEX_MODE_DISABLED,
        "cgc_index_requested": False,
        "cgc_available": None,
        "cgc_context_managed": False,
        "cgc_context_created": False,
        "cgc_context_already_exists": False,
        "cgc_context_returncode": None,
        "cgc_index_succeeded": False,
        "cgc_index_returncode": None,
        "cgc_commands": [],
        "cgc_index_skipped_reason": "disabled",
    }
    codegraph_mode = _worktree_codegraph_index_mode(self)
    cgc_mode = _worktree_cgc_index_mode(self)
    serena_project_source = self.config.base_dir / ".serena" / "project.yml"
    serena_project_target = target / ".serena" / "project.yml"
    copied_files[".serena/project.yml"] = (
        _copy_worktree_code_intelligence_file(
            source=serena_project_source,
            target=serena_project_target,
        )
        or serena_project_target.is_file()
    )
    serena_configured = serena_project_source.is_file() or serena_project_target.is_file()
    serena_local_target = target / ".serena" / "project.local.yml"
    copied_files[".serena/project.local.yml"] = False
    if serena_configured:
        copied_files[".serena/project.local.yml"] = _write_worktree_serena_project_local_file(
            target=serena_local_target,
            project_name=identity.serena_project_name,
            emit=getattr(self, "_emit", None),
        )
        _ensure_worktree_git_excludes(root=target, patterns=(".serena/project.local.yml",))
    serena_gitignore_target = target / ".serena" / ".gitignore"
    copied_files[".serena/.gitignore"] = (
        _copy_worktree_code_intelligence_file(
            source=self.config.base_dir / ".serena" / ".gitignore",
            target=serena_gitignore_target,
        )
        or serena_gitignore_target.is_file()
    )
    cgcignore_target = target / ".cgcignore"
    copied_files[".cgcignore"] = cgcignore_target.is_file()
    if cgc_mode != _WORKTREE_CGC_INDEX_MODE_DISABLED:
        copied_files[".cgcignore"] = (
            _copy_worktree_code_intelligence_file(
                source=self.config.base_dir / ".cgcignore",
                target=cgcignore_target,
            )
            or cgcignore_target.is_file()
        )
    if cgc_mode == _WORKTREE_CGC_INDEX_MODE_ENABLED:
        cgc_result = _index_worktree_with_cgc(self, target=target, context=identity.cgc_context)
    elif cgc_mode == _WORKTREE_CGC_INDEX_MODE_AUTO:
        cgc_result = _reuse_or_index_worktree_with_cgc(self, target=target, context=identity.cgc_context)
    if codegraph_mode != _WORKTREE_CODEGRAPH_INDEX_MODE_DISABLED:
        _ensure_worktree_git_excludes(root=self.config.base_dir, patterns=(".codegraph/",))
        _ensure_worktree_git_excludes(root=target, patterns=(".codegraph/",))
        codegraph_result = _index_worktree_with_codegraph(self, target=target, mode=codegraph_mode)
    copied_files[".codegraph/.gitignore"] = (target / ".codegraph" / ".gitignore").is_file()
    copied_files[".codegraph/codegraph.db"] = (target / ".codegraph" / "codegraph.db").is_file()
    _write_worktree_code_intelligence_metadata(
        target=target,
        identity=identity,
        copied_files=copied_files,
        codegraph_result=codegraph_result,
        cgc_database=_worktree_cgc_database(self),
        cgc_result=cgc_result,
    )
