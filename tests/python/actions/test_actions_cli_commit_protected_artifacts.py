from __future__ import annotations

from tests.python.actions.commit_action_test_support import CommitActionHarness, write_commit_ledger


def test_commit_action_skips_envctl_local_artifacts_and_commits_normal_changes(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True, exist_ok=True)
    write_commit_ledger(project_root, "# Envctl Commit Log\n\n### Envctl pointer ###\nShip the feature\n")
    harness = CommitActionHarness(
        project_root=project_root,
        pre_stage_statuses=["?? .envctl-commit-message.md\n?? MAIN_TASK.md\n M app.py\n"],
    )

    result = harness.run()

    assert result.code == 0
    assert "Skipping envctl-local artifacts: .envctl-commit-message.md, MAIN_TASK.md" in result.output
    assert ["add", "--all", "--", "app.py"] in harness.seen_git_args
    assert ["push", "-u", "origin", "feature/demo"] in harness.seen_git_args


def test_commit_action_noops_when_only_envctl_local_artifacts_are_present(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True, exist_ok=True)
    harness = CommitActionHarness(
        project_root=project_root,
        pre_stage_statuses=["?? .envctl\n?? OLD_TASK_feature.md\n"],
        staged_status="",
    )

    result = harness.run()

    assert result.code == 0
    assert "Skipping envctl-local artifacts: .envctl, OLD_TASK_feature.md" in result.output
    assert "No changes to commit for feature/demo." in result.output


def test_commit_action_recovers_when_envctl_local_artifacts_are_already_staged(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True, exist_ok=True)
    write_commit_ledger(project_root, "# Envctl Commit Log\n\n### Envctl pointer ###\nRecover protected artifacts\n")
    harness = CommitActionHarness(
        project_root=project_root,
        pre_stage_statuses=[
            "A  MAIN_TASK.md\n?? .envctl-commit-message.md\n M app.py\n",
            "?? MAIN_TASK.md\n?? .envctl-commit-message.md\n M app.py\n",
        ],
        staged_status="M  app.py\n?? MAIN_TASK.md\n?? .envctl-commit-message.md\n",
        commit_stdout="[feature/demo abc123] Recover\n",
    )

    result = harness.run()

    assert result.code == 0
    assert "Unstaged envctl-local artifacts: MAIN_TASK.md" in result.output
    assert "Skipping envctl-local artifacts: MAIN_TASK.md, .envctl-commit-message.md" in result.output
    assert "Refusing to commit" not in result.output
    assert ["reset", "-q", "--", "MAIN_TASK.md"] in harness.seen_git_args
    assert ["add", "--all", "--", "app.py"] in harness.seen_git_args
    assert ["push", "-u", "origin", "feature/demo"] in harness.seen_git_args


def test_commit_action_unstages_staged_envctl_ledger_but_still_uses_it_for_message(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True, exist_ok=True)
    ledger = write_commit_ledger(
        project_root,
        "# Envctl Commit Log\n\n### Envctl pointer ###\nLedger supplied summary\n",
    )
    harness = CommitActionHarness(
        project_root=project_root,
        pre_stage_statuses=[
            "A  .envctl-commit-message.md\n M app.py\n",
            "?? .envctl-commit-message.md\n M app.py\n",
        ],
        staged_status="M  app.py\n?? .envctl-commit-message.md\n",
        commit_stdout="[feature/demo abc123] Ledger\n",
    )

    result = harness.run()

    assert result.code == 0
    assert "Unstaged envctl-local artifacts: .envctl-commit-message.md" in result.output
    assert harness.captured_commit_messages == ["Ledger supplied summary"]
    assert ["reset", "-q", "--", ".envctl-commit-message.md"] in harness.seen_git_args
    assert ledger.read_text(encoding="utf-8") == (
        "# Envctl Commit Log\n\nLedger supplied summary\n\n### Envctl pointer ###\n"
    )


def test_commit_action_noops_when_only_staged_envctl_local_artifacts_remain_after_unstage(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True, exist_ok=True)
    harness = CommitActionHarness(
        project_root=project_root,
        pre_stage_statuses=[
            "A  MAIN_TASK.md\nA  .envctl-state/worktree-provenance.json\n",
            "?? MAIN_TASK.md\n?? .envctl-state/worktree-provenance.json\n",
        ],
        staged_status="?? MAIN_TASK.md\n?? .envctl-state/worktree-provenance.json\n",
    )

    result = harness.run()

    assert result.code == 0
    assert (
        "Unstaged envctl-local artifacts: MAIN_TASK.md, .envctl-state/worktree-provenance.json"
        in result.output
    )
    assert (
        "Skipping envctl-local artifacts: MAIN_TASK.md, .envctl-state/worktree-provenance.json"
        in result.output
    )
    assert "No changes to commit for feature/demo." in result.output
    assert not any(args and args[0] == "add" for args in harness.seen_git_args), harness.seen_git_args
    assert not any(args and args[0] == "commit" for args in harness.seen_git_args), harness.seen_git_args
    assert not any(args and args[0] == "push" for args in harness.seen_git_args), harness.seen_git_args


def test_commit_action_fails_when_unstaging_envctl_local_artifacts_fails(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True, exist_ok=True)
    harness = CommitActionHarness(
        project_root=project_root,
        pre_stage_statuses=["A  MAIN_TASK.md\n?? .envctl-commit-message.md\n M app.py\n"],
        reset_returncode=128,
        reset_stderr="fatal: reset failed\n",
    )

    result = harness.run()

    assert result.code == 1
    assert "git reset protected envctl-local artifacts failed" in result.output
    assert "Protected envctl-local artifacts still staged: MAIN_TASK.md" in result.output
    assert "Protected envctl-local artifacts still staged: MAIN_TASK.md, .envctl-commit-message.md" not in result.output
    assert not any(args and args[0] == "add" for args in harness.seen_git_args), harness.seen_git_args
    assert not any(args and args[0] == "commit" for args in harness.seen_git_args), harness.seen_git_args
    assert not any(args and args[0] == "push" for args in harness.seen_git_args), harness.seen_git_args
