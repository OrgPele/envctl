from __future__ import annotations

# ruff: noqa: F403,F405
from tests.python.runtime.prompt_install_support_test_support import *


class PromptInstallSupportSkillWritesTests(PromptInstallSupportTestCase):
    def test_install_prompts_writes_create_plan_auto_codex_skills_with_markers(self) -> None:
        for preset in _CREATE_PLAN_AUTO_PRESETS:
            with self.subTest(preset=preset), tempfile.TemporaryDirectory() as tmpdir:
                runtime = SimpleNamespace(env={"HOME": tmpdir})
                route = parse_route(
                    ["install-prompts", "--cli", "codex", "--preset", preset, "--json"],
                    env={},
                )

                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = run_install_prompts_command(runtime, route)

                self.assertEqual(code, 0)
                payload = json.loads(buffer.getvalue())
                expected = self._skill_target(home=Path(tmpdir), preset=preset)
                self.assertEqual(payload["skill_results"][0]["path"], str(expected))
                self.assertTrue(expected.exists())
                written = expected.read_text(encoding="utf-8")
                skill_name = f"envctl-{preset.replace('_', '-')}"
                self.assertIn(f'name: "{skill_name}"', written)
                self.assertIn(f"Use this skill explicitly with `${skill_name}`.", written)
                self.assertIn("<!-- ENVCTL_DIRECT_PROMPT_BODY_START -->", written)
                self.assertIn("<!-- ENVCTL_DIRECT_PROMPT_BODY_END -->", written)
                self.assertIn("Use the normal `create_plan` workflow", written)
                self.assertIn("--preset implement_task", written)
                openai_yaml = expected.parent / "agents" / "openai.yaml"
                self.assertTrue(openai_yaml.exists())
                self.assertIn("allow_implicit_invocation: false", openai_yaml.read_text(encoding="utf-8"))

    def test_install_prompts_writes_create_plan_auto_opencode_command_with_default_ulw_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(
                ["install-prompts", "--cli", "opencode", "--preset", "create_plan_auto_opencode", "--json"],
                env={},
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 0)
            payload = json.loads(buffer.getvalue())
            expected = self._target(cli="opencode", preset="create_plan_auto_opencode", home=Path(tmpdir))
            self.assertEqual(payload["results"][0]["path"], str(expected))
            self.assertTrue(expected.exists())
            written = expected.read_text(encoding="utf-8")
            self.assertIn(
                "envctl --plan <category>/<slug> --cmux --opencode --preset implement_task --entire-system "
                "--headless --new-session",
                written,
            )
            self.assertIn("OpenCode plan-agent launches use the `/ulw-loop` prefix by default", written)
