from __future__ import annotations

import importlib
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from envctl_engine.state.repository import RuntimeStateRepository


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
dispatch_module = importlib.import_module("envctl_engine.runtime.engine_runtime_dispatch")
command_policy_module = importlib.import_module("envctl_engine.runtime.command_policy")
lifecycle_lease_module = importlib.import_module("envctl_engine.runtime.lifecycle_operation_lease")
utility_module = importlib.import_module("envctl_engine.runtime.utility_command_support")
dispatch = dispatch_module.dispatch
dispatch_command = dispatch_module.dispatch_command


class EngineRuntimeDispatchTests(unittest.TestCase):
    def _runtime_root(self) -> Path:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        return Path(temporary_directory.name)

    def test_dispatch_entry_configures_probe_debug_recorder_and_route_events(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        calls: list[str] = []
        route = SimpleNamespace(command="start", mode="main")
        runtime = SimpleNamespace(
            runtime_root=self._runtime_root(),
            process_probe=None,
            _build_process_probe_backend=lambda: calls.append("probe_backend") or "backend",
            _effective_start_mode=lambda value: calls.append(f"effective:{value.command}") or "trees",
            _configure_debug_recorder=lambda value: calls.append(f"debug:{value.command}"),
            _emit=lambda event, **payload: events.append((event, payload)),
        )

        with (
            patch(
                "envctl_engine.runtime.engine_runtime_dispatch.ProcessProbe",
                side_effect=lambda backend: ("probe", backend),
            ),
            patch(
                "envctl_engine.runtime.engine_runtime_dispatch.dispatch_command",
                return_value=9,
            ) as command_dispatch,
        ):
            code = dispatch(runtime, route)

        self.assertEqual(code, 9)
        self.assertEqual(runtime.process_probe, ("probe", "backend"))
        self.assertEqual(calls, ["probe_backend", "effective:start", "debug:start"])
        self.assertEqual(
            events,
            [
                (
                    "engine.mode.selected",
                    {"mode": "main", "effective_mode": "trees", "command": "start"},
                ),
                (
                    "command.route.selected",
                    {"mode": "main", "effective_mode": "trees", "command": "start"},
                ),
            ],
        )
        command_dispatch.assert_called_once_with(runtime, route)

    def test_dispatch_entry_uses_route_mode_for_non_startup_commands(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        route = SimpleNamespace(command="health", mode="trees")
        runtime = SimpleNamespace(
            process_probe=None,
            _build_process_probe_backend=lambda: "backend",
            _effective_start_mode=lambda _route: (_ for _ in ()).throw(AssertionError("should not resolve")),
            _configure_debug_recorder=lambda _route: None,
            _emit=lambda event, **payload: events.append((event, payload)),
        )

        with (
            patch(
                "envctl_engine.runtime.engine_runtime_dispatch.ProcessProbe",
                side_effect=lambda backend: ("probe", backend),
            ),
            patch(
                "envctl_engine.runtime.engine_runtime_dispatch.dispatch_command",
                return_value=4,
            ),
        ):
            code = dispatch(runtime, route)

        self.assertEqual(code, 4)
        self.assertTrue(all(payload["effective_mode"] == "trees" for _event, payload in events))

    def test_exclusive_operation_commands_follow_mutating_command_policy_sets(self) -> None:
        expected = {
            *command_policy_module.LIFECYCLE_CLEANUP_COMMANDS,
            *command_policy_module.STARTUP_COMMANDS,
            "blast-worktree",
            "delete-worktree",
            "ensure-worktree",
            "resume",
            "self-destruct-worktree",
        }

        self.assertEqual(dispatch_module._EXCLUSIVE_OPERATION_COMMANDS, frozenset(expected))
        self.assertIn("import", expected)
        self.assertIn("self-destruct-worktree", expected)
        self.assertNotIn("test-focused", expected)
        self.assertNotIn("ship", expected)

    def test_nested_lifecycle_dispatch_is_reentrant_for_owning_runtime_thread(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        commands: list[str] = []
        runtime = SimpleNamespace(
            runtime_root=self._runtime_root(),
            process_probe=None,
            _build_process_probe_backend=lambda: "backend",
            _effective_start_mode=lambda route: route.mode,
            _configure_debug_recorder=lambda _route: None,
            _emit=lambda event, **payload: events.append((event, payload)),
        )
        outer_route = SimpleNamespace(command="start", mode="trees")
        nested_route = SimpleNamespace(command="stop", mode="trees")

        def command_dispatch(_runtime: object, route: object) -> int:
            command = str(getattr(route, "command", ""))
            commands.append(command)
            if command == "start":
                return dispatch(runtime, nested_route)
            return 7

        with (
            patch("envctl_engine.runtime.engine_runtime_dispatch.ProcessProbe", return_value="probe"),
            patch(
                "envctl_engine.runtime.engine_runtime_dispatch.dispatch_command",
                side_effect=command_dispatch,
            ),
        ):
            code = dispatch(runtime, outer_route)

        self.assertEqual(code, 7)
        self.assertEqual(commands, ["start", "stop"])
        self.assertFalse(any(event == "lifecycle.operation.busy" for event, _payload in events))
        self.assertIsNone(getattr(runtime, "_lifecycle_operation_owner", None))
        self.assertEqual(getattr(runtime, "_lifecycle_operation_depth", 0), 0)

    def test_concurrent_lifecycle_dispatch_on_another_thread_fails_busy_without_overlap(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        commands: list[str] = []
        entered = threading.Event()
        release = threading.Event()
        results: list[int] = []
        errors: list[BaseException] = []
        runtime = SimpleNamespace(
            runtime_root=self._runtime_root(),
            process_probe=None,
            _build_process_probe_backend=lambda: "backend",
            _effective_start_mode=lambda route: route.mode,
            _configure_debug_recorder=lambda _route: None,
            _emit=lambda event, **payload: events.append((event, payload)),
        )
        outer_route = SimpleNamespace(command="start", mode="trees")
        concurrent_route = SimpleNamespace(command="stop", mode="trees")

        def command_dispatch(_runtime: object, route: object) -> int:
            command = str(getattr(route, "command", ""))
            commands.append(command)
            if command == "start":
                entered.set()
                if not release.wait(timeout=2):
                    raise AssertionError("timed out waiting to release lifecycle operation")
            return 0

        def run_outer() -> None:
            try:
                results.append(dispatch(runtime, outer_route))
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        with (
            patch("envctl_engine.runtime.engine_runtime_dispatch.ProcessProbe", return_value="probe"),
            patch(
                "envctl_engine.runtime.engine_runtime_dispatch.dispatch_command",
                side_effect=command_dispatch,
            ),
        ):
            thread = threading.Thread(target=run_outer, name="envctl-dispatch-lock-test")
            thread.start()
            try:
                self.assertTrue(entered.wait(timeout=2))
                output = StringIO()
                with redirect_stdout(output):
                    concurrent_code = dispatch(runtime, concurrent_route)
            finally:
                release.set()
                thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results, [0])
        self.assertEqual(concurrent_code, 1)
        self.assertEqual(commands, ["start"])
        self.assertIn("Another envctl lifecycle operation is already active", output.getvalue())
        self.assertTrue(any(event == "lifecycle.operation.busy" for event, _payload in events))

    def test_committed_start_releases_lease_before_interactive_wait_so_stop_can_run(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        commands: list[str] = []
        interactive_wait_entered = threading.Event()
        release_interactive_wait = threading.Event()
        results: list[int] = []
        runtime = SimpleNamespace(
            runtime_root=self._runtime_root(),
            process_probe=None,
            _build_process_probe_backend=lambda: "backend",
            _effective_start_mode=lambda route: route.mode,
            _configure_debug_recorder=lambda _route: None,
            _emit=lambda event, **payload: events.append((event, payload)),
        )
        start_route = SimpleNamespace(command="start", mode="trees")
        stop_route = SimpleNamespace(command="stop", mode="trees")

        def command_dispatch(_runtime: object, route: object) -> int:
            command = str(getattr(route, "command", ""))
            commands.append(command)
            if command == "start":
                released = lifecycle_lease_module.release_lifecycle_operation(runtime)
                self.assertTrue(released)
                interactive_wait_entered.set()
                self.assertTrue(release_interactive_wait.wait(timeout=2))
            return 0

        def run_start() -> None:
            results.append(dispatch(runtime, start_route))

        with (
            patch("envctl_engine.runtime.engine_runtime_dispatch.ProcessProbe", return_value="probe"),
            patch(
                "envctl_engine.runtime.engine_runtime_dispatch.dispatch_command",
                side_effect=command_dispatch,
            ),
        ):
            thread = threading.Thread(target=run_start, name="envctl-interactive-start-test")
            thread.start()
            try:
                self.assertTrue(interactive_wait_entered.wait(timeout=2))
                stop_code = dispatch(runtime, stop_route)
            finally:
                release_interactive_wait.set()
                thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(results, [0])
        self.assertEqual(stop_code, 0)
        self.assertEqual(commands, ["start", "stop"])
        self.assertFalse(any(event == "lifecycle.operation.busy" for event, _payload in events))

    def test_operation_lock_rejects_retargeted_repository_root_before_external_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_dir = Path(tmpdir) / "runtime"
            runtime_root = runtime_dir / "scope"
            legacy_root = runtime_dir / "python-engine"
            runtime_root.mkdir(parents=True)
            legacy_root.mkdir()
            repository = RuntimeStateRepository(
                runtime_root=runtime_root,
                runtime_legacy_root=legacy_root,
                runtime_dir=runtime_dir,
                runtime_scope_id="repo-123",
                compat_mode=RuntimeStateRepository.SCOPED_ONLY,
            )
            external = Path(tmpdir) / "external"
            external.mkdir()
            sentinel = external / "sentinel.txt"
            sentinel.write_text("untouched", encoding="utf-8")
            runtime_root.rmdir()
            runtime_root.symlink_to(external, target_is_directory=True)
            runtime = SimpleNamespace(
                runtime_root=runtime_root,
                state_repository=repository,
                process_probe=None,
                _build_process_probe_backend=lambda: "backend",
                _effective_start_mode=lambda route: route.mode,
                _configure_debug_recorder=lambda _route: None,
                _emit=lambda *_args, **_kwargs: None,
            )

            with (
                patch("envctl_engine.runtime.engine_runtime_dispatch.ProcessProbe", return_value="probe"),
                patch(
                    "envctl_engine.runtime.engine_runtime_dispatch.dispatch_command",
                    side_effect=AssertionError("command must not run"),
                ),
                self.assertRaisesRegex(RuntimeError, "symlink"),
            ):
                dispatch(runtime, SimpleNamespace(command="start", mode="trees"))

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "untouched")
            self.assertEqual(list(external.iterdir()), [sentinel])

    def test_list_commands_dispatch_prints_supported_commands(self) -> None:
        runtime = SimpleNamespace()
        route = SimpleNamespace(command="list-commands", mode="main")

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = dispatch_command(runtime, route)

        self.assertEqual(code, 0)
        output = buffer.getvalue()
        self.assertIn("help", output)
        self.assertIn("blast-worktree", output)

    def test_action_command_dispatch_routes_to_action_orchestrator(self) -> None:
        seen: list[str] = []
        runtime = SimpleNamespace(
            action_command_orchestrator=SimpleNamespace(execute=lambda route: seen.append(str(route.command)) or 7),
            _unsupported_command=lambda command: 1,
        )
        route = SimpleNamespace(command="test", mode="main")

        code = dispatch_command(runtime, route)

        self.assertEqual(code, 7)
        self.assertEqual(seen, ["test"])

    def test_state_command_dispatch_routes_to_state_orchestrator(self) -> None:
        seen: list[str] = []
        runtime = SimpleNamespace(
            state_action_orchestrator=SimpleNamespace(execute=lambda route: seen.append(str(route.command)) or 5),
            _unsupported_command=lambda command: 1,
        )
        route = SimpleNamespace(command="health", mode="main")

        code = dispatch_command(runtime, route)

        self.assertEqual(code, 5)
        self.assertEqual(seen, ["health"])

    def test_startup_command_dispatch_routes_to_startup_orchestrator(self) -> None:
        seen: list[str] = []
        runtime = SimpleNamespace(
            startup_orchestrator=SimpleNamespace(execute=lambda route: seen.append(str(route.command)) or 3),
            _unsupported_command=lambda command: 1,
        )
        route = SimpleNamespace(command="plan", mode="trees")

        code = dispatch_command(runtime, route)

        self.assertEqual(code, 3)
        self.assertEqual(seen, ["plan"])

    def test_utility_command_dispatch_routes_to_prompt_installer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = SimpleNamespace(command="install-prompts", mode="main", flags={"cli": "codex", "dry_run": True})

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = dispatch_command(runtime, route)

        self.assertEqual(code, 0)
        self.assertIn("codex: planned", buffer.getvalue())

    def test_utility_command_dispatch_routes_to_codex_tmux_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            runtime = SimpleNamespace(
                env={},
                config=SimpleNamespace(base_dir=repo),
                _command_exists=lambda command: command in {"tmux", "codex"},
                process_runner=SimpleNamespace(
                    run_probe=lambda *args, **kwargs: __import__("subprocess").CompletedProcess(
                        args=["tmux"],
                        returncode=1,
                        stdout="",
                        stderr="",
                    )
                ),
            )
            route = SimpleNamespace(command="codex-tmux", mode="main", flags={"dry_run": True}, passthrough_args=[])

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = dispatch_command(runtime, route)

        self.assertEqual(code, 0)
        self.assertIn("session_name:", buffer.getvalue())

    def test_utility_command_dispatch_routes_to_supabase_user_support(self) -> None:
        runtime = SimpleNamespace(config=SimpleNamespace(supabase_auth_users=()))
        route = SimpleNamespace(command="supabase-user", mode="main", flags={"json": True}, passthrough_args=["list"])

        with patch(
            "envctl_engine.runtime.utility_command_support.run_supabase_user_command",
            return_value=0,
        ) as command:
            code = dispatch_command(runtime, route)

        self.assertEqual(code, 0)
        command.assert_called_once_with(runtime, route)

    def test_utility_command_handlers_are_table_driven_and_complete(self) -> None:
        self.assertEqual(
            set(utility_module.utility_command_handlers()),
            {
                "install-prompts",
                "codex-tmux",
                "ensure-worktree",
                "supabase-user",
                "qa-user",
                "playwright",
                "pr-preview-controller",
            },
        )

    def test_utility_command_dispatch_reports_unknown_command(self) -> None:
        runtime = SimpleNamespace()
        route = SimpleNamespace(command="unknown-utility")

        with self.assertRaisesRegex(RuntimeError, "Unsupported utility command: unknown-utility"):
            utility_module.dispatch_utility_command(runtime, route)


if __name__ == "__main__":
    unittest.main()
