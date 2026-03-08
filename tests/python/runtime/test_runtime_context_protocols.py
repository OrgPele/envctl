from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

_config = importlib.import_module("envctl_engine.config")
_engine_runtime = importlib.import_module("envctl_engine.runtime.engine_runtime")
_state_repository = importlib.import_module("envctl_engine.state.repository")
load_config = _config.load_config
PythonEngineRuntime = _engine_runtime.PythonEngineRuntime
RuntimeStateRepository = _state_repository.RuntimeStateRepository


class RuntimeContextProtocolsTests(unittest.TestCase):
    def test_runtime_initializes_context_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime)})
            engine = PythonEngineRuntime(config, env={})

            self.assertIsInstance(engine.state_repository, RuntimeStateRepository)
            self.assertIs(engine.runtime_context.state_repository, engine.state_repository)
            self.assertIs(engine.runtime_context.process_runtime, engine.process_runner)
            self.assertIs(engine.runtime_context.port_allocator, engine.port_planner)

    def test_engine_runtime_avoids_dynamic_dependency_probes(self) -> None:
        runtime_path = REPO_ROOT / "python/envctl_engine/engine_runtime.py"
        raw = runtime_path.read_text(encoding="utf-8")
        self.assertNotIn("getattr(self.process_runner", raw)
        self.assertNotIn("getattr(self.port_planner", raw)
        self.assertNotIn("getattr(self.state_repository", raw)
        self.assertNotIn("callable(", raw)

    def test_orchestrators_route_runtime_dependencies_via_context(self) -> None:
        orchestrator_paths = [
            REPO_ROOT / "python/envctl_engine/startup_orchestrator.py",
            REPO_ROOT / "python/envctl_engine/resume_orchestrator.py",
            REPO_ROOT / "python/envctl_engine/lifecycle_cleanup_orchestrator.py",
        ]
        for orchestrator_path in orchestrator_paths:
            raw = orchestrator_path.read_text(encoding="utf-8")
            self.assertNotIn("rt.port_planner", raw)
            self.assertNotIn("rt.state_repository", raw)
            self.assertNotIn("rt.process_runner", raw)


if __name__ == "__main__":
    unittest.main()
