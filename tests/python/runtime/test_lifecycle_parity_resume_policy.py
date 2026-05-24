# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.runtime.lifecycle_parity_test_support import *


class LifecycleResumePolicyParityTests(unittest.TestCase):
    def test_resume_blocks_when_mode_startup_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "MAIN_STARTUP_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            engine._try_load_existing_state = lambda **_kwargs: RunState(run_id="run-main", mode="main")  # type: ignore[assignment]
            engine._reconcile_state_truth = lambda _state: self.fail("reconcile should not run")  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume", "--main", "--batch"], env={}))

            self.assertEqual(code, 1)
            self.assertIn("envctl runs are disabled for main in .envctl", out.getvalue())

    def test_resume_does_not_fallback_to_cross_mode_state(self) -> None:
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
            seen_calls: list[tuple[str | None, bool]] = []
            trees_state = RunState(
                run_id="run-trees",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1234,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )

            def fake_load(*, mode=None, strict_mode_match=False):  # noqa: ANN001
                seen_calls.append((mode, strict_mode_match))
                if mode == "main" and not strict_mode_match:
                    return trees_state
                return None

            engine._try_load_existing_state = fake_load  # type: ignore[method-assign]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume", "--main", "--batch"], env={}))

            self.assertEqual(code, 1)
            self.assertIn("No previous state found to resume.", out.getvalue())
            self.assertEqual(seen_calls, [("main", True)])

    def test_resume_without_explicit_mode_falls_back_to_latest_state_mode(self) -> None:
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
            seen_calls: list[tuple[str | None, bool]] = []
            trees_state = RunState(
                run_id="run-trees",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1234,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )

            def fake_load(*, mode=None, strict_mode_match=False):  # noqa: ANN001
                seen_calls.append((mode, strict_mode_match))
                if mode == "main" and not strict_mode_match:
                    return trees_state
                return None

            engine._try_load_existing_state = fake_load  # type: ignore[method-assign]
            engine._reconcile_state_truth = lambda state: []  # type: ignore[method-assign]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertIn("Resumed run_id=run-trees session_id=", out.getvalue())
            self.assertEqual(seen_calls, [("main", False)])
            self.assertEqual(engine.env.get("ENVCTL_DEBUG_UI_RUN_ID"), "run-trees")

    def test_resume_interactive_suppresses_resumed_projection_banner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-interactive",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1234,
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
            engine._should_enter_resume_interactive = lambda _route: True  # type: ignore[method-assign]
            engine._run_interactive_dashboard_loop = lambda _state: 0  # type: ignore[method-assign]
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume"], env={}))

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertNotIn("Resumed run_id=", rendered)
            self.assertNotIn("backend=http://", rendered)

    def test_resume_reconciles_missing_service_status(self) -> None:
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
                        cwd=str(repo / "backend"),
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
            code = engine.dispatch(parse_route(["--resume"], env={}))

            self.assertEqual(code, 0)
            reconciled = json.loads((run_dir / "runtime_map.json").read_text(encoding="utf-8"))
            self.assertEqual(reconciled["run_id"], "run-1")
            self.assertTrue(any(event["event"] == "state.reconcile" for event in engine.events))

    def test_resume_fails_fast_for_conflicting_main_requirement_mode_flags(self) -> None:
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
                        cwd=str(repo / "backend"),
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
            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(
                    parse_route(
                        ["--resume", "--main-services-local", "--main-services-remote", "--batch"],
                        env={},
                    )
                )

            self.assertEqual(code, 1)
            self.assertIn("Conflicting main requirements flags", out.getvalue())

    def test_resume_restarts_missing_services_when_commands_are_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        pid=999999,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )
            dump_state(state, str(run_dir / "run_state.json"))

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 5'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 5'",
                },
            )
            restore_runner = _ResumeRestoreRunner()
            engine.process_runner = restore_runner  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertTrue(any("Restoring stale services..." in line for line in out.getvalue().splitlines()))
            resumed_state = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
            services = resumed_state["services"]
            self.assertIn("Main Backend", services)
            self.assertIn("Main Frontend", services)
            self.assertNotEqual(services["Main Backend"]["pid"], 999999)
            self.assertGreater(len(restore_runner.start_calls), 0)

    def test_resume_interactive_restarts_missing_services_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-2",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        pid=999999,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )
            dump_state(state, str(run_dir / "run_state.json"))

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 5'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 5'",
                },
            )
            restore_runner = _ResumeRestoreRunner()
            engine.process_runner = restore_runner  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume"], env={}))

            self.assertEqual(code, 0)
            self.assertTrue(any("Restoring stale services..." in line for line in out.getvalue().splitlines()))
            resumed_state = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
            services = resumed_state["services"]
            self.assertIn("Main Backend", services)
            self.assertIn("Main Frontend", services)
            self.assertGreater(len(restore_runner.start_calls), 0)

    def test_resume_reuses_healthy_requirements_when_only_services_are_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-5",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        pid=999999,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                requirements={
                    "Main": RequirementsResult(
                        project="Main",
                        db={
                            "requested": 5432,
                            "final": 5432,
                            "retries": 0,
                            "success": True,
                            "enabled": True,
                            "simulated": False,
                        },
                        redis={
                            "requested": 6379,
                            "final": 6379,
                            "retries": 0,
                            "success": True,
                            "enabled": True,
                            "simulated": False,
                        },
                        n8n={
                            "requested": 5678,
                            "final": 5678,
                            "retries": 0,
                            "success": True,
                            "enabled": False,
                            "simulated": False,
                        },
                        supabase={
                            "requested": 5432,
                            "final": 5432,
                            "retries": 0,
                            "success": True,
                            "enabled": False,
                            "simulated": False,
                        },
                        health="healthy",
                        failures=[],
                    )
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )
            dump_state(state, str(run_dir / "run_state.json"))

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                    "POSTGRES_MAIN_ENABLE": "true",
                    "REDIS_ENABLE": "true",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 5'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 5'",
                    "ENVCTL_DEBUG_RESTORE_TIMING": "true",
                },
            )
            restore_runner = _ResumeRestoreRunner()
            engine.process_runner = restore_runner  # type: ignore[assignment]
            engine._reconcile_project_requirement_truth = lambda *_args, **_kwargs: []  # type: ignore[method-assign]

            def fail_requirements_start(*_args, **_kwargs):  # noqa: ANN001
                raise AssertionError("requirements should have been reused and not restarted")

            engine._start_requirements_for_project = fail_requirements_start  # type: ignore[method-assign]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertIn("start_requirements=0.0ms", out.getvalue())
            self.assertTrue(any(event.get("event") == "resume.restore.requirements_reuse" for event in engine.events))
            self.assertGreater(len(restore_runner.start_calls), 0)
