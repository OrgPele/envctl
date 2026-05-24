# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.runtime.lifecycle_parity_test_support import *


class LifecycleStopHealthParityTests(unittest.TestCase):
    def test_stop_does_not_fallback_to_cross_mode_state(self) -> None:
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
            terminate_calls: list[str] = []
            trees_state = RunState(
                run_id="run-trees",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo / "trees" / "feature-a" / "1" / "backend"),
                        pid=12345,
                        requested_port=8020,
                        actual_port=8020,
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
            engine._terminate_services_from_state = (  # type: ignore[method-assign]
                lambda state, selected_services, aggressive, verify_ownership: terminate_calls.append(state.mode)
            )

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["stop", "--main", "--yes"], env={}))

            self.assertEqual(code, 0)
            self.assertIn("No active runtime state found.", out.getvalue())
            self.assertEqual(seen_calls, [("main", True)])
            self.assertEqual(terminate_calls, [])

    def test_stop_without_explicit_mode_falls_back_to_latest_state_mode(self) -> None:
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
            trees_state = RunState(run_id="run-trees", mode="trees")

            def fake_load(*, mode=None, strict_mode_match=False):  # noqa: ANN001
                seen_calls.append((mode, strict_mode_match))
                if mode == "main" and not strict_mode_match:
                    return trees_state
                return None

            engine._try_load_existing_state = fake_load  # type: ignore[method-assign]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["stop", "--yes"], env={}))

            self.assertEqual(code, 0)
            self.assertIn("Stopped runtime state.", out.getvalue())
            self.assertGreaterEqual(len(seen_calls), 1)
            self.assertEqual(seen_calls[0], ("main", False))

    def test_stop_and_blast_emit_cleanup_events_and_clear_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            runs_dir = run_dir / "runs" / "run-1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            runs_dir.mkdir(parents=True, exist_ok=True)

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
            dump_state(state, str(runs_dir / "run_state.json"))
            (run_dir / "runtime_map.json").write_text("{}", encoding="utf-8")
            (run_dir / "ports_manifest.json").write_text("{}", encoding="utf-8")
            (run_dir / "runtime_readiness_report.json").write_text("{}", encoding="utf-8")
            (run_dir / ".last_state.main").write_text(str(runs_dir / "run_state.json"), encoding="utf-8")

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})
            planner = _NoopPlanner()
            engine.port_planner = planner  # type: ignore[assignment]

            stop_code = engine.dispatch(parse_route(["stop"], env={}))
            self.assertEqual(stop_code, 0)
            self.assertTrue(planner.released)
            self.assertFalse((run_dir / "run_state.json").exists())
            self.assertFalse((run_dir / "runtime_readiness_report.json").exists())
            self.assertTrue(any(event["event"] == "cleanup.stop" for event in engine.events))

            (run_dir / "runs" / "run-1").mkdir(parents=True, exist_ok=True)
            tracking_runner = _TrackingRunner()
            engine.process_runner = tracking_runner  # type: ignore[assignment]
            out = StringIO()
            with redirect_stdout(out):
                blast_code = engine.dispatch(parse_route(["blast-all"], env={}))
            self.assertEqual(blast_code, 0)
            self.assertFalse((run_dir / "runs").exists())
            self.assertTrue(any(event["event"] == "cleanup.blast" for event in engine.events))
            self.assertTrue(
                any(call[:3] == ("pkill", "-9", "-f") for call in tracking_runner.run_calls),
                msg=tracking_runner.run_calls,
            )
            self.assertTrue(
                any(
                    call[:4] == ("pkill", "-9", "-f", "envctl_engine\\.cli.*--plan")
                    for call in tracking_runner.run_calls
                ),
                msg=tracking_runner.run_calls,
            )
            self.assertTrue(
                any(
                    call[:4] == ("pkill", "-9", "-f", "lib/engine/main\\.sh.*--plan")
                    for call in tracking_runner.run_calls
                ),
                msg=tracking_runner.run_calls,
            )
            self.assertTrue(
                any(call[:4] == ("docker", "ps", "-a", "--format") for call in tracking_runner.run_calls),
                msg=tracking_runner.run_calls,
            )
            self.assertTrue(
                any(
                    call[:4] == ("docker", "rm", "-f", "cid1") or call[:5] == ("docker", "rm", "-f", "-v", "cid1")
                    for call in tracking_runner.run_calls
                ),
                msg=tracking_runner.run_calls,
            )
            self.assertIn("BLAST-ALL", out.getvalue())

    def test_stop_all_remove_volumes_runs_docker_volume_cleanup(self) -> None:
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
            tracking_runner = _TrackingRunner()
            tracking_runner.docker_ps_stdout = "cid1|postgres:16|repo-postgres\n"
            tracking_runner.inspect_volumes_by_cid = {"cid1": "repo_postgres_data\n"}
            engine.process_runner = tracking_runner  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["stop-all", "--stop-all-remove-volumes"], env={}))

            self.assertEqual(code, 0)
            self.assertTrue(
                any(call[:4] == ("docker", "ps", "-a", "--format") for call in tracking_runner.run_calls),
                msg=tracking_runner.run_calls,
            )
            self.assertTrue(
                any(call[:5] == ("docker", "rm", "-f", "-v", "cid1") for call in tracking_runner.run_calls),
                msg=tracking_runner.run_calls,
            )
            self.assertTrue(
                any(call[:4] == ("docker", "volume", "rm", "repo_postgres_data") for call in tracking_runner.run_calls),
                msg=tracking_runner.run_calls,
            )
            self.assertIn("Stopped runtime state.", out.getvalue())

    def test_stop_with_project_selector_only_stops_selected_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo / "trees" / "feature-a" / "1" / "backend"),
                        pid=12001,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "feature-b-1 Backend": ServiceRecord(
                        name="feature-b-1 Backend",
                        type="backend",
                        cwd=str(repo / "trees" / "feature-b" / "1" / "backend"),
                        pid=13001,
                        requested_port=8020,
                        actual_port=8020,
                        status="running",
                    ),
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
            planner = _NoopPlanner()
            engine.port_planner = planner  # type: ignore[assignment]
            tracking_runner = _TrackingRunner()
            engine.process_runner = tracking_runner  # type: ignore[assignment]

            code = engine.dispatch(parse_route(["stop", "--tree", "--project", "feature-a-1"], env={}))

            self.assertEqual(code, 0)
            self.assertIn(12001, tracking_runner.terminated)
            self.assertNotIn(13001, tracking_runner.terminated)
            persisted = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
            self.assertIn("feature-b-1 Backend", persisted["services"])
            self.assertNotIn("feature-a-1 Backend", persisted["services"])

    def test_stop_returns_zero_when_no_state_exists(self) -> None:
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
            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["stop"], env={}))
            self.assertEqual(code, 0)
            self.assertIn("No active runtime state found.", out.getvalue())

    def test_health_and_errors_report_failed_run_without_services(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-failed",
                mode="main",
                metadata={"failed": True},
            )
            dump_state(state, str(run_dir / "run_state.json"))
            (run_dir / "error_report.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-failed",
                        "errors": ["Startup failed: Requirements unavailable for Main: postgres bind failure"],
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})

            health_out = StringIO()
            with redirect_stdout(health_out):
                health_code = engine.dispatch(parse_route(["health", "--main"], env={}))

            errors_out = StringIO()
            with redirect_stdout(errors_out):
                errors_code = engine.dispatch(parse_route(["errors", "--main"], env={}))

            self.assertEqual(health_code, 1)
            self.assertEqual(errors_code, 1)
            self.assertIn("Startup failed: Requirements unavailable for Main", health_out.getvalue())
            self.assertIn("Startup failed: Requirements unavailable for Main", errors_out.getvalue())

    def test_health_and_errors_support_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-healthy",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend", type="backend", cwd="/tmp/main", status="running", actual_port=8000
                    ),
                },
                requirements={
                    "Main": RequirementsResult(
                        project="Main",
                        redis={"enabled": True, "runtime_status": "healthy", "final": 6380, "success": True},
                        failures=[],
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

            health_out = StringIO()
            with (
                patch.object(engine, "_reconcile_state_truth", return_value=[]),
                patch.object(engine, "_requirement_truth_issues", return_value=[]),
                patch.object(engine, "_recent_failure_messages", return_value=[]),
                redirect_stdout(health_out),
            ):
                health_code = engine.dispatch(parse_route(["health", "--main", "--json"], env={}))

            errors_out = StringIO()
            with (
                patch.object(engine, "_reconcile_state_truth", return_value=[]),
                patch.object(engine, "_requirement_truth_issues", return_value=[]),
                patch.object(engine, "_recent_failure_messages", return_value=[]),
                redirect_stdout(errors_out),
            ):
                errors_code = engine.dispatch(parse_route(["errors", "--main", "--json"], env={}))

            health_payload = json.loads(health_out.getvalue())
            errors_payload = json.loads(errors_out.getvalue())
            self.assertEqual(health_code, 0)
            self.assertEqual(errors_code, 0)
            self.assertTrue(health_payload["healthy"])
            self.assertEqual(health_payload["dependencies"][0]["component"], "redis")
            self.assertTrue(errors_payload["ok"])

    def test_stop_clears_failed_run_state_when_no_services_are_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-failed",
                mode="main",
                metadata={"failed": True},
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
                code = engine.dispatch(parse_route(["stop", "--main", "--yes"], env={}))

            self.assertEqual(code, 0)
            self.assertIn("Stopped runtime state.", out.getvalue())
            self.assertFalse((run_dir / "run_state.json").exists())

    def test_stop_all_is_idempotent_when_no_state_exists(self) -> None:
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
            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["stop-all"], env={}))
            self.assertEqual(code, 0)
            self.assertIn("Stopped runtime state.", out.getvalue())
