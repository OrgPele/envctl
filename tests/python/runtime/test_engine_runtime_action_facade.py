from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from envctl_engine.config import load_config
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.engine_runtime import ProjectContext, PythonEngineRuntime


class RuntimeActionFacadeMixinTests(unittest.TestCase):
    def _runtime(self, repo: Path, runtime_root: Path) -> PythonEngineRuntime:
        return PythonEngineRuntime(
            load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime_root)}),
            env={},
        )

    def test_action_facade_methods_remain_on_python_engine_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            repo.mkdir()
            runtime = self._runtime(repo, runtime_root)
            route = Route(command="test", mode="main")
            target = ProjectContext(name="Main", root=repo, ports={})

            with patch(
                "envctl_engine.runtime.engine_runtime_action_facade.runtime_run_test_action",
                return_value=42,
            ) as run_test:
                result = runtime._run_test_action(route, [target])

        self.assertEqual(result, 42)
        run_test.assert_called_once_with(runtime, route, [target])

    def test_action_facade_keeps_static_selector_and_service_helpers(self) -> None:
        selectors = PythonEngineRuntime._selectors_from_passthrough(["--project", "Main", "--frontend"])

        self.assertEqual(selectors, {"main"})
        self.assertEqual(PythonEngineRuntime._project_name_from_service("Main Backend"), "Main")


if __name__ == "__main__":
    unittest.main()
