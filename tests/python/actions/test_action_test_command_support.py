from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from envctl_engine.actions.action_test_command_support import ConfiguredTestSpecResolver
from envctl_engine.actions.action_test_command_support import ActionTestExecutionSpecBuilder
from envctl_engine.actions.action_test_command_support import SharedTestCommandPlanner
from envctl_engine.actions.action_test_command_support import build_test_execution_specs
from envctl_engine.actions.action_test_command_support import normalize_backend_python_test_command
from envctl_engine.actions.action_test_support_models import TestTargetContext as TargetContext


class ActionTestCommandSupportTests(unittest.TestCase):
    def test_command_support_uses_named_planners_instead_of_inline_branching(self) -> None:
        self.assertTrue(callable(ActionTestExecutionSpecBuilder.build))
        self.assertTrue(callable(ConfiguredTestSpecResolver.resolve))
        self.assertTrue(callable(SharedTestCommandPlanner.build))

    def test_shared_legacy_tree_command_collapses_to_one_all_targets_spec(self) -> None:
        repo = Path("/repo")
        target = TargetContext(
            project_name="feature-a-1",
            project_root=Path("/repo/trees/feature-a/1"),
            target_obj=SimpleNamespace(name="feature-a-1"),
        )

        specs = build_test_execution_specs(
            shared_raw_command="bash scripts/test-all-trees.sh",
            backend_raw_command=None,
            frontend_raw_command=None,
            target_contexts=[target],
            repo_root=repo,
            include_backend=True,
            include_frontend=True,
            frontend_test_path=None,
            run_all=False,
            untested=True,
            split_command=lambda raw, _replacements: raw.split(),
            replacements_for_target=lambda _target: {},
            is_legacy_tree_test_script=lambda command: command == ["bash", "scripts/test-all-trees.sh"],
        )

        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].project_name, "all-targets")
        self.assertEqual(specs[0].spec.cwd, repo)
        self.assertEqual(specs[0].args, ["projects=feature-a-1", "untested=true"])

    def test_shared_frontend_package_command_normalizes_target_and_all_target_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            feature = repo / "trees" / "feature-a" / "1"
            frontend = feature / "frontend"
            frontend.mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text('{"scripts":{"test":"vitest"}}', encoding="utf-8")
            target = TargetContext(
                project_name="feature-a-1",
                project_root=feature,
                target_obj=SimpleNamespace(name="feature-a-1"),
            )

            specs = build_test_execution_specs(
                shared_raw_command="pnpm run test",
                backend_raw_command=None,
                frontend_raw_command=None,
                target_contexts=[target],
                repo_root=repo,
                include_backend=False,
                include_frontend=True,
                frontend_test_path="frontend/src",
                run_all=False,
                untested=False,
                split_command=lambda raw, _replacements: raw.split(),
                replacements_for_target=lambda _target: {},
                is_legacy_tree_test_script=lambda _command: False,
            )

        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].spec.cwd, frontend)
        self.assertEqual(specs[0].spec.command, ["pnpm", "run", "test", "--", "src"])
        self.assertEqual(specs[0].spec.source, "frontend_package_test")

    def test_backend_python_normalization_uses_poetry_project_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            backend = project_root / "backend"
            backend.mkdir(parents=True, exist_ok=True)
            (backend / "pyproject.toml").write_text("[tool.poetry]\nname = 'backend'\n", encoding="utf-8")

            command = normalize_backend_python_test_command(
                ["python", "-m", "pytest"],
                project_root,
                pyproject_uses_poetry_fn=lambda _path: True,
                which_fn=lambda name: f"/usr/bin/{name}" if name == "poetry" else None,
                detect_python_bin_fn=lambda *_roots: str(backend / ".venv" / "bin" / "python"),
            )

        self.assertEqual(command, ["poetry", "--project", str(backend), "run", "python", "-m", "pytest"])


if __name__ == "__main__":
    unittest.main()
