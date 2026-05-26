from __future__ import annotations

from pathlib import Path
from typing import Any

from envctl_engine.state.models import RunState


def prune_project_metadata(state: RunState, *, project_name: str) -> list[Path]:
    removed_paths: list[Path] = []
    for metadata_key in ("project_pr_links", "project_roots"):
        raw = state.metadata.get(metadata_key)
        if not isinstance(raw, dict):
            continue
        raw.pop(project_name, None)
        if raw:
            state.metadata[metadata_key] = raw
        else:
            state.metadata.pop(metadata_key, None)

    summaries_raw = state.metadata.get("project_test_summaries")
    if isinstance(summaries_raw, dict):
        entry = summaries_raw.pop(project_name, None)
        if isinstance(entry, dict):
            for path_key in ("summary_path", "short_summary_path", "state_path", "manifest_path"):
                raw_path = str(entry.get(path_key, "") or "").strip()
                if raw_path:
                    removed_paths.append(Path(raw_path))
        if summaries_raw:
            state.metadata["project_test_summaries"] = summaries_raw
        else:
            state.metadata.pop("project_test_summaries", None)
            state.metadata.pop("project_test_results_root", None)
            state.metadata.pop("project_test_results_updated_at", None)
    return removed_paths


def cleanup_artifact_paths(runtime: Any, *, project_name: str, paths: set[Path], warnings: list[str]) -> None:
    for artifact_path in sorted(paths):
        try:
            if artifact_path.is_file():
                artifact_path.unlink()
                runtime._emit(
                    "cleanup.worktree.artifact.removed",
                    project=project_name,
                    path=str(artifact_path),
                )
        except OSError as exc:
            warning = f"artifact cleanup failed for {project_name} ({artifact_path}): {exc}"
            warnings.append(warning)
            runtime._emit(
                "cleanup.worktree.warning",
                project=project_name,
                path=str(artifact_path),
                warning=warning,
            )
            continue

        parent = artifact_path.parent
        while parent != parent.parent:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
