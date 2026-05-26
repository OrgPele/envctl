import unittest

from envctl_engine.planning.plan_agent import omx_attach_support
from envctl_engine.planning.plan_agent import omx_lock_support
from envctl_engine.planning.plan_agent import omx_spawn_support
from envctl_engine.planning.plan_agent import omx_transport


class PlanAgentOmxTransportFacadeTests(unittest.TestCase):
    def test_stateless_omx_helpers_are_owner_aliases(self) -> None:
        expected_aliases = {
            "_cleanup_stale_omx_tmux_locks": omx_lock_support.cleanup_stale_omx_tmux_locks,
            "_cleanup_stale_omx_tmux_locks_under_root": omx_lock_support.cleanup_stale_omx_tmux_locks_under_root,
            "_utc_timestamp_from_epoch": omx_spawn_support.utc_timestamp_from_epoch,
            "_bounded_process_output_excerpt": omx_spawn_support.bounded_process_output_excerpt,
            "_omx_spawn_metadata_payload": omx_spawn_support.omx_spawn_metadata_payload,
            "_retained_omx_spawn_process": omx_spawn_support.retained_omx_spawn_process,
            "_retained_omx_spawn_returncode": omx_spawn_support.retained_omx_spawn_returncode,
            "_retained_omx_spawn_event_payload": omx_spawn_support.retained_omx_spawn_event_payload,
            "_deterministic_omx_root_for_worktree": omx_spawn_support.deterministic_omx_root_for_worktree,
            "_omx_spawn_failure_text": omx_spawn_support.omx_spawn_failure_text,
            "_sanitize_omx_tmux_token": omx_spawn_support.sanitize_omx_tmux_token,
            "_omx_launch_env": omx_spawn_support.omx_launch_env,
            "_retain_omx_spawn_process": omx_spawn_support.retain_omx_spawn_process,
            "_omx_session_state_path_for_root": omx_attach_support.omx_session_state_path_for_root,
            "_omx_session_state_path": omx_attach_support.omx_session_state_path,
            "_read_omx_session_payload_from_path": omx_attach_support.read_omx_session_payload_from_path,
            "_read_omx_session_payload": omx_attach_support.read_omx_session_payload,
            "_read_omx_session_payload_from_root": omx_attach_support.read_omx_session_payload_from_root,
            "_record_cwd_matches_worktree": omx_attach_support.record_cwd_matches_worktree,
            "_combined_omx_tmux_exclusions": omx_attach_support.combined_omx_tmux_exclusions,
        }

        for facade_name, owner_fn in expected_aliases.items():
            with self.subTest(facade_name=facade_name):
                self.assertIs(getattr(omx_transport, facade_name), owner_fn)
