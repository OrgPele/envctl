from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.actions.action_target_support import (  # noqa: E402
    ActionCommandResolution,
    action_target_identities,
    action_target_names,
    action_target_names_with_roots,
    build_action_target_contexts,
    execute_targeted_action,
    emit_action_output,
    projects_for_services,
    resolve_action_targets,
)
from envctl_engine.runtime.command_router import parse_route  # noqa: E402


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
    def test_action_target_identities_normalize_name_root_and_skip_invalid_targets(self) -> None:
        targets = [
            SimpleNamespace(name=" feature-a-1 ", root="/repo/trees/feature-a/1"),
            SimpleNamespace(name="", root="/repo/trees/feature-b/1"),
            SimpleNamespace(name="missing-root", root=""),
        ]

        identities = action_target_identities(targets, fallback_name_from_root=True)

        self.assertEqual([identity.name for identity in identities], ["feature-a-1", "1"])
        self.assertEqual([identity.root for identity in identities], [Path("/repo/trees/feature-a/1"), Path("/repo/trees/feature-b/1")])
        self.assertEqual(action_target_names(targets), ["feature-a-1", "missing-root"])
        self.assertEqual(action_target_names_with_roots(targets), ["feature-a-1"])

    def test_build_action_target_contexts_reports_progress_over_valid_targets_only(self) -> None:
        contexts = build_action_target_contexts(
            [
                _Target(name="feature-a-1", root="/repo/trees/feature-a/1"),
                _Target(name="", root="/repo/trees/invalid/1"),
                _Target(name="feature-b-1", root="/repo/trees/feature-b/1"),
            ]
        )

        self.assertEqual([(context.index, context.total) for context in contexts], [(1, 2), (2, 2)])

    def test_projects_for_services_resolves_from_state_and_deduplicates(self) -> None:
        state = SimpleNamespace(
            services={
                "feature-a-1 Backend": SimpleNamespace(type="backend"),
                "feature-a-1 Frontend": SimpleNamespace(type="frontend"),
                "feature-b-1 Worker": SimpleNamespace(type="worker"),
            }
        )
        runtime = SimpleNamespace(
            load_existing_state=lambda mode: state if mode == "trees" else None,
            project_name_from_service=lambda name: str(name).split()[0] if str(name).startswith("feature-") else "",
        )

        resolved = projects_for_services(runtime, ["service:backend", "feature-a-1 frontend", "worker"])

        self.assertEqual(resolved, ["feature-a-1", "feature-b-1"])

    def test_projects_for_services_resolves_all_projects_for_shared_service_type_once(self) -> None:
        state = SimpleNamespace(
            services={
                "feature-a-1 Worker": SimpleNamespace(type="worker"),
                "feature-b-1 Worker": SimpleNamespace(type="worker"),
            }
        )
        mapped: list[str] = []

        def project_name_from_service(name: str) -> str:
            mapped.append(name)
            return name.split()[0] if name.startswith("feature-") else ""

        runtime = SimpleNamespace(
            load_existing_state=lambda mode: state if mode == "trees" else None,
            project_name_from_service=project_name_from_service,
        )

        resolved = projects_for_services(runtime, ["worker", "service:worker"])

        self.assertEqual(resolved, ["feature-a-1", "feature-b-1"])
        self.assertEqual(mapped, ["feature-a-1 Worker", "feature-b-1 Worker"])

    def test_projects_for_services_prefers_additional_service_project_metadata(self) -> None:
        state = SimpleNamespace(
            services={
                "My Project Voice Runtime": SimpleNamespace(
                    name="My Project Voice Runtime",
                    type="voice-runtime",
                    project="My Project",
                )
            }
        )
        mapped: list[str] = []
        runtime = SimpleNamespace(
            load_existing_state=lambda mode: state if mode == "trees" else None,
            project_name_from_service=lambda name: mapped.append(name) or "",
        )

        resolved = projects_for_services(runtime, ["voice-runtime"])

        self.assertEqual(resolved, ["My Project"])
        self.assertEqual(mapped, [])

    def test_resolve_action_targets_uses_single_candidate_without_prompt(self) -> None:
        target = _Target(name="feature-a-1", root="/tmp/repo/trees/feature-a/1")
        runtime = SimpleNamespace(
            discover_projects=lambda mode: [target] if mode == "trees" else [],
            selectors_from_passthrough=lambda _args: [],
        )
        route = parse_route(["test"], env={"ENVCTL_DEFAULT_MODE": "trees"})

        selected, error = resolve_action_targets(
            runtime=runtime,
            route=route,
            trees_only=False,
            resolve_current_worktree_target=lambda **_kwargs: None,
            interactive_selection_allowed=lambda _route: False,
            no_target_selected_message=lambda _route: "no target",
        )

        self.assertEqual(selected, [target])
        self.assertIsNone(error)

    def test_resolve_action_targets_prefers_current_worktree_for_tree_mode_action_commands(self) -> None:
        current = _Target(name="feature-a-1", root="/tmp/repo/trees/feature-a/1")
        other = _Target(name="feature-b-1", root="/tmp/repo/trees/feature-b/1")
        runtime = SimpleNamespace(
            discover_projects=lambda mode: [current, other] if mode == "trees" else [],
            selectors_from_passthrough=lambda _args: [],
        )
        route = parse_route(["test-focused"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        calls: list[dict[str, object]] = []

        selected, error = resolve_action_targets(
            runtime=runtime,
            route=route,
            trees_only=False,
            resolve_current_worktree_target=lambda **kwargs: calls.append(kwargs) or current,
            interactive_selection_allowed=lambda _route: False,
            no_target_selected_message=lambda _route: "no target",
        )

        self.assertEqual(selected, [current])
        self.assertIsNone(error)
        self.assertEqual(calls, [{"require_configured_main_root": False, "require_configured_root_match": True}])

    def test_unresolved_external_checkout_never_falls_back_to_main_candidate(self) -> None:
        main = _Target(name="Main", root="/tmp/repo")
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                base_dir=Path("/tmp/repo"),
                execution_root=Path("/tmp/envctl-external-worktree"),
            ),
            discover_projects=lambda mode: [main] if mode == "main" else [],
            selectors_from_passthrough=lambda _args: [],
        )
        route = parse_route(["ship"], env={"ENVCTL_DEFAULT_MODE": "main"})

        selected, error = resolve_action_targets(
            runtime=runtime,
            route=route,
            trees_only=False,
            resolve_current_worktree_target=lambda **_kwargs: None,
            interactive_selection_allowed=lambda _route: False,
            no_target_selected_message=lambda _route: "no ship target",
        )

        self.assertEqual(selected, [])
        self.assertEqual(error, "no ship target")

    def test_all_current_checkout_actions_prefer_external_linked_target_in_both_modes(self) -> None:
        external = _Target(name="feature/external", root="/tmp/envctl-external-worktree")
        main = _Target(name="Main", root="/tmp/repo")
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                base_dir=Path("/tmp/repo"),
                execution_root=Path(external.root),
            ),
            discover_projects=lambda mode: [main] if mode == "main" else [],
            selectors_from_passthrough=lambda _args: [],
        )

        for mode in ("trees", "main"):
            for command in ("ship", "pr", "commit", "test", "test-focused"):
                with self.subTest(mode=mode, command=command):
                    calls: list[dict[str, object]] = []
                    route = parse_route([command], env={"ENVCTL_DEFAULT_MODE": mode})

                    selected, error = resolve_action_targets(
                        runtime=runtime,
                        route=route,
                        trees_only=False,
                        resolve_current_worktree_target=lambda **kwargs: calls.append(kwargs) or external,
                        interactive_selection_allowed=lambda _route: False,
                        no_target_selected_message=lambda _route: "no target",
                    )

                    self.assertEqual(selected, [external])
                    self.assertIsNone(error)
                    self.assertEqual(
                        calls,
                        [
                            {
                                "require_configured_main_root": mode == "main",
                                "require_configured_root_match": True,
                            }
                        ],
                    )

    def test_resolve_action_targets_explicit_project_overrides_current_worktree(self) -> None:
        current = _Target(name="feature-a-1", root="/tmp/repo/trees/feature-a/1")
        requested = _Target(name="feature-b-1", root="/tmp/repo/trees/feature-b/1")
        runtime = SimpleNamespace(
            discover_projects=lambda mode: [current, requested] if mode == "trees" else [],
            selectors_from_passthrough=lambda _args: [],
        )
        route = parse_route(
            ["test", "--project", "feature-b-1"],
            env={"ENVCTL_DEFAULT_MODE": "trees"},
        )

        selected, error = resolve_action_targets(
            runtime=runtime,
            route=route,
            trees_only=False,
            resolve_current_worktree_target=lambda **_kwargs: current,
            interactive_selection_allowed=lambda _route: False,
            no_target_selected_message=lambda _route: "no target",
        )

        self.assertEqual(selected, [requested])
        self.assertIsNone(error)

    def test_resolve_action_targets_unknown_service_does_not_fall_through_to_single_project(self) -> None:
        target = _Target(name="feature-a-1", root="/tmp/repo/trees/feature-a/1")
        runtime = SimpleNamespace(
            discover_projects=lambda mode: [target] if mode == "trees" else [],
            selectors_from_passthrough=lambda _args: [],
            load_existing_state=lambda mode: None,
            project_name_from_service=lambda _name: "",
        )
        route = parse_route(
            ["test", "--service", "missing-worker"],
            env={"ENVCTL_DEFAULT_MODE": "trees"},
        )

        selected, error = resolve_action_targets(
            runtime=runtime,
            route=route,
            trees_only=False,
            resolve_current_worktree_target=lambda **_kwargs: target,
            interactive_selection_allowed=lambda _route: False,
            no_target_selected_message=lambda _route: "no target",
        )

        self.assertEqual(selected, [])
        self.assertEqual(error, "No matching targets found for: missing-worker")

    def test_resolve_action_targets_rejects_partial_service_match(self) -> None:
        target = _Target(name="feature-a-1", root="/tmp/repo/trees/feature-a/1")
        state = SimpleNamespace(
            services={"feature-a-1 Worker": SimpleNamespace(type="worker")}
        )
        runtime = SimpleNamespace(
            discover_projects=lambda mode: [target] if mode == "trees" else [],
            selectors_from_passthrough=lambda _args: [],
            load_existing_state=lambda mode: state if mode == "trees" else None,
            project_name_from_service=lambda name: name.split()[0] if name.startswith("feature-") else "",
        )
        route = parse_route(
            ["test", "--service", "worker", "--service", "misspelled"],
            env={"ENVCTL_DEFAULT_MODE": "trees"},
        )

        selected, error = resolve_action_targets(
            runtime=runtime,
            route=route,
            trees_only=False,
            resolve_current_worktree_target=lambda **_kwargs: target,
            interactive_selection_allowed=lambda _route: False,
            no_target_selected_message=lambda _route: "no target",
        )

        self.assertEqual(selected, [])
        self.assertEqual(error, "No matching targets found for: misspelled")

    def test_resolve_action_targets_untested_does_not_auto_select_single_project(self) -> None:
        target = _Target(name="feature-a-1", root="/tmp/repo/trees/feature-a/1")
        runtime = SimpleNamespace(
            discover_projects=lambda mode: [target] if mode == "trees" else [],
            selectors_from_passthrough=lambda _args: [],
        )
        route = parse_route(["test", "--untested"], env={"ENVCTL_DEFAULT_MODE": "trees"})

        selected, error = resolve_action_targets(
            runtime=runtime,
            route=route,
            trees_only=False,
            resolve_current_worktree_target=lambda **_kwargs: target,
            interactive_selection_allowed=lambda _route: False,
            no_target_selected_message=lambda _route: "no target",
        )

        self.assertEqual(selected, [])
        self.assertIsNone(error)

    def test_resolve_action_targets_applies_interactive_selection(self) -> None:
        target_a = _Target(name="feature-a-1", root="/tmp/repo/trees/feature-a/1")
        target_b = _Target(name="feature-b-1", root="/tmp/repo/trees/feature-b/1")

        class _Selection:
            cancelled = False

            def apply_to_route(self, route):  # noqa: ANN001
                route.projects.append("feature-b-1")

        calls: list[dict[str, object]] = []
        runtime = SimpleNamespace(
            discover_projects=lambda mode: [target_a, target_b] if mode == "trees" else [],
            selectors_from_passthrough=lambda _args: [],
            select_project_targets=lambda **kwargs: calls.append(kwargs) or _Selection(),
        )
        route = parse_route(["test"], env={"ENVCTL_DEFAULT_MODE": "trees"})

        selected, error = resolve_action_targets(
            runtime=runtime,
            route=route,
            trees_only=False,
            resolve_current_worktree_target=lambda **_kwargs: None,
            interactive_selection_allowed=lambda _route: True,
            no_target_selected_message=lambda _route: "no target",
        )

        self.assertEqual(selected, [target_b])
        self.assertIsNone(error)
        self.assertEqual(calls[0]["prompt"], "Select test target")
        self.assertTrue(calls[0]["allow_untested"])

    def test_resolve_action_targets_rejects_partial_explicit_match(self) -> None:
        target = _Target(name="feature-a-1", root="/tmp/repo/trees/feature-a/1")
        runtime = SimpleNamespace(
            discover_projects=lambda mode: [target] if mode == "trees" else [],
            selectors_from_passthrough=lambda _args: [],
        )
        route = parse_route(
            ["test", "--project", "feature-a-1", "--project", "misspelled"],
            env={"ENVCTL_DEFAULT_MODE": "trees"},
        )

        selected, error = resolve_action_targets(
            runtime=runtime,
            route=route,
            trees_only=False,
            resolve_current_worktree_target=lambda **_kwargs: None,
            interactive_selection_allowed=lambda _route: False,
            no_target_selected_message=lambda _route: "no target",
        )

        self.assertEqual(selected, [])
        self.assertEqual(error, "No matching targets found for: misspelled")

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

    def test_execute_targeted_action_can_replace_generic_success_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = _Target(name="Main", root=tmpdir)
            printed: list[str] = []
            emitted: list[str] = []

            code = execute_targeted_action(
                targets=[target],
                command_name="ship",
                interactive_command=False,
                resolve_command=lambda _context: ActionCommandResolution(command=["envctl", "ship"], cwd=Path(tmpdir)),
                build_env=lambda _context: {},
                process_run=lambda _command, _cwd, _env: _Completed(
                    returncode=0,
                    stdout='{"contract_version": "envctl.ship.v1", "status": "checks_pending_timeout"}\n',
                ),
                emit_status=emitted.append,
                printer=printed.append,
                emit_success_output=False,
                success_print_formatter=lambda context, _completed: (
                    f"ship handoff status for {context.name}: checks_pending_timeout"
                ),
                success_status_formatter=lambda context, _completed: (
                    f"ship handoff status for {context.name}: checks_pending_timeout"
                ),
            )

            self.assertEqual(code, 0)
            self.assertEqual(printed, ["ship handoff status for Main: checks_pending_timeout"])
            self.assertIn("ship handoff status for Main: checks_pending_timeout", emitted)
            self.assertNotIn("ship action succeeded for Main.", printed)
            self.assertNotIn("ship succeeded for Main", emitted)

    def test_execute_targeted_action_counts_invalid_targets_and_keeps_valid_progress_accurate(self) -> None:
        printed: list[str] = []
        emitted: list[str] = []

        code = execute_targeted_action(
            targets=[
                _Target(name="", root="/tmp/invalid"),
                _Target(name="feature-a-1", root="/tmp/feature-a-1"),
            ],
            command_name="test",
            interactive_command=False,
            resolve_command=lambda context: ActionCommandResolution(command=["true"], cwd=context.root),
            build_env=lambda _context: {},
            process_run=lambda _command, _cwd, _env: _Completed(returncode=0),
            emit_status=emitted.append,
            printer=printed.append,
        )

        self.assertEqual(code, 1)
        self.assertIn("test action skipped 1 invalid target(s) without both a name and root.", printed)
        self.assertIn("Running test for feature-a-1 (1/1)...", emitted)
        self.assertIn("test action succeeded for feature-a-1.", printed)

    def test_execute_targeted_action_contains_callback_exception_and_continues_other_targets(self) -> None:
        targets = [
            _Target(name="feature-a-1", root="/tmp/feature-a-1"),
            _Target(name="feature-b-1", root="/tmp/feature-b-1"),
        ]
        processed: list[str] = []
        failures: list[tuple[str, str]] = []

        def build_env(context):  # noqa: ANN001,ANN202
            if context.name == "feature-a-1":
                raise RuntimeError("broken environment")
            return {}

        code = execute_targeted_action(
            targets=targets,
            command_name="test",
            interactive_command=False,
            resolve_command=lambda context: ActionCommandResolution(command=["true"], cwd=context.root),
            build_env=build_env,
            process_run=lambda _command, cwd, _env: processed.append(cwd.name) or _Completed(returncode=0),
            emit_status=lambda _message: None,
            printer=lambda _message: None,
            on_failure=lambda context, error: failures.append((context.name, error)),
        )

        self.assertEqual(code, 1)
        self.assertEqual(failures, [("feature-a-1", "RuntimeError: broken environment")])
        self.assertEqual(processed, ["feature-b-1"])

    def test_execute_targeted_action_rejects_empty_target_list(self) -> None:
        printed: list[str] = []
        emitted: list[str] = []

        code = execute_targeted_action(
            targets=[],
            command_name="review",
            interactive_command=False,
            resolve_command=lambda _context: ActionCommandResolution(command=["true"], cwd=Path("/tmp")),
            build_env=lambda _context: {},
            process_run=lambda _command, _cwd, _env: _Completed(returncode=0),
            emit_status=emitted.append,
            printer=printed.append,
        )

        self.assertEqual(code, 1)
        self.assertEqual(printed, ["review action failed: no targets were provided."])
        self.assertEqual(emitted, printed)


if __name__ == "__main__":
    unittest.main()
