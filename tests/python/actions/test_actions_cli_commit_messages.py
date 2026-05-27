from __future__ import annotations

from tests.python.actions.actions_cli_test_support import _TtyStringIO, strip_ansi
from tests.python.actions.commit_action_test_support import CommitActionHarness, write_commit_ledger


def test_commit_action_uses_envctl_pointer_segment_and_advances_pointer_after_commit(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True, exist_ok=True)
    ledger = write_commit_ledger(
        project_root,
        "# Envctl Commit Log\n\n"
        "Historical summary that should stay archived.\n\n"
        "### Envctl pointer ###\n"
        "Ship the feature\n\n"
        "- bullet one\n"
        "- bullet two\n",
    )
    harness = CommitActionHarness(project_root=project_root)

    result = harness.run()

    assert result.code == 0
    assert harness.captured_commit_messages == ["Ship the feature\n\n- bullet one\n- bullet two"]
    assert any(args[:2] == ["commit", "-F"] for args in harness.seen_git_args)
    assert ledger.read_text(encoding="utf-8") == (
        "# Envctl Commit Log\n\n"
        "Historical summary that should stay archived.\n\n"
        "Ship the feature\n\n"
        "- bullet one\n"
        "- bullet two\n\n"
        "### Envctl pointer ###\n"
    )


def test_commit_action_bootstraps_missing_envctl_commit_ledger_and_fails_when_segment_empty(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True, exist_ok=True)
    ledger = project_root / ".envctl-commit-message.md"
    harness = CommitActionHarness(project_root=project_root)

    result = harness.run()

    assert result.code == 1
    assert "Envctl commit log is empty after the pointer" in result.output
    assert not any(args[:2] == ["commit", "-F"] for args in harness.seen_git_args)
    assert ledger.read_text(encoding="utf-8") == "# Envctl Commit Log\n\n### Envctl pointer ###\n"


def test_commit_action_renders_clickable_missing_commit_message_file_path(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True, exist_ok=True)
    missing_file = project_root / "missing-message.txt"
    harness = CommitActionHarness(project_root=project_root)

    result = harness.run(
        env={"ENVCTL_COMMIT_MESSAGE_FILE": str(missing_file), "ENVCTL_UI_HYPERLINK_MODE": "on"},
        stdout_factory=_TtyStringIO,
    )

    assert result.code == 1
    assert "\x1b]8;;file://" in result.output
    assert f"Commit message file is missing or empty: {missing_file}" in strip_ansi(result.output)


def test_commit_action_renders_clickable_ledger_path_in_empty_pointer_error(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True, exist_ok=True)
    ledger = project_root / ".envctl-commit-message.md"
    harness = CommitActionHarness(project_root=project_root)

    result = harness.run(env={"ENVCTL_UI_HYPERLINK_MODE": "on"}, stdout_factory=_TtyStringIO)

    assert result.code == 1
    assert "\x1b]8;;file://" in result.output
    visible = strip_ansi(result.output)
    assert "Envctl commit log is empty after the pointer" in visible
    assert str(ledger) in visible


def test_commit_action_explicit_message_overrides_envctl_ledger(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True, exist_ok=True)
    ledger = write_commit_ledger(
        project_root,
        "# Envctl Commit Log\n\n### Envctl pointer ###\nQueued default summary\n",
    )
    harness = CommitActionHarness(project_root=project_root, commit_stdout="[feature/demo abc123] explicit\n")

    result = harness.run(env={"ENVCTL_COMMIT_MESSAGE": "Explicit summary"})

    assert result.code == 0
    assert ["commit", "-m", "Explicit summary"] in harness.seen_git_args
    assert ledger.read_text(encoding="utf-8") == (
        "# Envctl Commit Log\n\n### Envctl pointer ###\nQueued default summary\n"
    )


def test_commit_action_explicit_message_file_overrides_envctl_ledger(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True, exist_ok=True)
    ledger = write_commit_ledger(
        project_root,
        "# Envctl Commit Log\n\n### Envctl pointer ###\nQueued default summary\n",
    )
    message_file = project_root / "custom-message.txt"
    message_file.write_text("Explicit file summary\n", encoding="utf-8")
    harness = CommitActionHarness(project_root=project_root, commit_stdout="[feature/demo abc123] explicit file\n")

    result = harness.run(env={"ENVCTL_COMMIT_MESSAGE_FILE": str(message_file)})

    assert result.code == 0
    assert ["commit", "-F", str(message_file)] in harness.seen_git_args
    assert ledger.read_text(encoding="utf-8") == (
        "# Envctl Commit Log\n\n### Envctl pointer ###\nQueued default summary\n"
    )


def test_commit_action_uses_entire_envctl_ledger_when_marker_is_missing(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True, exist_ok=True)
    ledger = write_commit_ledger(project_root, "Ship the feature without a marker.\n")
    harness = CommitActionHarness(project_root=project_root)

    result = harness.run()

    assert result.code == 0
    assert "Committed and pushed changes for Main (feature/demo)." in result.output
    assert ["push", "-u", "origin", "feature/demo"] in harness.seen_git_args
    assert harness.captured_commit_messages == ["Ship the feature without a marker."]
    assert ledger.read_text(encoding="utf-8") == "Ship the feature without a marker.\n\n### Envctl pointer ###\n"


def test_commit_action_fails_when_envctl_ledger_has_duplicate_markers(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True, exist_ok=True)
    write_commit_ledger(
        project_root,
        "# Envctl Commit Log\n\n"
        "### Envctl pointer ###\n"
        "First queued summary\n\n"
        "### Envctl pointer ###\n"
        "Second queued summary\n",
    )
    harness = CommitActionHarness(project_root=project_root)

    result = harness.run()

    assert result.code == 1
    assert "contains multiple pointer markers" in result.output


def test_commit_action_push_failure_keeps_pointer_advanced_after_successful_commit(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True, exist_ok=True)
    ledger = write_commit_ledger(
        project_root,
        "# Envctl Commit Log\n\n"
        "Already committed summary\n\n"
        "### Envctl pointer ###\n"
        "Newest queued summary\n",
    )
    harness = CommitActionHarness(project_root=project_root, push_returncode=1, push_stderr="push failed")

    result = harness.run()

    assert result.code == 1
    assert harness.captured_commit_messages == ["Newest queued summary"]
    assert "git push failed" in result.output
    assert ledger.read_text(encoding="utf-8") == (
        "# Envctl Commit Log\n\n"
        "Already committed summary\n\n"
        "Newest queued summary\n\n"
        "### Envctl pointer ###\n"
    )
