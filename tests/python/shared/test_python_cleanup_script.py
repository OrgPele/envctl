from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from contextlib import redirect_stderr
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "python_cleanup.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("python_cleanup_script", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PythonCleanupScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_module()

    def test_resolved_paths_defaults_to_all_presets(self) -> None:
        paths = self.module._resolved_paths(REPO_ROOT, [], [])
        self.assertIn("python/envctl_engine/config", paths)
        self.assertIn("python/envctl_engine/runtime", paths)
        self.assertIn("python/envctl_engine/ui", paths)

    def test_resolved_paths_dedupes_and_preserves_order(self) -> None:
        paths = self.module._resolved_paths(REPO_ROOT, ["python/envctl_engine/state"], ["core", "core"])
        self.assertEqual(paths[0], "python/envctl_engine/state")
        self.assertEqual(paths.count("python/envctl_engine/state"), 1)
        self.assertIn("python/envctl_engine/shared", paths)

    def test_build_plan_in_report_mode_uses_check_variants(self) -> None:
        plan = self.module.build_plan(
            repo_root=REPO_ROOT,
            paths=["python/envctl_engine/config"],
            include_format=True,
            include_typecheck=True,
            include_dead_code=True,
            include_tests=True,
            fix=False,
            min_confidence=90,
        )
        stages = [item.stage for item in plan]
        self.assertEqual(
            stages,
            [
                "ruff-check",
                "ruff-format",
                "basedpyright",
                "vulture",
                "tests:tests/python/config",
            ],
        )
        self.assertIn("--check", plan[1].argv)
        self.assertEqual(
            plan[2].argv,
            [
                sys.executable,
                "-m",
                "basedpyright",
                "-p",
                "pyrightconfig.json",
                "--baselinefile",
                "basedpyright-baseline.json",
                "python/envctl_engine/config",
            ],
        )
        self.assertIn("90", plan[3].argv)
        self.assertEqual(
            plan[4].argv,
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests/python/config",
                "-p",
                "test_*.py",
            ],
        )

    def test_basedpyright_command_falls_back_without_repo_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            argv = self.module._basedpyright_command(repo_root, ["python/envctl_engine/config"])
        self.assertEqual(
            argv,
            [
                sys.executable,
                "-m",
                "basedpyright",
                "python/envctl_engine/config",
            ],
        )

    def test_build_plan_in_fix_mode_enables_ruff_fix_and_format(self) -> None:
        plan = self.module.build_plan(
            repo_root=REPO_ROOT,
            paths=["python/envctl_engine/config"],
            include_format=True,
            include_typecheck=False,
            include_dead_code=False,
            include_tests=False,
            fix=True,
            min_confidence=80,
        )
        self.assertIn("--fix", plan[0].argv)
        self.assertNotIn("--check", plan[1].argv)
        self.assertTrue(plan[0].fixes_code)
        self.assertTrue(plan[1].fixes_code)
        self.assertFalse(any(item.fixes_code for item in plan[2:]))

    def test_main_report_only_returns_zero(self) -> None:
        code = self.module.main(["--repo", str(REPO_ROOT), "--preset", "safe", "--json"])
        self.assertEqual(code, 0)

    def test_repo_root_is_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = self.module._repo_root(tmpdir)
            self.assertEqual(root, Path(tmpdir).resolve())

    def test_parse_args_defaults_to_execute_and_fix_with_positional_repo(self) -> None:
        args = self.module.parse_args([str(REPO_ROOT)])
        self.assertEqual(args.repo, str(REPO_ROOT))
        self.assertTrue(args.execute)
        self.assertTrue(args.fix)
        self.assertFalse(args.dry_run)

    def test_parse_args_dry_run_disables_execution(self) -> None:
        args = self.module.parse_args([str(REPO_ROOT), "--dry-run"])
        self.assertEqual(args.repo, str(REPO_ROOT))
        self.assertFalse(args.execute)
        self.assertTrue(args.fix)
        self.assertTrue(args.dry_run)

    def test_parse_args_no_fix_disables_ruff_autofix(self) -> None:
        args = self.module.parse_args([str(REPO_ROOT), "--no-fix"])
        self.assertTrue(args.execute)
        self.assertFalse(args.fix)

    def test_parse_args_rejects_positional_repo_and_flag_repo_together(self) -> None:
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.module.parse_args([str(REPO_ROOT), "--repo", str(REPO_ROOT)])

    def test_test_targets_map_source_domains_to_test_domains(self) -> None:
        paths = self.module._test_targets(
            REPO_ROOT,
            [
                "python/envctl_engine/config",
                "python/envctl_engine/ui/dashboard",
                "python/envctl_engine/runtime",
            ],
        )
        self.assertEqual(paths, ["tests/python/config", "tests/python/ui", "tests/python/runtime"])

    def test_test_targets_map_known_scripts_to_specific_python_tests(self) -> None:
        paths = self.module._test_targets(
            REPO_ROOT,
            [
                "scripts/python_cleanup.py",
                "scripts/analyze_debug_bundle.py",
            ],
        )
        self.assertEqual(
            paths,
            [
                "tests/python/shared/test_python_cleanup_script.py",
                "tests/python/debug/test_debug_bundle_analyzer.py",
            ],
        )

    def test_test_module_from_path_converts_file_to_unittest_module(self) -> None:
        module_name = self.module._test_module_from_path("tests/python/shared/test_python_cleanup_script.py")
        self.assertEqual(module_name, "tests.python.shared.test_python_cleanup_script")

    def test_resolved_paths_fail_for_missing_target(self) -> None:
        with self.assertRaises(SystemExit):
            self.module._resolved_paths(REPO_ROOT, ["python/envctl_engine/does_not_exist.py"], [])

    def test_required_python_modules_are_deduped_from_plan(self) -> None:
        plan = self.module.build_plan(
            repo_root=REPO_ROOT,
            paths=["python/envctl_engine/config"],
            include_format=True,
            include_typecheck=True,
            include_dead_code=True,
            include_tests=True,
            fix=True,
            min_confidence=80,
        )
        modules = self.module._required_python_modules(plan)
        self.assertEqual(modules, ["ruff", "basedpyright", "vulture", "unittest"])

    def test_ensure_python_modules_available_fails_fast_with_install_hint(self) -> None:
        with patch.object(self.module.importlib.util, "find_spec", return_value=None):
            with self.assertRaises(SystemExit) as exc:
                self.module._ensure_python_modules_available(["basedpyright"])
        self.assertIn("Missing required Python modules", str(exc.exception))
        self.assertIn(".venv/bin/python -m pip install -e '.[dev]'", str(exc.exception))

    def test_run_plan_prints_fix_scope_note(self) -> None:
        plan = self.module.build_plan(
            repo_root=REPO_ROOT,
            paths=["python/envctl_engine/config"],
            include_format=True,
            include_typecheck=False,
            include_dead_code=False,
            include_tests=False,
            fix=True,
            min_confidence=80,
        )
        output = io.StringIO()
        with (
            redirect_stdout(output),
            patch.object(self.module, "_ensure_python_modules_available"),
            patch.object(self.module.subprocess, "run", return_value=type("Result", (), {"returncode": 0})()),
        ):
            code = self.module._run_plan(plan, fix=True)
        self.assertEqual(code, 0)
        self.assertIn("note: --fix only applies Ruff autofixes/formatting", output.getvalue())

    def test_run_plan_writes_tool_output_to_log_file_instead_of_stdout(self) -> None:
        plan = self.module.build_plan(
            repo_root=REPO_ROOT,
            paths=["python/envctl_engine/config"],
            include_format=False,
            include_typecheck=False,
            include_dead_code=False,
            include_tests=False,
            fix=False,
            min_confidence=80,
        )
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "cleanup.log"

            def _fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
                kwargs["stdout"].write("tool output\n")
                return type("Result", (), {"returncode": 0})()

            with (
                redirect_stdout(output),
                patch.object(self.module, "_ensure_python_modules_available"),
                patch.object(self.module.subprocess, "run", side_effect=_fake_run),
            ):
                code = self.module._run_plan(plan, fix=False, log_file=log_file)
            self.assertEqual(code, 0)
            rendered = output.getvalue()
            self.assertIn("python-cleanup log:", rendered)
            self.assertIn("python-cleanup completed; see log:", rendered)
            self.assertNotIn("tool output", rendered)
            self.assertTrue(log_file.is_file())
            self.assertIn("tool output", log_file.read_text(encoding="utf-8"))

    def test_main_executes_by_default(self) -> None:
        with patch.object(self.module, "_run_plan", return_value=0) as run_plan:
            code = self.module.main(
                [str(REPO_ROOT), "--skip-format", "--skip-typecheck", "--skip-dead-code", "--skip-tests"]
            )
        self.assertEqual(code, 0)
        run_plan.assert_called_once()


if __name__ == "__main__":
    unittest.main()
