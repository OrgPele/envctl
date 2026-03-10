from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import ProjectContext, PythonEngineRuntime
from envctl_engine.shared.hooks import (
    build_python_hook_starter_stub,
    legacy_shell_hook_issue,
    migrate_legacy_shell_hooks,
    run_envctl_hook,
)
from envctl_engine.state.models import RequirementsResult


class HooksBridgeTests(unittest.TestCase):
    def test_run_hook_returns_not_found_when_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            result = run_envctl_hook(repo_root=repo, hook_name="envctl_setup_infrastructure", context={})
            self.assertFalse(result.found)
            self.assertTrue(result.success)
            self.assertIsNone(result.payload)

    def test_run_hook_parses_python_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            hook_file = repo / ".envctl_hooks.py"
            hook_file.write_text(
                "from __future__ import annotations\n\n"
                "def envctl_setup_infrastructure(context: dict) -> dict | None:\n"
                "    return {\"skip_default_requirements\": True}\n",
                encoding="utf-8",
            )
            result = run_envctl_hook(
                repo_root=repo,
                hook_name="envctl_setup_infrastructure",
                hook_file=hook_file,
                context={"project_name": "Main"},
            )
            self.assertTrue(result.found)
            self.assertTrue(result.success)
            self.assertEqual(result.payload, {"skip_default_requirements": True})

    def test_run_hook_reports_legacy_shell_hook_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl.sh").write_text(
                "envctl_setup_infrastructure() {\n"
                "  export ENVCTL_HOOK_JSON='{\"skip_default_requirements\":true}'\n"
                "}\n",
                encoding="utf-8",
            )
            result = run_envctl_hook(repo_root=repo, hook_name="envctl_setup_infrastructure", context={})
            self.assertTrue(result.found)
            self.assertFalse(result.success)
            self.assertIn("envctl migrate-hooks", result.error or "")
            self.assertIn(".envctl_hooks.py", result.error or "")

    def test_migrate_legacy_shell_hooks_generates_python_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl.sh").write_text(
                "envctl_setup_infrastructure() {\n"
                "  export ENVCTL_HOOK_JSON='{\"skip_default_requirements\":true}'\n"
                "}\n\n"
                "envctl_define_services() {\n"
                "  export ENVCTL_HOOK_JSON='{\"skip_default_services\":true,\"services\":[]}'\n"
                "}\n",
                encoding="utf-8",
            )
            result = migrate_legacy_shell_hooks(repo)
            self.assertTrue(result.migrated)
            self.assertTrue(result.python_hook_path.is_file())
            rendered = result.python_hook_path.read_text(encoding="utf-8")
            self.assertIn("def envctl_setup_infrastructure", rendered)
            self.assertIn("def envctl_define_services", rendered)

    def test_migrate_legacy_shell_hooks_returns_stub_for_unsupported_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl.sh").write_text(
                "envctl_setup_infrastructure() {\n"
                "  echo nope\n"
                "  export ENVCTL_HOOK_JSON='{}'\n"
                "}\n",
                encoding="utf-8",
            )
            result = migrate_legacy_shell_hooks(repo)
            self.assertFalse(result.migrated)
            self.assertIn("Unsupported shell hook bodies", result.error or "")
            self.assertEqual(result.starter_stub, build_python_hook_starter_stub(hook_names=["envctl_setup_infrastructure"]))

    def test_runtime_setup_hook_can_skip_default_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime_dir = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".envctl_hooks.py").write_text(
                "from __future__ import annotations\n\n"
                "def envctl_setup_infrastructure(context: dict) -> dict | None:\n"
                "    return {\n"
                "        \"skip_default_requirements\": True,\n"
                "        \"requirements\": {\n"
                "            \"postgres\": {\"success\": True},\n"
                "            \"redis\": {\"success\": True},\n"
                "            \"n8n\": {\"success\": True},\n"
                "            \"supabase\": {\"success\": True},\n"
                "        },\n"
                "    }\n",
                encoding="utf-8",
            )

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime_dir),
                }
            )
            runtime = PythonEngineRuntime(config, env={"ENVCTL_ENABLE_HOOK_BRIDGE": "true"})
            context = ProjectContext(name="Main", root=repo, ports=runtime.port_planner.plan_project_stack("Main", index=0))
            result = runtime._start_requirements_for_project(context, mode="main")
            self.assertIsInstance(result, RequirementsResult)
            self.assertEqual(result.health, "healthy")
            self.assertFalse(result.failures)

    def test_runtime_define_services_hook_returns_service_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime_dir = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".envctl_hooks.py").write_text(
                "from __future__ import annotations\n\n"
                "def envctl_define_services(context: dict) -> dict | None:\n"
                "    return {\n"
                "        \"skip_default_services\": True,\n"
                "        \"services\": [\n"
                "            {\"name\": \"Main Backend\", \"type\": \"backend\", \"port\": 8010, \"actual_port\": 8010, \"status\": \"running\", \"cwd\": \"/tmp/backend\"},\n"
                "            {\"name\": \"Main Frontend\", \"type\": \"frontend\", \"port\": 9010, \"actual_port\": 9010, \"status\": \"running\", \"cwd\": \"/tmp/frontend\"},\n"
                "        ],\n"
                "    }\n",
                encoding="utf-8",
            )

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime_dir),
                }
            )
            runtime = PythonEngineRuntime(config, env={"ENVCTL_ENABLE_HOOK_BRIDGE": "true"})
            context = ProjectContext(name="Main", root=repo, ports=runtime.port_planner.plan_project_stack("Main", index=0))
            requirements = RequirementsResult(
                project="Main",
                db={"enabled": False, "success": True},
                redis={"enabled": False, "success": True},
                n8n={"enabled": False, "success": True},
                supabase={"enabled": False, "success": True},
                health="healthy",
                failures=[],
            )
            records = runtime._start_project_services(context, requirements=requirements, run_id="run-1")
            self.assertIn("Main Backend", records)
            self.assertIn("Main Frontend", records)
            self.assertEqual(records["Main Backend"].actual_port, 8010)
            self.assertEqual(records["Main Frontend"].actual_port, 9010)

    def test_legacy_shell_hook_issue_ignores_plain_config_prefill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl.sh").write_text("ENVCTL_DEFAULT_MODE=trees\n", encoding="utf-8")
            self.assertIsNone(legacy_shell_hook_issue(repo))


if __name__ == "__main__":
    unittest.main()
