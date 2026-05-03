## 2026-05-03 - Plan-agent queued follow-up context hardening

### Scope
Fixed plan-agent Codex/OMX prompt context and queued follow-up submission for generated implementation sessions.

### Key behavior changes
- Initial `implement_task` prompts and browser E2E follow-up prompts now only inject saved runtime addresses that match the target worktree, avoiding stale localhost addresses from another tree.
- Browser E2E follow-up prompts still include the original plan and seeded `MAIN_TASK.md` paths for the target worktree.
- Codex queued follow-up prompts are pasted via the same tmux/surface paste path as direct prompt bodies and queued without requiring a full text echo match, making `$browser-use` and PR review follow-ups more reliable for long multi-line messages.

### Verification
- `pytest tests/python/planning/test_plan_agent_launch_support.py::PlanAgentLaunchSupportTests::test_worktree_prompt_does_not_inject_runtime_addresses_from_other_worktree tests/python/planning/test_plan_agent_launch_support.py::PlanAgentLaunchSupportTests::test_browser_e2e_followup_omits_stale_runtime_addresses_for_other_worktree tests/python/planning/test_plan_agent_launch_support.py::PlanAgentLaunchSupportTests::test_browser_e2e_followup_injects_matching_worktree_runtime_addresses -q` -> passed
- `pytest tests/python/planning/test_plan_agent_launch_support.py::PlanAgentLaunchSupportTests::test_tmux_codex_cycles_queue_remaining_workflow_steps tests/python/planning/test_plan_agent_launch_support.py::PlanAgentLaunchSupportTests::test_codex_cycle_queue_types_message_before_waiting_for_tab_ready -q` -> passed
