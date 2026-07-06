# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.runtime.lifecycle_parity_test_support import *


class LifecycleBlastParityTests(unittest.TestCase):
    def test_blast_all_port_range_includes_frontend_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "BACKEND_PORT_BASE": "8100",
                    "FRONTEND_PORT_BASE": "9100",
                    "PORT_SPACING": "20",
                    "ENVCTL_ADDITIONAL_SERVICES": "voice-runtime,relay",
                    "ENVCTL_SERVICE_VOICE_RUNTIME_START_CMD": "python -m voice_runtime {port}",
                    "ENVCTL_SERVICE_VOICE_RUNTIME_PORT_BASE": "8010",
                    "ENVCTL_SERVICE_RELAY_START_CMD": "python -m relay {port}",
                    "ENVCTL_SERVICE_RELAY_PORT_BASE": "13000",
                }
            )
            engine = PythonEngineRuntime(config, env={})

            ports = engine._blast_all_port_range()

            self.assertIn(8100, ports)
            self.assertIn(9100, ports)
            self.assertIn(9300, ports)
            self.assertIn(54321, ports)
            self.assertIn(54421, ports)
            self.assertIn(13000, ports)
            self.assertIn(13400, ports)

    def test_blast_all_kills_orphan_envctl_processes_but_skips_other_blast_commands(self) -> None:
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
            tracking_runner.ps_stdout = (
                "2222 /usr/bin/python -m envctl_engine.runtime.cli --repo /tmp/repo --plan\n"
                "7777 /usr/bin/node /tmp/repo/frontend/node_modules/.bin/vite\n"
                "3333 /usr/bin/python -m envctl_engine.runtime.cli --repo /tmp/repo blast-all\n"
                "4444 /usr/bin/python -m envctl_engine.runtime.cli --tree\n"
            )
            tracking_runner.ps_tree_stdout = "2222 1\n7777 2222\n3333 1\n4444 1\n"
            engine.process_runner = tracking_runner  # type: ignore[assignment]

            engine._blast_all_kill_orchestrator_processes()

            self.assertIn(("kill", "-9", "2222"), tracking_runner.run_calls)
            self.assertIn(("kill", "-9", "7777"), tracking_runner.run_calls)
            self.assertIn(("kill", "-9", "4444"), tracking_runner.run_calls)
            self.assertNotIn(("kill", "-9", "3333"), tracking_runner.run_calls)

    def test_blast_all_skips_current_process_ancestors(self) -> None:
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
            current_pid = os.getpid()
            parent_pid = os.getppid()
            ancestor_pid = 999_901
            tracking_runner.ps_stdout = (
                f"{ancestor_pid} /usr/bin/python -m envctl_engine.runtime.cli --repo /tmp/repo --plan\n"
                "2222 /usr/bin/python -m envctl_engine.runtime.cli --repo /tmp/repo --plan\n"
            )
            tracking_runner.ps_tree_stdout = (
                f"{current_pid} {parent_pid}\n"
                f"{parent_pid} {ancestor_pid}\n"
                f"{ancestor_pid} 1\n"
                "2222 1\n"
            )
            engine.process_runner = tracking_runner  # type: ignore[assignment]

            engine._blast_all_kill_orchestrator_processes()

            self.assertNotIn(("kill", "-9", str(ancestor_pid)), tracking_runner.run_calls)
            self.assertIn(("kill", "-9", "2222"), tracking_runner.run_calls)

    def test_terminate_service_record_never_terminates_current_process(self) -> None:
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
            engine.process_runner = tracking_runner  # type: ignore[assignment]

            service = ServiceRecord(
                name="Main Backend",
                type="backend",
                cwd=str(repo / "backend"),
                pid=os.getpid(),
                requested_port=8000,
                actual_port=8000,
                status="running",
            )

            terminated = engine._terminate_service_record(
                service,
                aggressive=False,
                verify_ownership=False,
            )

            self.assertFalse(terminated)
            self.assertEqual(tracking_runner.terminated, [])

    def test_terminate_service_record_verify_ownership_skips_when_port_is_unknown(self) -> None:
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
            engine.process_runner = tracking_runner  # type: ignore[assignment]

            service = ServiceRecord(
                name="Main Backend",
                type="backend",
                cwd=str(repo / "backend"),
                pid=12345,
                requested_port=None,
                actual_port=None,
                status="running",
            )

            terminated = engine._terminate_service_record(
                service,
                aggressive=False,
                verify_ownership=True,
            )

            self.assertFalse(terminated)
            self.assertEqual(tracking_runner.terminated, [])

    def test_terminate_service_record_verify_ownership_checks_in_best_effort_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            deny_runner = _OwnershipDenyRunner()
            engine.process_runner = deny_runner  # type: ignore[assignment]

            service = ServiceRecord(
                name="Main Backend",
                type="backend",
                cwd=str(repo / "backend"),
                pid=12345,
                requested_port=8000,
                actual_port=8000,
                status="running",
            )

            terminated = engine._terminate_service_record(
                service,
                aggressive=False,
                verify_ownership=True,
            )

            self.assertFalse(terminated)
            self.assertEqual(deny_runner.terminated, [])

    def test_blast_all_docker_volume_policy_defaults_and_overrides(self) -> None:
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

            engine = PythonEngineRuntime(config, env={"DOCKER_PROJECT_NAME": "envctl"})
            planner = _NoopPlanner()
            engine.port_planner = planner  # type: ignore[assignment]
            runner = _TrackingRunner()
            runner.docker_ps_stdout = "cid-main|postgres:16|envctl-postgres\ncid-tree|redis:7|feature-a-1-redis\n"
            runner.inspect_volumes_by_cid = {
                "cid-main": "mainvol\n",
                "cid-tree": "treevol1\ntreevol2\n",
            }
            engine.process_runner = runner  # type: ignore[assignment]

            out_default = StringIO()
            with redirect_stdout(out_default):
                engine.dispatch(parse_route(["blast-all"], env={}))

            self.assertIn("Worktree Docker volumes: remove (default)", out_default.getvalue())
            self.assertIn("Main Docker volumes: keep", out_default.getvalue())

            self.assertIn(("docker", "rm", "-f", "cid-main"), runner.run_calls)
            self.assertIn(
                (
                    "docker",
                    "inspect",
                    "-f",
                    '{{range .Mounts}}{{if eq .Type "volume"}}{{println .Name}}{{end}}{{end}}',
                    "cid-tree",
                ),
                runner.run_calls,
            )
            self.assertIn(("docker", "rm", "-f", "-v", "cid-tree"), runner.run_calls)
            self.assertIn(("docker", "volume", "rm", "treevol1"), runner.run_calls)
            self.assertIn(("docker", "volume", "rm", "treevol2"), runner.run_calls)
            self.assertNotIn(("docker", "rm", "-f", "-v", "cid-main"), runner.run_calls)
            self.assertNotIn(("docker", "volume", "rm", "mainvol"), runner.run_calls)

            engine2 = PythonEngineRuntime(config, env={"DOCKER_PROJECT_NAME": "envctl"})
            engine2.port_planner = _NoopPlanner()  # type: ignore[assignment]
            runner2 = _TrackingRunner()
            runner2.docker_ps_stdout = runner.docker_ps_stdout
            runner2.inspect_volumes_by_cid = runner.inspect_volumes_by_cid
            engine2.process_runner = runner2  # type: ignore[assignment]

            out_override = StringIO()
            with redirect_stdout(out_override):
                engine2.dispatch(
                    parse_route(
                        ["blast-all", "--blast-keep-worktree-volumes", "--blast-remove-main-volumes"],
                        env={},
                    )
                )

            self.assertIn(
                (
                    "docker",
                    "inspect",
                    "-f",
                    '{{range .Mounts}}{{if eq .Type "volume"}}{{println .Name}}{{end}}{{end}}',
                    "cid-main",
                ),
                runner2.run_calls,
            )
            self.assertIn(("docker", "rm", "-f", "-v", "cid-main"), runner2.run_calls)
            self.assertIn(("docker", "volume", "rm", "mainvol"), runner2.run_calls)
            self.assertNotIn(("docker", "rm", "-f", "-v", "cid-tree"), runner2.run_calls)
            self.assertNotIn(("docker", "volume", "rm", "treevol1"), runner2.run_calls)
            self.assertIn("Worktree Docker volumes: keep (override enabled)", out_override.getvalue())
            self.assertIn("Main Docker volumes: remove", out_override.getvalue())

    def test_blast_all_purges_shell_legacy_pointers_and_lock_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            run_dir = runtime / "python-engine"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "utils").mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            # Shell-style state pointers live at runtime root, not python-engine runtime dir.
            (runtime / ".last_state").write_text("/tmp/does-not-matter", encoding="utf-8")
            (runtime / ".last_state.main").write_text("/tmp/does-not-matter", encoding="utf-8")
            (runtime / ".last_state.trees.sample").write_text("/tmp/does-not-matter", encoding="utf-8")

            # Legacy reservation dirs from older shell paths.
            (repo / ".run-sh-port-reservations").mkdir(parents=True, exist_ok=True)
            (repo / "utils" / ".run-sh-port-reservations").mkdir(parents=True, exist_ok=True)

            # Stray shell state pointers historically left around in repo subdirs.
            nested_state = repo / "tmp" / "nested" / ".last_state"
            nested_state.parent.mkdir(parents=True, exist_ok=True)
            nested_state.write_text("/tmp/legacy-state", encoding="utf-8")

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={"ENVCTL_BLAST_ALL_ECOSYSTEM": "false"})
            engine.port_planner = _NoopPlanner()  # type: ignore[assignment]
            engine.process_runner = _TrackingRunner()  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["blast-all"], env={}))

            self.assertEqual(code, 0)
            self.assertFalse((runtime / ".last_state").exists())
            self.assertFalse((runtime / ".last_state.main").exists())
            self.assertFalse((runtime / ".last_state.trees.sample").exists())
            self.assertFalse((repo / ".run-sh-port-reservations").exists())
            self.assertFalse((repo / "utils" / ".run-sh-port-reservations").exists())
            self.assertFalse(nested_state.exists())
            self.assertIn("Purging leftover state pointers and locks", out.getvalue())

    def test_blast_all_releases_all_scoped_port_locks(self) -> None:
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
            engine = PythonEngineRuntime(config, env={"ENVCTL_BLAST_ALL_ECOSYSTEM": "false"})
            planner = _TrackingPlanner()
            engine.port_planner = planner  # type: ignore[assignment]
            engine.process_runner = _TrackingRunner()  # type: ignore[assignment]

            code = engine.dispatch(parse_route(["blast-all"], env={}))

            self.assertEqual(code, 0)
            self.assertTrue(planner.released_all)
            self.assertFalse(planner.released_session)

    def test_blast_all_uses_batched_lsof_port_sweep(self) -> None:
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
            engine = PythonEngineRuntime(config, env={"DOCKER_PROJECT_NAME": "envctl"})
            engine.port_planner = _NoopPlanner()  # type: ignore[assignment]
            runner = _TrackingRunner()
            engine.process_runner = runner  # type: ignore[assignment]

            engine.dispatch(parse_route(["blast-all"], env={}))

            self.assertIn(("lsof", "-nP", "-iTCP", "-sTCP:LISTEN"), runner.run_calls)
            self.assertFalse(
                any(
                    len(call) >= 3 and call[0] == "lsof" and call[1] == "-t" and str(call[2]).startswith("-iTCP:")
                    for call in runner.run_calls
                ),
                msg=runner.run_calls,
            )

    def test_blast_all_kills_child_processes_of_orphan_listener_pids(self) -> None:
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
            runner = _TrackingRunner()
            runner.ps_stdout = (
                "5000 /usr/bin/python -m uvicorn app.main:app\n"
                "5001 /usr/bin/node /tmp/frontend/node_modules/vite/bin/vite.js\n"
            )
            runner.ps_tree_stdout = "5000 1\n5001 5000\n"
            engine.process_runner = runner  # type: ignore[assignment]

            engine._blast_all_print_and_kill_listener_maps(
                kill_pid_ports={5000: {8060}},
                docker_pid_ports={},
            )

            self.assertIn(("kill", "-9", "5000"), runner.run_calls)
            self.assertIn(("kill", "-9", "5001"), runner.run_calls)

    def test_blast_all_is_idempotent_when_no_state_exists(self) -> None:
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
                code = engine.dispatch(parse_route(["blast-all"], env={}))
            self.assertEqual(code, 0)
            self.assertIn("Stopped runtime state.", out.getvalue())
