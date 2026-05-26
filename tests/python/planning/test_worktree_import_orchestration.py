from __future__ import annotations

import json
import subprocess
from pathlib import Path

from envctl_engine.config import load_config
import pytest

from envctl_engine.planning.worktree_import_commands import WorktreeImportError
from envctl_engine.planning.worktree_import_orchestration import (
    dry_run_import_remote_branch_worktree,
    import_remote_branch_worktree,
)
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _runtime(repo: Path, runtime: Path) -> PythonEngineRuntime:
    return PythonEngineRuntime(
        load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(runtime),
                "TREES_STARTUP_ENABLE": "false",
                "ENVCTL_WORKTREE_CODE_INTELLIGENCE": "off",
            }
        ),
        env={},
    )


def _repo_with_remote_branch(tmp_path: Path) -> tuple[Path, Path]:
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", str(origin), str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "test@example.test")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("main\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "main")
    _git(repo, "push", "origin", "HEAD:main")
    _git(repo, "checkout", "-b", "feature/import-me")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "feature")
    _git(repo, "push", "origin", "HEAD:feature/import-me")
    _git(repo, "checkout", "main")
    _git(repo, "branch", "-D", "feature/import-me")
    return repo, origin


def test_import_remote_branch_worktree_creates_tracking_worktree_with_provenance(tmp_path: Path) -> None:
    repo, _origin = _repo_with_remote_branch(tmp_path)
    runtime = _runtime(repo, tmp_path / "runtime")

    result = import_remote_branch_worktree(runtime, "origin/feature/import-me")

    worktree = repo / "trees" / "imported" / "feature-import-me"
    assert result.worktree.name == "imported-feature-import-me"
    assert result.worktree.root == worktree.resolve()
    assert result.action == "created"
    assert (worktree / "feature.txt").read_text(encoding="utf-8") == "feature\n"
    assert _git(worktree, "rev-parse", "--abbrev-ref", "HEAD") == "feature/import-me"
    assert _git(worktree, "config", "--get", "branch.feature/import-me.remote") == "origin"
    assert _git(worktree, "config", "--get", "branch.feature/import-me.merge") == "refs/heads/feature/import-me"

    provenance = json.loads((worktree / ".envctl-state" / "worktree-provenance.json").read_text(encoding="utf-8"))
    assert provenance["resolution_reason"] == "remote_branch_import"
    assert provenance["imported_branch"] == "feature/import-me"
    assert provenance["remote_ref"] == "origin/feature/import-me"


def test_import_remote_branch_worktree_reuses_and_ff_updates(tmp_path: Path) -> None:
    repo, origin = _repo_with_remote_branch(tmp_path)
    runtime = _runtime(repo, tmp_path / "runtime")
    first = import_remote_branch_worktree(runtime, "feature/import-me")

    updater = tmp_path / "updater"
    subprocess.run(["git", "clone", str(origin), str(updater)], check=True, capture_output=True)
    _git(updater, "config", "user.email", "test@example.test")
    _git(updater, "config", "user.name", "Test User")
    _git(updater, "checkout", "feature/import-me")
    (updater / "feature.txt").write_text("updated\n", encoding="utf-8")
    _git(updater, "commit", "-am", "update")
    _git(updater, "push", "origin", "HEAD:feature/import-me")

    second = import_remote_branch_worktree(runtime, "refs/remotes/origin/feature/import-me")

    assert second.action == "reused"
    assert second.worktree.root == first.worktree.root
    assert (first.worktree.root / "feature.txt").read_text(encoding="utf-8") == "updated\n"


def test_import_remote_branch_worktree_uses_existing_local_branch(tmp_path: Path) -> None:
    repo, _origin = _repo_with_remote_branch(tmp_path)
    _git(repo, "branch", "feature/import-me", "origin/feature/import-me")
    runtime = _runtime(repo, tmp_path / "runtime")

    result = import_remote_branch_worktree(runtime, "feature/import-me")

    assert result.action == "created"
    assert _git(result.worktree.root, "rev-parse", "--abbrev-ref", "HEAD") == "feature/import-me"
    assert _git(result.worktree.root, "config", "--get", "branch.feature/import-me.remote") == "origin"
    assert _git(result.worktree.root, "config", "--get", "branch.feature/import-me.merge") == (
        "refs/heads/feature/import-me"
    )


