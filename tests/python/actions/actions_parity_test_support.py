from __future__ import annotations

import unittest
import importlib
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
actions_test_module = importlib.import_module("envctl_engine.actions.actions_test")
action_test_support_module = importlib.import_module("envctl_engine.actions.action_test_support")
action_command_orchestrator_module = importlib.import_module("envctl_engine.actions.action_command_orchestrator")
action_test_summary_support_module = importlib.import_module("envctl_engine.actions.action_test_summary_support")
action_migrate_support_module = importlib.import_module("envctl_engine.actions.action_migrate_support")
command_router_module = importlib.import_module("envctl_engine.runtime.command_router")
config_module = importlib.import_module("envctl_engine.config")
engine_runtime_module = importlib.import_module("envctl_engine.runtime.engine_runtime")

default_test_command = actions_test_module.default_test_command
default_test_commands = actions_test_module.default_test_commands
rich_test_command_suggestions = actions_test_module.test_command_suggestions
frontend_test_path_suggestions = actions_test_module.frontend_test_path_suggestions
suggest_backend_test_command = actions_test_module.suggest_backend_test_command
suggest_frontend_test_command = actions_test_module.suggest_frontend_test_command
_configured_or_default_test_spec = action_test_support_module._configured_or_default_test_spec
collect_failed_test_manifest_entries = action_test_summary_support_module.collect_failed_test_manifest_entries
default_git_state_components = action_test_summary_support_module.default_git_state_components
ActionCommandOrchestrator = action_command_orchestrator_module.ActionCommandOrchestrator
parse_route = command_router_module.parse_route
load_config = config_module.load_config
PythonEngineRuntime = engine_runtime_module.PythonEngineRuntime
RunState = engine_runtime_module.RunState
ServiceRecord = engine_runtime_module.ServiceRecord
RequirementsResult = engine_runtime_module.RequirementsResult
strip_ansi = importlib.import_module("envctl_engine.test_output.parser_base").strip_ansi


class _FakeRunner:
    def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.run_calls: list[tuple[tuple[str, ...], str]] = []
        self.run_envs: list[dict[str, str] | None] = []

    def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
        _ = env, timeout
        self.run_calls.append((tuple(cmd), str(cwd)))
        self.run_envs.append(dict(env) if isinstance(env, dict) else None)
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr=self.stderr)

    def start(self, cmd, *, cwd=None, env=None):  # noqa: ANN001
        _ = cmd, cwd, env
        return SimpleNamespace(pid=10001, poll=lambda: None)

    def wait_for_port(self, _port: int, *, host: str = "127.0.0.1", timeout: float = 30.0) -> bool:
        _ = host, timeout
        return True

    def is_pid_running(self, _pid: int) -> bool:
        return False


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


class _ActionsParityTestCase(unittest.TestCase):
    def _config(self, repo: Path, runtime: Path):
        return load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(runtime),
                "ENVCTL_DEFAULT_MODE": "trees",
            }
        )

    def _save_state(self, engine: PythonEngineRuntime, state: RunState) -> None:
        engine.state_repository.save_resume_state(
            state=state,
            emit=engine._emit,
            runtime_map_builder=engine_runtime_module.build_runtime_map,
        )
