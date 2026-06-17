from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]


class DebugStateStructureLayoutTests(unittest.TestCase):
    def test_debug_bundle_diagnostics_has_selector_and_startup_owners(self) -> None:
        debug = REPO_ROOT / "python" / "envctl_engine" / "debug"
        facade = debug / "debug_bundle_diagnostics.py"
        selector_owner = debug / "debug_bundle_selector_diagnostics.py"
        startup_owner = debug / "debug_bundle_startup_diagnostics.py"

        self.assertTrue(selector_owner.is_file())
        self.assertTrue(startup_owner.is_file())
        selector_text = selector_owner.read_text(encoding="utf-8")
        startup_text = startup_owner.read_text(encoding="utf-8")
        facade_text = facade.read_text(encoding="utf-8")
        self.assertIn("class SelectorDiagnostics", selector_text)
        self.assertIn("def analyze_selector_diagnostics", selector_text)
        self.assertIn("class StartupDiagnostics", startup_text)
        self.assertIn("def analyze_startup_diagnostics", startup_text)
        self.assertIn("analyze_selector_diagnostics", facade_text)
        self.assertIn("analyze_startup_diagnostics", facade_text)
        self.assertLessEqual(len(facade_text.splitlines()), 380)

    def test_state_action_orchestrator_has_log_owner(self) -> None:
        owner = REPO_ROOT / "python" / "envctl_engine" / "state" / "action_log_support.py"
        health_owner = REPO_ROOT / "python" / "envctl_engine" / "state" / "action_health_support.py"
        command_owner = REPO_ROOT / "python" / "envctl_engine" / "state" / "action_command_support.py"
        orchestrator = REPO_ROOT / "python" / "envctl_engine" / "state" / "action_orchestrator.py"

        self.assertTrue(owner.is_file())
        self.assertTrue(health_owner.is_file())
        self.assertTrue(command_owner.is_file())
        owner_text = owner.read_text(encoding="utf-8")
        health_owner_text = health_owner.read_text(encoding="utf-8")
        command_owner_text = command_owner.read_text(encoding="utf-8")
        self.assertIn("class StateActionLogSupport", owner_text)
        self.assertIn("def logs_payload", owner_text)
        self.assertIn("def clear_service_logs", owner_text)
        self.assertIn("class StateActionHealthSupport", health_owner_text)
        self.assertIn("def health_payload", health_owner_text)
        self.assertIn("def health_service_rows", health_owner_text)
        self.assertIn("class StateActionCommandRunner", command_owner_text)
        self.assertIn("def execute_state_action", command_owner_text)
        orchestrator_text = orchestrator.read_text(encoding="utf-8")
        self.assertIn("StateActionLogSupport", orchestrator_text)
        self.assertIn("StateActionHealthSupport", orchestrator_text)
        self.assertIn("execute_state_action", orchestrator_text)
        self.assertLessEqual(len(orchestrator_text.splitlines()), 360)
