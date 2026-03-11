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
            self.assertEqual(payload["preset"], "implement_task")
            self.assertTrue(payload["dry_run"])
            self.assertEqual([item["cli"] for item in payload["results"]], ["codex", "claude", "opencode"])
            self.assertTrue(all(item["status"] == "planned" for item in payload["results"]))
            self.assertFalse((Path(tmpdir) / ".codex" / "prompts" / "implement_task.md").exists())
            self.assertFalse((Path(tmpdir) / ".claude" / "commands" / "implement_task.md").exists())
            self.assertFalse((Path(tmpdir) / ".config" / "opencode" / "commands" / "implement_task.md").exists())

    def test_install_prompts_positional_all_installs_every_preset_for_selected_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(
                ["install-prompts", "--cli", "codex", "all", "--dry-run"],
                env={},
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 0)
            rendered = buffer.getvalue()
            self.assertIn("Would install implement_task for codex", rendered)
            self.assertIn("Would install review_task_imp for codex", rendered)
            self.assertIn("Would install continue_task for codex", rendered)
            self.assertIn("Would install merge_trees_into_dev for codex", rendered)
            self.assertIn("Would install create_plan for codex", rendered)
            self.assertEqual(rendered.count("codex: planned "), 5)

    def test_install_prompts_flag_all_installs_every_preset_for_selected_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(
                ["install-prompts", "--cli", "codex", "--preset", "all", "--dry-run", "--json"],
                env={},
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 0)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(payload["preset"], "all")
            self.assertEqual(
                [item["path"] for item in payload["results"]],
                [
                    str(Path(tmpdir) / ".codex" / "prompts" / "continue_task.md"),
                    str(Path(tmpdir) / ".codex" / "prompts" / "create_plan.md"),
                    str(Path(tmpdir) / ".codex" / "prompts" / "implement_task.md"),
                    str(Path(tmpdir) / ".codex" / "prompts" / "merge_trees_into_dev.md"),
                    str(Path(tmpdir) / ".codex" / "prompts" / "review_task_imp.md"),
                ],
            )

    def test_install_prompts_overwrites_existing_file_with_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            target = home / ".codex" / "prompts" / "implement_task.md"
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
            backup_path = home / ".codex" / "prompts" / "implement_task.bak-20260310-150000.md"
            self.assertEqual(payload["results"][0]["backup_path"], str(backup_path))
            self.assertEqual(backup_path.read_text(encoding="utf-8"), "old prompt\n")
            written = target.read_text(encoding="utf-8")
            self.assertTrue(written.startswith("You are implementing real code, end-to-end."))
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
            self.assertIn("implement_task", payload["results"][0]["message"])

    def test_template_registry_discovers_built_in_templates_by_filename(self) -> None:
        self.assertIn("implement_task", _available_presets())
        self.assertIn("review_task_imp", _available_presets())
        self.assertIn("continue_task", _available_presets())
        self.assertIn("merge_trees_into_dev", _available_presets())
        self.assertIn("create_plan", _available_presets())

    def test_renderers_produce_expected_target_shapes(self) -> None:
        template = _load_template("implement_task")
        codex = _render_codex_template(template)
        claude = _render_claude_template(template)
        opencode = _render_opencode_template(template)

        self.assertEqual(template.name, "implement_task")
        self.assertTrue(codex.startswith("You are implementing real code, end-to-end."))
        self.assertIn("Authoritative spec file: MAIN_TASK.md.", codex)
        self.assertIn("write that content into `MAIN_TASK.md` first", codex)
        self.assertEqual(claude, codex)
        self.assertEqual(opencode, codex)

        merge_prompt = _load_template("merge_trees_into_dev")
        self.assertEqual(merge_prompt.name, "merge_trees_into_dev")
        self.assertIn("Read `MAIN_TASK.md` from branch A and branch B separately.", merge_prompt.body)
        self.assertIn("first merge branch A into `dev`", merge_prompt.body)


if __name__ == "__main__":
    unittest.main()
