from __future__ import annotations

import json
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.test_output.parser_base import strip_ansi

from tests.python.runtime.engine_runtime_real_startup_test_support import (
    _EngineRuntimeRealStartupTestCase,
    _FakeProcessRunner,
)


class EngineRuntimeMigrationStartupTests(_EngineRuntimeRealStartupTestCase):
    def test_frontend_bootstrap_installs_dependencies_when_node_modules_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            frontend_dir = repo / "trees" / "feature-a" / "1" / "frontend"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            frontend_dir.mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            (frontend_dir / "package.json").write_text(
                json.dumps({"name": "feature-a-frontend", "scripts": {"dev": "vite"}}),
                encoding="utf-8",
            )
            (frontend_dir / "package-lock.json").write_text("{}", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine._command_exists = (  # type: ignore[attr-defined]
                lambda executable: "/" in executable or executable in {"npm", "python3.12", "python3", "python", "sh"}
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            npm_calls = [cmd for cmd, _cwd in fake_runner.run_calls if cmd and cmd[0] == "npm"]
            self.assertTrue(any(cmd[:2] == ("npm", "ci") for cmd in npm_calls), msg=str(npm_calls))

    def test_frontend_bootstrap_skips_install_when_vite_binary_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            frontend_dir = repo / "trees" / "feature-a" / "1" / "frontend"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            vite_bin = frontend_dir / "node_modules" / ".bin" / "vite"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            frontend_dir.mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            vite_bin.parent.mkdir(parents=True, exist_ok=True)
            vite_bin.write_text("#!/bin/sh\n", encoding="utf-8")
            (frontend_dir / "package.json").write_text(
                json.dumps({"name": "feature-a-frontend", "scripts": {"dev": "vite"}}),
                encoding="utf-8",
            )
            (frontend_dir / "package-lock.json").write_text("{}", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine._command_exists = (  # type: ignore[attr-defined]
                lambda executable: "/" in executable or executable in {"npm", "python3.12", "python3", "python", "sh"}
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            npm_calls = [cmd for cmd, _cwd in fake_runner.run_calls if cmd and cmd[0] == "npm"]
            self.assertEqual(npm_calls, [])

    def test_backend_migrations_are_skipped_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            (backend_dir / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            output = out.getvalue()
            self.assertNotIn("Warning: backend migration step failed", output)
            self.assertFalse(any(call[0][-3:] == ("alembic", "upgrade", "head") for call in fake_runner.run_calls))

    def test_backend_alembic_missing_revision_warning_includes_actionable_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            (backend_dir / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.env["ENVCTL_BACKEND_MIGRATIONS_ON_STARTUP"] = "true"
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.fail_alembic = True
            fake_runner.alembic_error_text = (
                "ERROR [alembic.util.messaging] Can't locate revision identified by 'e6f7a8b9c0d1'"
            )
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            engine.env["ENVCTL_UI_SPINNER_MODE"] = "off"
            engine.env["ENVCTL_UI_HYPERLINK_MODE"] = "on"
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            output = out.getvalue()
            self.assertIn("Warning: backend migration step failed", output)
            self.assertIn("\x1b]8;;file://", output)
            visible = strip_ansi(output)
            self.assertIn("backend log:", visible)
            self.assertIn("hint: alembic revision e6f7a8b9c0d1 is missing", visible)

    def test_backend_alembic_failure_is_hard_when_bootstrap_strict_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            (backend_dir / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "ENVCTL_BACKEND_BOOTSTRAP_STRICT": "true",
                    "ENVCTL_BACKEND_MIGRATIONS_ON_STARTUP": "true",
                    "BACKEND_ENV_FILE_OVERRIDE": str(backend_dir / ".env"),
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.fail_alembic = True
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("backend bootstrap failed", out.getvalue())

    def test_backend_alembic_async_driver_mismatch_retries_with_asyncpg_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("sqlalchemy==2.0.31\nalembic==1.13.2\n", encoding="utf-8")
            (backend_dir / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
            (backend_dir / ".env").write_text(
                "DATABASE_URL=postgresql+psycopg2://svc_user:svc_pass@localhost:5432/svc_db\n",
                encoding="utf-8",
            )

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "ENVCTL_BACKEND_BOOTSTRAP_STRICT": "true",
                    "ENVCTL_BACKEND_MIGRATIONS_ON_STARTUP": "true",
                    "BACKEND_ENV_FILE_OVERRIDE": str(backend_dir / ".env"),
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.fail_alembic_async_mismatch_once = True
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            alembic_envs = [
                env
                for (cmd, _cwd), env in zip(fake_runner.run_calls, fake_runner.run_envs)
                if tuple(cmd[-3:]) == ("alembic", "upgrade", "head") and isinstance(env, dict)
            ]
            self.assertGreaterEqual(len(alembic_envs), 2)
            self.assertTrue(any("psycopg2" in str(env.get("DATABASE_URL", "")) for env in alembic_envs))
            self.assertTrue(any("postgresql+asyncpg://" in str(env.get("DATABASE_URL", "")) for env in alembic_envs))

    def test_startup_backend_migrations_use_distinct_env_contracts_for_multiple_worktrees(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            first_backend = repo / "trees" / "feature-a" / "1" / "backend"
            second_backend = repo / "trees" / "feature-b" / "1" / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            for backend_dir, marker in ((first_backend, "a"), (second_backend, "b")):
                backend_dir.mkdir(parents=True, exist_ok=True)
                (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
                (backend_dir / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
                (backend_dir / ".env").write_text(f"PROJECT_MARKER={marker}\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_BACKEND_MIGRATIONS_ON_STARTUP": "true"},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(
                ["--trees", "--project", "feature-a-1", "--project", "feature-b-1", "--isolated-deps", "--batch"],
                env={},
            )

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            alembic_envs = [
                env
                for (cmd, _cwd), env in zip(fake_runner.run_calls, fake_runner.run_envs)
                if tuple(cmd[-3:]) == ("alembic", "upgrade", "head") and isinstance(env, dict)
            ]
            self.assertEqual(len(alembic_envs), 2)
            first_env = next(env for env in alembic_envs if env.get("PROJECT_MARKER") == "a")
            second_env = next(env for env in alembic_envs if env.get("PROJECT_MARKER") == "b")
            self.assertEqual(first_env.get("APP_ENV_FILE"), str((first_backend / ".env").resolve()))
            self.assertEqual(second_env.get("APP_ENV_FILE"), str((second_backend / ".env").resolve()))
            self.assertNotEqual(first_env.get("DATABASE_URL"), second_env.get("DATABASE_URL"))

    def test_startup_migration_warnings_include_backend_env_source_without_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            env_file = backend_dir / ".env"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            (backend_dir / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
            env_file.write_text(
                "DATABASE_URL=postgresql+psycopg2://svc_user:super-secret@localhost:5432/svc_db\n",
                encoding="utf-8",
            )

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_BACKEND_MIGRATIONS_ON_STARTUP": "true"},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.fail_alembic = True
            fake_runner.alembic_error_text = "alembic failure"
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--isolated-deps", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("backend env source: default", rendered)
            self.assertIn(str(env_file.resolve()), rendered)
            self.assertNotIn("super-secret", rendered)

