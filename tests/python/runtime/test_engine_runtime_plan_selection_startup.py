from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from unittest.mock import patch

from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime

from tests.python.runtime.engine_runtime_real_startup_test_support import (
    _EngineRuntimeRealStartupTestCase,
    _FakeProcessRunner,
)


class EngineRuntimePlanSelectionStartupTests(_EngineRuntimeRealStartupTestCase):
    def test_plan_without_selection_and_without_planning_files_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            route = parse_route(["--plan"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 1)

    def test_plan_without_selection_uses_interactive_planning_choice_when_tty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "backend" / "task.md").write_text("# task\n", encoding="utf-8")
            (repo / "trees" / "backend_task" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan"], env={})

            with (
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False),
                patch.object(engine, "_run_planning_selection_menu", return_value={"backend/task.md": 1}),
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0),
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)

    def test_plan_without_selection_and_without_tty_fails_when_planning_files_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "docs" / "planning" / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "docs" / "planning" / "backend" / "task.md").write_text("# task\n", encoding="utf-8")
            (repo / "trees" / "backend_task" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            route = parse_route(["--plan"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 1)

    def test_initial_plan_selected_counts_prefers_existing_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            selected = engine._initial_plan_selected_counts(
                planning_files=["backend/task-a.md", "backend/task-b.md"],
                existing_counts={"backend/task-a.md": 2, "backend/task-b.md": 1},
            )
            self.assertEqual(selected, {"backend/task-a.md": 2, "backend/task-b.md": 1})

    def test_initial_plan_selected_counts_ignores_stale_memory_when_existing_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            memory_path = runtime / "python-engine" / "planning_selection.json"
            memory_path.parent.mkdir(parents=True, exist_ok=True)
            memory_path.write_text(
                json.dumps({"selected_counts": {"backend/task-a.md": 3}}, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            selected = engine._initial_plan_selected_counts(
                planning_files=["backend/task-a.md", "backend/task-b.md"],
                existing_counts={},
            )
            self.assertEqual(selected, {"backend/task-a.md": 0, "backend/task-b.md": 0})

    def test_planning_menu_apply_key_supports_arrow_navigation_and_count_adjustment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            planning_files = ["backend/task-a.md", "frontend/task-b.md"]
            selected_counts = {"backend/task-a.md": 0, "frontend/task-b.md": 2}
            existing_counts = {"backend/task-a.md": 1, "frontend/task-b.md": 0}
            cursor = 0

            cursor, action, _ = engine._planning_menu_apply_key(
                key="down",
                cursor=cursor,
                planning_files=planning_files,
                selected_counts=selected_counts,
                existing_counts=existing_counts,
            )
            self.assertEqual((cursor, action), (1, "continue"))
            cursor, _, _ = engine._planning_menu_apply_key(
                key="right",
                cursor=cursor,
                planning_files=planning_files,
                selected_counts=selected_counts,
                existing_counts=existing_counts,
            )
            self.assertEqual(selected_counts["frontend/task-b.md"], 3)
            cursor, _, _ = engine._planning_menu_apply_key(
                key="left",
                cursor=cursor,
                planning_files=planning_files,
                selected_counts=selected_counts,
                existing_counts=existing_counts,
            )
            self.assertEqual(selected_counts["frontend/task-b.md"], 2)
            cursor, _, _ = engine._planning_menu_apply_key(
                key="up",
                cursor=cursor,
                planning_files=planning_files,
                selected_counts=selected_counts,
                existing_counts=existing_counts,
            )
            self.assertEqual(cursor, 0)
            cursor, _, _ = engine._planning_menu_apply_key(
                key="space",
                cursor=cursor,
                planning_files=planning_files,
                selected_counts=selected_counts,
                existing_counts=existing_counts,
            )
            self.assertEqual(selected_counts["backend/task-a.md"], 1)
            cursor, _, _ = engine._planning_menu_apply_key(
                key="space",
                cursor=cursor,
                planning_files=planning_files,
                selected_counts=selected_counts,
                existing_counts=existing_counts,
            )
            self.assertEqual(selected_counts["backend/task-a.md"], 0)
            _, action, _ = engine._planning_menu_apply_key(
                key="enter",
                cursor=cursor,
                planning_files=planning_files,
                selected_counts=selected_counts,
                existing_counts=existing_counts,
            )
            self.assertEqual(action, "submit")

    def test_planning_menu_render_respects_terminal_width_and_scrolls(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            planning_files = [
                f"implementations/super-long-plan-name-{idx:02d}-for-rendering-check.md" for idx in range(1, 31)
            ]
            selected_counts = {name: 1 if idx % 5 == 0 else 0 for idx, name in enumerate(planning_files, start=1)}
            existing_counts = {planning_files[9]: 2}

            frame = engine._render_planning_selection_menu(
                planning_files=planning_files,
                selected_counts=selected_counts,
                existing_counts=existing_counts,
                cursor=20,
                message="",
                terminal_width=72,
                terminal_height=14,
            )
            plain = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", frame)
            lines = plain.splitlines()

            self.assertIn("Showing 17-24 of 30", plain)
            self.assertIn("super-long-plan-name-21", plain)
            self.assertNotIn("super-long-plan-name-01", plain)
            for line in lines:
                self.assertLessEqual(len(line), 72)
