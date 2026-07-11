from __future__ import annotations

from dataclasses import dataclass

from envctl_engine.config.local_artifacts import is_envctl_local_artifact_path


@dataclass(frozen=True, slots=True)
class EnvctlProtectedPathPartition:
    protected_staged_paths: list[str]
    protected_skipped_paths: list[str]
    stageable_paths: list[str]


def partition_envctl_protected_paths(status_output: str) -> EnvctlProtectedPathPartition:
    protected_staged_paths: list[str] = []
    protected_skipped_paths: list[str] = []
    stageable_paths: list[str] = []
    seen_protected_staged: set[str] = set()
    seen_protected_skipped: set[str] = set()
    seen_stageable: set[str] = set()
    for raw_line in str(status_output or "").splitlines():
        line = raw_line.rstrip("\n")
        if not line:
            continue
        if len(line) < 4:
            continue
        index_status = line[0]
        candidate = status_candidate_path(line)
        if not candidate:
            continue
        if is_envctl_local_artifact_path(candidate):
            if index_status not in {" ", "?"}:
                if candidate not in seen_protected_staged:
                    protected_staged_paths.append(candidate)
                    seen_protected_staged.add(candidate)
                if candidate in seen_protected_skipped:
                    protected_skipped_paths = [path for path in protected_skipped_paths if path != candidate]
                    seen_protected_skipped.remove(candidate)
            elif candidate not in seen_protected_staged and candidate not in seen_protected_skipped:
                protected_skipped_paths.append(candidate)
                seen_protected_skipped.add(candidate)
            continue
        if candidate not in seen_stageable:
            stageable_paths.append(candidate)
            seen_stageable.add(candidate)
    return EnvctlProtectedPathPartition(
        protected_staged_paths=protected_staged_paths,
        protected_skipped_paths=protected_skipped_paths,
        stageable_paths=stageable_paths,
    )


def ordered_unique_paths(*path_groups: list[str]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for group in path_groups:
        for path in group:
            if path in seen:
                continue
            paths.append(path)
            seen.add(path)
    return paths


def unstaged_stageable_paths(status_output: str) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for raw_line in str(status_output or "").splitlines():
        line = raw_line.rstrip("\n")
        if len(line) < 4:
            continue
        is_untracked = line.startswith("?? ")
        worktree_status = line[1]
        if not is_untracked and worktree_status == " ":
            continue
        candidates = status_candidate_paths(line, include_rename_source=not is_untracked)
        for candidate in candidates:
            if is_envctl_local_artifact_path(candidate) or candidate in seen:
                continue
            paths.append(candidate)
            seen.add(candidate)
    return paths


def status_candidate_path(line: str) -> str:
    if line.startswith("?? "):
        return line[3:].strip()
    payload = line[3:].strip()
    if not payload:
        return ""
    if " -> " in payload:
        return payload.split(" -> ", 1)[1].strip()
    return payload


def status_candidate_paths(line: str, *, include_rename_source: bool = False) -> list[str]:
    candidate = status_candidate_path(line)
    if not candidate:
        return []
    if not include_rename_source:
        return [candidate]
    payload = line[3:].strip()
    if " -> " not in payload:
        return [candidate]
    source = payload.split(" -> ", 1)[0].strip()
    return [source, candidate] if source and source != candidate else [candidate]
