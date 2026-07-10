# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchPromptOptionsTests(PlanAgentLaunchSupportTestCase):
    def test_resolve_plan_agent_launch_config_ulw_route_enables_direct_prompt_prefix(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                config = load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_PLAN_AGENT_DIRECT_PROMPT": "false",
                    }
                )

                launch_config = launch_support.resolve_plan_agent_launch_config(
                    config,
                    {},
                    route=parse_route(["--plan", "feature-a", "--tmux", "--opencode", "--ulw"], env={}),
                )

            self.assertTrue(launch_config.direct_prompt_enabled)
            self.assertTrue(launch_config.ulw_loop_prefix)

    def test_resolve_plan_agent_launch_config_no_ulw_loop_route_disables_default_prefix(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                prompt_path = Path(tmpdir) / ".config" / "opencode" / "commands" / "implement_task.md"
                repo.mkdir(parents=True, exist_ok=True)
                prompt_path.parent.mkdir(parents=True, exist_ok=True)
                prompt_path.write_text("Implement this directly.\n", encoding="utf-8")
                config = load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                    }
                )
                launch_config = launch_support.resolve_plan_agent_launch_config(
                    config,
                    {"HOME": tmpdir},
                    route=parse_route(["--plan", "feature-a", "--cmux", "--opencode", "--no-ulw-loop"], env={}),
                )
                rt = self._runtime(repo, runtime, env={"HOME": tmpdir})

                prompt_text, error = workflow_prompt_support._resolve_preset_submission_text(
                    rt,
                    launch_config=launch_config,
                    cli="opencode",
                    preset="implement_task",
                )

            self.assertEqual(launch_config.transport, "cmux")
            self.assertTrue(launch_config.direct_prompt_enabled)
            self.assertFalse(launch_config.ulw_loop_prefix)
            self.assertIsNone(error)
            self.assertEqual(prompt_text, "Implement this directly.\n")

    def test_resolve_plan_agent_launch_config_goal_defaults_and_route_overrides(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime)})

                codex_default = launch_support.resolve_plan_agent_launch_config(
                    config, {}, route=parse_route(["--plan", "feature-a", "--tmux"], env={})
                )
                opencode_default = launch_support.resolve_plan_agent_launch_config(
                    config, {}, route=parse_route(["--plan", "feature-a", "--tmux", "--opencode"], env={})
                )
                disabled = launch_support.resolve_plan_agent_launch_config(
                    config, {}, route=parse_route(["--plan", "feature-a", "--tmux", "--no-goal", "--goal"], env={})
                )
                enabled_by_route = launch_support.resolve_plan_agent_launch_config(
                    load_config({
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_PLAN_AGENT_CODEX_GOAL_ENABLE": "false",
                    }),
                    {},
                    route=parse_route(["--plan", "feature-a", "--tmux", "--goal"], env={}),
                )

            self.assertTrue(codex_default.codex_goal_enable)
            self.assertFalse(opencode_default.codex_goal_enable)
            self.assertFalse(disabled.codex_goal_enable)
            self.assertTrue(enabled_by_route.codex_goal_enable)

    def test_resolve_plan_agent_launch_config_allows_pr_review_comment_followup_toggle(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                (repo / ".envctl").write_text(
                    "ENVCTL_PLAN_AGENT_PR_REVIEW_COMMENTS_ENABLE=true\n",
                    encoding="utf-8",
                )
                config = load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                    }
                )

                launch_config = launch_support.resolve_plan_agent_launch_config(
                    config,
                    {},
                    route=parse_route(["--plan", "features/example", "--omx", "--ralph"], env={}),
                )
                workflow = _build_plan_agent_workflow(
                    cli=launch_config.cli,
                    preset=launch_config.preset,
                    codex_cycles=launch_config.codex_cycles,
                    direct_prompt_enabled=launch_config.direct_prompt_enabled,
                    pr_review_comments_followup_enable=launch_config.pr_review_comments_followup_enable,
                )

            self.assertTrue(launch_config.pr_review_comments_followup_enable)
            self.assertIn(_pr_review_comments_instruction_text(), [step.text for step in workflow.steps])
            self.assertNotIn(_browser_e2e_instruction_text(), [step.text for step in workflow.steps])

    def test_resolve_plan_agent_launch_config_disables_browser_e2e_followup_by_default(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                config = load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                    }
                )

                launch_config = launch_support.resolve_plan_agent_launch_config(
                    config,
                    {},
                    route=parse_route(["--plan", "features/example"], env={}),
                )
                workflow = _build_plan_agent_workflow(
                    cli=launch_config.cli,
                    preset=launch_config.preset,
                    codex_cycles=launch_config.codex_cycles,
                    direct_prompt_enabled=launch_config.direct_prompt_enabled,
                    browser_e2e_followup_enable=launch_config.browser_e2e_followup_enable,
                    pr_review_comments_followup_enable=launch_config.pr_review_comments_followup_enable,
                )

            self.assertFalse(launch_config.browser_e2e_followup_enable)
            self.assertNotIn(_browser_e2e_instruction_text(), [step.text for step in workflow.steps])
            self.assertNotIn(_pr_review_comments_instruction_text(), [step.text for step in workflow.steps])

    def test_resolve_plan_agent_launch_config_allows_browser_e2e_followup_opt_in(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                (repo / ".envctl").write_text(
                    "ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE=true\n",
                    encoding="utf-8",
                )
                config = load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                    }
                )

                launch_config = launch_support.resolve_plan_agent_launch_config(
                    config,
                    {},
                    route=parse_route(["--plan", "features/example"], env={}),
                )
                workflow = _build_plan_agent_workflow(
                    cli=launch_config.cli,
                    preset=launch_config.preset,
                    codex_cycles=launch_config.codex_cycles,
                    direct_prompt_enabled=launch_config.direct_prompt_enabled,
                    browser_e2e_followup_enable=launch_config.browser_e2e_followup_enable,
                    pr_review_comments_followup_enable=launch_config.pr_review_comments_followup_enable,
                )

            self.assertTrue(launch_config.browser_e2e_followup_enable)
            self.assertIn(_browser_e2e_instruction_text(), [step.text for step in workflow.steps])
            self.assertNotIn(_pr_review_comments_instruction_text(), [step.text for step in workflow.steps])

    def test_fullstack_pr_url_e2e_policy_auto_enables_browser_followup_for_frontend_backend_app(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                (repo / ".envctl").write_text(
                    "ENVCTL_PLAN_AGENT_FULLSTACK_PR_URL_E2E_ENABLE=true\n",
                    encoding="utf-8",
                )
                config = load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                    }
                )

                launch_config = launch_support.resolve_plan_agent_launch_config(
                    config,
                    {},
                    route=parse_route(["--plan", "features/example", "--tmux", "--entire-system"], env={}),
                )
                workflow = _build_plan_agent_workflow(
                    cli=launch_config.cli,
                    preset=launch_config.preset,
                    codex_cycles=launch_config.codex_cycles,
                    direct_prompt_enabled=launch_config.direct_prompt_enabled,
                    browser_e2e_followup_enable=launch_config.browser_e2e_followup_enable,
                    pr_review_comments_followup_enable=launch_config.pr_review_comments_followup_enable,
                )

            self.assertTrue(launch_config.fullstack_pr_url_e2e_enable)
            self.assertTrue(launch_config.fullstack_pr_url_e2e_active)
            self.assertIsNone(launch_config.fullstack_pr_url_e2e_reason)
            self.assertTrue(launch_config.browser_e2e_followup_enable)
            self.assertIn(_browser_e2e_instruction_text(), [step.text for step in workflow.steps])

    def test_fullstack_pr_url_e2e_policy_fields_are_visible_in_launch_inspection(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                rt = self._runtime(
                    repo,
                    runtime,
                    env={"ENVCTL_PLAN_AGENT_FULLSTACK_PR_URL_E2E_ENABLE": "true"},
                )

                payload = launch_support.inspect_plan_agent_launch(
                    rt,
                    route=parse_route(["--plan", "features/example", "--tmux", "--entire-system"], env={}),
                )

            self.assertTrue(payload["fullstack_pr_url_e2e_enable"])
            self.assertTrue(payload["fullstack_pr_url_e2e_active"])
            self.assertIsNone(payload["fullstack_pr_url_e2e_reason"])
            self.assertTrue(payload["browser_e2e_followup_enable"])

    def test_fullstack_pr_url_e2e_policy_inactive_for_backend_only_scope(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                (repo / ".envctl").write_text(
                    "ENVCTL_PLAN_AGENT_FULLSTACK_PR_URL_E2E_ENABLE=true\n",
                    encoding="utf-8",
                )
                config = load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                    }
                )

                launch_config = launch_support.resolve_plan_agent_launch_config(
                    config,
                    {},
                    route=parse_route(["--plan", "features/example", "--tmux", "--backend"], env={}),
                )

            self.assertTrue(launch_config.fullstack_pr_url_e2e_enable)
            self.assertFalse(launch_config.fullstack_pr_url_e2e_active)
            self.assertEqual(launch_config.fullstack_pr_url_e2e_reason, "runtime_scope_backend")
            self.assertFalse(launch_config.browser_e2e_followup_enable)

    def test_fullstack_pr_url_e2e_policy_inactive_for_backend_only_config(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                (repo / ".envctl").write_text(
                    "ENVCTL_PLAN_AGENT_FULLSTACK_PR_URL_E2E_ENABLE=true\n"
                    "TREES_FRONTEND_ENABLE=false\n",
                    encoding="utf-8",
                )
                config = load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                    }
                )

                launch_config = launch_support.resolve_plan_agent_launch_config(
                    config,
                    {},
                    route=parse_route(["--plan", "features/example", "--tmux", "--entire-system"], env={}),
                )

            self.assertTrue(launch_config.fullstack_pr_url_e2e_enable)
            self.assertFalse(launch_config.fullstack_pr_url_e2e_active)
            self.assertEqual(launch_config.fullstack_pr_url_e2e_reason, "trees_frontend_disabled")
            self.assertFalse(launch_config.browser_e2e_followup_enable)

    def test_browser_e2e_explicit_opt_in_still_works_without_fullstack_policy(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                (repo / ".envctl").write_text(
                    "ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE=true\n",
                    encoding="utf-8",
                )
                config = load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                    }
                )

                launch_config = launch_support.resolve_plan_agent_launch_config(
                    config,
                    {},
                    route=parse_route(["--plan", "features/example", "--tmux", "--backend"], env={}),
                )

            self.assertFalse(launch_config.fullstack_pr_url_e2e_enable)
            self.assertFalse(launch_config.fullstack_pr_url_e2e_active)
            self.assertEqual(launch_config.fullstack_pr_url_e2e_reason, "disabled")
            self.assertTrue(launch_config.browser_e2e_followup_enable)

    def test_fullstack_pr_url_e2e_policy_keeps_opencode_single_prompt_unaffected(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                (repo / ".envctl").write_text(
                    "ENVCTL_PLAN_AGENT_FULLSTACK_PR_URL_E2E_ENABLE=true\n",
                    encoding="utf-8",
                )
                config = load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                    }
                )

                launch_config = launch_support.resolve_plan_agent_launch_config(
                    config,
                    {},
                    route=parse_route(["--plan", "features/example", "--tmux", "--opencode", "--entire-system"], env={}),
                )
                workflow = _build_plan_agent_workflow(
                    cli=launch_config.cli,
                    preset=launch_config.preset,
                    codex_cycles=launch_config.codex_cycles,
                    direct_prompt_enabled=launch_config.direct_prompt_enabled,
                    browser_e2e_followup_enable=launch_config.browser_e2e_followup_enable,
                )

            self.assertEqual(launch_config.cli, "opencode")
            self.assertTrue(launch_config.fullstack_pr_url_e2e_enable)
            self.assertFalse(launch_config.fullstack_pr_url_e2e_active)
            self.assertEqual(launch_config.fullstack_pr_url_e2e_reason, "unsupported_cli")
            self.assertFalse(launch_config.browser_e2e_followup_enable)
            self.assertEqual([(step.kind, step.text) for step in workflow.steps], [("submit_direct_prompt", "implement_task")])

    def test_resolve_plan_agent_launch_config_parses_direct_prompt_and_ulw_flags(self) -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                repo = Path(tmpdir) / "repo"
                runtime = Path(tmpdir) / "runtime"
                repo.mkdir(parents=True, exist_ok=True)
                config = load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_PLAN_AGENT_DIRECT_PROMPT": "true",
                        "ENVCTL_PLAN_AGENT_ULW_LOOP_PREFIX": "true",
                        "ENVCTL_PLAN_AGENT_APPEND_ULW": "true",
                    }
                )

                launch_config = launch_support.resolve_plan_agent_launch_config(config, {})

            self.assertTrue(launch_config.direct_prompt_enabled)
            self.assertTrue(launch_config.ulw_loop_prefix)
            self.assertTrue(launch_config.ulw_suffix)
