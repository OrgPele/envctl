from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.prompt_install_support import (  # noqa: E402
    _available_presets,
    _load_template,
    _print_install_results,
    _render_claude_template,
    _render_codex_template,
    _render_opencode_template,
    _target_path,
    PromptInstallResult,
    codex_skill_invocation_for_preset,
    resolve_codex_direct_prompt_body,
    resolve_opencode_direct_prompt_body,
    run_install_prompts_command,
)
from envctl_engine.test_output.parser_base import strip_ansi


_CREATE_PLAN_AUTO_PRESETS = (
    "create_plan_auto_codex",
    "create_plan_auto_opencode",
    "create_plan_auto_omx",
)


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True




class PromptInstallSupportTestCase(unittest.TestCase):
    def _target(self, *, cli: str, preset: str, home: Path) -> Path:
        return _target_path(cli_name=cli, preset=preset, home=home, env={"HOME": str(home)})

    def _skill_target(self, *, home: Path, preset: str) -> Path:
        skill_name = f"envctl-{preset.replace('_', '-')}"
        if preset == "review_worktree_imp":
            skill_name = "envctl-review-worktree"
        return home / ".codex" / "skills" / skill_name / "SKILL.md"

    @staticmethod
    def _skill_body_wrapper(body: str) -> str:
        return (
            '---\n'
            'name: "envctl-test"\n'
            'description: "test"\n'
            '---\n\n'
            '# Test\n\n'
            '<!-- ENVCTL_DIRECT_PROMPT_BODY_START -->\n'
            + body
            + '\n<!-- ENVCTL_DIRECT_PROMPT_BODY_END -->\n'
        )


__all__ = [
    "Path",
    "PromptInstallResult",
    "PromptInstallSupportTestCase",
    "SimpleNamespace",
    "StringIO",
    "_CREATE_PLAN_AUTO_PRESETS",
    "_TtyStringIO",
    "_available_presets",
    "_load_template",
    "_print_install_results",
    "_render_claude_template",
    "_render_codex_template",
    "_render_opencode_template",
    "codex_skill_invocation_for_preset",
    "json",
    "parse_route",
    "patch",
    "redirect_stdout",
    "resolve_codex_direct_prompt_body",
    "resolve_opencode_direct_prompt_body",
    "run_install_prompts_command",
    "strip_ansi",
    "tempfile",
]
