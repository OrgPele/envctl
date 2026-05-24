from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from envctl_engine.config import load_config
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime


class RuntimeDebugFacadeMixinTests(unittest.TestCase):
    def _runtime(self, repo: Path, runtime_root: Path) -> PythonEngineRuntime:
        return PythonEngineRuntime(
            load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime_root)}),
            env={},
        )

    def test_debug_facade_methods_remain_on_python_engine_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            repo.mkdir()
            runtime = self._runtime(repo, runtime_root)
            route = Route(command="debug-pack", mode="main")

            with patch(
                "envctl_engine.runtime.engine_runtime_debug_facade.runtime_debug_pack",
                return_value=3,
            ) as debug_pack:
                result = runtime._debug_pack(route)

        self.assertEqual(result, 3)
        debug_pack.assert_called_once_with(runtime, route)

    def test_debug_facade_preserves_static_scope_helpers(self) -> None:
        scope_dir = Path("/tmp/envctl-scope")

        with patch(
            "envctl_engine.runtime.engine_runtime_debug_facade.runtime_scope_latest_run_id",
            return_value="run-1",
        ) as latest_run:
            result = PythonEngineRuntime._scope_latest_run_id(scope_dir)

        self.assertEqual(result, "run-1")
        latest_run.assert_called_once_with(scope_dir)


if __name__ == "__main__":
    unittest.main()
