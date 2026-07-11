from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any, Callable

GitOutput = Callable[[Path, list[str]], str]
RunGit = Callable[[Path, list[str]], subprocess.CompletedProcess[str]]
ResolveBaseBranch = Callable[[Any, Path], str]
ResolveBaseRef = Callable[[Path, str], str]


def existing_merge_conflict_report(git_root: Path, *, branch: str, git_output: GitOutput) -> dict[str, object]:
    paths = [path for path in git_output(git_root, ["diff", "--name-only", "--diff-filter=U"]).splitlines() if path]
    if not paths:
        return {
            "state": "clean",
            "type": "unmerged_index",
            "base_ref": "",
            "head_ref": branch or "HEAD",
            "merge_base": "",
            "conflicting_files": [],
            "resolution_steps": [],
            "messages": [],
        }
    stage_entries = unmerged_stage_entries(git_root, git_output=git_output)
    files: list[dict[str, object]] = []
    for path in paths:
        entries = stage_entries.get(path, [])
        stages = sorted({str(entry.get("stage", "")) for entry in entries if entry.get("stage")})
        files.append(
            {
                "path": path,
                "kind": "unmerged_index",
                "stages": stages,
                "stage_entries": entries,
                "messages": [f"Unmerged index entries exist for {path}."],
            }
        )
    return {
        "state": "conflicts",
        "type": "unmerged_index",
        "base_ref": "",
        "head_ref": branch or "HEAD",
        "merge_base": "",
        "conflicting_files": files,
        "resolution_steps": [
            "Open each conflicting file and resolve conflict markers.",
            "git add <resolved-file>",
            "rerun envctl ship --project <name>",
        ],
        "messages": ["The worktree already has unresolved merge conflicts."],
    }


def predicted_merge_conflict_report(
    context: Any,
    git_root: Path,
    *,
    branch: str,
    resolve_base_branch: ResolveBaseBranch,
    resolve_base_ref: ResolveBaseRef,
    run_git: RunGit,
    git_output: GitOutput,
    base_branch_override: str = "",
) -> dict[str, object]:
    del branch
    base_branch = base_branch_override.strip() or resolve_base_branch(context, git_root)
    base_ref = resolve_base_ref(git_root, base_branch)
    if not base_ref:
        return {
            "state": "unknown",
            "type": "predicted_merge",
            "base_branch": base_branch,
            "base_ref": "",
            "head_ref": "HEAD",
            "merge_base": "",
            "conflicting_files": [],
            "resolution_steps": [],
            "messages": [f"Unable to resolve PR base branch '{base_branch}' for conflict prediction."],
        }
    merge_base = git_output(git_root, ["merge-base", "HEAD", base_ref]).strip()
    completed = run_git(git_root, ["merge-tree", "--write-tree", "--messages", "--name-only", "HEAD", base_ref])
    if completed.returncode == 0:
        return {
            "state": "clean",
            "type": "predicted_merge",
            "base_branch": base_branch,
            "base_ref": base_ref,
            "head_ref": "HEAD",
            "merge_base": merge_base,
            "conflicting_files": [],
            "resolution_steps": [],
            "messages": [],
        }
    if completed.returncode == 1:
        conflict_files = parse_merge_tree_conflicts(completed.stdout)
        return {
            "state": "conflicts",
            "type": "predicted_merge",
            "base_branch": base_branch,
            "base_ref": base_ref,
            "head_ref": "HEAD",
            "merge_base": merge_base,
            "conflicting_files": conflict_files,
            "resolution_steps": [
                f"git fetch origin {base_branch}",
                f"git merge {base_ref}",
                "Resolve each file listed in merge_conflicts.conflicting_files.",
                "git add <resolved-file>",
                "rerun envctl ship --project <name>",
            ],
            "messages": [line for line in completed.stdout.splitlines() if line.strip().startswith("CONFLICT")],
        }
    return {
        "state": "unknown",
        "type": "predicted_merge",
        "base_branch": base_branch,
        "base_ref": base_ref,
        "head_ref": "HEAD",
        "merge_base": merge_base,
        "conflicting_files": [],
        "resolution_steps": [],
        "messages": [(completed.stderr or completed.stdout).strip()],
    }


def unmerged_stage_entries(git_root: Path, *, git_output: GitOutput) -> dict[str, list[dict[str, str]]]:
    entries: dict[str, list[dict[str, str]]] = {}
    for line in git_output(git_root, ["ls-files", "-u"]).splitlines():
        left, sep, path = line.partition("\t")
        if not sep or not path:
            continue
        parts = left.split()
        if len(parts) < 3:
            continue
        entry = {"mode": parts[0], "object": parts[1], "stage": parts[2], "path": path}
        entries.setdefault(path, []).append(entry)
    return entries


def parse_merge_tree_conflicts(output: str) -> list[dict[str, object]]:
    lines = output.splitlines()
    path_lines: list[str] = []
    message_lines: list[str] = []
    reading_paths = False
    for index, line in enumerate(lines):
        if index == 0:
            reading_paths = True
            continue
        if reading_paths and not line.strip():
            reading_paths = False
            continue
        if reading_paths:
            path_lines.append(line.strip())
        elif line.strip():
            message_lines.append(line.strip())
    files: list[dict[str, object]] = []
    for path in path_lines:
        messages = [line for line in message_lines if path in line]
        messages = sorted(messages, key=lambda line: 0 if line.startswith("CONFLICT") else 1)
        files.append(
            {
                "path": path,
                "kind": "predicted_merge",
                "messages": messages or list(message_lines),
            }
        )
    return files


__all__ = [
    "GitOutput",
    "ResolveBaseBranch",
    "ResolveBaseRef",
    "RunGit",
    "existing_merge_conflict_report",
    "parse_merge_tree_conflicts",
    "predicted_merge_conflict_report",
    "unmerged_stage_entries",
]
