from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


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

    def test_main_report_only_returns_zero(self) -> None:
        code = self.module.main(["--repo", str(REPO_ROOT), "--preset", "safe", "--json"])
        self.assertEqual(code, 0)

    def test_repo_root_is_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = self.module._repo_root(tmpdir)
            self.assertEqual(root, Path(tmpdir).resolve())

    def test_test_targets_map_source_domains_to_test_domains(self) -> None:
        paths = self.module._test_targets(
            REPO_ROOT,
            [
                "python/envctl_engine/config",
                "python/envctl_engine/ui/dashboard",
                "python/envctl_engine/runtime",
            ]
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


if __name__ == "__main__":
    unittest.main()
