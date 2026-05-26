from __future__ import annotations

from tests.python.actions.actions_cli_test_support import (
    PYTHON_ROOT,
    REPO_ROOT,
    os,
    patch,
    subprocess,
    sys,
)
from tests.python.actions.commit_action_test_support import CommitActionHarness, write_commit_ledger


def test_commit_action_uses_main_task_and_pushes_branch(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True, exist_ok=True)
    ledger = write_commit_ledger(
        project_root,
        "# Envctl Commit Log\n\n### Envctl pointer ###\nShip the feature\n",
    )
    harness = CommitActionHarness(project_root=project_root)

    result = harness.run()

    assert result.code == 0
    assert "Committed and pushed changes for Main (feature/demo)." in result.output
    commit_args = next(args for args in harness.seen_git_args if args[:2] == ["commit", "-F"])
    assert commit_args[2].endswith(".envctl-commit-message.txt")
    assert ["push", "-u", "origin", "feature/demo"] in harness.seen_git_args
    assert ledger.read_text(encoding="utf-8") == "# Envctl Commit Log\n\nShip the feature\n\n### Envctl pointer ###\n"


def test_commit_action_respects_pr_remote_override(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True, exist_ok=True)
    write_commit_ledger(project_root, "# Envctl Commit Log\n\n### Envctl pointer ###\nShip the feature\n")
    harness = CommitActionHarness(project_root=project_root)

    result = harness.run(env={"PR_REMOTE": "fork"})

    assert result.code == 0
    assert ["push", "-u", "fork", "feature/demo"] in harness.seen_git_args


def test_commit_action_interactive_mode_does_not_prompt_for_message(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir(parents=True, exist_ok=True)
    harness = CommitActionHarness(project_root=project_root)

    with (
        patch("sys.stdin.isatty", return_value=True),
        patch("builtins.input", side_effect=AssertionError("input() should not be called for commit action")),
    ):
        result = harness.run(env={"ENVCTL_ACTION_INTERACTIVE": "1"})

    assert result.code == 1
    assert "Envctl commit log is empty after the pointer" in result.output


def test_headless_main_commit_recovers_staged_envctl_artifacts_with_real_git(tmp_path):
    repo_root = tmp_path / "repo"
    origin = tmp_path / "origin.git"
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    git_env = {
        **{key: value for key, value in os.environ.items() if key != "ENVCTL_EXECUTION_ROOT"},
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"),
        "GIT_TERMINAL_PROMPT": "0",
    }

    def git(args: list[str], *, cwd=repo_root) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            env=git_env,
            text=True,
            capture_output=True,
            check=True,
        )

    subprocess.run(
        ["git", "init", "--bare", str(origin)],
        env=git_env,
        text=True,
        capture_output=True,
        check=True,
    )
    repo_root.mkdir(parents=True, exist_ok=True)
    git(["init"])
    git(["config", "user.email", "envctl-tests@example.invalid"])
    git(["config", "user.name", "Envctl Tests"])
    git(["checkout", "-b", "feature/protected-recovery"])
    (repo_root / "app.py").write_text("print('initial')\n", encoding="utf-8")
    git(["add", "app.py"])
    git(["commit", "-m", "initial"])
    git(["remote", "add", "origin", str(origin)])
    git(["push", "-u", "origin", "feature/protected-recovery"])
    initial_head = git(["rev-parse", "HEAD"]).stdout.strip()

    (repo_root / "app.py").write_text("print('changed')\n", encoding="utf-8")
    (repo_root / "MAIN_TASK.md").write_text("# Protected task\n", encoding="utf-8")
    ledger = write_commit_ledger(
        repo_root,
        "# Envctl Commit Log\n\n### Envctl pointer ###\nReal integration summary\n",
    )
    git(["add", "."])

    env = {
        **git_env,
        "RUN_REPO_ROOT": str(repo_root),
        "ENVCTL_DEFAULT_MODE": "main",
        "ENVCTL_SPINNER": "0",
        "ENVCTL_USE_REPO_WRAPPER": "1",
        "PYTHONPATH": str(PYTHON_ROOT),
    }
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "bin" / "envctl"),
            "commit",
            "--headless",
            "--main",
        ],
        cwd=str(repo_root),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    new_head = git(["rev-parse", "HEAD"]).stdout.strip()
    pushed_head = git(["rev-parse", "origin/feature/protected-recovery"]).stdout.strip()
    committed_files = git(["ls-tree", "-r", "--name-only", "HEAD"]).stdout.splitlines()
    assert new_head != initial_head
    assert pushed_head == new_head
    assert git(["log", "-1", "--pretty=%B"]).stdout.strip() == "Real integration summary"
    assert committed_files == ["app.py"]
    assert git(["diff", "--cached", "--name-only"]).stdout.strip() == ""
    assert (repo_root / "MAIN_TASK.md").is_file()
    assert ledger.read_text(encoding="utf-8") == (
        "# Envctl Commit Log\n\nReal integration summary\n\n### Envctl pointer ###\n"
    )
