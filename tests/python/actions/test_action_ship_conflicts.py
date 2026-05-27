from __future__ import annotations

import subprocess
from pathlib import Path

from envctl_engine.actions.action_ship_support import (
    existing_merge_conflict_report,
    parse_merge_tree_conflicts,
    predicted_merge_conflict_report,
)


def test_existing_merge_conflict_report_includes_unmerged_stage_entries(tmp_path: Path) -> None:
    def git_output(_root: Path, args: list[str]) -> str:
        if args == ["diff", "--name-only", "--diff-filter=U"]:
            return "python/app.py\n"
        if args == ["ls-files", "-u"]:
            return "100644 aaaaa 1\tpython/app.py\n100644 bbbbb 2\tpython/app.py\n100644 ccccc 3\tpython/app.py\n"
        raise AssertionError(args)

    report = existing_merge_conflict_report(tmp_path, branch="feature", git_output=git_output)

    assert report["state"] == "conflicts"
    assert report["type"] == "unmerged_index"
    assert report["head_ref"] == "feature"
    assert report["conflicting_files"] == [
        {
            "path": "python/app.py",
            "kind": "unmerged_index",
            "stages": ["1", "2", "3"],
            "stage_entries": [
                {"mode": "100644", "object": "aaaaa", "stage": "1", "path": "python/app.py"},
                {"mode": "100644", "object": "bbbbb", "stage": "2", "path": "python/app.py"},
                {"mode": "100644", "object": "ccccc", "stage": "3", "path": "python/app.py"},
            ],
            "messages": ["Unmerged index entries exist for python/app.py."],
        }
    ]

def test_predicted_merge_conflict_report_parses_merge_tree_conflicts(tmp_path: Path) -> None:
    def git_output(_root: Path, args: list[str]) -> str:
        assert args == ["merge-base", "HEAD", "origin/main"]
        return "merge-base-sha\n"

    def run_git(_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        assert args == ["merge-tree", "--write-tree", "--messages", "--name-only", "HEAD", "origin/main"]
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout=("tree-sha\npython/app.py\n\nCONFLICT (content): Merge conflict in python/app.py\n"),
            stderr="",
        )

    report = predicted_merge_conflict_report(
        object(),
        tmp_path,
        branch="feature",
        resolve_base_branch=lambda _context, _root: "main",
        resolve_base_ref=lambda _root, _branch: "origin/main",
        run_git=run_git,
        git_output=git_output,
    )

    assert report["state"] == "conflicts"
    assert report["merge_base"] == "merge-base-sha"
    assert report["conflicting_files"] == [
        {
            "path": "python/app.py",
            "kind": "predicted_merge",
            "messages": ["CONFLICT (content): Merge conflict in python/app.py"],
        }
    ]

def test_parse_merge_tree_conflicts_falls_back_to_global_messages() -> None:
    assert parse_merge_tree_conflicts("tree\nREADME.md\n\nCONFLICT (rename/delete): conflict\n") == [
        {
            "path": "README.md",
            "kind": "predicted_merge",
            "messages": ["CONFLICT (rename/delete): conflict"],
        }
    ]
