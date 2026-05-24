# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.runtime.lifecycle_parity_test_support import *


class LifecycleResumeLegacyParityTests(unittest.TestCase):
    def test_resume_legacy_shell_state_skips_restore_startup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})
            legacy_state = RunState(
                run_id="legacy-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        pid=12345,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                metadata={"legacy_state": True},
            )

            restore_calls: list[list[str]] = []
            engine._try_load_existing_state = lambda mode=None, strict_mode_match=False: legacy_state  # type: ignore[method-assign]
            engine._reconcile_state_truth = lambda _state: ["Main Backend"]  # type: ignore[method-assign]
            engine._resume_restore_missing = (  # type: ignore[method-assign]
                lambda _state, missing, route=None: restore_calls.append(list(missing)) or []
            )

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertEqual(restore_calls, [])
            self.assertIn("Warning: stale services detected during resume", out.getvalue())

    def test_resume_legacy_shell_state_sanitizes_service_pids_before_truth_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})
            legacy_state = RunState(
                run_id="legacy-2",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        pid=os.getpid(),
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo / "frontend"),
                        pid=os.getpid(),
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
                metadata={"legacy_state": True},
            )

            engine._try_load_existing_state = lambda mode=None, strict_mode_match=False: legacy_state  # type: ignore[method-assign]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertIsNone(legacy_state.services["Main Backend"].pid)
            self.assertIsNone(legacy_state.services["Main Frontend"].pid)
            saved = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
            self.assertIsNone(saved["services"]["Main Backend"]["pid"])
            self.assertIsNone(saved["services"]["Main Frontend"]["pid"])

    def test_resume_skip_startup_flag_disables_restore_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=999999,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )
            dump_state(state, str(run_dir / "run_state.json"))

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})
            restore_runner = _ResumeRestoreRunner()
            engine.process_runner = restore_runner  # type: ignore[assignment]

            code = engine.dispatch(parse_route(["--resume", "--skip-startup", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertEqual(restore_runner.start_calls, [])
