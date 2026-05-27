import unittest

from envctl_engine.planning.plan_agent import tmux_surface_support
from envctl_engine.planning.plan_agent import tmux_transport


class PlanAgentTmuxTransportFacadeTests(unittest.TestCase):
    def test_stateless_tmux_surface_helpers_are_owner_aliases(self) -> None:
        expected_aliases = {
            "_tmux_target": tmux_surface_support.tmux_target,
            "_run_tmux_command": tmux_surface_support.run_tmux_command,
            "_send_tmux_text": tmux_surface_support.send_tmux_text,
            "_send_tmux_key": tmux_surface_support.send_tmux_key,
            "_read_tmux_screen": tmux_surface_support.read_tmux_screen,
            "_send_tmux_prompt": tmux_surface_support.send_tmux_prompt,
        }

        for facade_name, owner_fn in expected_aliases.items():
            with self.subTest(facade_name=facade_name):
                self.assertIs(getattr(tmux_transport, facade_name), owner_fn)
