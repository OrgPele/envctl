# ruff: noqa: F403,F405
from __future__ import annotations

import unittest

from envctl_engine.requirements.supabase_lifecycle import compose, compose_handoff
from tests.python.requirements.requirements_adapter_contract_support import *


class SupabaseComposeContractTests(unittest.TestCase):
    def test_supabase_compose_reexports_handoff_owner_functions(self) -> None:
        self.assertIs(compose._compose_up_handoff, compose_handoff.compose_up_handoff)
        self.assertIs(compose._compose_handoff_ready, compose_handoff.compose_handoff_ready)
        self.assertIs(compose._compose_services_started, compose_handoff.compose_services_started)
        self.assertIs(compose._compose_db_port, compose_handoff.compose_db_port)
        self.assertIs(compose._compose_public_port, compose_handoff.compose_public_port)

    def test_supabase_compose_up_default_timeout_is_120_seconds(self) -> None:
        runner = _FakeRunner()
        captured: dict[str, float] = {}

        def _capture_handoff(**kwargs):  # noqa: ANN001
            captured["timeout_seconds"] = kwargs["timeout_seconds"]
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            compose_path = root / "docker-compose.yml"
            compose_path.write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (root / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")

            with mock.patch(
                "envctl_engine.requirements.supabase_lifecycle.compose._compose_up_handoff",
                side_effect=_capture_handoff,
            ):
                result = _compose_run(
                    process_runner=runner,
                    compose_root=root,
                    compose_project_name="envctl-supabase-test",
                    compose_path=compose_path,
                    env={},
                    args=["up", "-d", "supabase-db"],
                )

        self.assertIsNone(result)
        self.assertEqual(captured["timeout_seconds"], 120.0)

    def test_supabase_compose_run_reports_lock_timeout(self) -> None:
        runner = _FakeRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            compose_path = root / "docker-compose.yml"
            compose_path.write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            lock_context = mock.MagicMock()
            lock_context.__enter__.side_effect = TimeoutError("busy")
            with mock.patch(
                "envctl_engine.requirements.supabase_lifecycle.compose.file_lock", return_value=lock_context
            ):
                result = _compose_run(
                    process_runner=runner,
                    compose_root=root,
                    compose_project_name="envctl-supabase-test",
                    compose_path=compose_path,
                    env={"ENVCTL_SUPABASE_COMPOSE_LOCK_TIMEOUT_SECONDS": "1"},
                    args=["up", "-d", "supabase-db"],
                )

        self.assertIsNotNone(result)
        self.assertIn("timed out acquiring Supabase compose lock after 1.0s", result or "")
        self.assertIn("busy", result or "")

    def test_supabase_compose_up_reports_unpublished_probe_port_after_timeout(self) -> None:
        runner = _FakeRunner()
        runner.wait_for_port_result = False
        runner.compose_up_process = lambda *args, **kwargs: _FakeComposeProcess(returncode=None)  # type: ignore[method-assign]
        runner.status["supabase-db-container-id"] = "running"
        runner.health_status["supabase-db-container-id"] = "healthy"
        runner.status["supabase-auth-container-id"] = "created"
        runner.status["supabase-kong-container-id"] = "created"
        runner.port_mappings[("supabase-db-container-id", "5432")] = "0.0.0.0:5432\n"
        runner.port_mapping_errors[("supabase-db-container-id", "5432")] = (
            "no public port '5432' published for supabase-db-container-id"
        )

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
        self.assertIn("stalled before publishing Supabase DB host port 5432", result or "")
        self.assertIn("supabase-db", result or "")

    def test_supabase_auth_health_probe_retries_transient_http_failure(self) -> None:
        runner = _FlakyHealthRunner()

        ready, error = _probe_supabase_auth_health(
            process_runner=runner,
            public_port=54321,
            health_url="http://localhost:54321/auth/v1/health",
            env={"ENVCTL_SUPABASE_AUTH_PROBE_TIMEOUT_SECONDS": "1"},
        )

        self.assertTrue(ready)
        self.assertIsNone(error)
        self.assertEqual(runner.run_calls, 2)
        self.assertTrue(runner.sleep_calls)

    def test_supabase_auth_health_probe_does_not_surface_partial_urllib_traceback(self) -> None:
        class _PartialTracebackRunner:
            def wait_for_port(self, port: int, *, host: str = "127.0.0.1", timeout: float = 30.0) -> bool:
                _ = port, host, timeout
                return True

            def run(self, cmd, *, cwd=None, env=None, timeout=None, process_started_callback=None):  # noqa: ANN001
                _ = cwd, env, timeout, process_started_callback
                return subprocess.CompletedProcess(
                    list(cmd),
                    1,
                    "",
                    "Traceback (most recent call last):\n"
                    '  File "/usr/lib/python3.12/urllib/request.py", line 492, in _call_chain\n',
                )

            def sleep(self, seconds: float) -> None:
                _ = seconds

        ready, error = _probe_supabase_auth_health(
            process_runner=_PartialTracebackRunner(),
            public_port=54321,
            health_url="http://127.0.0.1:54321/auth/v1/health",
            env={"ENVCTL_SUPABASE_AUTH_PROBE_TIMEOUT_SECONDS": "0.5"},
        )

        self.assertFalse(ready)
        self.assertEqual(error, "HTTP health probe failed")
        self.assertNotIn("urllib/request.py", error or "")
        self.assertNotIn('File "', error or "")

    def test_supabase_auth_probe_error_condensing_ignores_traceback_frame_line_numbers(self) -> None:
        raw_error = (
            "ConnectionRefusedError: [Errno 111] Connection refused\n"
            '  File "/usr/lib/python3.12/urllib/request.py", line 492, in _call_chain\n'
        )

        self.assertEqual(
            _condense_probe_error(raw_error),
            "ConnectionRefusedError: [Errno 111] Connection refused",
        )

    def test_supabase_auth_recovery_defaults_allow_multiple_probe_windows(self) -> None:
        self.assertEqual(_auth_restart_probe_attempts({}), 2)
        self.assertEqual(_auth_recreate_probe_attempts({}), 3)


if __name__ == "__main__":
    unittest.main()
