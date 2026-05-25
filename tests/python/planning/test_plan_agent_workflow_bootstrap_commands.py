from __future__ import annotations

import unittest
from pathlib import Path

from envctl_engine.planning.plan_agent.workflow_bootstrap_commands import (
    CliBootstrapCommandTyper,
)


class PlanAgentWorkflowBootstrapCommandsTests(unittest.TestCase):
    def test_types_cd_and_cli_command_in_order_with_quoted_cwd(self) -> None:
        calls: list[tuple[str, str, str]] = []

        typer = CliBootstrapCommandTyper(
            send_text=lambda text: calls.append(("text", text, "ok")) or None,
            send_key=lambda key: calls.append(("key", key, "ok")) or None,
        )

        self.assertEqual(
            typer.type_bootstrap_commands(
                cwd=Path("/repo/work tree"),
                cli_command="codex --flag",
            ),
            [None, None, None, None],
        )
        self.assertEqual(
            calls,
            [
                ("text", "cd '/repo/work tree'", "ok"),
                ("key", "enter", "ok"),
                ("text", "codex --flag", "ok"),
                ("key", "enter", "ok"),
            ],
        )

    def test_preserves_individual_send_errors_without_short_circuiting(self) -> None:
        typer = CliBootstrapCommandTyper(
            send_text=lambda text: "bad text" if text.startswith("cd ") else None,
            send_key=lambda key: "bad key" if key == "enter" else None,
        )

        self.assertEqual(
            typer.type_bootstrap_commands(cwd=Path("/repo"), cli_command="codex"),
            ["bad text", "bad key", None, "bad key"],
        )


if __name__ == "__main__":
    unittest.main()
