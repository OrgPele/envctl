from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime


class RuntimeTruthFacadeMixinTests(unittest.TestCase):
    def _runtime(self, repo: Path, runtime_root: Path) -> PythonEngineRuntime:
        return PythonEngineRuntime(
            load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime_root)}),
            env={},
        )

    def test_state_truth_wrapper_remains_on_python_engine_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            repo.mkdir()
            runtime = self._runtime(repo, runtime_root)
            state = object()

            with patch(
                "envctl_engine.runtime.engine_runtime_truth_facade.runtime_reconcile_state_truth",
                return_value=["issue"],
            ) as reconcile:
                result = runtime._reconcile_state_truth(state)

        self.assertEqual(result, ["issue"])
        reconcile.assert_called_once_with(runtime, state)

    def test_service_truth_wrapper_remains_on_python_engine_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            repo.mkdir()
            runtime = self._runtime(repo, runtime_root)
            service = object()

            with patch(
                "envctl_engine.runtime.engine_runtime_truth_facade.runtime_service_truth_status",
                return_value="running",
            ) as truth_status:
                result = runtime._service_truth_status(service)

        self.assertEqual(result, "running")
        truth_status.assert_called_once_with(runtime, service)


if __name__ == "__main__":
    unittest.main()