def test_import_remote_branch_worktree_fails_for_missing_remote_branch(tmp_path: Path) -> None:
    repo, _origin = _repo_with_remote_branch(tmp_path)
    runtime = _runtime(repo, tmp_path / "runtime")

    with pytest.raises(WorktreeImportError, match="Remote branch not found"):
        import_remote_branch_worktree(runtime, "feature/not-pushed")

    assert not (repo / "trees" / "imported" / "feature-not-pushed").exists()


def test_import_remote_branch_worktree_fails_on_diverged_local_branch(tmp_path: Path) -> None:
    repo, origin = _repo_with_remote_branch(tmp_path)
    runtime = _runtime(repo, tmp_path / "runtime")
    first = import_remote_branch_worktree(runtime, "feature/import-me")

    _git(first.worktree.root, "config", "user.email", "test@example.test")
    _git(first.worktree.root, "config", "user.name", "Test User")
    (first.worktree.root / "feature.txt").write_text("local\n", encoding="utf-8")
    _git(first.worktree.root, "commit", "-am", "local diverged change")

    updater = tmp_path / "updater"
    subprocess.run(["git", "clone", str(origin), str(updater)], check=True, capture_output=True)
    _git(updater, "config", "user.email", "test@example.test")
    _git(updater, "config", "user.name", "Test User")
    _git(updater, "checkout", "feature/import-me")
    (updater / "feature.txt").write_text("remote\n", encoding="utf-8")
    _git(updater, "commit", "-am", "remote diverged change")
    _git(updater, "push", "origin", "HEAD:feature/import-me")

    with pytest.raises(WorktreeImportError, match="dirty or diverged"):
        import_remote_branch_worktree(runtime, "feature/import-me")


def test_import_remote_branch_worktree_dry_run_previews_create_without_mutating(tmp_path: Path) -> None:
    repo, _origin = _repo_with_remote_branch(tmp_path)
    runtime = _runtime(repo, tmp_path / "runtime")
    remote_ref = repo / ".git" / "refs" / "remotes" / "origin" / "feature" / "import-me"
    before_remote_ref = remote_ref.read_text(encoding="utf-8") if remote_ref.exists() else ""

    result = dry_run_import_remote_branch_worktree(runtime, "origin/feature/import-me")

    worktree = repo / "trees" / "imported" / "feature-import-me"
    assert result.action == "would create"
    assert result.worktree.name == "imported-feature-import-me"
    assert result.worktree.root == worktree.resolve()
    assert not worktree.exists()
    assert not (worktree / ".envctl-state" / "worktree-provenance.json").exists()
    assert (remote_ref.read_text(encoding="utf-8") if remote_ref.exists() else "") == before_remote_ref


def test_import_remote_branch_worktree_dry_run_previews_existing_local_branch(tmp_path: Path) -> None:
    repo, _origin = _repo_with_remote_branch(tmp_path)
    _git(repo, "branch", "feature/import-me", "origin/feature/import-me")
    runtime = _runtime(repo, tmp_path / "runtime")

    result = dry_run_import_remote_branch_worktree(runtime, "feature/import-me")

    assert result.action == "would use existing local branch"
    assert result.worktree.root == (repo / "trees" / "imported" / "feature-import-me").resolve()
    assert not result.worktree.root.exists()


def test_import_remote_branch_worktree_dry_run_previews_existing_worktree(tmp_path: Path) -> None:
    repo, _origin = _repo_with_remote_branch(tmp_path)
    runtime = _runtime(repo, tmp_path / "runtime")
    first = import_remote_branch_worktree(runtime, "feature/import-me")

    result = dry_run_import_remote_branch_worktree(runtime, "refs/remotes/origin/feature/import-me")

    assert result.action == "would reuse existing worktree"
    assert result.worktree.root == first.worktree.root


def test_import_remote_branch_worktree_dry_run_fails_for_wrong_branch_target(tmp_path: Path) -> None:
    repo, _origin = _repo_with_remote_branch(tmp_path)
    _git(repo, "checkout", "-b", "feature/other")
    _git(repo, "checkout", "main")
    target = repo / "trees" / "imported" / "feature-import-me"
    target.parent.mkdir(parents=True)
    _git(repo, "worktree", "add", str(target), "feature/other")
    runtime = _runtime(repo, tmp_path / "runtime")

    with pytest.raises(WorktreeImportError, match="does not match requested branch"):
        dry_run_import_remote_branch_worktree(runtime, "feature/import-me")
