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
from envctl_engine.shared.hooks import run_envctl_hook
from envctl_engine.state.models import RequirementsResult


class HooksBridgeTests(unittest.TestCase):
    def test_run_hook_returns_not_found_when_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            result = run_envctl_hook(repo_root=repo, hook_name="envctl_setup_infrastructure", env={})
            self.assertFalse(result.found)
            self.assertTrue(result.success)
            self.assertIsNone(result.payload)

    def test_run_hook_parses_json_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            hook_file = repo / ".envctl.sh"
            hook_file.write_text(
                "envctl_setup_infrastructure() {\n"
                "  export ENVCTL_HOOK_JSON='{\"skip_default_requirements\":true}'\n"
                "}\n",
                encoding="utf-8",
            )
            result = run_envctl_hook(repo_root=repo, hook_name="envctl_setup_infrastructure", env={})
            self.assertTrue(result.found)
            self.assertTrue(result.success)
            self.assertIsInstance(result.payload, dict)
            assert isinstance(result.payload, dict)
            self.assertIs(result.payload.get("skip_default_requirements"), True)

    def test_runtime_setup_hook_can_skip_default_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime_dir = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".envctl.sh").write_text(
                "envctl_setup_infrastructure() {\n"
                "  export ENVCTL_HOOK_JSON='{\"skip_default_requirements\":true,"
                "\"requirements\":{"
                "\"postgres\":{\"success\":true},"
                "\"redis\":{\"success\":true},"
                "\"n8n\":{\"success\":true},"
                "\"supabase\":{\"success\":true}"
                "}}'\n"
                "}\n",
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
            (repo / ".envctl.sh").write_text(
                "envctl_define_services() {\n"
                "  export ENVCTL_HOOK_JSON='{\"skip_default_services\":true,\"services\":["
                "{\"name\":\"Main Backend\",\"type\":\"backend\",\"port\":8010,\"actual_port\":8010,\"status\":\"running\",\"cwd\":\"/tmp/backend\"},"
                "{\"name\":\"Main Frontend\",\"type\":\"frontend\",\"port\":9010,\"actual_port\":9010,\"status\":\"running\",\"cwd\":\"/tmp/frontend\"}"
                "]}'\n"
                "}\n",
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


if __name__ == "__main__":
    unittest.main()
