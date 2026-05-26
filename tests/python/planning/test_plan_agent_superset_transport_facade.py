from __future__ import annotations

import unittest

from envctl_engine.planning.plan_agent import superset_cli_support
from envctl_engine.planning.plan_agent import superset_goal_agent_support
from envctl_engine.planning.plan_agent import superset_transport


class PlanAgentSupersetTransportFacadeTests(unittest.TestCase):
    def test_stateless_superset_helpers_are_direct_owner_aliases(self) -> None:
        expected_aliases = {
            "_git_branch_name": superset_cli_support.git_branch_name,
            "_open_superset_workspace": superset_cli_support.open_superset_workspace,
            "_superset_workspace_name": superset_cli_support.superset_workspace_name,
            "_ensure_superset_codex_goal_agent": superset_goal_agent_support.ensure_superset_codex_goal_agent,
            "_write_superset_codex_goal_launcher": superset_goal_agent_support.write_superset_codex_goal_launcher,
            "_superset_host_agent_db": superset_goal_agent_support.superset_host_agent_db,
        }

        for facade_name, owner in expected_aliases.items():
            with self.subTest(facade_name=facade_name):
                self.assertIs(getattr(superset_transport, facade_name), owner)


if __name__ == "__main__":
    unittest.main()
