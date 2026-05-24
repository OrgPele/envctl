from __future__ import annotations

import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime

from tests.python.runtime.engine_runtime_real_startup_test_support import (
    _EngineRuntimeRealStartupTestCase,
    _FakeProcessRunner,
    _FakeSetupWorktreeRunner,
)


class EngineRuntimeSetupWorktreesTests(_EngineRuntimeRealStartupTestCase):
    def test_setup_worktrees_switches_start_to_trees_mode_and_targets_new_feature(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeSetupWorktreeRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--setup-worktrees", "feature-a", "2", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            route_events = [event for event in engine.events if event.get("event") == "command.route.selected"]
            self.assertTrue(route_events)
            latest_route = route_events[-1]
            self.assertEqual(latest_route.get("mode"), "main")
            self.assertEqual(latest_route.get("effective_mode"), "trees")
            state = engine._try_load_existing_state(mode="trees")
            self.assertIsNotNone(state)
            assert state is not None
            self.assertEqual(state.mode, "trees")
            project_roots = state.metadata.get("project_roots", {})
            self.assertIsInstance(project_roots, dict)
            self.assertIn("feature-a-1", project_roots)
            self.assertIn("feature-a-2", project_roots)
            self.assertIn("feature-a-1 Backend", state.services)
            self.assertIn("feature-a-2 Backend", state.services)

    def test_setup_worktree_existing_and_include_existing_filters_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "2").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-b" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(
                [
                    "--setup-worktree",
                    "feature-a",
                    "1",
                    "--setup-worktree-existing",
                    "--setup-include-worktrees",
                    "2",
                    "--batch",
                ],
                env={},
            )

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            state = engine._try_load_existing_state(mode="trees")
            self.assertIsNotNone(state)
            assert state is not None
            roots = state.metadata.get("project_roots", {})
            self.assertIsInstance(roots, dict)
            self.assertIn("feature-a-1", roots)
            self.assertIn("feature-a-2", roots)
            self.assertNotIn("feature-b-1", roots)

    def test_setup_worktree_existing_path_requires_existing_or_recreate_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--setup-worktree", "feature-a", "1", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("already exists", out.getvalue())

    def test_setup_worktree_uses_flat_trees_feature_root_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees-feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(
                [
                    "--setup-worktree",
                    "feature-a",
                    "1",
                    "--setup-worktree-existing",
                    "--batch",
                ],
                env={},
            )

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            state = engine._try_load_existing_state(mode="trees")
            self.assertIsNotNone(state)
            assert state is not None
            roots = state.metadata.get("project_roots", {})
            self.assertIsInstance(roots, dict)
            self.assertEqual(
                Path(str(roots.get("feature-a-1", ""))).resolve(),
                (repo / "trees-feature-a" / "1").resolve(),
            )
            self.assertIn("feature-a-1 Backend", state.services)

    def test_setup_worktrees_prefers_existing_flat_feature_root_for_new_iterations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees-feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeSetupWorktreeRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--setup-worktrees", "feature-a", "1", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            state = engine._try_load_existing_state(mode="trees")
            self.assertIsNotNone(state)
            assert state is not None
            roots = state.metadata.get("project_roots", {})
            self.assertIsInstance(roots, dict)
            self.assertEqual(
                Path(str(roots.get("feature-a-2", ""))).resolve(),
                (repo / "trees-feature-a" / "2").resolve(),
            )

    def test_setup_worktree_uses_nested_flat_trees_feature_root_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "work" / "trees-feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime, {"TREES_DIR_NAME": "work/trees"}),
                env={},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(
                [
                    "--setup-worktree",
                    "feature-a",
                    "1",
                    "--setup-worktree-existing",
                    "--batch",
                ],
                env={},
            )

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            state = engine._try_load_existing_state(mode="trees")
            self.assertIsNotNone(state)
            assert state is not None
            roots = state.metadata.get("project_roots", {})
            self.assertIsInstance(roots, dict)
            self.assertEqual(
                Path(str(roots.get("feature-a-1", ""))).resolve(),
                (repo / "work" / "trees-feature-a" / "1").resolve(),
            )

    def test_setup_worktrees_prefers_existing_nested_flat_feature_root_for_new_iterations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "work" / "trees-feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime, {"TREES_DIR_NAME": "work/trees"}),
                env={},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeSetupWorktreeRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--setup-worktrees", "feature-a", "1", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            state = engine._try_load_existing_state(mode="trees")
            self.assertIsNotNone(state)
            assert state is not None
            roots = state.metadata.get("project_roots", {})
            self.assertIsInstance(roots, dict)
            self.assertEqual(
                Path(str(roots.get("feature-a-2", ""))).resolve(),
                (repo / "work" / "trees-feature-a" / "2").resolve(),
            )

    def test_setup_worktrees_parallel_flags_apply_in_effective_trees_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeSetupWorktreeRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(
                [
                    "--setup-worktrees",
                    "feature-a",
                    "2",
                    "--parallel-trees",
                    "--parallel-trees-max",
                    "2",
                    "--batch",
                ],
                env={},
            )

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            execution_events = [event for event in engine.events if event.get("event") == "startup.execution"]
            self.assertTrue(execution_events)
            latest = execution_events[-1]
            self.assertEqual(latest.get("mode"), "parallel")
            self.assertEqual(latest.get("workers"), 2)

    def test_setup_worktrees_use_trees_requirement_policy_not_main_route_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = self._config(
                repo,
                runtime,
                extra={
                    "N8N_ENABLE": "true",
                    "N8N_MAIN_ENABLE": "true",
                },
            )
            engine = PythonEngineRuntime(config, env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeSetupWorktreeRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(
                [
                    "--setup-worktrees",
                    "feature-a",
                    "1",
                    "--isolated-deps",
                    "--main-services-remote",
                    "--batch",
                ],
                env={},
            )

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            state = engine._try_load_existing_state(mode="trees")
            self.assertIsNotNone(state)
            assert state is not None
            requirements = state.requirements.get("feature-a-1")
            self.assertIsNotNone(requirements)
            assert requirements is not None
            self.assertTrue(requirements.component("n8n").get("enabled"))

    def test_setup_worktrees_fails_when_git_worktree_add_fails_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeSetupWorktreeRunner(fail_worktree_add=True)
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--setup-worktrees", "feature-a", "1", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("failed creating worktree feature-a/1", out.getvalue().lower())
            self.assertFalse((repo / "trees" / "feature-a" / "1" / ".envctl_worktree_placeholder").exists())

    def test_setup_worktrees_placeholder_fallback_can_be_enabled_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true"},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeSetupWorktreeRunner(fail_worktree_add=True)
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--setup-worktrees", "feature-a", "1", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertTrue((repo / "trees" / "feature-a" / "1" / ".envctl_worktree_placeholder").exists())
            fallback_events = [
                event for event in engine.events if event.get("event") == "setup.worktree.placeholder_fallback"
            ]
            self.assertTrue(fallback_events)

    def test_read_planning_menu_key_parses_modified_arrow_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            reads = [b"\x1b", b"[", b"1", b";", b"5", b"C"]

            def fake_read(_fd: int, _count: int) -> bytes:
                return reads.pop(0) if reads else b""

            def fake_selector(_r, _w, _x, _timeout):  # noqa: ANN001
                if reads:
                    return ([_r[0]], [], [])
                return ([], [], [])

            with patch("os.read", side_effect=fake_read):
                key = engine._read_planning_menu_key(fd=7, selector=fake_selector)

            self.assertEqual(key, "right")

    def test_read_planning_menu_key_treats_unknown_escape_sequence_as_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            reads = [b"\x1b", b"[", b"2", b"0", b"0", b"~"]

            def fake_read(_fd: int, _count: int) -> bytes:
                return reads.pop(0) if reads else b""

            def fake_selector(_r, _w, _x, _timeout):  # noqa: ANN001
                if reads:
                    return ([_r[0]], [], [])
                return ([], [], [])

            with patch("os.read", side_effect=fake_read):
                key = engine._read_planning_menu_key(fd=7, selector=fake_selector)

            self.assertEqual(key, "noop")

    def test_read_planning_menu_key_ignores_csi_fragment_without_escape_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            reads = [b"[", b"A"]

            def fake_read(_fd: int, _count: int) -> bytes:
                return reads.pop(0) if reads else b""

            def fake_selector(_r, _w, _x, _timeout):  # noqa: ANN001
                if reads:
                    return ([_r[0]], [], [])
                return ([], [], [])

            with patch("os.read", side_effect=fake_read):
                key = engine._read_planning_menu_key(fd=7, selector=fake_selector)

            self.assertEqual(key, "noop")

    def test_read_planning_menu_key_ignores_ss3_fragment_without_escape_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            reads = [b"O", b"D"]

            def fake_read(_fd: int, _count: int) -> bytes:
                return reads.pop(0) if reads else b""

            def fake_selector(_r, _w, _x, _timeout):  # noqa: ANN001
                if reads:
                    return ([_r[0]], [], [])
                return ([], [], [])

            with patch("os.read", side_effect=fake_read):
                key = engine._read_planning_menu_key(fd=7, selector=fake_selector)

            self.assertEqual(key, "noop")

    def test_read_planning_menu_key_keeps_plain_escape_as_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            reads = [b"\x1b"]

            def fake_read(_fd: int, _count: int) -> bytes:
                return reads.pop(0) if reads else b""

            def fake_selector(_r, _w, _x, _timeout):  # noqa: ANN001
                return ([], [], [])

            with patch("os.read", side_effect=fake_read):
                key = engine._read_planning_menu_key(fd=7, selector=fake_selector)

            self.assertEqual(key, "esc")

    def test_read_planning_menu_key_maps_vim_navigation_letters(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            mapping = {
                b"j": "down",
                b"k": "up",
                b"h": "left",
                b"l": "right",
                b"x": "space",
                b"t": "space",
            }

            def fake_selector(_r, _w, _x, _timeout):  # noqa: ANN001
                return ([], [], [])

            for raw_byte, expected in mapping.items():
                with self.subTest(raw_byte=raw_byte):
                    reads = [raw_byte]

                    def fake_read(_fd: int, _count: int) -> bytes:
                        return reads.pop(0) if reads else b""

                    with patch("os.read", side_effect=fake_read):
                        key = engine._read_planning_menu_key(fd=7, selector=fake_selector)
                    self.assertEqual(key, expected)

    def test_to_terminal_lines_uses_crlf_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            rendered = engine._to_terminal_lines("a\nb\nc")

            self.assertEqual(rendered, "a\r\nb\r\nc")

