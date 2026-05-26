from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from envctl_engine.ui.dashboard.command_input_support import (
    parse_interactive_command,
    prompt_commit_message,
    prompt_pr_message,
    queue_return_to_dashboard_prompt,
    read_interactive_line,
    recover_single_letter_command_from_escape_fragment,
    repo_root_for_project,
    sanitize_interactive_input,
    tokens_set_mode,
)


class DashboardCommandInputSupportTests(unittest.TestCase):
    def test_read_interactive_line_prefers_runtime_reader(self) -> None:
        runtime = SimpleNamespace(_read_interactive_command_line=lambda prompt: f"read:{prompt}")

        self.assertEqual(read_interactive_line(runtime, "Command: "), "read:Command: ")

    def test_queue_return_to_dashboard_prompt_stores_prompt_without_raising(self) -> None:
        runtime = SimpleNamespace()

        queue_return_to_dashboard_prompt(runtime, "Press Enter")

        self.assertEqual(runtime._dashboard_return_prompt, "Press Enter")

    def test_prompt_commit_and_pr_messages_delegate_to_runtime_dialog(self) -> None:
        calls: list[dict[str, object]] = []

        def prompt_text_input(**kwargs: object) -> str:
            calls.append(kwargs)
            return f"value:{kwargs['title']}"

        runtime = SimpleNamespace(_prompt_text_input=prompt_text_input)

        self.assertEqual(prompt_commit_message(runtime), "value:Commit Message")
        self.assertEqual(prompt_pr_message(runtime), "value:PR Message")
        self.assertEqual([call["initial_value"] for call in calls], ["", ""])

    def test_prompt_commit_message_returns_none_when_dialog_is_cancelled(self) -> None:
        runtime = SimpleNamespace(_prompt_text_input=lambda **_kwargs: None)

        self.assertIsNone(prompt_commit_message(runtime))

    def test_repo_root_for_project_detects_git_or_todo_ancestors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            worktree = repo / "trees" / "feature" / "1"
            worktree.mkdir(parents=True)
            (repo / ".git").mkdir()

            self.assertEqual(repo_root_for_project(worktree), repo.resolve())

    def test_repo_root_for_project_returns_none_without_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir) / "plain" / "child"
            project.mkdir(parents=True)

            self.assertIsNone(repo_root_for_project(project))

    def test_interactive_command_parsing_wrappers_share_ui_parser_behavior(self) -> None:
        raw = "\x1b[200~restart --project Main\x1b[201~"

        sanitized = sanitize_interactive_input(raw)

        self.assertEqual(sanitized, "restart --project Main")
        self.assertEqual(parse_interactive_command(sanitized), ["restart", "--project", "Main"])
        self.assertTrue(tokens_set_mode(["--trees", "status"]))
        self.assertEqual(recover_single_letter_command_from_escape_fragment("\x1bOq"), "q")

    def test_dispatch_kill_session_uses_selected_tmux_sessions(self) -> None:
        from envctl_engine.ui.dashboard.command_input_support import dispatch_kill_session

        killed: list[str] = []

        with (
            patch(
                "envctl_engine.runtime.session_management.list_tmux_sessions",
                return_value=[{"name": "agent-1", "windows": 2}, {"name": "agent-2", "windows": 1}],
            ),
            patch("envctl_engine.runtime.session_management.kill_session", side_effect=lambda name: killed.append(name) or True),
        ):
            dispatch_kill_session(
                SimpleNamespace(),
                selector_fn=lambda **kwargs: [option.token for option in kwargs["options"] if option.token == "agent-2"],
            )

        self.assertEqual(killed, ["agent-2"])


if __name__ == "__main__":
    unittest.main()
