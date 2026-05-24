from __future__ import annotations

import unittest
from types import SimpleNamespace

from envctl_engine.state.models import RunState
from envctl_engine.ui.dashboard import command_support


class DashboardCommandSupportTests(unittest.TestCase):
    def test_dashboard_hidden_commands_normalizes_metadata_and_always_hidden_policy(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="trees",
            services={"Main Backend": SimpleNamespace(name="Main Backend")},
            metadata={"dashboard_hidden_commands": [" Restart ", "", "HEALTH"]},
        )

        hidden = command_support.dashboard_hidden_commands(state)

        self.assertIn("restart", hidden)
        self.assertIn("health", hidden)
        self.assertIn("install-prompts", hidden)
        self.assertNotIn("migrate", hidden)

    def test_dashboard_hidden_commands_hides_migrate_without_running_services(self) -> None:
        state = RunState(run_id="run-1", mode="trees", metadata={"dashboard_hidden_commands": "restart"})

        hidden = command_support.dashboard_hidden_commands(state)

        self.assertIn("migrate", hidden)
        self.assertIn("install-prompts", hidden)
        self.assertNotIn("restart", hidden)


if __name__ == "__main__":
    unittest.main()
