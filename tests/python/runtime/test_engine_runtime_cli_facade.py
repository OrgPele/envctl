from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from envctl_engine.config import load_config
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime


class RuntimeCliFacadeMixinTests(unittest.TestCase):
    def _runtime(self, repo: Path, runtime_root: Path) -> PythonEngineRuntime:
        return PythonEngineRuntime(
            load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime_root)}),
            env={},
        )

    def test_cli_facade_methods_remain_on_python_engine_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            repo.mkdir()
            runtime = self._runtime(repo, runtime_root)
            route = Route(command="config", mode="main")

            with patch(
                "envctl_engine.runtime.engine_runtime_cli_facade.runtime_run_config",
                return_value=7,
            ) as run_config:
                result = runtime._config(route)

        self.assertEqual(result, 7)
        run_config.assert_called_once_with(runtime, route)

    def test_cli_facade_preserves_static_help_text_wrapper(self) -> None:
        route = Route(command="help", mode="main")

        with patch(
            "envctl_engine.runtime.engine_runtime_cli_facade.runtime_render_help_text",
            return_value="usage",
        ) as render_help:
            result = PythonEngineRuntime._render_help_text(route)

        self.assertEqual(result, "usage")
        render_help.assert_called_once_with(route)


if __name__ == "__main__":
    unittest.main()
