from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.planning.plan_agent.cmux_workspace_support import (
    default_workspace_target,
    surface_ids_from_list_output,
    workspace_entries_from_list_output,
    workspace_ref_from_identify_output,
)
from envctl_engine.planning.plan_agent.config import PlanAgentLaunchConfig


class PlanAgentCmuxWorkspaceSupportTests(unittest.TestCase):
    def test_workspace_entries_are_parsed_from_list_output(self) -> None:
        payload = """
        * workspace:1  envctl  [selected]
          workspace:2  envctl implementation
          workspace:3  supportopia
        """

        self.assertEqual(
            workspace_entries_from_list_output(payload),
            (
                ("workspace:1", "envctl"),
                ("workspace:2", "envctl implementation"),
                ("workspace:3", "supportopia"),
            ),
        )

    def test_surface_ids_parser_dedupes_and_ignores_non_numeric_surface_refs(self) -> None:
        payload = """
        pane:1
          surface:20 [terminal] "~/repo"
        pane:2
          surface:20 [terminal] "~/repo" [selected]
          surface:abc [terminal] "ignore"
          surface:21 [terminal] "feature-a-1"
        """

        self.assertEqual(surface_ids_from_list_output(payload), ("surface:20", "surface:21"))

    def test_workspace_ref_from_identify_output_prefers_caller_ref(self) -> None:
        payload = json.dumps(
            {
                "caller": {"workspace_ref": "workspace:4"},
                "focused": {"workspace_ref": "workspace:9"},
            }
        )

        self.assertEqual(workspace_ref_from_identify_output(payload), "workspace:4")

    def test_default_workspace_target_uses_current_workspace_title_and_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)

            class _Runner:
                def run(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
                    return subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:4  envctl  [selected]\n  workspace:8  envctl implementation\n",
                        stderr="",
                    )

            runtime = SimpleNamespace(
                config=SimpleNamespace(base_dir=repo),
                env={"CMUX_WORKSPACE_ID": "workspace:4"},
                process_runner=_Runner(),
            )
            launch_config = PlanAgentLaunchConfig(
                enabled=True,
                transport="cmux",
                cli="codex",
                cli_command="codex",
                preset="implementation",
                codex_cycles=1,
                codex_cycles_warning=None,
                shell="/bin/zsh",
                require_cmux_context=True,
                cmux_workspace="",
                direct_prompt_enabled=False,
                ulw_loop_prefix=True,
                ulw_suffix=True,
            )

            self.assertEqual(
                default_workspace_target(runtime, launch_config, workspace_mode="implementation"),
                ("envctl implementation", "workspace:8"),
            )


if __name__ == "__main__":
    unittest.main()
