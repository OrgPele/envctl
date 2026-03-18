from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.config import PortDefaults, StartupProfile
from envctl_engine.config.git_global_ignore import GlobalIgnoreStatus
from envctl_engine.config.persistence import ConfigSaveResult, ManagedConfigValues
from envctl_engine.ui.textual.screens.config_wizard import ConfigWizardResult
from envctl_engine.config.wizard_domain import _save_message, edit_local_config, ensure_local_config


class ConfigWizardDomainTests(unittest.TestCase):
    def test_save_message_reports_global_ignore_warning(self) -> None:
        result = ConfigWizardResult(
            values=ManagedConfigValues(
                default_mode="main",
                main_profile=StartupProfile(True, True, True, False, False, False, False),
                trees_profile=StartupProfile(True, True, True, False, False, False, False),
                port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
            ),
            save_result=ConfigSaveResult(
                path=Path("/tmp/repo/.envctl"),
                ignore_updated=False,
                ignore_warning="Git global excludes are not configured.",
            ),
        )

        message = _save_message(result)

        self.assertIn("Saved startup config: /tmp/repo/.envctl", message)
        self.assertIn("Git global excludes are not configured.", message)

    def test_ensure_local_config_requires_tty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            with patch("envctl_engine.config.wizard_domain._has_tty", return_value=False):
                with self.assertRaises(RuntimeError):
                    ensure_local_config(base_dir=repo, env={})

    def test_ensure_local_config_runs_wizard_and_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            def fake_run_wizard(*, local_state, emit=None):  # noqa: ANN001
                from envctl_engine.config.persistence import ManagedConfigValues, PortDefaults, save_local_config
                from envctl_engine.config import StartupProfile

                _ = emit
                values = ManagedConfigValues(
                    default_mode="main",
                    main_profile=StartupProfile(True, True, True, True, True, False, False),
                    trees_profile=StartupProfile(True, True, True, True, True, False, True),
                    port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
                )
                save_result = save_local_config(local_state=local_state, values=values)
                return SimpleNamespace(values=values, save_result=save_result)

            with (
                patch("envctl_engine.config.wizard_domain._has_tty", return_value=True),
                patch("envctl_engine.config.wizard_domain._textual_stack_available", return_value=True),
                patch("envctl_engine.config.wizard_domain._run_wizard", side_effect=fake_run_wizard),
            ):
                result = ensure_local_config(base_dir=repo, env={})

            self.assertTrue(result.changed)
            self.assertTrue((repo / ".envctl").is_file())

    def test_edit_local_config_cancel_is_nonfatal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl").write_text("ENVCTL_DEFAULT_MODE=main\n", encoding="utf-8")
            with (
                patch("envctl_engine.config.wizard_domain._has_tty", return_value=True),
                patch("envctl_engine.config.wizard_domain._textual_stack_available", return_value=True),
                patch("envctl_engine.config.wizard_domain._run_wizard", return_value=None),
            ):
                result = edit_local_config(base_dir=repo, env={})
            self.assertFalse(result.changed)
            self.assertEqual(result.message, "Configuration edit cancelled.")

    def test_edit_local_config_uses_shared_wizard_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl").write_text("ENVCTL_DEFAULT_MODE=main\n", encoding="utf-8")

            def fake_run_wizard(*, local_state, emit=None):  # noqa: ANN001
                _ = local_state, emit
                return None

            with (
                patch("envctl_engine.config.wizard_domain._has_tty", return_value=True),
                patch("envctl_engine.config.wizard_domain._textual_stack_available", return_value=True),
                patch("envctl_engine.config.wizard_domain._run_wizard", side_effect=fake_run_wizard),
            ):
                result = edit_local_config(base_dir=repo, env={})

            self.assertFalse(result.changed)

    def test_ensure_local_config_emits_ignore_status_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            events: list[tuple[str, dict[str, object]]] = []

            def emit(event: str, **payload: object) -> None:
                events.append((event, payload))

            result = ConfigWizardResult(
                values=ManagedConfigValues(
                    default_mode="main",
                    main_profile=StartupProfile(True, True, True, False, False, False, False),
                    trees_profile=StartupProfile(True, True, True, False, False, False, False),
                    port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
                ),
                save_result=ConfigSaveResult(
                    path=repo / ".envctl",
                    ignore_updated=False,
                    ignore_warning="Git global excludes are not configured.",
                    ignore_status=GlobalIgnoreStatus(
                        code="missing_global_excludes_configuration",
                        updated=False,
                        scope="git_global_excludes",
                        target_path=None,
                        managed_patterns=(".envctl*",),
                        warning="Git global excludes are not configured.",
                    ),
                ),
            )

            with (
                patch("envctl_engine.config.wizard_domain._has_tty", return_value=True),
                patch("envctl_engine.config.wizard_domain._textual_stack_available", return_value=True),
                patch("envctl_engine.config.wizard_domain._run_wizard", return_value=result),
            ):
                ensure_local_config(base_dir=repo, env={}, emit=emit)

            self.assertTrue(any(event == "config.ignore.global.skipped" for event, _payload in events))

    def test_save_message_reports_global_ignore_bootstrap(self) -> None:
        result = ConfigWizardResult(
            values=ManagedConfigValues(
                default_mode="main",
                main_profile=StartupProfile(True, True, True, False, False, False, False),
                trees_profile=StartupProfile(True, True, True, False, False, False, False),
                port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
            ),
            save_result=ConfigSaveResult(
                path=Path("/tmp/repo/.envctl"),
                ignore_updated=True,
                ignore_warning=None,
                ignore_status=GlobalIgnoreStatus(
                    code="configured_global_excludes",
                    updated=True,
                    scope="git_global_excludes",
                    target_path=Path("/tmp/home/.gitignore_global"),
                    managed_patterns=(".envctl*",),
                    warning=None,
                ),
            ),
        )

        message = _save_message(result)

        self.assertIn("Saved startup config: /tmp/repo/.envctl", message)
        self.assertIn("Configured Git global excludes", message)

    def test_ensure_local_config_emits_updated_event_for_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            events: list[tuple[str, dict[str, object]]] = []

            def emit(event: str, **payload: object) -> None:
                events.append((event, payload))

            result = ConfigWizardResult(
                values=ManagedConfigValues(
                    default_mode="main",
                    main_profile=StartupProfile(True, True, True, False, False, False, False),
                    trees_profile=StartupProfile(True, True, True, False, False, False, False),
                    port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
                ),
                save_result=ConfigSaveResult(
                    path=repo / ".envctl",
                    ignore_updated=True,
                    ignore_warning=None,
                    ignore_status=GlobalIgnoreStatus(
                        code="configured_global_excludes",
                        updated=True,
                        scope="git_global_excludes",
                        target_path=Path(tmpdir) / "home" / ".gitignore_global",
                        managed_patterns=(".envctl*",),
                        warning=None,
                    ),
                ),
            )

            with (
                patch("envctl_engine.config.wizard_domain._has_tty", return_value=True),
                patch("envctl_engine.config.wizard_domain._textual_stack_available", return_value=True),
                patch("envctl_engine.config.wizard_domain._run_wizard", return_value=result),
            ):
                ensure_local_config(base_dir=repo, env={}, emit=emit)

            self.assertTrue(any(event == "config.ignore.global.updated" for event, _payload in events))


if __name__ == "__main__":
    unittest.main()
