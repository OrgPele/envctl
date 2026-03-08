from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.shared.node_tooling import detect_package_manager, detect_python_bin, load_package_json
from envctl_engine.shared.parsing import parse_bool, parse_float, parse_int, strip_quotes


class UtilityConsolidationContractTests(unittest.TestCase):
    def test_parse_helpers_preserve_truthy_falsey_contract(self) -> None:
        self.assertTrue(parse_bool("true", False))
        self.assertTrue(parse_bool("1", False))
        self.assertFalse(parse_bool("false", True))
        self.assertFalse(parse_bool("0", True))
        self.assertTrue(parse_bool("invalid", True))
        self.assertEqual(parse_int("42", 1), 42)
        self.assertEqual(parse_int("bad", 7), 7)
        self.assertAlmostEqual(parse_float("3.14", 1.0), 3.14)
        self.assertEqual(parse_float("bad", 2.5), 2.5)
        self.assertEqual(strip_quotes('"abc"'), "abc")
        self.assertEqual(strip_quotes("'abc'"), "abc")

    def test_node_tooling_load_package_json_and_detect_manager(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = root / "package.json"
            package.write_text('{"name":"demo","scripts":{"dev":"vite","test":"vitest"}}', encoding="utf-8")
            payload = load_package_json(package)
            self.assertIsNotNone(payload)
            assert payload is not None
            self.assertEqual(payload.get("name"), "demo")

            (root / "pnpm-lock.yaml").write_text("lock", encoding="utf-8")
            manager = detect_package_manager(root, command_exists=lambda name: name == "pnpm")
            self.assertEqual(manager, "pnpm")

    def test_detect_python_bin_prefers_local_virtualenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            python_path = root / ".venv" / "bin" / "python"
            python_path.parent.mkdir(parents=True, exist_ok=True)
            python_path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            detected = detect_python_bin(root, command_exists=lambda _name: False)
            self.assertEqual(detected, str(python_path))


if __name__ == "__main__":
    unittest.main()
