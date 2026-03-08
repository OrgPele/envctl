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
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.state import dump_state, load_legacy_shell_state, load_state_from_pointer


class StateShellCompatibilityTests(unittest.TestCase):
    def test_load_legacy_shell_state_parses_declare_arrays(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "legacy.state"
            state_path.write_text(
                "#!/bin/bash\n"
                "# envctl State File\n"
                "export TIMESTAMP='20260224_101500'\n"
                "export TREES_MODE='true'\n"
                "declare -a services=(\n"
                "  'Tree Alpha Backend|http://localhost:8000|Backend docs'\n"
                "  'Tree Alpha Frontend|http://localhost:9000|Frontend docs'\n"
                ")\n"
                "declare -A service_info=(\n"
                "  [Tree\\ Alpha\\ Backend]='321|8000|/tmp/backend.log|backend|/tmp/tree-alpha/backend'\n"
                "  [Tree\\ Alpha\\ Frontend]='654|9000|/tmp/frontend.log|frontend|/tmp/tree-alpha/frontend'\n"
                ")\n"
                "declare -A actual_ports=(\n"
                "  [Tree\\ Alpha\\ Backend]='8010'\n"
                "  [Tree\\ Alpha\\ Frontend]='9002'\n"
                ")\n",
                encoding="utf-8",
            )

            loaded = load_legacy_shell_state(str(state_path), allowed_root=tmpdir)

            self.assertEqual(loaded.mode, "trees")
            self.assertEqual(loaded.services["Tree Alpha Backend"].pid, 321)
            self.assertEqual(loaded.services["Tree Alpha Backend"].actual_port, 8010)
            self.assertEqual(loaded.services["Tree Alpha Frontend"].cwd, "/tmp/tree-alpha/frontend")

    def test_load_state_from_pointer_supports_json_and_shell_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            json_state_path = root / "run_state.json"
            pointer_json = root / ".last_state.main"
            shell_state_path = root / "legacy.state"
            pointer_shell = root / ".last_state.trees.tree-alpha"

            dump_state(
                RunState(
                    run_id="run-json",
                    mode="main",
                    services={
                        "Main Backend": ServiceRecord(
                            name="Main Backend",
                            type="backend",
                            cwd="/tmp/main/backend",
                            pid=123,
                            requested_port=8000,
                            actual_port=8000,
                            status="running",
                        )
                    },
                ),
                str(json_state_path),
            )
            pointer_json.write_text(f"{json_state_path}\n", encoding="utf-8")

            shell_state_path.write_text(
                "#!/bin/bash\n"
                "# envctl State File\n"
                "export TIMESTAMP='20260224_101500'\n"
                "export TREES_MODE='true'\n"
                "declare -a services=(\n"
                "  'Tree Alpha Backend|http://localhost:8000|Backend docs'\n"
                ")\n"
                "declare -A service_info=(\n"
                "  [Tree\\ Alpha\\ Backend]='321|8000|/tmp/backend.log|backend|/tmp/tree-alpha/backend'\n"
                ")\n"
                "declare -A actual_ports=(\n"
                "  [Tree\\ Alpha\\ Backend]='8011'\n"
                ")\n",
                encoding="utf-8",
            )
            pointer_shell.write_text(f"{shell_state_path}\n", encoding="utf-8")

            loaded_json = load_state_from_pointer(str(pointer_json), allowed_root=tmpdir)
            loaded_shell = load_state_from_pointer(str(pointer_shell), allowed_root=tmpdir)

            self.assertEqual(loaded_json.run_id, "run-json")
            self.assertEqual(loaded_shell.services["Tree Alpha Backend"].actual_port, 8011)

    def test_engine_runtime_resolves_state_from_pointer_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_dir = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            runtime_engine = runtime_dir / "python-engine"
            runtime_engine.mkdir(parents=True, exist_ok=True)

            state_path = runtime_dir / "states" / "run_legacy.state"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                "#!/bin/bash\n"
                "# envctl State File\n"
                "export TIMESTAMP='20260224_101500'\n"
                "export TREES_MODE='false'\n"
                "declare -a services=(\n"
                "  'Main Backend|http://localhost:8000|Backend docs'\n"
                ")\n"
                "declare -A service_info=(\n"
                "  [Main\\ Backend]='321|8000|/tmp/backend.log|backend|/tmp/main/backend'\n"
                ")\n"
                "declare -A actual_ports=(\n"
                "  [Main\\ Backend]='8000'\n"
                ")\n",
                encoding="utf-8",
            )
            (runtime_engine / ".last_state.main").write_text(f"{state_path}\n", encoding="utf-8")

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime_dir),
                }
            )
            runtime = PythonEngineRuntime(config, env={})

            loaded = runtime._try_load_existing_state()

            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.mode, "main")
            self.assertIn("Main Backend", loaded.services)


if __name__ == "__main__":
    unittest.main()
