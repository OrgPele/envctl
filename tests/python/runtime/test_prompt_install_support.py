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
    _render_claude_template,
    _render_codex_template,
    _render_opencode_template,
    run_install_prompts_command,
)


class PromptInstallSupportTests(unittest.TestCase):
    def test_install_prompts_dry_run_json_reports_all_targets_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(
                ["install-prompts", "--cli", "all", "--dry-run", "--json"],
                env={},
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 0)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(payload["command"], "install-prompts")
            self.assertEqual(payload["preset"], "implement_tdd")
            self.assertTrue(payload["dry_run"])
            self.assertEqual([item["cli"] for item in payload["results"]], ["codex", "claude", "opencode"])
            self.assertTrue(all(item["status"] == "planned" for item in payload["results"]))
            self.assertFalse((Path(tmpdir) / ".codex" / "prompts" / "implement_tdd.md").exists())
            self.assertFalse((Path(tmpdir) / ".claude" / "commands" / "implement_tdd.md").exists())
            self.assertFalse((Path(tmpdir) / ".config" / "opencode" / "commands" / "implement_tdd.md").exists())

    def test_install_prompts_overwrites_existing_file_with_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            target = home / ".codex" / "prompts" / "implement_tdd.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("old prompt\n", encoding="utf-8")
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(["install-prompts", "--cli", "codex", "--json"], env={})

            buffer = StringIO()
            with (
                redirect_stdout(buffer),
                patch("envctl_engine.runtime.prompt_install_support._backup_timestamp", return_value="20260310-150000"),
            ):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 0)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(payload["results"][0]["status"], "overwritten")
            backup_path = home / ".codex" / "prompts" / "implement_tdd.bak-20260310-150000.md"
            self.assertEqual(payload["results"][0]["backup_path"], str(backup_path))
            self.assertEqual(backup_path.read_text(encoding="utf-8"), "old prompt\n")
            written = target.read_text(encoding="utf-8")
            self.assertIn("description: Implement MAIN_TASK.md using strict TDD", written)
            self.assertIn("argument-hint:", written)
            self.assertIn("Before any implementation work, run `git add .`", written)

    def test_install_prompts_reports_partial_failure_for_invalid_cli_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(
                ["install-prompts", "--cli", "codex,unknown", "--dry-run", "--json"],
                env={},
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 1)
            payload = json.loads(buffer.getvalue())
            results = payload["results"]
            self.assertEqual(results[0]["cli"], "unknown")
            self.assertEqual(results[0]["status"], "failed")
            self.assertEqual(results[1]["cli"], "codex")
            self.assertEqual(results[1]["status"], "planned")

    def test_install_prompts_rejects_missing_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(["install-prompts", "--json"], env={})

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 1)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(payload["results"][0]["status"], "failed")
            self.assertIn("Missing required --cli", payload["results"][0]["message"])

    def test_install_prompts_rejects_unsupported_preset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(
                ["install-prompts", "--cli", "codex", "--preset", "review_perfect", "--json"],
                env={},
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 1)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(payload["results"][0]["status"], "failed")
            self.assertIn("Unsupported preset", payload["results"][0]["message"])
            self.assertIn("implement_tdd", payload["results"][0]["message"])

    def test_template_registry_discovers_built_in_templates_by_filename(self) -> None:
        self.assertIn("implement_tdd", _available_presets())

    def test_renderers_produce_expected_target_shapes(self) -> None:
        template = _load_template("implement_tdd")
        codex = _render_codex_template(template)
        claude = _render_claude_template(template)
        opencode = _render_opencode_template(template)

        self.assertEqual(template.name, "implement_tdd")
        self.assertEqual(template.claude_title, "Implement MAIN_TASK.md using strict TDD")
        self.assertEqual(template.opencode_tools, {"bash": True, "edit": True, "write": True})

        self.assertTrue(codex.startswith("---\ndescription: "))
        self.assertIn("argument-hint:", codex)
        self.assertIn("Authoritative spec file: $ARGUMENTS", codex)
        self.assertTrue(claude.startswith("# Implement MAIN_TASK.md using strict TDD"))
        self.assertIn("Analyze the following: $ARGUMENTS", claude)
        self.assertNotIn("agent: Sisyphus", claude)
        self.assertTrue(opencode.startswith("---\ndescription: "))
        self.assertIn("agent: Sisyphus", opencode)
        self.assertIn("model: openai/gpt-5.2-codex", opencode)
        self.assertIn("tools:", opencode)


if __name__ == "__main__":
    unittest.main()
