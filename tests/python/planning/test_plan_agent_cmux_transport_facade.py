import unittest

from envctl_engine.planning.plan_agent import cmux_surface_support
from envctl_engine.planning.plan_agent import cmux_transport
from envctl_engine.planning.plan_agent import cmux_workspace_support


class PlanAgentCmuxTransportFacadeTests(unittest.TestCase):
    def test_stateless_cmux_helpers_are_owner_aliases(self) -> None:
        expected_aliases = {
            "_surface_id_from_output": cmux_workspace_support.surface_id_from_output,
            "_default_target_workspace_title": cmux_workspace_support.default_target_workspace_title,
            "_default_workspace_target": cmux_workspace_support.default_workspace_target,
            "_missing_required_cmux_context": cmux_workspace_support.missing_required_cmux_context,
            "_current_workspace_title": cmux_workspace_support.current_workspace_title,
            "_current_workspace_ref": cmux_workspace_support.current_workspace_ref,
            "_identify_workspace_ref": cmux_workspace_support.identify_workspace_ref,
            "_workspace_ref_from_identify_output": cmux_workspace_support.workspace_ref_from_identify_output,
            "_resolve_configured_workspace_id": cmux_workspace_support.resolve_configured_workspace_id,
            "_ensure_configured_workspace_id": cmux_workspace_support.ensure_configured_workspace_id,
            "_looks_like_workspace_handle": cmux_workspace_support.looks_like_workspace_handle,
            "_resolve_workspace_ref_by_title": cmux_workspace_support.resolve_workspace_ref_by_title,
            "_list_workspaces": cmux_workspace_support.list_workspaces,
            "_workspace_entries_from_list_output": cmux_workspace_support.workspace_entries_from_list_output,
            "_surface_ids_from_list_output": cmux_workspace_support.surface_ids_from_list_output,
            "_list_workspace_surfaces": cmux_workspace_support.list_workspace_surfaces,
            "_starter_surface_for_new_workspace": cmux_workspace_support.starter_surface_for_new_workspace,
            "_create_named_workspace": cmux_workspace_support.create_named_workspace,
            "_workspace_ref_from_command_output": cmux_workspace_support.workspace_ref_from_command_output,
            "_create_surface": cmux_surface_support.create_surface,
            "_send_surface_text": cmux_surface_support.send_surface_text,
            "_paste_surface_text": cmux_surface_support.paste_surface_text,
            "_send_prompt_text": cmux_surface_support.send_prompt_text,
            "_send_surface_key": cmux_surface_support.send_surface_key,
            "_run_cmux_command": cmux_surface_support.run_cmux_command,
            "_completed_process_error_text": cmux_surface_support.completed_process_error_text,
            "_read_surface_screen": cmux_surface_support.read_surface_screen,
            "_wait_for_prompt_submit_ready": cmux_surface_support.wait_for_prompt_submit_ready,
            "_wait_for_prompt_picker_ready": cmux_surface_support.wait_for_prompt_picker_ready,
            "_prepare_surface": cmux_surface_support.prepare_surface,
        }

        for facade_name, owner_fn in expected_aliases.items():
            with self.subTest(facade_name=facade_name):
                self.assertIs(getattr(cmux_transport, facade_name), owner_fn)

