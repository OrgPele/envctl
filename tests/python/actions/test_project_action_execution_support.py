from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest

from envctl_engine.actions.action_target_support import ActionCommandResolution
from envctl_engine.actions.project_action_execution_support import run_project_action
from envctl_engine.runtime.command_router import parse_route


class _Runner:
    def __init__(self) -> None:
        self.run_calls: list[dict[str, object]] = []
        self.streaming_calls: list[dict[str, object]] = []

    def run(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.run_calls.append({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    def run_streaming(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.streaming_calls.append({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0, stdout="streamed\n", stderr="")


class ProjectActionExecutionSupportTests(unittest.TestCase):
    def test_missing_command_reports_configuration_gap(self) -> None:
        route = parse_route(["review"], env={"ENVCTL_DEFAULT_MODE": "main"})
        runtime = SimpleNamespace(env={})
        stdout = StringIO()

        with redirect_stdout(stdout):
            code = run_project_action(
                runtime=runtime,
                route=route,
                targets=[],
                command_name="review",
                env_key="ENVCTL_ACTION_ANALYZE_CMD",
                default_command=None,
                default_cwd=Path("/repo"),
                default_append_project_path=False,
                extra_env={},
                action_replacements_builder=lambda _targets, target: {},
                action_env_builder=lambda *_args, **_kwargs: {},
                emit_status=lambda _message: None,
                success_handler=lambda *_args, **_kwargs: None,
                failure_handler=lambda *_args, **_kwargs: None,
                stdout_is_live_terminal=lambda: False,
                execute_targeted_action_fn=lambda **_kwargs: 99,
            )

        self.assertEqual(code, 1)
        self.assertIn("No review command configured. Set ENVCTL_ACTION_ANALYZE_CMD", stdout.getvalue())

    def test_raw_command_uses_runtime_split_command_with_replacements(self) -> None:
        route = parse_route(["pr", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        target = SimpleNamespace(name="feature-a-1", root="/repo/trees/feature-a/1")
        captured: dict[str, object] = {}

        def execute_targeted_action_fn(**kwargs: object) -> int:
            captured.update(kwargs)
            context = SimpleNamespace(name="feature-a-1", root=target.root, target_obj=target)
            resolution = kwargs["resolve_command"](context)
            env = kwargs["build_env"](context)
            captured["resolution"] = resolution
            captured["env"] = env
            return 17

        runtime = SimpleNamespace(
            env={"ENVCTL_ACTION_PR_CMD": "gh pr create --head {project}"},
            process_runner=_Runner(),
            split_command=lambda raw, replacements: ["gh", "pr", "create", "--head", replacements["project"]],
        )

        code = run_project_action(
            runtime=runtime,
            route=route,
            targets=[target],
            command_name="pr",
            env_key="ENVCTL_ACTION_PR_CMD",
            default_command=["unused"],
            default_cwd=Path("/repo"),
            default_append_project_path=False,
            extra_env={"ENVCTL_PR_BASE": "main"},
            action_replacements_builder=lambda _targets, target: {
                "project": target.name,
                "project_root": str(target.root),
            },
            action_env_builder=lambda command_name, targets, route, target, extra: {
                "command": command_name,
                "project": target.name,
                **dict(extra),
            },
            emit_status=lambda _message: None,
            success_handler=lambda *_args, **_kwargs: "success-handler",
            failure_handler=lambda *_args, **_kwargs: "failure-handler",
            stdout_is_live_terminal=lambda: True,
            execute_targeted_action_fn=execute_targeted_action_fn,
        )

        self.assertEqual(code, 17)
        resolution = captured["resolution"]
        self.assertIsInstance(resolution, ActionCommandResolution)
        self.assertEqual(resolution.command, ["gh", "pr", "create", "--head", "feature-a-1"])
        self.assertEqual(resolution.cwd, Path("/repo/trees/feature-a/1"))
        self.assertEqual(captured["env"], {"command": "pr", "project": "feature-a-1", "ENVCTL_PR_BASE": "main"})
        self.assertTrue(captured["interactive_print_failures"])

    def test_default_command_substitutes_replacements_and_can_append_project_path(self) -> None:
        route = parse_route(["review", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        target = SimpleNamespace(name="feature-a-1", root="/repo/trees/feature-a/1")
        captured: dict[str, object] = {}

        def execute_targeted_action_fn(**kwargs: object) -> int:
            context = SimpleNamespace(name="feature-a-1", root=target.root, target_obj=target)
            captured["resolution"] = kwargs["resolve_command"](context)
            return 0

        runtime = SimpleNamespace(env={}, process_runner=_Runner())

        run_project_action(
            runtime=runtime,
            route=route,
            targets=[target],
            command_name="review",
            env_key="ENVCTL_ACTION_ANALYZE_CMD",
            default_command=["review-tool", "--repo", "{repo_root}", "--project", "{project}"],
            default_cwd=Path("/repo"),
            default_append_project_path=True,
            extra_env={},
            action_replacements_builder=lambda _targets, target: {
                "repo_root": "/repo",
                "project": target.name,
            },
            action_env_builder=lambda *_args, **_kwargs: {},
            emit_status=lambda _message: None,
            success_handler=lambda *_args, **_kwargs: None,
            failure_handler=lambda *_args, **_kwargs: None,
            stdout_is_live_terminal=lambda: True,
            execute_targeted_action_fn=execute_targeted_action_fn,
        )

        resolution = captured["resolution"]
        self.assertEqual(
            resolution.command,
            ["review-tool", "--repo", "/repo", "--project", "feature-a-1", "/repo/trees/feature-a/1"],
        )
        self.assertEqual(resolution.cwd, Path("/repo"))

    def test_noninteractive_live_review_streams_output_and_forces_rich_env(self) -> None:
        route = parse_route(["review", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        target = SimpleNamespace(name="feature-a-1", root="/repo/trees/feature-a/1")
        runner = _Runner()
        captured: dict[str, object] = {}

        def execute_targeted_action_fn(**kwargs: object) -> int:
            context = SimpleNamespace(name="feature-a-1", root=target.root, target_obj=target)
            env = kwargs["build_env"](context)
            completed = kwargs["process_run"](["review-tool"], Path("/repo"), env)
            captured["env"] = env
            captured["completed"] = completed
            captured["emit_success_output"] = kwargs["emit_success_output"]
            return completed.returncode

        runtime = SimpleNamespace(env={}, process_runner=runner)

        code = run_project_action(
            runtime=runtime,
            route=route,
            targets=[target],
            command_name="review",
            env_key="ENVCTL_ACTION_ANALYZE_CMD",
            default_command=["review-tool"],
            default_cwd=Path("/repo"),
            default_append_project_path=False,
            extra_env={},
            action_replacements_builder=lambda _targets, target: {"project": target.name},
            action_env_builder=lambda _command_name, _targets, route, target, extra: dict(extra),
            emit_status=lambda _message: None,
            success_handler=lambda *_args, **_kwargs: None,
            failure_handler=lambda *_args, **_kwargs: None,
            stdout_is_live_terminal=lambda: True,
            execute_targeted_action_fn=execute_targeted_action_fn,
        )

        self.assertEqual(code, 0)
        self.assertEqual(captured["env"], {"ENVCTL_ACTION_FORCE_RICH": "1"})
        self.assertEqual(len(runner.streaming_calls), 1)
        self.assertEqual(runner.run_calls, [])
        completed = captured["completed"]
        self.assertEqual(completed.stdout, "")
        self.assertFalse(captured["emit_success_output"])

    def test_noninteractive_live_ship_streams_output_and_retains_stdout_for_status(self) -> None:
        route = parse_route(["ship", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        target = SimpleNamespace(name="feature-a-1", root="/repo/trees/feature-a/1")
        runner = _Runner()
        ship_output = (
            "ship: GitHub checks still running after 10s (pending=1, passed=0, failed=0, timeout=120s)\n"
            "{\n"
            '  "contract_version": "envctl.ship.v1",\n'
            '  "operation_statuses": {"commit": "success", "push": "success", "pr": "existing", "merge_conflicts": "none", "checks": "checks_passed"},\n'
            '  "status": "checks_passed"\n'
            "}\n"
        )

        def run_streaming(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            runner.streaming_calls.append({"command": command, **kwargs})
            return subprocess.CompletedProcess(command, 0, stdout=ship_output, stderr="")

        runner.run_streaming = run_streaming  # type: ignore[method-assign]
        captured: dict[str, object] = {}

        def execute_targeted_action_fn(**kwargs: object) -> int:
            context = SimpleNamespace(name="feature-a-1", root=target.root, target_obj=target)
            completed = kwargs["process_run"](["envctl", "ship"], Path("/repo"), {})
            captured["completed"] = completed
            captured["emit_success_output"] = kwargs["emit_success_output"]
            captured["print_noninteractive_failures"] = kwargs["print_noninteractive_failures"]
            captured["print_message"] = kwargs["success_print_formatter"](context, completed)
            return completed.returncode

        runtime = SimpleNamespace(env={}, process_runner=runner)

        code = run_project_action(
            runtime=runtime,
            route=route,
            targets=[target],
            command_name="ship",
            env_key="ENVCTL_ACTION_SHIP_CMD",
            default_command=["envctl", "ship"],
            default_cwd=Path("/repo"),
            default_append_project_path=False,
            extra_env={},
            action_replacements_builder=lambda _targets, target: {"project": target.name},
            action_env_builder=lambda *_args, **_kwargs: {},
            emit_status=lambda _message: None,
            success_handler=lambda *_args, **_kwargs: None,
            failure_handler=lambda *_args, **_kwargs: None,
            stdout_is_live_terminal=lambda: False,
            execute_targeted_action_fn=execute_targeted_action_fn,
        )

        self.assertEqual(code, 0)
        self.assertEqual(runner.run_calls, [])
        self.assertEqual(len(runner.streaming_calls), 1)
        stream_call = runner.streaming_calls[0]
        self.assertEqual(stream_call["command"], ["envctl", "ship"])
        self.assertTrue(callable(stream_call["callback"]))
        completed = captured["completed"]
        self.assertEqual(completed.stdout, ship_output)
        self.assertFalse(captured["emit_success_output"])
        self.assertFalse(captured["print_noninteractive_failures"])
        self.assertIn("checks_passed", captured["print_message"])

    def test_ship_action_uses_structured_status_success_messages(self) -> None:
        route = parse_route(["ship", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        target = SimpleNamespace(name="feature-a-1", root="/repo/trees/feature-a/1")
        captured: dict[str, object] = {}

        def execute_targeted_action_fn(**kwargs: object) -> int:
            captured.update(kwargs)
            context = SimpleNamespace(name="feature-a-1", root=target.root, target_obj=target)
            completed = subprocess.CompletedProcess(
                ["envctl", "ship"],
                0,
                stdout=(
                    "{\n"
                    '  "contract_version": "envctl.ship.v1",\n'
                    '  "operation_statuses": {"commit": "success", "push": "success", "pr": "existing", "merge_conflicts": "none", "checks": "pending"},\n'
                    '  "pr_url": "https://github.test/acme/envctl/pull/12",\n'
                    '  "status": "checks_pending_timeout"\n'
                    "}\n"
                ),
                stderr="",
            )
            captured["print_message"] = kwargs["success_print_formatter"](context, completed)
            captured["status_message"] = kwargs["success_status_formatter"](context, completed)
            return 0

        runtime = SimpleNamespace(env={}, process_runner=_Runner())

        code = run_project_action(
            runtime=runtime,
            route=route,
            targets=[target],
            command_name="ship",
            env_key="ENVCTL_ACTION_SHIP_CMD",
            default_command=["envctl", "ship"],
            default_cwd=Path("/repo"),
            default_append_project_path=False,
            extra_env={},
            action_replacements_builder=lambda _targets, target: {"project": target.name},
            action_env_builder=lambda *_args, **_kwargs: {},
            emit_status=lambda _message: None,
            success_handler=lambda *_args, **_kwargs: None,
            failure_handler=lambda *_args, **_kwargs: None,
            stdout_is_live_terminal=lambda: False,
            execute_targeted_action_fn=execute_targeted_action_fn,
        )

        self.assertEqual(code, 0)
        self.assertIn("success_print_formatter", captured)
        self.assertIn("success_status_formatter", captured)
        self.assertIn("checks_pending_timeout", captured["print_message"])
        self.assertIn("checks_pending_timeout", captured["status_message"])
        self.assertNotIn("succeeded", captured["print_message"])


if __name__ == "__main__":
    unittest.main()
