from __future__ import annotations

from pathlib import Path
import unittest

from envctl_engine.runtime.release_gate import (
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

    def test_runtime_guide_describes_repo_root_bootstrap_without_pythonpath(self) -> None:
        runtime_guide = (REPO_ROOT / "docs" / "developer" / "python-runtime-guide.md").read_text(encoding="utf-8")
        self.assertIn("tests/python", runtime_guide)
        self.assertNotIn("PYTHONPATH=python", runtime_guide)

        for relative in (
            "README.md",
            "docs/developer/contributing.md",
            "docs/developer/testing-and-validation.md",
        ):
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("PYTHONPATH=python", text, msg=relative)

    def test_user_docs_distinguish_installed_source_and_contributor_runtime_bootstrap(self) -> None:
        for relative in (
            "README.md",
            "docs/user/getting-started.md",
            "docs/user/faq.md",
            "docs/operations/troubleshooting.md",
        ):
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("pipx install", text, msg=relative)
            self.assertIn("python/requirements.txt", text, msg=relative)
            self.assertNotIn(".venv/bin/python -m pip install -e '.[dev]'", text, msg=relative)

    def test_docs_describe_runtime_dependency_gate_boundary(self) -> None:
        for relative in (
            "docs/user/getting-started.md",
            "docs/operations/troubleshooting.md",
            "docs/developer/config-and-bootstrap.md",
        ):
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("start`, `plan`, and `restart", text, msg=relative)
            self.assertIn("`--version`, `--help`", text, msg=relative)
            self.assertIn("`install`, and `uninstall`", text, msg=relative)
            self.assertIn("`show-config`, `show-state`, `explain-startup`, and `list-commands`", text, msg=relative)

    def test_reference_commands_page_summarizes_command_boundaries(self) -> None:
        text = (REPO_ROOT / "docs" / "reference" / "commands.md").read_text(encoding="utf-8")
        self.assertIn("launcher-owned commands", text)
        self.assertIn("bootstrap-safe inspection or utility commands", text)
        self.assertIn("operational runtime commands", text)
        for token in (
            "`--version`",
            "`--help`",
            "`doctor`",
            "`show-config`",
            "`show-state`",
            "`explain-startup`",
            "`list-commands`",
            "`install-prompts`",
            "`codex-tmux`",
            "`start`",
            "`plan`",
            "`restart`",
        ):
            self.assertIn(token, text)
        self.assertIn("repo-scoped tmux session", text)
        self.assertIn("distinct from the optional post-`--plan` cmux-based plan-agent launch flow", text)

    def test_active_developer_docs_do_not_reference_deleted_shell_domain(self) -> None:
        for relative in (
            "docs/developer/debug-and-diagnostics.md",
            "docs/developer/module-layout.md",
            "docs/developer/python-runtime-guide.md",
        ):
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("shell/release_gate.py", text, msg=relative)
            self.assertNotIn("`shell/`", text, msg=relative)

    def test_active_plan_docs_do_not_reference_retired_bats_lane_or_shell_release_gate(self) -> None:
        plans_root = REPO_ROOT / "todo" / "plans"
        bats_pattern = "".join(("tests", "/", "bats")) + "|" + "B" + "ATS"
        for path in plans_root.rglob("*.md"):
            relative = path.relative_to(REPO_ROOT)
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, bats_pattern, msg=str(relative))
            self.assertNotIn("python/envctl_engine/shell/release_gate.py", text, msg=str(relative))
            self.assertNotIn("shell/release_gate.py", text, msg=str(relative))

    def test_active_runtime_code_and_tests_do_not_reference_legacy_bats_env_guards(self) -> None:
        env_markers = ("BATS" + "_TEST" + "_FILENAME", "BATS" + "_RUN" + "_TMPDIR")
        for relative in (
            "python/envctl_engine/ui/terminal_session.py",
            "tests/python/runtime/test_engine_runtime_real_startup.py",
        ):
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
            for marker in env_markers:
                self.assertNotIn(marker, text, msg=relative)

    def test_python_cleanup_bootstrap_hint_matches_dev_extra_contract(self) -> None:
        script = (REPO_ROOT / "scripts" / "python_cleanup.py").read_text(encoding="utf-8")
        self.assertIn(".venv/bin/python -m pip install -e '.[dev]'", script)


if __name__ == "__main__":
    unittest.main()
