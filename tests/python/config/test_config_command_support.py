from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.config import load_config
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime


class ConfigCommandSupportTests(unittest.TestCase):
    def _runtime(self, repo: Path, runtime_root: Path) -> PythonEngineRuntime:
        config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime_root)})
        return PythonEngineRuntime(config, env={})

    def test_config_set_saves_repo_local_envctl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            runtime = self._runtime(repo, runtime_root)

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = runtime.dispatch(
                    parse_route(
                        ["config", "--set", "ENVCTL_DEFAULT_MODE=trees", "--set", "BACKEND_DIR=api", "--set", "MAIN_STARTUP_ENABLE=false"],
                        env={},
                    )
                )

            self.assertEqual(code, 0)
            text = (repo / ".envctl").read_text(encoding="utf-8")
            self.assertIn("ENVCTL_DEFAULT_MODE=trees", text)
            self.assertIn("BACKEND_DIR=api", text)
            self.assertIn("MAIN_STARTUP_ENABLE=false", text)

    def test_config_stdin_json_updates_nested_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            runtime = self._runtime(repo, runtime_root)
            payload = {
                "default_mode": "trees",
                "directories": {"backend": "api", "frontend": "web"},
                "profiles": {
                    "main": {"startup_enabled": False, "backend": True, "frontend": False, "dependencies": {"postgres": True, "redis": True, "supabase": False, "n8n": False}},
                    "trees": {"startup_enabled": True, "backend": True, "frontend": True, "dependencies": {"postgres": True, "redis": True, "supabase": False, "n8n": True}},
                },
            }

            buffer = io.StringIO()
            with patch("sys.stdin", io.StringIO(json.dumps(payload))):
                with redirect_stdout(buffer):
                    code = runtime.dispatch(parse_route(["config", "--stdin-json", "--json"], env={}))

            self.assertEqual(code, 0)
            response = json.loads(buffer.getvalue())
            self.assertEqual(response["config"]["default_mode"], "trees")
            self.assertEqual(response["config"]["directories"]["backend"], "api")
            self.assertEqual(response["config"]["directories"]["frontend"], "web")
            self.assertEqual(response["config"]["profiles"]["main"]["startup_enabled"], False)
            text = (repo / ".envctl").read_text(encoding="utf-8")
            self.assertIn("FRONTEND_DIR=web", text)
            self.assertIn("MAIN_STARTUP_ENABLE=false", text)


if __name__ == "__main__":
    unittest.main()
