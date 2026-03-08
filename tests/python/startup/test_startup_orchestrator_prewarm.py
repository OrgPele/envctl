from __future__ import annotations

import subprocess
import unittest
from types import SimpleNamespace
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.startup.startup_orchestrator import StartupOrchestrator


class _Runner:
    def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = int(returncode)
        self.stdout = str(stdout)
        self.stderr = str(stderr)
        self.calls: list[dict[str, object]] = []

    def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
        self.calls.append({"cmd": list(cmd), "timeout": timeout})
        return subprocess.CompletedProcess(list(cmd), self.returncode, self.stdout, self.stderr)


class _Runtime:
    def __init__(self, *, enabled_env: dict[str, str] | None = None, docker_exists: bool = True, requirement_enabled: bool = True) -> None:
        self.env = dict(enabled_env or {})
        self.config = SimpleNamespace(raw={})
        self.process_runner = _Runner()
        self.events: list[dict[str, object]] = []
        self._docker_exists = bool(docker_exists)
        self._requirement_enabled_flag = bool(requirement_enabled)

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append({"event": event, **payload})

    def _command_exists(self, executable: str) -> bool:
        return executable == "docker" and self._docker_exists

    def _requirement_enabled(self, service_name: str, *, mode: str, route=None) -> bool:  # noqa: ANN001
        _ = service_name, mode, route
        return self._requirement_enabled_flag


class StartupOrchestratorPrewarmTests(unittest.TestCase):
    def test_prewarm_runs_when_enabled_and_requirements_are_enabled(self) -> None:
        runtime = _Runtime()
        orchestrator = StartupOrchestrator(runtime)

        orchestrator._maybe_prewarm_docker(route=None, mode="main")

        self.assertEqual(len(runtime.process_runner.calls), 1)
        self.assertEqual(runtime.process_runner.calls[0]["cmd"], ["docker", "ps"])
        events = [item for item in runtime.events if item.get("event") == "requirements.docker_prewarm"]
        self.assertTrue(events)
        self.assertEqual(bool(events[-1].get("used")), True)
        self.assertEqual(bool(events[-1].get("success")), True)

    def test_prewarm_skips_when_disabled(self) -> None:
        runtime = _Runtime(enabled_env={"ENVCTL_DOCKER_PREWARM": "0"})
        orchestrator = StartupOrchestrator(runtime)

        orchestrator._maybe_prewarm_docker(route=None, mode="main")

        self.assertEqual(len(runtime.process_runner.calls), 0)
        events = [item for item in runtime.events if item.get("event") == "requirements.docker_prewarm"]
        self.assertTrue(events)
        self.assertEqual(bool(events[-1].get("used")), False)
        self.assertEqual(str(events[-1].get("reason", "")), "disabled")

    def test_prewarm_skips_when_no_requirements_enabled(self) -> None:
        runtime = _Runtime(requirement_enabled=False)
        orchestrator = StartupOrchestrator(runtime)

        orchestrator._maybe_prewarm_docker(route=None, mode="main")

        self.assertEqual(len(runtime.process_runner.calls), 0)
        events = [item for item in runtime.events if item.get("event") == "requirements.docker_prewarm"]
        self.assertTrue(events)
        self.assertEqual(bool(events[-1].get("used")), False)
        self.assertEqual(str(events[-1].get("reason", "")), "no_enabled_requirements")


if __name__ == "__main__":
    unittest.main()
