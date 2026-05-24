from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime


class RuntimeDoctorFacadeMixinTests(unittest.TestCase):
    def _runtime(self, repo: Path, runtime_root: Path) -> PythonEngineRuntime:
        return PythonEngineRuntime(
            load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime_root)}),
            env={},
        )

    def test_doctor_facade_methods_remain_on_python_engine_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            repo.mkdir()
            runtime = self._runtime(repo, runtime_root)

            with patch(
                "envctl_engine.runtime.engine_runtime_doctor_facade.runtime_doctor",
                return_value=5,
            ) as doctor:
                result = runtime._doctor()

        self.assertEqual(result, 5)
        doctor.assert_called_once_with(runtime)

    def test_doctor_facade_preserves_shipability_contract_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            repo.mkdir()
            runtime = self._runtime(repo, runtime_root)

            with patch(
                "envctl_engine.runtime.engine_runtime_doctor_facade.runtime_evaluate_runtime_shipability",
                return_value={"ok": True},
            ) as evaluate:
                result = runtime._evaluate_shipability(enforce_runtime_readiness_contract=False)

        self.assertEqual(result, {"ok": True})
        evaluate.assert_called_once_with(runtime, enforce_runtime_readiness_contract=False)


if __name__ == "__main__":
    unittest.main()
