from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import subprocess
import unittest

from envctl_engine.actions.action_migrate_execution_support import run_migrate_action
from envctl_engine.actions.action_target_support import ActionCommandResolution
from envctl_engine.runtime.command_router import parse_route


class _Runner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")


class ActionMigrateExecutionSupportTests(unittest.TestCase):
    def test_raw_migrate_command_uses_replacements_and_target_root(self) -> None:
        route = parse_route(["migrate", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        target = SimpleNamespace(name="feature-a-1", root="/repo/trees/feature-a/1")
        captured: dict[str, object] = {}
        runner = _Runner()
        runtime = SimpleNamespace(
            env={"ENVCTL_ACTION_MIGRATE_CMD": "custom migrate {project}"},
            process_runner=runner,
            split_command=lambda raw, replacements: ["custom", "migrate", replacements["project"]],
        )

        def execute_targeted_action_fn(**kwargs: object) -> int:
            captured.update(kwargs)
            context = SimpleNamespace(name="feature-a-1", root=target.root, target_obj=target)
            resolution = kwargs["resolve_command"](context)
            env = kwargs["build_env"](context)
            completed = kwargs["process_run"](resolution.command, resolution.cwd, env)
            captured["resolution"] = resolution
            captured["env"] = env
            return completed.returncode

        code = run_migrate_action(
            runtime=runtime,
            route=route,
            targets=[target],
            extra_env={"ENVCTL_PR_BASE": "main"},
            action_replacements_builder=lambda _targets, target: {"project": target.name},
            migrate_action_env_builder=lambda **kwargs: {"project": kwargs["target"].name, **dict(kwargs["extra"])},
            success_handler=lambda *_args, **_kwargs: None,
            failure_handler=lambda *_args, **_kwargs: None,
            emit_status=lambda _message: None,
            failure_summary_lines=lambda **_kwargs: [],
            failure_headline=lambda _output: "",
            print_result_summary=lambda **_kwargs: None,
            set_deferred_output=lambda _callback: None,
            execute_targeted_action_fn=execute_targeted_action_fn,
        )

        self.assertEqual(code, 0)
        resolution = captured["resolution"]
        self.assertIsInstance(resolution, ActionCommandResolution)
        self.assertEqual(resolution.command, ["custom", "migrate", "feature-a-1"])
        self.assertEqual(resolution.cwd, Path("/repo/trees/feature-a/1"))
        self.assertEqual(captured["env"], {"project": "feature-a-1", "ENVCTL_PR_BASE": "main"})
        self.assertEqual(runner.calls[0]["command"], ["custom", "migrate", "feature-a-1"])

    def test_default_migrate_resolution_is_delegated_per_target(self) -> None:
        route = parse_route(["migrate", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        target = SimpleNamespace(name="feature-a-1", root="/repo/trees/feature-a/1")
        captured: dict[str, object] = {}
        runtime = SimpleNamespace(env={}, process_runner=_Runner())

        def execute_targeted_action_fn(**kwargs: object) -> int:
            context = SimpleNamespace(name="feature-a-1", root=target.root, target_obj=target)
            captured["resolution"] = kwargs["resolve_command"](context)
            return 0

        run_migrate_action(
            runtime=runtime,
            route=route,
            targets=[target],
            extra_env={},
            action_replacements_builder=lambda _targets, target: {"project": target.name},
            migrate_action_env_builder=lambda **_kwargs: {},
            default_migrate_command_builder=lambda root: ActionCommandResolution(
                command=["python", "-m", "alembic", "upgrade", "head"],
                cwd=root / "backend",
            ),
            success_handler=lambda *_args, **_kwargs: None,
            failure_handler=lambda *_args, **_kwargs: None,
            emit_status=lambda _message: None,
            failure_summary_lines=lambda **_kwargs: [],
            failure_headline=lambda _output: "",
            print_result_summary=lambda **_kwargs: None,
            set_deferred_output=lambda _callback: None,
            execute_targeted_action_fn=execute_targeted_action_fn,
        )

        resolution = captured["resolution"]
        self.assertEqual(resolution.command, ["python", "-m", "alembic", "upgrade", "head"])
        self.assertEqual(resolution.cwd, Path("/repo/trees/feature-a/1/backend"))

    def test_failure_records_clean_summary_backend_env_and_persists_failure(self) -> None:
        route = parse_route(["migrate", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        target = SimpleNamespace(name="feature-a-1", root="/repo/trees/feature-a/1")
        persisted: list[tuple[str, str]] = []
        summaries: list[dict[str, object]] = []
        deferred: list[object] = []
        runtime = SimpleNamespace(env={}, process_runner=_Runner())

        def execute_targeted_action_fn(**kwargs: object) -> int:
            context = SimpleNamespace(name="feature-a-1", root=target.root, target_obj=target)
            kwargs["on_failure"](context, "\x1b[31mRuntimeError: bad env\x1b[0m")
            return 1

        code = run_migrate_action(
            runtime=runtime,
            route=route,
            targets=[target],
            extra_env={},
            action_replacements_builder=lambda _targets, target: {"project": target.name},
            migrate_action_env_builder=lambda **_kwargs: {},
            migrate_env_contracts={"feature-a-1": {"env_file_source": "default"}},
            success_handler=lambda *_args, **_kwargs: None,
            failure_handler=lambda context, output: persisted.append((context.name, output)),
            emit_status=lambda _message: None,
            failure_summary_lines=lambda **kwargs: ["RuntimeError: bad env", kwargs["migrate_env_metadata"]["env_file_source"]],
            failure_headline=lambda output: f"headline:{output}",
            print_result_summary=lambda **kwargs: summaries.append(kwargs),
            set_deferred_output=lambda callback: deferred.append(callback),
            execute_targeted_action_fn=execute_targeted_action_fn,
        )

        self.assertEqual(code, 1)
        self.assertEqual(persisted, [("feature-a-1", "\x1b[31mRuntimeError: bad env\x1b[0m")])
        self.assertEqual(len(deferred), 1)
        deferred[0]()
        self.assertEqual(summaries[0]["fallback_entries"]["feature-a-1"]["status"], "failed")
        self.assertEqual(summaries[0]["fallback_entries"]["feature-a-1"]["headline"], "headline:RuntimeError: bad env")
        self.assertEqual(
            summaries[0]["fallback_entries"]["feature-a-1"]["summary"],
            "RuntimeError: bad env\ndefault",
        )
        self.assertEqual(
            summaries[0]["fallback_entries"]["feature-a-1"]["backend_env"],
            {"env_file_source": "default"},
        )


if __name__ == "__main__":
    unittest.main()
