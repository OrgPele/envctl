from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from envctl_engine.actions.actions_test_models import (
    TestCommandSuggestion as CommandSuggestion,
    TestPathSuggestion as PathSuggestion,
)
from envctl_engine.ui.textual.screens.config_wizard_hints import ConfigWizardHintResolver


class ConfigWizardHintResolverTests(unittest.TestCase):
    def _resolver(
        self,
        *,
        base_dir: Path,
        parsed_values: dict[str, object] | None = None,
        suggestions_by_field: dict[str, tuple[CommandSuggestion | PathSuggestion, ...]] | None = None,
        field_values: dict[str, object] | None = None,
    ) -> ConfigWizardHintResolver:
        values = field_values or {}
        return ConfigWizardHintResolver(
            base_dir=base_dir,
            parsed_values=parsed_values or {},
            suggestions_by_field=suggestions_by_field or {},
            field_value=lambda field_name: values.get(field_name, ""),
        )

    def test_test_command_hint_prefers_existing_envctl_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            resolver = self._resolver(
                base_dir=Path(tmpdir),
                parsed_values={"ENVCTL_BACKEND_TEST_CMD": "custom test command"},
                suggestions_by_field={
                    "backend_test_cmd": (
                        CommandSuggestion(
                            command_text="python -m pytest backend/tests",
                            command=["python", "-m", "pytest", "backend/tests"],
                            cwd=Path(tmpdir),
                            source="backend",
                            label="Backend pytest",
                            confidence="high",
                            reason="pytest tests were detected",
                            target="backend",
                        ),
                    )
                },
                field_values={"backend_test_cmd": "custom test command"},
            )

            self.assertEqual(
                resolver.field_hint_text("backend_test_cmd"),
                "Existing value from .envctl; detection will not overwrite it.",
            )

    def test_test_command_hint_describes_matching_suggestion_and_cycle_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            suggestion = CommandSuggestion(
                command_text="python -m pytest backend/tests",
                command=["python", "-m", "pytest", "backend/tests"],
                cwd=Path(tmpdir),
                source="backend",
                label="Backend pytest",
                confidence="high",
                reason="pytest tests were detected",
                target="backend",
            )
            alternate = CommandSuggestion(
                command_text="python -m unittest discover -s tests -t . -p test_*.py",
                command=["python", "-m", "unittest"],
                cwd=Path(tmpdir),
                source="root",
                label="Unittest discovery",
                confidence="medium",
                reason="unittest tests were detected",
                target="backend",
            )
            resolver = self._resolver(
                base_dir=Path(tmpdir),
                suggestions_by_field={"backend_test_cmd": (suggestion, alternate)},
                field_values={"backend_test_cmd": suggestion.command_text},
            )

            hint = resolver.field_hint_text("backend_test_cmd")

            self.assertIn("Detected: Backend pytest", hint)
            self.assertIn("pytest tests were detected", hint)
            self.assertIn("Multiple suggestions available", hint)

    def test_frontend_path_hint_distinguishes_manual_and_detected_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            suggestion = PathSuggestion(
                path="frontend/src",
                source="frontend",
                label="Frontend source tests",
                confidence="high",
                reason="test files were detected under frontend/src",
            )
            resolver = self._resolver(
                base_dir=Path(tmpdir),
                suggestions_by_field={"frontend_test_path": (suggestion,)},
                field_values={"frontend_test_path": "frontend/src"},
            )

            self.assertEqual(
                resolver.field_hint_text("frontend_test_path"),
                "Detected: frontend/src — test files were detected under frontend/src",
            )

            manual = self._resolver(
                base_dir=Path(tmpdir),
                suggestions_by_field={"frontend_test_path": (suggestion,)},
                field_values={"frontend_test_path": "custom/frontend"},
            )
            self.assertEqual(
                manual.field_hint_text("frontend_test_path"),
                "Manual frontend test path; detection will not overwrite it.",
            )

    def test_directory_validation_rules_match_wizard_field_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "backend").mkdir()
            resolver = self._resolver(base_dir=repo)

            self.assertIsNone(resolver.directory_validation_error("backend_dir_name", raw="backend"))
            self.assertEqual(
                resolver.directory_validation_error("backend_dir_name", raw="api"),
                "Directory does not exist: api",
            )
            self.assertEqual(
                resolver.directory_validation_error("backend_start_cmd", raw=""),
                "Backend entrypoint must not be empty.",
            )
            self.assertIsNone(resolver.directory_validation_error("backend_test_cmd", raw=""))
            self.assertIsNone(resolver.directory_validation_error("frontend_test_path", raw=""))
