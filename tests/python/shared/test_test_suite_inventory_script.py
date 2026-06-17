from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "test_suite_inventory.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("test_suite_inventory_script", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestSuiteInventoryScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_module()

    def test_collect_inventory_reports_counts_helpers_markers_and_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            unit_dir = repo / "tests" / "python" / "unit"
            runtime_dir = repo / "tests" / "python" / "runtime"
            unit_dir.mkdir(parents=True)
            runtime_dir.mkdir(parents=True)
            (unit_dir / "unit_test_support.py").write_text(
                "def helper():\n"
                "    return None\n",
                encoding="utf-8",
            )
            (unit_dir / "test_alpha.py").write_text(
                "import pytest\n"
                "\n"
                "@pytest.mark.skip(reason='example')\n"
                "def test_duplicate_contract():\n"
                "    assert True\n"
                "\n"
                "@pytest.mark.slow\n"
                "def test_slow_path():\n"
                "    assert True\n",
                encoding="utf-8",
            )
            (runtime_dir / "test_beta.py").write_text(
                "def test_duplicate_contract():\n"
                "    assert True\n",
                encoding="utf-8",
            )

            inventory = self.module.collect_inventory(repo)

        self.assertEqual(inventory["totals"]["files"], 3)
        self.assertEqual(inventory["totals"]["helpers"], 1)
        self.assertEqual(inventory["totals"]["duplicate_test_name_clusters"], 1)
        self.assertEqual(inventory["totals"]["slow_or_skipped_tests"], 2)
        self.assertEqual(
            inventory["categories"],
            [
                {"name": "runtime", "files": 1, "lines": 2},
                {"name": "unit", "files": 2, "lines": 11},
            ],
        )
        self.assertEqual(inventory["helper_modules"], ["tests/python/unit/unit_test_support.py"])
        self.assertEqual(inventory["pytest_markers"], [{"name": "skip", "count": 1}, {"name": "slow", "count": 1}])
        self.assertEqual(inventory["duplicate_test_name_clusters"][0]["name"], "test_duplicate_contract")
        self.assertEqual(inventory["duplicate_test_name_clusters"][0]["count"], 2)

    def test_render_markdown_includes_summary_sections(self) -> None:
        inventory = {
            "tests_root": "tests/python",
            "totals": {
                "files": 1,
                "lines": 3,
                "helpers": 0,
                "duplicate_test_name_clusters": 0,
                "slow_or_skipped_tests": 0,
            },
            "categories": [{"name": "runtime", "files": 1, "lines": 3}],
            "largest_files": [{"path": "tests/python/runtime/test_example.py", "lines": 3}],
            "helper_modules": [],
            "pytest_markers": [],
            "slow_or_skipped_tests": [],
            "duplicate_test_name_clusters": [],
        }

        rendered = self.module.render_markdown(inventory)

        self.assertIn("# Test Suite Inventory", rendered)
        self.assertIn("| runtime | 1 | 3 |", rendered)
        self.assertIn("`tests/python/runtime/test_example.py`: 3 lines", rendered)
        self.assertIn("None detected", rendered)

    def test_check_inventory_reports_threshold_failures(self) -> None:
        inventory = {
            "largest_files": [
                {"path": "tests/python/runtime/test_large.py", "lines": 501},
                {"path": "tests/python/runtime/test_small.py", "lines": 10},
            ],
            "totals": {"duplicate_test_name_clusters": 7},
        }

        failures = self.module.check_inventory(
            inventory,
            max_file_lines=500,
            max_duplicate_clusters=5,
        )

        self.assertEqual(
            failures,
            [
                "tests/python/runtime/test_large.py has 501 lines, above limit 500",
                "duplicate test-name clusters: 7 above limit 5",
            ],
        )

    def test_main_json_returns_zero(self) -> None:
        with redirect_stdout(io.StringIO()) as stdout:
            code = self.module.main(["--repo", str(REPO_ROOT), "--tests-root", "tests/python/shared", "--json"])

        self.assertEqual(code, 0)
        self.assertIn('"tests_root": "tests/python/shared"', stdout.getvalue())
