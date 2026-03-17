from __future__ import annotations

from pathlib import Path
import unittest

from envctl_engine.shell.release_gate import (
    CANONICAL_BOOTSTRAP_COMMANDS,
    CANONICAL_BUILD_COMMAND_DISPLAY,
    CANONICAL_RELEASE_GATE_COMMAND,
    CANONICAL_RELEASE_GATE_WITH_TESTS_COMMAND,
    CANONICAL_VALIDATION_COMMAND_DISPLAY,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


class ValidationWorkflowContractTests(unittest.TestCase):
    def test_authoritative_docs_share_the_same_bootstrap_and_validation_lane(self) -> None:
        contributing = (REPO_ROOT / "docs" / "developer" / "contributing.md").read_text(encoding="utf-8")
        testing = (REPO_ROOT / "docs" / "developer" / "testing-and-validation.md").read_text(encoding="utf-8")

        for command in CANONICAL_BOOTSTRAP_COMMANDS:
            self.assertIn(command, contributing)
            self.assertIn(command, testing)
        self.assertIn(CANONICAL_VALIDATION_COMMAND_DISPLAY, contributing)
        self.assertIn(CANONICAL_VALIDATION_COMMAND_DISPLAY, testing)
        self.assertIn(CANONICAL_BUILD_COMMAND_DISPLAY, contributing)
        self.assertIn(CANONICAL_BUILD_COMMAND_DISPLAY, testing)
        self.assertIn(CANONICAL_RELEASE_GATE_COMMAND, contributing)
        self.assertIn(CANONICAL_RELEASE_GATE_WITH_TESTS_COMMAND, testing)

    def test_docs_no_longer_present_repo_wide_unittest_discover_as_authoritative(self) -> None:
        legacy = ".venv/bin/python -m unittest discover -s tests/python -p 'test_*.py'"
        for relative in (
            "README.md",
            "docs/developer/contributing.md",
            "docs/developer/testing-and-validation.md",
        ):
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn(legacy, text, msg=relative)

    def test_pythonpath_guidance_is_limited_to_runtime_guide(self) -> None:
        runtime_guide = (REPO_ROOT / "docs" / "developer" / "python-runtime-guide.md").read_text(encoding="utf-8")
        self.assertIn("PYTHONPATH=python", runtime_guide)

        for relative in (
            "README.md",
            "docs/developer/contributing.md",
            "docs/developer/testing-and-validation.md",
        ):
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("PYTHONPATH=python", text, msg=relative)

    def test_python_cleanup_bootstrap_hint_matches_dev_extra_contract(self) -> None:
        script = (REPO_ROOT / "scripts" / "python_cleanup.py").read_text(encoding="utf-8")
        self.assertIn(".venv/bin/python -m pip install -e '.[dev]'", script)


if __name__ == "__main__":
    unittest.main()
