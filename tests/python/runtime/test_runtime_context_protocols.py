from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

_config = importlib.import_module("envctl_engine.config")
_engine_runtime = importlib.import_module("envctl_engine.runtime.engine_runtime")
_state_repository = importlib.import_module("envctl_engine.state.repository")
_runtime_context = importlib.import_module("envctl_engine.runtime.runtime_context")
_resume_restore_support = importlib.import_module("envctl_engine.startup.resume_restore_support")
_startup_selection_support = importlib.import_module("envctl_engine.startup.startup_selection_support")
_lifecycle_cleanup = importlib.import_module("envctl_engine.runtime.lifecycle_cleanup_orchestrator")
load_config = _config.load_config
PythonEngineRuntime = _engine_runtime.PythonEngineRuntime
RuntimeStateRepository = _state_repository.RuntimeStateRepository
RuntimeContext = _runtime_context.RuntimeContext


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
        runtime_path = REPO_ROOT / "python/envctl_engine/runtime/engine_runtime.py"
        raw = runtime_path.read_text(encoding="utf-8")
        self.assertNotIn("getattr(self.process_runner", raw)
        self.assertNotIn("getattr(self.port_planner", raw)
        self.assertNotIn("getattr(self.state_repository", raw)
        self.assertNotIn("callable(", raw)

    def test_orchestrators_route_runtime_dependencies_via_context(self) -> None:
        orchestrator_paths = [
            REPO_ROOT / "python/envctl_engine/startup/startup_orchestrator.py",
            REPO_ROOT / "python/envctl_engine/startup/resume_orchestrator.py",
            REPO_ROOT / "python/envctl_engine/runtime/lifecycle_cleanup_orchestrator.py",
        ]
        for orchestrator_path in orchestrator_paths:
            raw = orchestrator_path.read_text(encoding="utf-8")
            self.assertNotIn("rt.port_planner", raw)
            self.assertNotIn("rt.state_repository", raw)
            self.assertNotIn("rt.process_runner", raw)

    def test_helper_accessors_prefer_runtime_context_dependencies(self) -> None:
        context_state_repository = object()
        context_port_allocator = object()
        context_process_runtime = object()
        runtime = SimpleNamespace()
        runtime.runtime_context = RuntimeContext(
            config=object(),
            env={},
            process_runtime=context_process_runtime,
            port_allocator=context_port_allocator,
            state_repository=context_state_repository,
            terminal_ui=object(),
            emit=lambda *_args, **_kwargs: None,
        )
        runtime.state_repository = object()
        runtime.port_planner = object()
        runtime.process_runner = object()

        self.assertIs(_resume_restore_support._state_repository(runtime), context_state_repository)
        self.assertIs(_resume_restore_support._port_allocator(runtime), context_port_allocator)
        self.assertIs(_startup_selection_support._port_allocator(runtime), context_port_allocator)
        self.assertIs(_startup_selection_support._process_runtime(runtime), context_process_runtime)
        self.assertIs(
            _lifecycle_cleanup.LifecycleCleanupOrchestrator._state_repository(runtime), context_state_repository
        )
        self.assertIs(
            _lifecycle_cleanup.LifecycleCleanupOrchestrator._process_runtime(runtime), context_process_runtime
        )

    def test_helper_accessors_fall_back_to_runtime_attributes_when_context_missing(self) -> None:
        runtime = SimpleNamespace()
        runtime.state_repository = object()
        runtime.port_planner = object()
        runtime.process_runner = object()

        self.assertIs(_resume_restore_support._state_repository(runtime), runtime.state_repository)
        self.assertIs(_resume_restore_support._port_allocator(runtime), runtime.port_planner)
        self.assertIs(_startup_selection_support._port_allocator(runtime), runtime.port_planner)
        self.assertIs(_startup_selection_support._process_runtime(runtime), runtime.process_runner)
        self.assertIs(
            _lifecycle_cleanup.LifecycleCleanupOrchestrator._state_repository(runtime), runtime.state_repository
        )
        self.assertIs(_lifecycle_cleanup.LifecycleCleanupOrchestrator._process_runtime(runtime), runtime.process_runner)

    def test_runtime_context_stays_synced_when_runtime_collaborators_are_reassigned(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime)})
            engine = PythonEngineRuntime(config, env={})

            process_runner = object()
            port_planner = object()
            state_repository = object()
            terminal_ui = object()

            engine.process_runner = process_runner  # type: ignore[assignment]
            engine.port_planner = port_planner  # type: ignore[assignment]
            engine.state_repository = state_repository  # type: ignore[assignment]
            engine.terminal_ui = terminal_ui  # type: ignore[assignment]

            self.assertIs(engine.runtime_context.process_runtime, process_runner)
            self.assertIs(engine.runtime_context.port_allocator, port_planner)
            self.assertIs(engine.runtime_context.state_repository, state_repository)
            self.assertIs(engine.runtime_context.terminal_ui, terminal_ui)


if __name__ == "__main__":
    unittest.main()
