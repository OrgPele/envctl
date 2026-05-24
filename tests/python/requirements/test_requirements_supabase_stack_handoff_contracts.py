# ruff: noqa: F403,F405
from __future__ import annotations

import unittest

from tests.python.requirements.requirements_adapter_contract_support import *


class SupabaseStackHandoffContractTests(unittest.TestCase):
    def test_supabase_compose_handoff_does_not_treat_created_service_as_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            compose_path = supabase_dir / "docker-compose.yml"
            compose_path.write_text("services:\n  supabase-auth: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_ps_q_stdout["supabase-auth"] = "auth-container-id\n"
            runner.status["auth-container-id"] = "created"

            ready = _compose_services_started(
                process_runner=runner,
                compose_root=supabase_dir,
                compose_project_name="envctl-supabase-test",
                compose_path=compose_path,
                env={},
                service_names=["supabase-auth"],
            )

            self.assertFalse(ready)

    def test_supabase_compose_timeout_override_does_not_exceed_overall_startup_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [True]
            runner.wait_for_port_sequences[54321] = [True]
            runner.health_returncode_sequence = [0]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={
                    "ENVCTL_SUPABASE_STARTUP_TIMEOUT_SECONDS": "1",
                    "ENVCTL_SUPABASE_COMPOSE_UP_TIMEOUT_SECONDS": "45",
                },
            )

            self.assertTrue(result.success)
            graph_event = next(item for item in result.stage_events or [] if item.get("stage") == "supabase.graph.up")
            self.assertEqual(graph_event.get("timeout_s"), 1.0)
            self.assertEqual(graph_event.get("startup_budget_s"), 1.0)

    def test_supabase_graph_handoff_does_not_finish_when_only_db_is_ready(self) -> None:
        runner = _FakeRunner()
        runner.wait_for_port_result = True
        runner.compose_up_process = lambda *args, **kwargs: _FakeComposeProcess(returncode=None)  # type: ignore[method-assign]
        runner.status["supabase-db-container-id"] = "running"
        runner.health_status["supabase-db-container-id"] = "healthy"
        runner.status["supabase-auth-container-id"] = "created"
        runner.status["supabase-kong-container-id"] = "created"
        runner.port_mappings[("supabase-db-container-id", "5432")] = "0.0.0.0:5432\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            compose_path = root / "docker-compose.yml"
            compose_path.write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (root / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")

            result = _compose_run(
                process_runner=runner,
                compose_root=root,
                compose_project_name="envctl-supabase-test",
                compose_path=compose_path,
                env={"ENVCTL_SUPABASE_COMPOSE_UP_TIMEOUT_SECONDS": "5"},
                args=["up", "-d", "supabase-db", "supabase-auth", "supabase-kong"],
            )

        self.assertIsNotNone(result)
        self.assertIn("Command timed out after 5.0s", result or "")
        self.assertIn("supabase-auth", result or "")

    def test_supabase_graph_startup_does_not_fail_when_auth_kong_progress_past_old_compose_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_ps_q_stdout["supabase-db"] = "db-container-id\n"
            runner.compose_ps_q_stdout["supabase-auth"] = "auth-container-id\n"
            runner.compose_ps_q_stdout["supabase-kong"] = "kong-container-id\n"
            runner.status["db-container-id"] = "running"
            runner.status["auth-container-id"] = "running"
            runner.status["kong-container-id"] = "running"
            runner.health_status["kong-container-id"] = "healthy"
            runner.wait_for_port_overrides[5432] = True
            runner.wait_for_port_overrides[54321] = True
            runner.health_returncode_sequence = [0]

            def _hung_graph(cmd, *, cwd=None, env=None):  # noqa: ANN001
                _ = cwd, env
                runner.commands.append(list(cmd))
                return _FakeComposeProcess(returncode=None)

            runner.compose_up_process = _hung_graph  # type: ignore[method-assign]

            with mock.patch("envctl_engine.requirements.supabase.os.killpg", side_effect=OSError()):
                result = start_supabase_stack(
                    process_runner=runner,
                    project_root=root,
                    project_name="feature-a-1",
                    db_port=5432,
                    public_port=54321,
                )

            self.assertTrue(result.success)
            self.assertTrue(
                any(
                    cmd[:2] == ["docker", "compose"]
                    and cmd[-5:] == ["up", "-d", "supabase-db", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )
            self.assertEqual(runner.health_urls, ["http://127.0.0.1:54321/auth/v1/health"])

    def test_supabase_graph_startup_failure_reports_phase_timeout_port_and_service_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_returncode["up -d supabase-db supabase-auth supabase-kong"] = 1
            runner.compose_stderr["up -d supabase-db supabase-auth supabase-kong"] = (
                "Container supabase-kong-1 Starting"
            )
            runner.compose_ps_q_stdout["supabase-db"] = "db-container-id\n"
            runner.compose_ps_q_stdout["supabase-auth"] = "auth-container-id\n"
            runner.compose_ps_q_stdout["supabase-kong"] = "kong-container-id\n"
            runner.status["db-container-id"] = "running"
            runner.status["auth-container-id"] = "running"
            runner.status["kong-container-id"] = "created"

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_COMPOSE_UP_TIMEOUT_SECONDS": "45"},
            )

            self.assertFalse(result.success)
            self.assertIn("phase=compose_graph", result.error or "")
            self.assertIn("compose_timeout_s=45", result.error or "")
            self.assertIn("public_port=54321", result.error or "")
            self.assertIn("probe_url=http://127.0.0.1:54321/auth/v1/health", result.error or "")
            self.assertIn("supabase-kong", result.error or "")
            self.assertIn("status=created", result.error or "")
            self.assertIn("last_error=Container supabase-kong-1 Starting", result.error or "")
            self.assertIn("startup_budget_s=120", result.error or "")
            self.assertIn("elapsed_ms=", result.error or "")

    def test_supabase_handoffs_when_compose_cli_hangs_after_db_is_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_services_stdout = "supabase-db\n"
            runner.compose_ps_q_stdout["supabase-db"] = ["", "abc123\n", "abc123\n"]
            runner.wait_for_port_sequences[5432] = [False, True]

            def _hung_compose(cmd, *, cwd=None, env=None):  # noqa: ANN001
                _ = cwd, env
                runner.commands.append(list(cmd))
                return _FakeComposeProcess(returncode=None)

            runner.compose_up_process = _hung_compose  # type: ignore[method-assign]

            with mock.patch("envctl_engine.requirements.supabase.os.killpg", side_effect=OSError()):
                result = start_supabase_stack(
                    process_runner=runner,
                    project_root=root,
                    project_name="feature-a-1",
                    db_port=5432,
                )

            self.assertTrue(result.success)
            db_ups = [
                cmd for cmd in runner.commands if cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["-d", "supabase-db"]
            ]
            self.assertEqual(len(db_ups), 1)
            self.assertTrue(any(cmd[-4:] == ["ps", "--format", "json", "supabase-db"] for cmd in runner.commands))

    def test_supabase_recovers_when_initial_up_times_out_but_service_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_services_stdout = "supabase-db\n"
            runner.compose_ps_q_stdout["supabase-db"] = ["abc123\n", "abc123\n"]
            runner.wait_for_port_result = True

            def _hung_compose(cmd, *, cwd=None, env=None):  # noqa: ANN001
                _ = cwd, env
                runner.commands.append(list(cmd))
                return _FakeComposeProcess(returncode=None)

            runner.compose_up_process = _hung_compose  # type: ignore[method-assign]

            with mock.patch("envctl_engine.requirements.supabase.os.killpg", side_effect=OSError()):
                result = start_supabase_stack(
                    process_runner=runner,
                    project_root=root,
                    project_name="feature-a-1",
                    db_port=5432,
                )

            self.assertTrue(result.success)

    def test_supabase_timeout_recovery_skips_repeated_db_up_when_service_already_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_services_stdout = "supabase-db\n"
            runner.compose_ps_q_stdout["supabase-db"] = ["", "abc123\n", "abc123\n"]
            runner.wait_for_port_sequences[5432] = [False, True]

            def _hung_compose(cmd, *, cwd=None, env=None):  # noqa: ANN001
                _ = cwd, env
                runner.commands.append(list(cmd))
                return _FakeComposeProcess(returncode=None)

            runner.compose_up_process = _hung_compose  # type: ignore[method-assign]

            with mock.patch("envctl_engine.requirements.supabase.os.killpg", side_effect=OSError()):
                result = start_supabase_stack(
                    process_runner=runner,
                    project_root=root,
                    project_name="feature-a-1",
                    db_port=5432,
                )

            self.assertTrue(result.success)
            db_ups = [
                cmd for cmd in runner.commands if cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["-d", "supabase-db"]
            ]
            self.assertEqual(len(db_ups), 1)


if __name__ == "__main__":
    unittest.main()
