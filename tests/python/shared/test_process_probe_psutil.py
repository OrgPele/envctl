from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import importlib
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
config_module = importlib.import_module("envctl_engine.config")
runtime_module = importlib.import_module("envctl_engine.runtime.engine_runtime")
probe_module = importlib.import_module("envctl_engine.shared.process_probe")

load_config = config_module.load_config
PythonEngineRuntime = runtime_module.PythonEngineRuntime
PsutilProbeBackend = probe_module.PsutilProbeBackend


class ProcessProbePsutilTests(unittest.TestCase):
    def test_psutil_backend_reports_pid_running(self) -> None:
        class _Proc:
            def is_running(self) -> bool:
                return True

        fake_psutil = SimpleNamespace(
            pid_exists=lambda _pid: True,
            Process=lambda _pid: _Proc(),
            net_connections=lambda **_kwargs: [],
            AccessDenied=RuntimeError,
            NoSuchProcess=RuntimeError,
        )

        backend = PsutilProbeBackend(psutil_module=fake_psutil)
        self.assertTrue(backend.is_pid_running(123))

    def test_psutil_backend_pid_owns_port(self) -> None:
        conn = SimpleNamespace(pid=123, laddr=SimpleNamespace(port=8000), status="LISTEN")
        fake_psutil = SimpleNamespace(
            pid_exists=lambda _pid: True,
            Process=lambda _pid: SimpleNamespace(is_running=lambda: True),
            net_connections=lambda **_kwargs: [conn],
            AccessDenied=RuntimeError,
            NoSuchProcess=RuntimeError,
        )

        backend = PsutilProbeBackend(psutil_module=fake_psutil)
        self.assertTrue(backend.pid_owns_port(123, 8000))
        self.assertFalse(backend.pid_owns_port(123, 9000))

    def test_psutil_backend_wait_for_port(self) -> None:
        conn = SimpleNamespace(pid=123, laddr=SimpleNamespace(port=8001), status="LISTEN")
        fake_psutil = SimpleNamespace(
            pid_exists=lambda _pid: True,
            Process=lambda _pid: SimpleNamespace(is_running=lambda: True),
            net_connections=lambda **_kwargs: [conn],
            AccessDenied=RuntimeError,
            NoSuchProcess=RuntimeError,
        )

        backend = PsutilProbeBackend(psutil_module=fake_psutil, time_source=lambda: 0.0, sleep=lambda _s: None)
        self.assertTrue(backend.wait_for_port(8001, timeout=0.0))
        self.assertFalse(backend.wait_for_port(9000, timeout=0.0))

    def test_runtime_uses_psutil_backend_when_enabled(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
            }
        )

        class _BackendStub:
            def __init__(self) -> None:
                self.label = "psutil"

        with (
            patch("envctl_engine.runtime.engine_runtime.psutil_available", return_value=True),
            patch("envctl_engine.runtime.engine_runtime.PsutilProbeBackend", return_value=_BackendStub()),
        ):
            runtime = PythonEngineRuntime(config, env={"ENVCTL_PROBE_PSUTIL": "true"})

        self.assertEqual(getattr(runtime.process_probe.backend, "label", ""), "psutil")
        self.assertTrue(
            any(event.get("event") == "probe.backend" and event.get("backend") == "psutil" for event in runtime.events)
        )


if __name__ == "__main__":
    unittest.main()
