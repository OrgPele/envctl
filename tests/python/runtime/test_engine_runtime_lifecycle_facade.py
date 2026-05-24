from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime


class RuntimeLifecycleFacadeMixinTests(unittest.TestCase):
    def _runtime(self, repo: Path, runtime_root: Path) -> PythonEngineRuntime:
        return PythonEngineRuntime(
            load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime_root)}),
            env={},
        )

    def test_lifecycle_wrapper_remains_on_python_engine_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            repo.mkdir()
            runtime = self._runtime(repo, runtime_root)
            services = {"backend": object()}

            with patch(
                "envctl_engine.runtime.engine_runtime_lifecycle_facade.runtime_terminate_started_services",
            ) as terminate:
                runtime._terminate_started_services(services)

        terminate.assert_called_once_with(runtime, services)

    def test_requirement_port_release_wrapper_remains_on_python_engine_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            repo.mkdir()
            runtime = self._runtime(repo, runtime_root)
            requirements = object()

            with patch(
                "envctl_engine.runtime.engine_runtime_lifecycle_facade.runtime_release_requirement_ports",
            ) as release:
                runtime._release_requirement_ports(requirements)

        release.assert_called_once_with(runtime, requirements)


if __name__ == "__main__":
    unittest.main()
