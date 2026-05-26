from __future__ import annotations

from pathlib import Path

import pytest

from envctl_engine.planning.worktree_import_commands import (
    build_existing_branch_worktree_add_command,
    build_import_fetch_command,
    build_import_update_command,
    build_import_worktree_add_command,
    find_worktree_for_branch,
    normalize_import_branch_ref,
)


def test_normalize_import_branch_ref_accepts_branch_and_origin_forms() -> None:
    for raw in ("feature/foo", "origin/feature/foo", "refs/remotes/origin/feature/foo"):
        ref = normalize_import_branch_ref(raw)

        assert ref.branch == "feature/foo"
        assert ref.remote == "origin"
        assert ref.remote_ref == "origin/feature/foo"
        assert ref.local_branch == "feature/foo"
        assert ref.slug == "feature-foo"
        assert ref.project_name == "imported-feature-foo"


@pytest.mark.parametrize("raw", ["", "../bad", "feature/*", "feature foo", "0123456789abcdef", "refs/remotes/upstream/x"])
def test_normalize_import_branch_ref_rejects_unsafe_inputs(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_import_branch_ref(raw)


def test_import_fetch_command_updates_remote_tracking_ref_only() -> None:
    ref = normalize_import_branch_ref("feature/foo")

    assert build_import_fetch_command(repo_root=Path("/repo"), ref=ref) == [
        "git",
        "-C",
        "/repo",
        "fetch",
        "origin",
        "refs/heads/feature/foo:refs/remotes/origin/feature/foo",
    ]


def test_import_worktree_add_command_tracks_remote_branch_with_hooks_disabled() -> None:
    ref = normalize_import_branch_ref("feature/foo")

    assert build_import_worktree_add_command(
        repo_root=Path("/repo"),
        target=Path("/repo/trees/imported/feature-foo"),
        ref=ref,
        git_hooks_disabled=True,
    ) == [
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "-C",
        "/repo",
        "worktree",
        "add",
        "--track",
        "-b",
        "feature/foo",
        "/repo/trees/imported/feature-foo",
        "origin/feature/foo",
    ]


def test_existing_branch_worktree_add_command_preserves_local_branch() -> None:
    ref = normalize_import_branch_ref("feature/foo")

    assert build_existing_branch_worktree_add_command(
        repo_root=Path("/repo"),
        target=Path("/repo/trees/imported/feature-foo"),
        ref=ref,
        git_hooks_disabled=False,
    ) == [
        "git",
        "-C",
        "/repo",
        "worktree",
        "add",
        "/repo/trees/imported/feature-foo",
        "feature/foo",
    ]


def test_import_update_command_uses_ff_only_merge() -> None:
    ref = normalize_import_branch_ref("feature/foo")

    assert build_import_update_command(worktree_root=Path("/repo/trees/imported/feature-foo"), ref=ref) == [
        "git",
        "-C",
        "/repo/trees/imported/feature-foo",
        "merge",
        "--ff-only",
        "origin/feature/foo",
    ]


def test_find_worktree_for_branch_reads_git_porcelain() -> None:
    ref = normalize_import_branch_ref("feature/foo")
    porcelain = """worktree /repo
HEAD abc
branch refs/heads/main

worktree /repo/trees/imported/feature-foo
HEAD def
branch refs/heads/feature/foo
"""

    assert find_worktree_for_branch(porcelain, ref=ref) == Path("/repo/trees/imported/feature-foo")
