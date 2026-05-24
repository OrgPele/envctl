# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.runtime.lifecycle_parity_test_support import *


class LifecycleRestoreStartupParityTests(unittest.TestCase):
    def test_resume_restore_skips_backend_migration_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            backend_dir = repo / "backend"
            frontend_dir = repo / "frontend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            frontend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            (backend_dir / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-resume-migrate",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(backend_dir),
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
            restore_runner.fail_alembic = True
            engine.process_runner = restore_runner  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertNotIn("Warning: backend migration step failed", out.getvalue())
            self.assertFalse(
                any(command[-3:] == ("alembic", "upgrade", "head") for command in restore_runner.run_calls)
            )

    def test_resume_restore_does_not_reuse_requirements_when_project_root_reveals_owner_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            backend_dir = repo / "backend"
            frontend_dir = repo / "frontend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            frontend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-resume-owner-mismatch",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(backend_dir),
                        pid=999999,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(frontend_dir),
                        pid=999998,
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
                requirements={
                    "Main": RequirementsResult(
                        project="Main",
                        db={
                            "requested": 5432,
                            "final": 5432,
                            "retries": 0,
                            "success": False,
                            "enabled": False,
                            "simulated": False,
                        },
                        redis={
                            "requested": 6379,
                            "final": 6379,
                            "retries": 0,
                            "success": True,
                            "enabled": True,
                            "simulated": False,
                            "runtime_status": "healthy",
                        },
                        supabase={
                            "requested": 5432,
                            "final": 5432,
                            "retries": 0,
                            "success": False,
                            "enabled": False,
                            "simulated": False,
                        },
                        n8n={
                            "requested": 5678,
                            "final": 5678,
                            "retries": 0,
                            "success": False,
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
                    "REDIS_ENABLE": "true",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                    "POSTGRES_MAIN_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 1'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 1'",
                    "ENVCTL_DEBUG_RESTORE_TIMING": "true",
                },
            )
            restore_runner = _ResumeRestoreRunner()
            engine.process_runner = restore_runner  # type: ignore[assignment]

            def fake_reconcile(project: str, requirements: RequirementsResult, *, project_root: Path | None = None):  # noqa: ANN001
                self.assertEqual(project, "Main")
                self.assertEqual(project_root, repo)
                return [{"component": "redis", "status": "unreachable"}]

            engine._reconcile_project_requirement_truth = fake_reconcile  # type: ignore[method-assign]

            started_requirements: list[str] = []

            def fake_start_requirements(_context: object, *, mode: str, route):  # noqa: ANN001
                _ = mode, route
                started_requirements.append("Main")
                return RequirementsResult(
                    project="Main",
                    db={
                        "requested": 5432,
                        "final": 5432,
                        "retries": 0,
                        "success": False,
                        "enabled": False,
                        "simulated": False,
                    },
                    redis={
                        "requested": 6380,
                        "final": 6380,
                        "retries": 0,
                        "success": True,
                        "enabled": True,
                        "simulated": False,
                        "runtime_status": "healthy",
                    },
                    supabase={
                        "requested": 5432,
                        "final": 5432,
                        "retries": 0,
                        "success": False,
                        "enabled": False,
                        "simulated": False,
                    },
                    n8n={
                        "requested": 5678,
                        "final": 5678,
                        "retries": 0,
                        "success": False,
                        "enabled": False,
                        "simulated": False,
                    },
                    health="healthy",
                    failures=[],
                )

            engine._start_requirements_for_project = fake_start_requirements  # type: ignore[method-assign]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertEqual(started_requirements, ["Main"])
            reuse_event = next(
                event for event in engine.events if event.get("event") == "resume.restore.requirements_reuse"
            )
            self.assertFalse(bool(reuse_event.get("reused")))
            self.assertEqual(reuse_event.get("reason"), "dependency_endpoint_changed")

    def test_resume_restore_uses_spinner_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-3",
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
            original_start_requirements = engine._start_requirements_for_project

            def reporting_start_requirements(context, mode, route=None):  # noqa: ANN001
                spinner_update = None if route is None else route.flags.get("_spinner_update")
                if callable(spinner_update):
                    spinner_update("Loading requirements: redis | queued: supabase")
                return original_start_requirements(context, mode=mode, route=route)

            engine._start_requirements_for_project = reporting_start_requirements  # type: ignore[method-assign]

            spinner_calls: list[tuple[str, str] | tuple[str, str, bool]] = []

            class _SpinnerStub:
                def update(self, message: str) -> None:
                    spinner_calls.append(("update", message))

                def succeed(self, message: str) -> None:
                    spinner_calls.append(("succeed", message))

                def fail(self, message: str) -> None:
                    spinner_calls.append(("fail", message))

            @contextmanager
            def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
                _ = start_immediately
                spinner_calls.append(("start", message, enabled))
                yield _SpinnerStub()

            out = StringIO()
            with (
                patch("envctl_engine.startup.resume_orchestrator.spinner_enabled", return_value=True),
                patch("envctl_engine.startup.resume_orchestrator.spinner", side_effect=fake_spinner),
                redirect_stdout(out),
            ):
                code = engine.dispatch(parse_route(["--resume", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertIn(("start", "Preparing stale restore for 1 project(s)...", True), spinner_calls)
            self.assertIn(("update", "[1/1] Restoring stale services..."), spinner_calls)
            self.assertIn(("update", "[1/1] Loading requirements: redis | queued: supabase"), spinner_calls)
            self.assertIn(("succeed", "stale services restored"), spinner_calls)
            self.assertNotIn("Restoring stale services...", out.getvalue())

    def test_resume_restore_uses_project_spinner_group_for_multi_project_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            tree_a = repo / "trees" / "feature-a" / "1"
            tree_b = repo / "trees" / "feature-b" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (tree_a / "backend").mkdir(parents=True, exist_ok=True)
            (tree_a / "frontend").mkdir(parents=True, exist_ok=True)
            (tree_b / "backend").mkdir(parents=True, exist_ok=True)
            (tree_b / "frontend").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-5",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(tree_a / "backend"),
                        pid=999999,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "feature-b-1 Backend": ServiceRecord(
                        name="feature-b-1 Backend",
                        type="backend",
                        cwd=str(tree_b / "backend"),
                        pid=999998,
                        requested_port=8010,
                        actual_port=8010,
                        status="running",
                    ),
                },
                metadata={
                    "project_roots": {
                        "feature-a-1": str(tree_a),
                        "feature-b-1": str(tree_b),
                    }
                },
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
                    "ENVCTL_UI_SPINNER_MODE": "on",
                },
            )
            restore_runner = _ResumeRestoreRunner()
            engine.process_runner = restore_runner  # type: ignore[assignment]

            def reporting_start_requirements(context, mode, route=None):  # noqa: ANN001
                project_update = None if route is None else route.flags.get("_spinner_update_project")
                if callable(project_update):
                    project_update(context.name, "Loading requirements: postgres")
                return RequirementsResult(
                    project=context.name,
                    db={"enabled": True, "success": True, "requested": 5432, "final": 5432},
                    redis={"enabled": False, "success": True},
                    n8n={"enabled": False, "success": True},
                    supabase={"enabled": False, "success": True},
                    health="healthy",
                )

            engine._start_requirements_for_project = reporting_start_requirements  # type: ignore[method-assign]

            group_calls: list[tuple[str, str, str]] = []

            class _GroupStub:
                def __init__(self, projects, **_kwargs):  # noqa: ANN001
                    self._projects = list(projects)

                def __enter__(self):
                    group_calls.append(("enter", ",".join(self._projects), ""))
                    return self

                def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
                    _ = exc_type, exc, tb
                    group_calls.append(("exit", "", ""))
                    return False

                def update_project(self, project: str, message: str) -> None:
                    group_calls.append(("update", project, message))

                def mark_success(self, project: str, message: str) -> None:
                    group_calls.append(("success", project, message))

                def mark_failure(self, project: str, message: str) -> None:
                    group_calls.append(("failure", project, message))

            with (
                patch("envctl_engine.startup.resume_orchestrator.spinner_enabled", return_value=True),
                patch("envctl_engine.startup.resume_orchestrator._ResumeProjectSpinnerGroup", _GroupStub),
                patch("envctl_engine.startup.resume_orchestrator.resolve_spinner_policy") as policy_mock,
            ):
                policy_mock.side_effect = lambda *_args, **_kwargs: type(
                    "_Policy",
                    (),
                    {
                        "mode": "on",
                        "enabled": True,
                        "reason": "",
                        "backend": "rich",
                        "min_ms": 120,
                        "verbose_events": False,
                        "style": "dots",
                    },
                )()
                code = engine.dispatch(parse_route(["--resume", "--tree", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertTrue(any(kind == "enter" for kind, _project, _msg in group_calls))
            updated_projects = {project for kind, project, _msg in group_calls if kind == "update"}
            self.assertIn("feature-a-1", updated_projects)
            self.assertIn("feature-b-1", updated_projects)
            update_messages = [msg for kind, _project, msg in group_calls if kind == "update"]
            self.assertTrue(any("Loading requirements: postgres" in msg for msg in update_messages))
            succeeded_projects = {project for kind, project, _msg in group_calls if kind == "success"}
            self.assertIn("feature-a-1", succeeded_projects)
            self.assertIn("feature-b-1", succeeded_projects)
            execution_events = [event for event in engine.events if event.get("event") == "resume.restore.execution"]
            self.assertTrue(execution_events)
            self.assertEqual(execution_events[-1].get("mode"), "parallel")

    def test_resume_restore_failure_marks_existing_requirements_unreachable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            tree = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (tree / "backend").mkdir(parents=True, exist_ok=True)
            (tree / "frontend").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-fail",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(tree / "backend"),
                        pid=1234,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                },
                requirements={
                    "feature-a-1": RequirementsResult(
                        project="feature-a-1",
                        redis={
                            "enabled": True,
                            "success": True,
                            "final": 6384,
                            "container_name": "envctl-redis-feature-a",
                        },
                        n8n={"enabled": True, "success": True, "final": 5683, "container_name": "envctl-n8n-feature-a"},
                        supabase={
                            "enabled": True,
                            "success": True,
                            "final": 5437,
                            "container_name": "envctl-supabase-feature-a-supabase-db-1",
                        },
                    )
                },
                metadata={"project_roots": {"feature-a-1": str(tree)}},
            )
            dump_state(state, str(run_dir / "run_state.json"))

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            restore_runner = _ResumeRestoreRunner()
            engine.process_runner = restore_runner  # type: ignore[assignment]

            def fail_requirements(*_args, **_kwargs):  # noqa: ANN001
                raise RuntimeError("requirements unavailable: redis failed, n8n failed")

            engine._start_requirements_for_project = fail_requirements  # type: ignore[method-assign]
            errors = engine._resume_restore_missing(
                state, ["feature-a-1 Backend"], route=parse_route(["--resume", "--batch"], env={})
            )

            self.assertTrue(errors)
            requirements = state.requirements["feature-a-1"]
            self.assertEqual(requirements.health, "degraded")
            self.assertTrue(requirements.failures)
            self.assertEqual(requirements.redis["runtime_status"], "unreachable")
            self.assertEqual(requirements.n8n["runtime_status"], "unreachable")
            self.assertEqual(requirements.supabase["runtime_status"], "unreachable")

    def test_resume_restore_runs_projects_in_parallel_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            tree_a = repo / "trees" / "feature-a" / "1"
            tree_b = repo / "trees" / "feature-b" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (tree_a / "backend").mkdir(parents=True, exist_ok=True)
            (tree_a / "frontend").mkdir(parents=True, exist_ok=True)
            (tree_b / "backend").mkdir(parents=True, exist_ok=True)
            (tree_b / "frontend").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-6",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(tree_a / "backend"),
                        pid=999999,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "feature-b-1 Backend": ServiceRecord(
                        name="feature-b-1 Backend",
                        type="backend",
                        cwd=str(tree_b / "backend"),
                        pid=999998,
                        requested_port=8010,
                        actual_port=8010,
                        status="running",
                    ),
                },
                metadata={
                    "project_roots": {
                        "feature-a-1": str(tree_a),
                        "feature-b-1": str(tree_b),
                    }
                },
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
                    "RUN_SH_OPT_PARALLEL_TREES": "true",
                    "RUN_SH_OPT_PARALLEL_TREES_MAX": "4",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 5'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 5'",
                    "ENVCTL_UI_SPINNER_MODE": "off",
                },
            )
            restore_runner = _ResumeRestoreRunner()
            engine.process_runner = restore_runner  # type: ignore[assignment]
            engine._start_requirements_for_project = (  # type: ignore[method-assign]
                lambda context, mode, route=None: RequirementsResult(
                    project=context.name,
                    db={"enabled": True, "success": True, "requested": 5432, "final": 5432},
                    redis={"enabled": False, "success": True},
                    n8n={"enabled": False, "success": True},
                    supabase={"enabled": False, "success": True},
                    health="healthy",
                )
            )

            active_lock = threading.Lock()
            active_calls = 0
            max_concurrency = 0

            def fake_start_project_services(context, *, requirements, run_id, route=None):  # noqa: ANN001
                _ = requirements, run_id, route
                nonlocal active_calls, max_concurrency
                with active_lock:
                    active_calls += 1
                    if active_calls > max_concurrency:
                        max_concurrency = active_calls
                time.sleep(0.2)
                with active_lock:
                    active_calls -= 1
                backend_name = f"{context.name} Backend"
                frontend_name = f"{context.name} Frontend"
                return {
                    backend_name: ServiceRecord(
                        name=backend_name,
                        type="backend",
                        cwd=str(context.root / "backend"),
                        pid=42001,
                        requested_port=context.ports["backend"].requested,
                        actual_port=context.ports["backend"].final,
                        status="running",
                    ),
                    frontend_name: ServiceRecord(
                        name=frontend_name,
                        type="frontend",
                        cwd=str(context.root / "frontend"),
                        pid=42002,
                        requested_port=context.ports["frontend"].requested,
                        actual_port=context.ports["frontend"].final,
                        status="running",
                    ),
                }

            engine._start_project_services = fake_start_project_services  # type: ignore[method-assign]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume", "--trees", "--batch"], env={}))

            self.assertEqual(code, 0)
            execution_event = next(event for event in engine.events if event.get("event") == "resume.restore.execution")
            self.assertEqual(execution_event.get("mode"), "parallel")
            self.assertEqual(execution_event.get("workers"), 2)

    def test_resume_restore_emits_timing_events_and_prints_summary_in_debug_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-4",
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
                    "ENVCTL_DEBUG_UI_MODE": "deep",
                },
            )
            restore_runner = _ResumeRestoreRunner()
            engine.process_runner = restore_runner  # type: ignore[assignment]

            out = StringIO()
            with (
                patch("envctl_engine.startup.resume_orchestrator.spinner_enabled", return_value=False),
                redirect_stdout(out),
            ):
                code = engine.dispatch(parse_route(["--resume", "--batch"], env={}))

            self.assertEqual(code, 0)
            output = out.getvalue()
            self.assertIn("Restore timing summary:", output)
            self.assertIn("Total restore time:", output)
            self.assertIn("Requirements timing for Main:", output)
            self.assertIn("Service timing for Main:", output)
            self.assertTrue(any(event.get("event") == "resume.restore.step" for event in engine.events))
            self.assertTrue(any(event.get("event") == "requirements.timing.component" for event in engine.events))
            self.assertTrue(any(event.get("event") == "requirements.timing.summary" for event in engine.events))
            self.assertTrue(any(event.get("event") == "service.timing.summary" for event in engine.events))
            timing_events = [event for event in engine.events if event.get("event") == "resume.restore.timing"]
            self.assertEqual(len(timing_events), 1)

    def test_resume_restore_suppresses_timing_lines_when_spinner_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-4b",
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
                    "ENVCTL_DEBUG_UI_MODE": "deep",
                },
            )
            restore_runner = _ResumeRestoreRunner()
            engine.process_runner = restore_runner  # type: ignore[assignment]

            @contextmanager
            def fake_spinner(_message: str, *, enabled: bool, start_immediately: bool = True):
                _ = enabled, start_immediately

                class _SpinnerStub:
                    @staticmethod
                    def update(_inner_message: str) -> None:
                        return None

                    @staticmethod
                    def succeed(_inner_message: str) -> None:
                        return None

                    @staticmethod
                    def fail(_inner_message: str) -> None:
                        return None

                yield _SpinnerStub()

            out = StringIO()
            with (
                patch("envctl_engine.startup.resume_orchestrator.spinner_enabled", return_value=True),
                patch("envctl_engine.startup.resume_orchestrator.spinner", side_effect=fake_spinner),
                redirect_stdout(out),
            ):
                code = engine.dispatch(parse_route(["--resume", "--batch"], env={}))

            self.assertEqual(code, 0)
            output = out.getvalue()
            self.assertNotIn("Restore timing summary:", output)
            self.assertNotIn("Requirements timing for Main:", output)
            self.assertNotIn("Service timing for Main:", output)
            self.assertNotIn("Startup summary:", output)
            self.assertTrue(any(event.get("event") == "resume.restore.step" for event in engine.events))
            self.assertTrue(any(event.get("event") == "requirements.timing.summary" for event in engine.events))
            self.assertTrue(any(event.get("event") == "service.timing.summary" for event in engine.events))

    def test_resume_restore_uses_ownership_verification_when_terminating_stale_services(self) -> None:
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

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        pid=12345,
                        requested_port=8000,
                        actual_port=8000,
                        status="stale",
                    )
                },
                requirements={"Main": RequirementsResult(project="Main")},
            )

            seen_verify_flags: list[bool] = []
            seen_aggressive_flags: list[bool] = []

            def fake_terminate(_service, *, aggressive: bool, verify_ownership: bool):  # noqa: ANN001
                seen_aggressive_flags.append(aggressive)
                seen_verify_flags.append(verify_ownership)
                return False

            context = ProjectContext(
                name="Main",
                root=repo,
                ports={
                    "backend": PortPlan("Main", 8000, 8000, 8000, "requested"),
                    "frontend": PortPlan("Main", 9000, 9000, 9000, "requested"),
                    "db": PortPlan("Main", 5432, 5432, 5432, "requested"),
                    "redis": PortPlan("Main", 6379, 6379, 6379, "requested"),
                    "n8n": PortPlan("Main", 5678, 5678, 5678, "requested"),
                },
            )

            engine._terminate_service_record = fake_terminate  # type: ignore[method-assign]
            engine._resume_context_for_project = lambda _state, _project: context  # type: ignore[method-assign]
            engine._reserve_project_ports = lambda _context: None  # type: ignore[method-assign]
            engine._start_requirements_for_project = (  # type: ignore[method-assign]
                lambda _context, mode, route=None: RequirementsResult(project="Main")
            )
            engine._start_project_services = (  # type: ignore[method-assign]
                lambda _context, requirements, run_id, route=None: {}
            )

            engine._resume_restore_missing(state, ["Main Backend"], route=None)

            self.assertEqual(seen_verify_flags, [True])
            self.assertEqual(seen_aggressive_flags, [True])
