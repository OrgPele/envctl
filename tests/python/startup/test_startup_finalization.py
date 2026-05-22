from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from envctl_engine.runtime.command_router import parse_route
from envctl_engine.startup.finalization import failure_context_label, render_final_failure_status
from envctl_engine.startup.session import StartupSession


def _session(*, contexts: list[object], contexts_to_start: list[object] | None = None) -> StartupSession:
    route = parse_route(["start"], env={})
    return StartupSession(
        requested_route=route,
        effective_route=route,
        requested_command="start",
        runtime_mode="trees",
        run_id="run-finalization",
        selected_contexts=contexts,
        contexts_to_start=list(contexts_to_start or []),
    )


class StartupFinalizationTests(unittest.TestCase):
    def test_failure_context_label_prefers_named_context_from_error(self) -> None:
        alpha = SimpleNamespace(name="alpha", root=Path("/repo/trees/alpha/1"))
        beta = SimpleNamespace(name="beta", root=Path("/repo/beta"))
        session = _session(contexts=[alpha, beta])

        label = failure_context_label(session, "Startup failed: beta backend missing")

        self.assertEqual(label, "project: beta")

    def test_failure_context_label_uses_single_worktree_context_when_error_is_generic(self) -> None:
        context = SimpleNamespace(name="feature-a-1", root=Path("/repo/trees/feature-a/1"))
        session = _session(contexts=[context])

        label = failure_context_label(session, "Startup failed: no free port found")

        self.assertEqual(label, "worktree: feature-a-1")

    def test_render_final_failure_status_adds_context_once(self) -> None:
        context = SimpleNamespace(name="feature-a-1", root=Path("/repo/trees/feature-a/1"))
        session = _session(contexts=[context])
        runtime = SimpleNamespace(env={})

        rendered = render_final_failure_status(
            runtime,
            session,
            "Startup failed: missing command",
            interactive_tty=False,
        )

        self.assertEqual(rendered, "✗ Startup failed: missing command (worktree: feature-a-1)")


if __name__ == "__main__":
    unittest.main()
