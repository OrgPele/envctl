from __future__ import annotations

from io import StringIO
from pathlib import Path
import sys
import unittest
from contextlib import redirect_stdout

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.test_output.parser_base import TestResult
from envctl_engine.test_output.parser_jest import JestOutputParser
from envctl_engine.test_output.parser_pytest import PytestOutputParser
from envctl_engine.test_output.summary import TestSummaryFormatter


class TestOutputShellParityTests(unittest.TestCase):
    def test_pytest_parser_extracts_shell_style_counts_and_failed_tests(self) -> None:
        output = """
============================= test session starts =============================
platform darwin -- Python 3.12.8, pytest-8.4.2
collected 7 items

tests/test_auth.py::test_ok PASSED
tests/test_auth.py::test_bad FAILED
tests/test_user.py::TestUser::test_create FAILED

=================================== FAILURES ===================================
______________________________ test_bad ______________________________
>       assert 1 == 2
E       AssertionError: expected foo
E       assert 1 == 2

tests/test_auth.py:10: AssertionError
__________________________ TestUser.test_create __________________________
E       AssertionError: expected foo
E       assert "x" == "y"

tests/test_user.py:22: AssertionError
=========================== short test summary info ============================
FAILED tests/test_auth.py::test_bad - AssertionError: expected foo
FAILED tests/test_user.py::TestUser::test_create - AssertionError: expected foo
========================= 2 failed, 5 passed in 1.23s =========================
"""
        parser = PytestOutputParser()
        result = parser.parse_output(output)

        self.assertEqual(result.passed, 5)
        self.assertEqual(result.failed, 2)
        self.assertAlmostEqual(result.duration, 1.23, places=2)
        self.assertEqual(
            sorted(result.failed_tests),
            [
                "tests/test_auth.py::test_bad",
                "tests/test_user.py::TestUser::test_create",
            ],
        )
        self.assertIn("tests/test_auth.py::test_bad", result.error_details)
        self.assertIn("AssertionError", result.error_details["tests/test_auth.py::test_bad"])

    def test_jest_parser_extracts_shell_style_failed_entries(self) -> None:
        output = """
 FAIL  src/auth/auth.test.ts
  ✕ should reject invalid token (8 ms)
  ✓ should accept valid token (3 ms)
AssertionError: Invalid token
  at src/auth/auth.test.ts:44:11

 FAIL  src/config/bootstrap.test.ts
Error: Failed Suites setup

Test Suites: 2 failed, 0 passed, 2 total
Tests:       1 failed, 3 passed, 4 total
Time:        2.34 s
"""
        parser = JestOutputParser()
        result = parser.parse_output(output)

        self.assertEqual(result.passed, 3)
        self.assertEqual(result.failed, 1)
        self.assertAlmostEqual(result.duration, 2.34, places=2)
        self.assertIn("src/auth/auth.test.ts::should reject invalid token", result.failed_tests)
        self.assertIn("src/config/bootstrap.test.ts", result.failed_tests)
        self.assertIn("src/auth/auth.test.ts", result.error_details)
        self.assertIn("AssertionError", result.error_details["src/auth/auth.test.ts"])

    def test_summary_formatter_groups_shared_errors_like_shell(self) -> None:
        result = TestResult(
            passed=2,
            failed=2,
            total=4,
            failed_tests=[
                "tests/test_auth.py::test_bad",
                "tests/test_user.py::test_bad",
            ],
            error_details={
                "tests/test_auth.py::test_bad": "AssertionError: expected foo",
                "tests/test_user.py::test_bad": "AssertionError: expected foo",
            },
        )
        formatter = TestSummaryFormatter(detailed=True)
        out = StringIO()
        with redirect_stdout(out):
            formatter.print_summary(result, returncode=1)
        rendered = out.getvalue()

        self.assertIn("Shared error for 2 tests", rendered)
        self.assertIn("tests/test_auth.py::test_bad", rendered)
        self.assertIn("tests/test_user.py::test_bad", rendered)

    def test_pytest_parser_maps_failure_section_headers_to_full_test_paths(self) -> None:
        output = """
=================================== FAILURES ===================================
__________________________ TestUser.test_create __________________________
self = <tests.test_user.TestUser object>

    def test_create(self):
>       assert "x" == "y"
E       AssertionError: expected foo
E       assert 'x' == 'y'

tests/test_user.py:22: AssertionError
__________________________________ test_auth __________________________________
>       raise TypeError("boom")
E       TypeError: boom

tests/test_auth.py:11: TypeError
=========================== short test summary info ============================
FAILED tests/test_user.py::TestUser::test_create - AssertionError: expected foo
FAILED tests/test_auth.py::test_auth - TypeError: boom
========================= 2 failed, 1 passed in 3.21s =========================
"""
        parser = PytestOutputParser()
        result = parser.parse_output(output)

        first = result.error_details.get("tests/test_user.py::TestUser::test_create", "")
        second = result.error_details.get("tests/test_auth.py::test_auth", "")

        self.assertIn("AssertionError", first)
        self.assertIn("tests/test_user.py:22", first)
        self.assertIn("TypeError", second)
        self.assertIn("tests/test_auth.py:11", second)

    def test_summary_formatter_frontend_shared_error_layout_matches_shell(self) -> None:
        result = TestResult(
            passed=1,
            failed=2,
            total=3,
            failed_tests=[
                "src/auth/a.test.ts::fails one",
                "src/auth/b.test.ts::fails two",
            ],
            error_details={
                "src/auth/a.test.ts::fails one": "AssertionError: token invalid",
                "src/auth/b.test.ts::fails two": "AssertionError: token invalid",
            },
        )
        formatter = TestSummaryFormatter(detailed=True)
        out = StringIO()
        with redirect_stdout(out):
            formatter.print_summary(result, returncode=1, test_type="jest")
        rendered = out.getvalue()

        self.assertIn("Shared error for 2 tests", rendered)
        self.assertRegex(
            rendered,
            r"Shared error for 2 tests:\n\s+- src/auth/a\.test\.ts::fails one\n\s+- src/auth/b\.test\.ts::fails two\n\s+AssertionError: token invalid",
        )

    def test_vitest_parser_extracts_counts_from_modern_vitest_summary(self) -> None:
        output = """
 RUN  v3.2.4 /Users/kfiramar/projects/supportopia/frontend

 ✓ src/components/button.test.ts (12 tests) 250ms
 ✓ src/pages/home.test.tsx (31 tests) 410ms

 Test Files  2 passed (2)
      Tests  43 passed | 1 skipped (44)
   Start at  12:33:50
   Duration  3m 9s (transform 1.2s, setup 0.9s, collect 0.5s, tests 180.4s)
"""
        parser = JestOutputParser()
        result = parser.parse_output(output)

        self.assertEqual(result.passed, 43)
        self.assertEqual(result.failed, 0)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.total, 44)
        self.assertAlmostEqual(result.duration, 189.0, places=1)


if __name__ == "__main__":
    unittest.main()
