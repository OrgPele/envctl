from __future__ import annotations

from pathlib import Path
import unittest

from envctl_engine.planning.plan_agent.models import PlanAgentLaunchConfig, _WorkspaceLaunchTarget
from envctl_engine.planning.plan_agent import cmux_review_launch_support


def _launch_config(
    *,
    transport: str = "cmux",
    cli: str = "codex",
    cmux_workspace: str = "",
) -> PlanAgentLaunchConfig:
    return PlanAgentLaunchConfig(
        enabled=True,
        transport=transport,  # type: ignore[arg-type]
        cli=cli,
        cli_command=cli,
        preset="default",
        codex_cycles=1,
        codex_cycles_warning=None,
        shell="zsh",
        require_cmux_context=False,
        cmux_workspace=cmux_workspace,
        direct_prompt_enabled=False,
        ulw_loop_prefix=True,
        ulw_suffix=True,
    )


class _Runtime:
    def __init__(self) -> None:
        self.config = object()
        self.env: dict[str, str] = {}
        self.events: list[tuple[str, dict[str, object]]] = []

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append((event, payload))


class PlanAgentCmuxReviewLaunchSupportTests(unittest.TestCase):
    def test_resolve_review_agent_launch_readiness_rejects_superset(self) -> None:
        readiness = cmux_review_launch_support.resolve_review_agent_launch_readiness(
            runtime=_Runtime(),
            resolve_launch_config_fn=lambda *_args, **_kwargs: _launch_config(transport="superset"),
            missing_launch_commands_fn=lambda *_args, **_kwargs: (),
            default_target_workspace_title_fn=lambda *_args, **_kwargs: "",
            missing_required_cmux_context_fn=lambda *_args, **_kwargs: False,
        )

        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.reason, "unsupported_superset_review_tab")
        self.assertEqual(readiness.cli, "codex")

    def test_resolve_review_agent_launch_readiness_reports_missing_commands(self) -> None:
        readiness = cmux_review_launch_support.resolve_review_agent_launch_readiness(
            runtime=_Runtime(),
            resolve_launch_config_fn=lambda *_args, **_kwargs: _launch_config(cli="opencode"),
            missing_launch_commands_fn=lambda *_args, **_kwargs: ("cmux", "opencode"),
            default_target_workspace_title_fn=lambda *_args, **_kwargs: "",
            missing_required_cmux_context_fn=lambda *_args, **_kwargs: False,
        )

        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.reason, "missing_executables")
        self.assertEqual(readiness.cli, "opencode")
        self.assertEqual(readiness.missing, ("cmux", "opencode"))

    def test_resolve_review_agent_launch_readiness_accepts_configured_or_default_workspace(self) -> None:
        configured = cmux_review_launch_support.resolve_review_agent_launch_readiness(
            runtime=_Runtime(),
            resolve_launch_config_fn=lambda *_args, **_kwargs: _launch_config(cmux_workspace="workspace-1"),
            missing_launch_commands_fn=lambda *_args, **_kwargs: (),
            default_target_workspace_title_fn=lambda *_args, **_kwargs: "",
            missing_required_cmux_context_fn=lambda *_args, **_kwargs: True,
        )
        defaulted = cmux_review_launch_support.resolve_review_agent_launch_readiness(
            runtime=_Runtime(),
            resolve_launch_config_fn=lambda *_args, **_kwargs: _launch_config(),
            missing_launch_commands_fn=lambda *_args, **_kwargs: (),
            default_target_workspace_title_fn=lambda _runtime, _launch_config, *, workspace_mode: (
                "reviews" if workspace_mode == "reviews" else ""
            ),
            missing_required_cmux_context_fn=lambda *_args, **_kwargs: True,
        )

        self.assertTrue(configured.ready)
        self.assertEqual(configured.reason, "ready")
        self.assertTrue(defaulted.ready)
        self.assertEqual(defaulted.reason, "ready")

    def test_resolve_review_agent_launch_readiness_distinguishes_context_and_workspace_failures(self) -> None:
        missing_context = cmux_review_launch_support.resolve_review_agent_launch_readiness(
            runtime=_Runtime(),
            resolve_launch_config_fn=lambda *_args, **_kwargs: _launch_config(),
            missing_launch_commands_fn=lambda *_args, **_kwargs: (),
            default_target_workspace_title_fn=lambda *_args, **_kwargs: "",
            missing_required_cmux_context_fn=lambda *_args, **_kwargs: True,
        )
        unavailable = cmux_review_launch_support.resolve_review_agent_launch_readiness(
            runtime=_Runtime(),
            resolve_launch_config_fn=lambda *_args, **_kwargs: _launch_config(),
            missing_launch_commands_fn=lambda *_args, **_kwargs: (),
            default_target_workspace_title_fn=lambda *_args, **_kwargs: "",
            missing_required_cmux_context_fn=lambda *_args, **_kwargs: False,
        )

        self.assertEqual(missing_context.reason, "missing_cmux_context")
        self.assertEqual(unavailable.reason, "workspace_unavailable")

    def test_launch_review_agent_terminal_reports_workspace_unavailable(self) -> None:
        runtime = _Runtime()

        result = cmux_review_launch_support.launch_cmux_review_agent_terminal(
            runtime,
            repo_root=Path("/repo"),
            project_name="feature-a-1",
            project_root=Path("/repo/trees/feature-a/1"),
            review_bundle_path=None,
            resolve_launch_config_fn=lambda *_args, **_kwargs: _launch_config(),
            missing_launch_commands_fn=lambda *_args, **_kwargs: (),
            ensure_workspace_id_fn=lambda *_args, **_kwargs: None,
            missing_required_cmux_context_fn=lambda *_args, **_kwargs: False,
            create_surface_fn=lambda *_args, **_kwargs: ("surface-1", None),
            start_background_review_surface_bootstrap_fn=lambda *_args, **_kwargs: None,
            print_launch_summary_fn=lambda _message: None,
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "workspace_unavailable")
        self.assertEqual(runtime.events[0][0], "dashboard.review_tab.failed")
        self.assertEqual(runtime.events[0][1]["reason"], "workspace_unavailable")

    def test_launch_review_agent_terminal_reports_surface_create_failure(self) -> None:
        runtime = _Runtime()

        result = cmux_review_launch_support.launch_cmux_review_agent_terminal(
            runtime,
            repo_root=Path("/repo"),
            project_name="feature-a-1",
            project_root=Path("/repo/trees/feature-a/1"),
            review_bundle_path=None,
            resolve_launch_config_fn=lambda *_args, **_kwargs: _launch_config(),
            missing_launch_commands_fn=lambda *_args, **_kwargs: (),
            ensure_workspace_id_fn=lambda *_args, **_kwargs: _WorkspaceLaunchTarget(workspace_id="workspace-1", created=False),
            missing_required_cmux_context_fn=lambda *_args, **_kwargs: False,
            create_surface_fn=lambda *_args, **_kwargs: (None, "create failed"),
            start_background_review_surface_bootstrap_fn=lambda *_args, **_kwargs: None,
            print_launch_summary_fn=lambda _message: None,
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "create failed")
        self.assertEqual(runtime.events[0][1]["reason"], "surface_create_failed")
        self.assertEqual(runtime.events[0][1]["workspace_id"], "workspace-1")

    def test_launch_review_agent_terminal_starts_bootstrap_and_prints_summary(self) -> None:
        runtime = _Runtime()
        bootstrap_calls: list[dict[str, object]] = []
        summaries: list[str] = []

        result = cmux_review_launch_support.launch_cmux_review_agent_terminal(
            runtime,
            repo_root=Path("/repo"),
            project_name="feature-a-1",
            project_root=Path("/repo/trees/feature-a/1"),
            review_bundle_path=Path("/repo/review.json"),
            resolve_launch_config_fn=lambda *_args, **_kwargs: _launch_config(cli="opencode"),
            missing_launch_commands_fn=lambda *_args, **_kwargs: (),
            ensure_workspace_id_fn=lambda *_args, **_kwargs: _WorkspaceLaunchTarget(workspace_id="workspace-1", created=False),
            missing_required_cmux_context_fn=lambda *_args, **_kwargs: False,
            create_surface_fn=lambda *_args, **_kwargs: ("surface-1", None),
            start_background_review_surface_bootstrap_fn=lambda *_runtime, **kwargs: bootstrap_calls.append(kwargs),
            print_launch_summary_fn=summaries.append,
        )

        self.assertEqual(result.status, "launched")
        self.assertEqual(result.reason, "launched")
        self.assertEqual(result.surface_id, "surface-1")
        self.assertEqual(
            [event for event, _payload in runtime.events],
            ["dashboard.review_tab.surface_created", "dashboard.review_tab.launched"],
        )
        self.assertEqual(bootstrap_calls[0]["surface_id"], "surface-1")
        self.assertEqual(bootstrap_calls[0]["review_bundle_path"], Path("/repo/review.json"))
        self.assertEqual(summaries, ["Opened origin review tab for feature-a-1."])


if __name__ == "__main__":
    unittest.main()
