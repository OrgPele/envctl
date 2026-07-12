from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.config import _default_port_value
from envctl_engine.shared.node_tooling import detect_package_manager, detect_python_bin, load_package_json
from envctl_engine.shared.services import (
    project_name_from_service_name,
    resolve_service_project_name,
    service_display_name,
    service_project_name,
)
from envctl_engine.shared.parsing import parse_bool, parse_float, parse_int, strip_quotes
from envctl_engine.test_output.parser_base import strip_ansi
from envctl_engine.ui.capabilities import (
    prompt_toolkit_disabled,
    prompt_toolkit_selector_enabled,
    textual_importable,
)
from envctl_engine.ui.command_parsing import (
    parse_interactive_command,
    recover_single_letter_command_from_escape_fragment,
    sanitize_interactive_input,
    tokens_set_mode,
)


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

    def test_ui_capability_helpers_preserve_current_env_contract(self) -> None:
        self.assertTrue(prompt_toolkit_disabled({"ENVCTL_UI_PROMPT_TOOLKIT": "false"}))
        self.assertFalse(prompt_toolkit_disabled({"ENVCTL_UI_PROMPT_TOOLKIT": "true"}))

        with (
            patch("envctl_engine.ui.terminal_session.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.terminal_session.prompt_toolkit_available", return_value=True),
        ):
            self.assertTrue(prompt_toolkit_selector_enabled({}))
            self.assertFalse(prompt_toolkit_selector_enabled({"ENVCTL_UI_SELECTOR_BACKEND": "textual"}))

        self.assertIsInstance(textual_importable(), bool)

    def test_shared_domain_helpers_cover_services_ports_and_ansi(self) -> None:
        self.assertEqual(project_name_from_service_name("Main Backend"), "Main")
        self.assertEqual(project_name_from_service_name("Worker"), "Worker")
        self.assertEqual(service_display_name("voice-runtime"), "Voice Runtime")
        self.assertEqual(service_display_name("voice_runtime"), "Voice Runtime")
        self.assertEqual(_default_port_value("DB_PORT"), 5432)
        self.assertEqual(strip_ansi("\x1b[31mhello\x1b[0m"), "hello")
        self.assertEqual(strip_ansi("\x1b]22;default\x07hello\x1b[15;72H"), "hello")
        self.assertEqual(strip_ansi("\\x1b[48;2;39;39;39m hello \\x1b[0m"), " hello ")

    def test_service_project_resolution_prefers_record_metadata_then_legacy_parser(self) -> None:
        legacy_calls: list[str] = []
        service = SimpleNamespace(name="Opaque Runtime Process", project="Customer Platform")

        self.assertEqual(
            resolve_service_project_name(
                service.name,
                service,
                project_name_from_service=lambda name: legacy_calls.append(name) or "Wrong Project",
            ),
            "Customer Platform",
        )
        self.assertEqual(legacy_calls, [])

        legacy_additional = SimpleNamespace(
            name="Customer Platform Voice Runtime",
            project=None,
            type="voice-runtime",
            service_slug="voice-runtime",
        )
        self.assertEqual(service_project_name(legacy_additional), "Customer Platform")
        self.assertEqual(
            resolve_service_project_name(
                legacy_additional.name,
                legacy_additional,
                project_name_from_service=lambda _name: "Customer Platform Voice",
            ),
            "Customer Platform",
        )

        legacy = SimpleNamespace(name="Legacy Voice Runtime", project=None)
        self.assertEqual(
            resolve_service_project_name(
                legacy.name,
                legacy,
                project_name_from_service=lambda _name: "Legacy",
            ),
            "Legacy",
        )

    def test_service_display_name_has_one_shared_owner(self) -> None:
        for relative_path in (
            "python/envctl_engine/dashboard_metadata.py",
            "python/envctl_engine/runtime/service_manager.py",
            "python/envctl_engine/state/runtime_map.py",
        ):
            raw = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("def _service_display_name", raw, relative_path)
            self.assertNotIn("part.capitalize() for part in", raw, relative_path)

    def test_command_parsing_helpers_preserve_interactive_shell_behavior(self) -> None:
        self.assertEqual(sanitize_interactive_input("\x1b[A restart\r"), "restart")
        self.assertEqual(recover_single_letter_command_from_escape_fragment("\x1bOr"), "r")
        self.assertEqual(parse_interactive_command("logs --all"), ["logs", "--all"])
        self.assertTrue(tokens_set_mode(["--main", "logs"]))

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            parsed = parse_interactive_command('"unterminated')
        self.assertIsNone(parsed)
        self.assertIn("Invalid command syntax", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
