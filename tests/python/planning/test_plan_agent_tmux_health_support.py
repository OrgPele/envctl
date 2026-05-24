from __future__ import annotations

from types import SimpleNamespace
import unittest

from envctl_engine.planning.plan_agent import tmux_health_support


class PlanAgentTmuxHealthSupportTests(unittest.TestCase):
    def test_existing_tmux_session_health_skips_unknown_cli(self) -> None:
        read_calls: list[str] = []

        result = tmux_health_support.existing_tmux_session_health(
            runtime=object(),
            session_name="envctl-feature",
            window_name="feature-a-1",
            cli="vim",
            read_tmux_screen_fn=lambda *_args, **_kwargs: read_calls.append("read") or "",
            screen_looks_ready_fn=lambda *_args, **_kwargs: False,
            screen_looks_active_fn=lambda *_args, **_kwargs: False,
            screen_excerpt_fn=lambda screen: str(screen),
        )

        self.assertTrue(result.ready)
        self.assertEqual(result.reason, "health_check_not_required")
        self.assertEqual(read_calls, [])

    def test_existing_tmux_session_health_reports_empty_codex_session(self) -> None:
        result = tmux_health_support.existing_tmux_session_health(
            runtime=object(),
            session_name="envctl-feature",
            window_name="feature-a-1",
            cli=" Codex ",
            read_tmux_screen_fn=lambda *_args, **_kwargs: "  \n",
            screen_looks_ready_fn=lambda *_args, **_kwargs: False,
            screen_looks_active_fn=lambda *_args, **_kwargs: False,
            screen_excerpt_fn=lambda screen: str(screen).strip(),
        )

        self.assertFalse(result.ready)
        self.assertEqual(result.reason, "existing_codex_session_empty")
        self.assertEqual(result.screen_excerpt, "")

    def test_existing_tmux_session_health_accepts_ready_or_active_screen(self) -> None:
        ready = tmux_health_support.existing_tmux_session_health(
            runtime=object(),
            session_name="envctl-feature",
            window_name="feature-a-1",
            cli="opencode",
            read_tmux_screen_fn=lambda *_args, **_kwargs: "ready prompt",
            screen_looks_ready_fn=lambda cli, screen: cli == "opencode" and "ready" in screen,
            screen_looks_active_fn=lambda *_args, **_kwargs: False,
            screen_excerpt_fn=lambda screen: f"excerpt:{screen}",
        )
        active = tmux_health_support.existing_tmux_session_health(
            runtime=object(),
            session_name="envctl-feature",
            window_name="feature-a-1",
            cli="opencode",
            read_tmux_screen_fn=lambda *_args, **_kwargs: "working",
            screen_looks_ready_fn=lambda *_args, **_kwargs: False,
            screen_looks_active_fn=lambda cli, screen: cli == "opencode" and "working" in screen,
            screen_excerpt_fn=lambda screen: f"excerpt:{screen}",
        )

        self.assertTrue(ready.ready)
        self.assertEqual(ready.reason, "healthy")
        self.assertEqual(ready.screen_excerpt, "excerpt:ready prompt")
        self.assertTrue(active.ready)
        self.assertEqual(active.reason, "healthy")
        self.assertEqual(active.screen_excerpt, "excerpt:working")

    def test_existing_tmux_session_health_reports_unhealthy_supported_session(self) -> None:
        result = tmux_health_support.existing_tmux_session_health(
            runtime=SimpleNamespace(),
            session_name="envctl-feature",
            window_name="feature-a-1",
            cli="codex",
            read_tmux_screen_fn=lambda *_args, **_kwargs: "login required",
            screen_looks_ready_fn=lambda *_args, **_kwargs: False,
            screen_looks_active_fn=lambda *_args, **_kwargs: False,
            screen_excerpt_fn=lambda screen: f"short:{screen}",
        )

        self.assertFalse(result.ready)
        self.assertEqual(result.reason, "existing_codex_session_unhealthy")
        self.assertEqual(result.screen_excerpt, "short:login required")

    def test_existing_tmux_session_looks_healthy_uses_health_result(self) -> None:
        self.assertTrue(
            tmux_health_support.existing_tmux_session_looks_healthy(
                runtime=object(),
                session_name="envctl-feature",
                window_name="feature-a-1",
                cli="codex",
                existing_session_health_fn=lambda *_args, **_kwargs: SimpleNamespace(ready=True),
            )
        )


if __name__ == "__main__":
    unittest.main()
