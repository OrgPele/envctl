from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.actions.action_target_support import (  # noqa: E402
    ActionCommandResolution,
    execute_targeted_action,
    emit_action_output,
    resolve_action_targets,
)
from envctl_engine.runtime.command_router import Route
from envctl_engine.ui.target_selector import TargetSelection


@dataclass
class _Completed:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass
class _Target:
    name: str
    root: str


class ActionTargetSupportTests(unittest.TestCase):
    def test_resolve_action_targets_applies_service_selectors_from_state(self) -> None:
        candidates = [_Target(name="Main", root="/tmp/main")]
        state = type(
            "State",
            (),
            {
                "services": {
                    "Main Voice Runtime": type(
                        "Service",
                        (),
                        {"type": "voice-runtime"},
                    )()
                }
            },
        )()

        targets, error = resolve_action_targets(
            route=Route(command="test", mode="main", flags={"services": ["voice-runtime"]}),
            trees_only=False,
            discover_projects=lambda mode: candidates if mode == "main" else [],
            selectors_from_passthrough=lambda _args: set(),
            load_existing_state=lambda mode: state if mode == "main" else None,
            project_name_from_service=lambda service_name: "Main" if service_name == "Main Voice Runtime" else "",
            select_project_targets=lambda **_kwargs: TargetSelection(cancelled=True),
            resolve_current_worktree_target=lambda _require_configured_main_root=False: None,
            interactive_selection_allowed=lambda _route: False,
            no_target_selected_message=lambda route: f"No {route.command} target selected.",
        )

        self.assertIsNone(error)
        self.assertEqual([target.name for target in targets], ["Main"])

    def test_resolve_action_targets_uses_interactive_selection_for_ambiguous_targets(self) -> None:
        candidates = [_Target(name="alpha", root="/tmp/alpha"), _Target(name="beta", root="/tmp/beta")]
        route = Route(command="test", mode="trees", flags={"interactive_command": True})

        targets, error = resolve_action_targets(
            route=route,
            trees_only=False,
            discover_projects=lambda mode: candidates if mode == "trees" else [],
            selectors_from_passthrough=lambda _args: set(),
            load_existing_state=lambda _mode: None,
            project_name_from_service=lambda _service_name: "",
            select_project_targets=lambda **_kwargs: TargetSelection(all_selected=True),
            resolve_current_worktree_target=lambda _require_configured_main_root=False: None,
            interactive_selection_allowed=lambda _route: True,
            no_target_selected_message=lambda route: f"No {route.command} target selected.",
        )

        self.assertIsNone(error)
        self.assertEqual([target.name for target in targets], ["alpha", "beta"])
        self.assertTrue(route.flags["all"])

    def test_resolve_action_targets_prefers_current_worktree_for_main_actions(self) -> None:
        current = _Target(name="feature-a-1", root="/tmp/repo/trees/feature-a/1")

        targets, error = resolve_action_targets(
            route=Route(command="commit", mode="main", raw_args=["--main", "commit"]),
            trees_only=False,
            discover_projects=lambda _mode: [_Target(name="Main", root="/tmp/repo")],
            selectors_from_passthrough=lambda _args: set(),
            load_existing_state=lambda _mode: None,
            project_name_from_service=lambda _service_name: "",
            select_project_targets=lambda **_kwargs: TargetSelection(cancelled=True),
            resolve_current_worktree_target=lambda require_configured_main_root=False: (
                current if require_configured_main_root else None
            ),
            interactive_selection_allowed=lambda _route: False,
            no_target_selected_message=lambda route: f"No {route.command} target selected.",
        )

        self.assertIsNone(error)
        self.assertEqual(targets, [current])

    def test_emit_action_output_trims_and_emits_status(self) -> None:
        printed: list[str] = []
        emitted: list[str] = []

        wrote = emit_action_output(
            "\n first \n\n second \n",
            emit_status=emitted.append,
            printer=printed.append,
        )

        self.assertTrue(wrote)
        self.assertEqual(printed, ["first", "second"])
        self.assertEqual(emitted, ["first", "second"])

    def test_execute_targeted_action_suppresses_interactive_failure_print_for_migrate_style_flow(self) -> None:
        target = _Target(name="Main", root="/tmp/main")
        printed: list[str] = []
        emitted: list[str] = []

        code = execute_targeted_action(
            targets=[target],
            command_name="migrate",
            interactive_command=True,
            resolve_command=lambda _context: ActionCommandResolution(command=["sh", "-lc", "exit 1"], cwd=Path("/tmp")),
            build_env=lambda _context: {},
            process_run=lambda _command, _cwd, _env: _Completed(returncode=1, stderr="boom"),
            emit_status=emitted.append,
            printer=printed.append,
            interactive_print_failures=False,
        )

        self.assertEqual(code, 1)
        self.assertEqual(printed, [])
        self.assertIn("migrate failed for Main: boom", emitted)

    def test_execute_targeted_action_uses_bounded_interactive_failure_status_formatter_for_migrate(self) -> None:
        target = _Target(name="Main", root="/tmp/main")
        printed: list[str] = []
        emitted: list[str] = []
        raw_error = (
            "Traceback (most recent call last):\n"
            '  File "/tmp/project/backend/alembic/env.py", line 19, in <module>\n'
            "    from app.core.config import settings\n"
            "alembic.util.exc.CommandError: migration failed"
        )

        code = execute_targeted_action(
            targets=[target],
            command_name="migrate",
            interactive_command=True,
            resolve_command=lambda _context: ActionCommandResolution(command=["sh", "-lc", "exit 1"], cwd=Path("/tmp")),
            build_env=lambda _context: {},
            process_run=lambda _command, _cwd, _env: _Completed(returncode=1, stderr=raw_error),
            emit_status=emitted.append,
            printer=printed.append,
            interactive_print_failures=False,
            failure_status_formatter=lambda context, _error: (
                f"migrate failed for {context.name}: alembic.util.exc.CommandError: migration failed"
            ),
        )

        self.assertEqual(code, 1)
        self.assertEqual(printed, [])
        self.assertIn(
            "migrate failed for Main: alembic.util.exc.CommandError: migration failed",
            emitted,
        )
        self.assertFalse(any("Traceback (most recent call last):" in item for item in emitted))

    def test_execute_targeted_action_prints_interactive_failure_for_project_actions(self) -> None:
        target = _Target(name="Main", root="/tmp/main")
        printed: list[str] = []
        emitted: list[str] = []

        code = execute_targeted_action(
            targets=[target],
            command_name="pr",
            interactive_command=True,
            resolve_command=lambda _context: ActionCommandResolution(command=["sh", "-lc", "exit 1"], cwd=Path("/tmp")),
            build_env=lambda _context: {},
            process_run=lambda _command, _cwd, _env: _Completed(returncode=1, stderr="boom"),
            emit_status=emitted.append,
            printer=printed.append,
            interactive_print_failures=True,
        )

        self.assertEqual(code, 1)
        self.assertIn("pr action failed for Main: boom", printed)
        self.assertIn("pr failed for Main: boom", emitted)

    def test_execute_targeted_action_reports_combined_failure_output_to_failure_hook(self) -> None:
        target = _Target(name="Main", root="/tmp/main")
        captured: list[str] = []

        code = execute_targeted_action(
            targets=[target],
            command_name="migrate",
            interactive_command=True,
            resolve_command=lambda _context: ActionCommandResolution(command=["sh", "-lc", "exit 1"], cwd=Path("/tmp")),
            build_env=lambda _context: {},
            process_run=lambda _command, _cwd, _env: _Completed(
                returncode=1, stdout="stdout detail", stderr="stderr detail"
            ),
            emit_status=lambda _message: None,
            interactive_print_failures=False,
            on_failure=lambda _context, output: captured.append(output),
        )

        self.assertEqual(code, 1)
        self.assertEqual(captured, ["stderr detail\n\nstdout:\nstdout detail"])

    def test_execute_targeted_action_preserves_multiline_interactive_failure_details(self) -> None:
        target = _Target(name="Main", root="/tmp/main")
        printed: list[str] = []
        emitted: list[str] = []
        details = "Review failed: Main\n  Output directory\n    /tmp/review\n  Details: analyzer failed"

        code = execute_targeted_action(
            targets=[target],
            command_name="review",
            interactive_command=True,
            resolve_command=lambda _context: ActionCommandResolution(command=["sh", "-lc", "exit 1"], cwd=Path("/tmp")),
            build_env=lambda _context: {},
            process_run=lambda _command, _cwd, _env: _Completed(returncode=1, stderr=details),
            emit_status=emitted.append,
            printer=printed.append,
            interactive_print_failures=True,
        )

        self.assertEqual(code, 1)
        self.assertEqual(len(printed), 1)
        self.assertIn("review action failed for Main: Review failed: Main", printed[0])
        self.assertIn("Output directory", printed[0])
        self.assertIn("/tmp/review", printed[0])
        self.assertIn("analyzer failed", printed[0])
        self.assertTrue(any("review failed for Main: Review failed: Main" in item for item in emitted))

    def test_execute_targeted_action_reports_success_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = _Target(name="Main", root=tmpdir)
            printed: list[str] = []
            emitted: list[str] = []

            code = execute_targeted_action(
                targets=[target],
                command_name="review",
                interactive_command=False,
                resolve_command=lambda _context: ActionCommandResolution(command=["echo", "ok"], cwd=Path(tmpdir)),
                build_env=lambda _context: {},
                process_run=lambda _command, _cwd, _env: _Completed(returncode=0, stdout="report written\n"),
                emit_status=emitted.append,
                printer=printed.append,
            )

            self.assertEqual(code, 0)
            self.assertIn("report written", printed)
            self.assertIn("review action succeeded for Main.", printed)
            self.assertIn("review succeeded for Main", emitted)

    def test_execute_targeted_action_invokes_success_hook_without_printing_success_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = _Target(name="Main", root=tmpdir)
            printed: list[str] = []
            emitted: list[str] = []
            seen: list[tuple[str, str]] = []

            code = execute_targeted_action(
                targets=[target],
                command_name="pr",
                interactive_command=True,
                resolve_command=lambda _context: ActionCommandResolution(command=["echo", "ok"], cwd=Path(tmpdir)),
                build_env=lambda _context: {},
                process_run=lambda _command, _cwd, _env: _Completed(
                    returncode=0, stdout="https://github.com/acme/supportopia/pull/123\n"
                ),
                emit_status=emitted.append,
                printer=printed.append,
                emit_success_output=False,
                on_success=lambda context, completed: seen.append(
                    (context.name, str(getattr(completed, "stdout", "")).strip())
                ),
            )

            self.assertEqual(code, 0)
            self.assertEqual(printed, [])
            self.assertEqual(seen, [("Main", "https://github.com/acme/supportopia/pull/123")])
            self.assertIn("pr succeeded for Main", emitted)


if __name__ == "__main__":
    unittest.main()
