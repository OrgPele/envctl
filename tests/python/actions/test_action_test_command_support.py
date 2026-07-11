from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from envctl_engine.actions import action_test_command_support
from envctl_engine.actions.action_test_command_support import ConfiguredTestSpecResolver
from envctl_engine.actions.action_test_command_support import ActionTestExecutionSpecBuilder
from envctl_engine.actions.action_test_command_support import SharedTestCommandPlanner
from envctl_engine.actions.action_test_command_support import build_test_execution_specs
from envctl_engine.actions.action_test_command_support import build_test_target_contexts
from envctl_engine.actions.action_test_command_support import is_legacy_tree_test_script
from envctl_engine.actions.action_test_command_support import normalize_backend_python_test_command
from envctl_engine.actions.action_test_support_models import TestTargetContext as TargetContext


class ActionTestCommandSupportTests(unittest.TestCase):
    def test_command_support_uses_named_planners_instead_of_inline_branching(self) -> None:
        self.assertEqual(
            set(ActionTestExecutionSpecBuilder.__dataclass_fields__),
            {"commands", "target_scope", "planning_scope", "dependencies"},
        )
        self.assertTrue(hasattr(action_test_command_support, "ActionTestCommandSources"))
        self.assertTrue(hasattr(action_test_command_support, "ActionTestCommandTargetScope"))
        self.assertTrue(hasattr(action_test_command_support, "ActionTestCommandPlanningScope"))
        self.assertTrue(hasattr(action_test_command_support, "ActionTestCommandDependencies"))
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

    def test_empty_target_contexts_keep_main_fallback_for_non_aggregate_callers(self) -> None:
        repo = Path("/repo")

        contexts = build_test_target_contexts([], repo_root=repo)

        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0].project_name, "Main")
        self.assertEqual(contexts[0].project_root, repo)
        self.assertIsNone(contexts[0].target_obj)

    def test_legacy_tree_script_detection_accepts_absolute_bash_path(self) -> None:
        self.assertTrue(is_legacy_tree_test_script(["bash", "scripts/test-all-trees.sh"]))
        self.assertTrue(is_legacy_tree_test_script(["/bin/bash", "/repo/scripts/test-all-trees.sh"]))
        self.assertFalse(is_legacy_tree_test_script(["zsh", "/repo/scripts/test-all-trees.sh"]))
        self.assertFalse(is_legacy_tree_test_script(["/bin/bash", "/repo/scripts/test-one-tree.sh"]))

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

    def test_package_test_aliases_are_treated_as_frontend_package_test_commands(self) -> None:
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

            for manager in ("npm", "pnpm", "bun"):
                with self.subTest(manager=manager):
                    specs = build_test_execution_specs(
                        shared_raw_command=f"{manager} test",
                        backend_raw_command=None,
                        frontend_raw_command=None,
                        target_contexts=[target],
                        repo_root=repo,
                        include_backend=False,
                        include_frontend=True,
                        frontend_test_path="frontend/src/App.test.tsx",
                        run_all=False,
                        untested=False,
                        split_command=lambda raw, _replacements: raw.split(),
                        replacements_for_target=lambda _target: {},
                        is_legacy_tree_test_script=lambda _command: False,
                    )

                    self.assertEqual(len(specs), 1)
                    self.assertEqual(specs[0].spec.cwd, frontend)
                    self.assertEqual(specs[0].spec.command, [manager, "test", "--", "src/App.test.tsx"])
                    self.assertEqual(specs[0].spec.source, "frontend_package_test")

    def test_configured_frontend_path_is_normalized_against_resolved_command_cwd(self) -> None:
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
            resolver = ConfiguredTestSpecResolver(
                repo_root=repo,
                frontend_test_path="frontend/src/App.test.tsx",
                split_command=lambda raw, _replacements: raw.split(),
                replacements_for_target=lambda _target: {},
                normalize_backend_command=lambda command, _root: list(command),
                default_test_commands=lambda **_kwargs: [],
            )

            spec = resolver.resolve(
                raw_command="npm test",
                target=target,
                include_backend=False,
                include_frontend=True,
                configured_test_command_cwd_fn=lambda project_root: project_root,
            )

        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.cwd, feature)
        self.assertEqual(spec.command, ["npm", "test", "--", "frontend/src/App.test.tsx"])

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

    def test_backend_python_normalization_uses_root_poetry_project_without_backend_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            project_root.mkdir(parents=True, exist_ok=True)
            (project_root / "pyproject.toml").write_text("[tool.poetry]\nname = 'backend'\n", encoding="utf-8")

            command = normalize_backend_python_test_command(
                ["python", "-m", "pytest"],
                project_root,
                pyproject_uses_poetry_fn=lambda path: path == project_root / "pyproject.toml",
                which_fn=lambda name: f"/usr/bin/{name}" if name == "poetry" else None,
                detect_python_bin_fn=lambda *_roots: "python3.12",
            )

        self.assertEqual(command, ["poetry", "--project", str(project_root), "run", "python", "-m", "pytest"])

    def test_backend_python_normalization_uses_root_poetry_project_when_backend_dir_is_plain(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            backend = project_root / "backend"
            backend.mkdir(parents=True, exist_ok=True)
            (project_root / "pyproject.toml").write_text("[tool.poetry]\nname = 'backend'\n", encoding="utf-8")

            command = normalize_backend_python_test_command(
                ["python", "-m", "pytest"],
                project_root,
                pyproject_uses_poetry_fn=lambda path: path == project_root / "pyproject.toml",
                which_fn=lambda name: f"/usr/bin/{name}" if name == "poetry" else None,
                detect_python_bin_fn=lambda *_roots: "python3.12",
            )

        self.assertEqual(command, ["poetry", "--project", str(project_root), "run", "python", "-m", "pytest"])

    def test_backend_python_normalization_does_not_cross_backend_project_boundary_for_poetry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            backend = project_root / "backend"
            backend.mkdir(parents=True, exist_ok=True)
            (project_root / "pyproject.toml").write_text("[tool.poetry]\nname = 'repo'\n", encoding="utf-8")
            (backend / "pyproject.toml").write_text("[project]\nname = 'backend'\n", encoding="utf-8")

            command = normalize_backend_python_test_command(
                ["python", "-m", "pytest"],
                project_root,
                pyproject_uses_poetry_fn=lambda path: path == project_root / "pyproject.toml",
                which_fn=lambda name: f"/usr/bin/{name}" if name == "poetry" else None,
                detect_python_bin_fn=lambda *_roots: None,
            )

        self.assertEqual(command, ["python", "-m", "pytest"])

if __name__ == "__main__":
    unittest.main()
