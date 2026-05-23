# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.planning_worktree_setup_test_support import *


class PlanningWorktreeSetupFreshAiSpinnerTests(PlanningWorktreeSetupTestCase):
    def test_fresh_ai_worktree_is_not_scaled_down_while_session_marker_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")
            for iteration in ("1", "2", "3"):
                worktree = repo / "trees" / "implementations_task" / iteration
                worktree.mkdir(parents=True, exist_ok=True)
                (worktree / ".git").write_text(f"gitdir: /tmp/worktree-{iteration}\n", encoding="utf-8")
            protected = repo / "trees" / "implementations_task" / "3"
            (protected / ".envctl-state").mkdir(parents=True, exist_ok=True)
            (protected / ".envctl-state" / "worktree-provenance.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "plan_file": "implementations/task.md",
                        "created_for_fresh_ai_launch": True,
                        "fresh_ai_launch_status": "launching",
                        "launch_transport": "omx",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            engine = self._runtime(repo, runtime)
            events: list[dict[str, object]] = []
            engine._emit = lambda event, **payload: events.append({"event": event, **payload})  # type: ignore[method-assign]
            raw_projects = [(ctx.name, ctx.root) for ctx in engine._discover_projects(mode="trees")]  # noqa: SLF001

            def fake_delete_worktree_path(**kwargs):  # noqa: ANN001
                shutil.rmtree(Path(kwargs["worktree_root"]))

                class _Result:
                    success = True
                    message = ""

                return _Result()

            with patch("envctl_engine.planning.worktree_domain.delete_worktree_path", side_effect=fake_delete_worktree_path):
                result = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                    plan_counts={"implementations/task.md": 1},
                    raw_projects=raw_projects,
                    keep_plan=True,
                )

            self.assertIsNone(result.error)
            self.assertTrue(protected.is_dir())
            self.assertTrue(
                any(
                    event.get("event") == "planning.worktree.cleanup.skipped_active_ai_session"
                    and event.get("worktree") == "implementations_task-3"
                    for event in events
                )
            )

    def test_stale_fresh_ai_worktree_can_be_scaled_down_after_session_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")
            for iteration in ("1", "2"):
                worktree = repo / "trees" / "implementations_task" / iteration
                worktree.mkdir(parents=True, exist_ok=True)
                (worktree / ".git").write_text(f"gitdir: /tmp/worktree-{iteration}\n", encoding="utf-8")
            stale = repo / "trees" / "implementations_task" / "2"
            (stale / ".envctl-state").mkdir(parents=True, exist_ok=True)
            (stale / ".envctl-state" / "worktree-provenance.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "plan_file": "implementations/task.md",
                        "created_for_fresh_ai_launch": True,
                        "fresh_ai_launch_status": "launched",
                        "launch_transport": "omx",
                        "session_name": "omx-missing-session",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            engine = self._runtime(repo, runtime)
            raw_projects = [(ctx.name, ctx.root) for ctx in engine._discover_projects(mode="trees")]  # noqa: SLF001

            def fake_delete_worktree_path(**kwargs):  # noqa: ANN001
                shutil.rmtree(Path(kwargs["worktree_root"]))

                class _Result:
                    success = True
                    message = ""

                return _Result()

            with patch("envctl_engine.planning.worktree_domain.delete_worktree_path", side_effect=fake_delete_worktree_path):
                result = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                    plan_counts={"implementations/task.md": 1},
                    raw_projects=raw_projects,
                    keep_plan=True,
                )

            self.assertIsNone(result.error)
            self.assertFalse(stale.exists())

    def test_setup_worktrees_emits_spinner_policy_and_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime, env={"ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true"})
            events: list[dict[str, object]] = []

            def capture_emit(event: str, **payload: object) -> None:
                entry = {"event": event}
                entry.update(payload)
                events.append(entry)

            engine._emit = capture_emit  # type: ignore[method-assign]
            contexts = engine._discover_projects(mode="main")
            route = parse_route(["--setup-worktrees", "feature-a", "1"], env={})
            spinner_calls: list[tuple[str, bool]] = []

            @contextmanager
            def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
                _ = start_immediately
                spinner_calls.append((message, enabled))

                class _SpinnerStub:
                    def start(self) -> None:
                        return None

                    def update(self, _message: str) -> None:
                        return None

                    def succeed(self, _message: str) -> None:
                        return None

                    def fail(self, _message: str) -> None:
                        return None

                yield _SpinnerStub()

            with (
                patch("envctl_engine.planning.worktree_setup_coordinator.spinner", side_effect=fake_spinner),
                patch(
                    "envctl_engine.planning.worktree_setup_coordinator.resolve_spinner_policy",
                    return_value=SpinnerPolicy(
                        mode="auto",
                        enabled=True,
                        reason="",
                        backend="rich",
                        min_ms=0,
                        verbose_events=False,
                    ),
                ),
            ):
                selected = engine._apply_setup_worktree_selection(route, contexts)  # noqa: SLF001

            self.assertTrue(selected)
            self.assertEqual(spinner_calls, [("Setting up worktrees...", True)])
            self.assertTrue(any(item.get("event") == "ui.spinner.policy" for item in events))
            lifecycle = [item for item in events if item.get("event") == "ui.spinner.lifecycle"]
            self.assertTrue(any(item.get("state") == "start" for item in lifecycle))
            self.assertTrue(any(item.get("state") == "success" for item in lifecycle))
            self.assertTrue(any(item.get("state") == "stop" for item in lifecycle))

    def test_sync_plan_worktrees_emits_spinner_policy_and_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = self._runtime(repo, runtime, env={"ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true"})
            events: list[dict[str, object]] = []

            def capture_emit(event: str, **payload: object) -> None:
                entry = {"event": event}
                entry.update(payload)
                events.append(entry)

            engine._emit = capture_emit  # type: ignore[method-assign]
            spinner_calls: list[tuple[str, bool]] = []

            @contextmanager
            def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
                _ = start_immediately
                spinner_calls.append((message, enabled))

                class _SpinnerStub:
                    def start(self) -> None:
                        return None

                    def update(self, _message: str) -> None:
                        return None

                    def succeed(self, _message: str) -> None:
                        return None

                    def fail(self, _message: str) -> None:
                        return None

                yield _SpinnerStub()

            with (
                patch("envctl_engine.planning.worktree_sync_orchestration.spinner", side_effect=fake_spinner),
                patch(
                    "envctl_engine.planning.worktree_sync_orchestration.resolve_spinner_policy",
                    return_value=SpinnerPolicy(
                        mode="auto",
                        enabled=True,
                        reason="",
                        backend="rich",
                        min_ms=0,
                        verbose_events=False,
                    ),
                ),
            ):
                synced, error = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                    plan_counts={"implementations/task.md": 2},
                    raw_projects=[],
                    keep_plan=True,
                )

            self.assertIsNone(error)
            self.assertEqual(len(synced), 2)
            self.assertEqual(spinner_calls, [("Syncing planning worktrees...", True)])
            self.assertTrue(any(item.get("event") == "ui.spinner.policy" for item in events))
            lifecycle = [item for item in events if item.get("event") == "ui.spinner.lifecycle"]
            self.assertTrue(any(item.get("state") == "start" for item in lifecycle))
            self.assertTrue(any(item.get("state") == "success" for item in lifecycle))
            self.assertTrue(any(item.get("state") == "stop" for item in lifecycle))

    def test_sync_plan_worktrees_hyperlinks_plan_file_in_spinner_updates_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")
            (repo / "trees" / "implementations_task" / "1").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime, env={"ENVCTL_UI_HYPERLINK_MODE": "on"})
            update_messages: list[str] = []
            lifecycle_messages: list[str] = []

            @contextmanager
            def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
                _ = message, enabled, start_immediately

                class _SpinnerStub:
                    def start(self) -> None:
                        return None

                    def update(self, message: str) -> None:
                        update_messages.append(message)

                    def succeed(self, _message: str) -> None:
                        return None

                    def fail(self, _message: str) -> None:
                        return None

                yield _SpinnerStub()

            def capture_emit(event: str, **payload: object) -> None:
                if event == "ui.spinner.lifecycle" and payload.get("state") == "update":
                    lifecycle_messages.append(str(payload.get("message", "")))

            engine._emit = capture_emit  # type: ignore[method-assign]
            raw_projects = [(ctx.name, ctx.root) for ctx in engine._discover_projects(mode="trees")]  # noqa: SLF001

            with (
                patch("envctl_engine.planning.worktree_sync_orchestration.spinner", side_effect=fake_spinner),
                patch(
                    "envctl_engine.planning.worktree_sync_orchestration.resolve_spinner_policy",
                    return_value=SpinnerPolicy(
                        mode="auto",
                        enabled=True,
                        reason="",
                        backend="rich",
                        min_ms=0,
                        verbose_events=False,
                    ),
                ),
            ):
                synced, error = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                    plan_counts={"implementations/task.md": 0},
                    raw_projects=raw_projects,
                    keep_plan=False,
                )

            self.assertIsNone(error)
            self.assertEqual(synced, [])
            self.assertTrue(any("\x1b]8;;file://" in message for message in update_messages))
            self.assertTrue(
                any("implementations/task.md" in strip_ansi(message) for message in update_messages)
            )
            self.assertTrue(any("\x1b]8;;file://" not in message for message in lifecycle_messages))
            self.assertTrue(any("implementations/task.md" in message for message in lifecycle_messages))


if __name__ == "__main__":
    unittest.main()
