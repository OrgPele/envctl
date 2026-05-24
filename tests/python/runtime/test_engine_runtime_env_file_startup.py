from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime

from tests.python.runtime.engine_runtime_real_startup_test_support import (
    _EngineRuntimeRealStartupTestCase,
    _FakeProcessRunner,
)


class EngineRuntimeEnvFileStartupTests(_EngineRuntimeRealStartupTestCase):
    def test_backend_env_file_is_loaded_and_app_env_file_is_exported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            (backend_dir / ".env").write_text(
                "CUSTOM_BACKEND_FLAG=enabled\nREDIS_URL=redis://legacy:6379/0\n",
                encoding="utf-8",
            )

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})
            self._planned_ports(engine, "feature-a-1")["db"].final

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            bootstrap_envs = [env for env in fake_runner.run_envs if isinstance(env, dict)]
            self.assertTrue(
                any(
                    isinstance(env.get("APP_ENV_FILE"), str)
                    and Path(str(env.get("APP_ENV_FILE"))).resolve() == (backend_dir / ".env").resolve()
                    for env in bootstrap_envs
                )
            )
            self.assertTrue(any(env.get("CUSTOM_BACKEND_FLAG") == "enabled" for env in bootstrap_envs))

    def test_backend_env_override_file_preserves_database_url_and_sets_app_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            override_file = repo / "config" / "backend.override.env"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            override_file.parent.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            override_file.write_text(
                "DATABASE_URL=postgresql+psycopg2://override_user:override_pass@db.internal/override_db\n"
                "CUSTOM_BACKEND_FLAG=override-enabled\n",
                encoding="utf-8",
            )

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"BACKEND_ENV_FILE_OVERRIDE": str(override_file)},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})
            self._planned_ports(engine, "feature-a-1")["db"].final

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            bootstrap_envs = [env for env in fake_runner.run_envs if isinstance(env, dict)]
            self.assertTrue(
                any(
                    env.get("DATABASE_URL")
                    == "postgresql+psycopg2://override_user:override_pass@db.internal/override_db"
                    for env in bootstrap_envs
                )
            )
            self.assertTrue(any(env.get("CUSTOM_BACKEND_FLAG") == "override-enabled" for env in bootstrap_envs))
            self.assertTrue(
                any(
                    isinstance(env.get("APP_ENV_FILE"), str)
                    and Path(str(env.get("APP_ENV_FILE"))).resolve() == override_file.resolve()
                    for env in bootstrap_envs
                )
            )
            self.assertIn(
                "DATABASE_URL=postgresql+psycopg2://override_user:override_pass@db.internal/override_db",
                override_file.read_text(encoding="utf-8"),
            )
            backend_start_envs = [
                env
                for (_cmd, cwd), env in zip(fake_runner.start_background_calls, fake_runner.start_background_envs)
                if Path(cwd).resolve() == backend_dir.resolve() and isinstance(env, dict)
            ]
            self.assertTrue(backend_start_envs)
            self.assertTrue(
                any(
                    env.get("DATABASE_URL")
                    == "postgresql+psycopg2://override_user:override_pass@db.internal/override_db"
                    for env in backend_start_envs
                )
            )
            self.assertTrue(any(env.get("CUSTOM_BACKEND_FLAG") == "override-enabled" for env in backend_start_envs))

    def test_main_env_file_path_applies_backend_env_override_in_main_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "backend"
            main_env_file = repo / "config" / "main.backend.env"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            main_env_file.parent.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            main_env_file.write_text(
                "DATABASE_URL=postgresql+psycopg2://main_user:main_pass@main.db.internal/main_db\n",
                encoding="utf-8",
            )

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"MAIN_ENV_FILE_PATH": str(main_env_file)},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--main", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            bootstrap_envs = [env for env in fake_runner.run_envs if isinstance(env, dict)]
            self.assertTrue(
                any(
                    env.get("DATABASE_URL") == "postgresql+psycopg2://main_user:main_pass@main.db.internal/main_db"
                    for env in bootstrap_envs
                )
            )
            self.assertTrue(
                any(
                    isinstance(env.get("APP_ENV_FILE"), str)
                    and Path(str(env.get("APP_ENV_FILE"))).resolve() == main_env_file.resolve()
                    for env in bootstrap_envs
                )
            )
            backend_start_envs = [
                env
                for (_cmd, cwd), env in zip(fake_runner.start_background_calls, fake_runner.start_background_envs)
                if Path(cwd).resolve() == backend_dir.resolve() and isinstance(env, dict)
            ]
            self.assertTrue(backend_start_envs)
            self.assertTrue(
                any(
                    env.get("DATABASE_URL") == "postgresql+psycopg2://main_user:main_pass@main.db.internal/main_db"
                    for env in backend_start_envs
                )
            )

    def test_backend_env_file_does_not_persist_projected_managed_dependency_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            env_file = backend_dir / ".env"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            env_file.write_text(
                "KEEP_ME=1\nDATABASE_URL=postgresql://legacy\nREDIS_URL=redis://legacy\n",
                encoding="utf-8",
            )

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "DB_USER": "svc_user",
                    "DB_PASSWORD": "svc_pass",
                    "DB_NAME": "svc_db",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--isolated-deps", "--batch"], env={})
            planned_db_port = self._planned_ports(engine, "feature-a-1")["db"].final

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            content = env_file.read_text(encoding="utf-8")
            self.assertIn("KEEP_ME=1", content)
            self.assertIn("DATABASE_URL=postgresql://legacy", content)
            self.assertIn("REDIS_URL=redis://legacy", content)
            self.assertNotIn(f"@localhost:{planned_db_port}/svc_db", content)
            self.assertNotIn(
                f"REDIS_URL=redis://localhost:{self._planned_ports(engine, 'feature-a-1')['redis'].final}/0",
                content,
            )
            backend_start_envs = [
                env
                for (_cmd, cwd), env in zip(fake_runner.start_background_calls, fake_runner.start_background_envs)
                if Path(cwd).resolve() == backend_dir.resolve() and isinstance(env, dict)
            ]
            self.assertTrue(backend_start_envs)
            self.assertTrue(
                any(
                    env.get("DATABASE_URL")
                    == f"postgresql+asyncpg://svc_user:svc_pass@localhost:{planned_db_port}/svc_db"
                    for env in backend_start_envs
                )
            )
            self.assertTrue(
                any(
                    env.get("REDIS_URL")
                    == f"redis://localhost:{self._planned_ports(engine, 'feature-a-1')['redis'].final}/0"
                    for env in backend_start_envs
                )
            )

    def test_backend_env_file_writeback_removes_stale_db_alias_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            env_file = backend_dir / ".env"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            env_file.write_text(
                "DATABASE_URL=postgresql://legacy\n"
                "SQLALCHEMY_DATABASE_URL=postgresql://legacy\n"
                "ASYNC_DATABASE_URL=postgresql://legacy\n"
                "REDIS_URL=redis://legacy\n",
                encoding="utf-8",
            )

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            content = env_file.read_text(encoding="utf-8")
            self.assertIn("DATABASE_URL=postgresql://legacy", content)
            self.assertNotIn("SQLALCHEMY_DATABASE_URL=postgresql://legacy", content)
            self.assertNotIn("ASYNC_DATABASE_URL=postgresql://legacy", content)

    def test_backend_service_start_env_includes_backend_env_file_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / ".env").write_text("CUSTOM_BACKEND_FLAG=enabled\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            backend_start_envs = [
                env
                for (cmd, _cwd), env in zip(fake_runner.start_background_calls, fake_runner.start_background_envs)
                if isinstance(env, dict) and "backend" in " ".join(cmd).lower()
            ]
            if not backend_start_envs:
                backend_start_envs = [env for env in fake_runner.start_background_envs if isinstance(env, dict)]
            self.assertTrue(any(env.get("CUSTOM_BACKEND_FLAG") == "enabled" for env in backend_start_envs))
            self.assertTrue(
                any(
                    isinstance(env.get("APP_ENV_FILE"), str) and Path(str(env.get("APP_ENV_FILE"))).name == ".env"
                    for env in backend_start_envs
                )
            )

    def test_startup_uses_configured_backend_and_frontend_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "api"
            frontend_dir = repo / "web"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            frontend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            (frontend_dir / "package.json").write_text(
                json.dumps({"name": "web", "scripts": {"dev": "vite"}}),
                encoding="utf-8",
            )
            (frontend_dir / "node_modules" / ".bin").mkdir(parents=True, exist_ok=True)
            (frontend_dir / "node_modules" / ".bin" / "vite").write_text("#!/bin/sh\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(
                    repo,
                    runtime,
                    extra={"BACKEND_DIR": "api", "FRONTEND_DIR": "web"},
                ),
                env={},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]

            code = engine.dispatch(parse_route(["--main", "--batch"], env={}))

            self.assertEqual(code, 0)
            cwd_values = {Path(cwd).resolve() for _cmd, cwd in fake_runner.start_background_calls}
            self.assertIn(backend_dir.resolve(), cwd_values)
            self.assertIn(frontend_dir.resolve(), cwd_values)

    def test_main_frontend_env_file_path_is_loaded_in_main_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "backend"
            frontend_dir = repo / "frontend"
            main_frontend_env = repo / "config" / "main.frontend.env"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            frontend_dir.mkdir(parents=True, exist_ok=True)
            main_frontend_env.parent.mkdir(parents=True, exist_ok=True)
            main_frontend_env.write_text("MAIN_FRONTEND_FLAG=active\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"MAIN_FRONTEND_ENV_FILE_PATH": str(main_frontend_env)},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--main", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            frontend_start_envs = [env for env in fake_runner.start_background_envs if isinstance(env, dict)]
            self.assertTrue(frontend_start_envs)
            self.assertTrue(any(env.get("MAIN_FRONTEND_FLAG") == "active" for env in frontend_start_envs))

    def test_main_frontend_relative_env_file_path_is_loaded_in_main_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "backend"
            frontend_dir = repo / "frontend"
            main_frontend_env = repo / "config" / "main.frontend.env"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            frontend_dir.mkdir(parents=True, exist_ok=True)
            main_frontend_env.parent.mkdir(parents=True, exist_ok=True)
            main_frontend_env.write_text("MAIN_FRONTEND_FLAG=relative\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"MAIN_FRONTEND_ENV_FILE_PATH": "config/main.frontend.env"},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--main", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            frontend_start_envs = [env for env in fake_runner.start_background_envs if isinstance(env, dict)]
            self.assertTrue(frontend_start_envs)
            self.assertTrue(any(env.get("MAIN_FRONTEND_FLAG") == "relative" for env in frontend_start_envs))

    def test_startup_scrubs_inherited_shell_backend_env_keys_before_backend_prep(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            env_file = backend_dir / ".env"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            env_file.write_text("CUSTOM_BACKEND_FLAG=enabled\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--isolated-deps", "--batch"], env={})
            planned_db_port = self._planned_ports(engine, "feature-a-1")["db"].final

            with patch.dict(
                os.environ,
                {
                    "APP_ENV_FILE": "/tmp/leaked.env",
                    "DATABASE_URL": "postgresql://shell-leak",
                    "SQLALCHEMY_DATABASE_URL": "postgresql://shell-leak",
                    "ASYNC_DATABASE_URL": "postgresql://shell-leak",
                },
                clear=False,
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            bootstrap_envs = [
                env
                for (cmd, _cwd), env in zip(fake_runner.run_calls, fake_runner.run_envs)
                if len(cmd) >= 4 and cmd[1:4] == ("-m", "pip", "install") and isinstance(env, dict)
            ]
            self.assertTrue(bootstrap_envs)
            env = bootstrap_envs[0]
            self.assertEqual(env.get("APP_ENV_FILE"), str(env_file.resolve()))
            self.assertEqual(
                env.get("DATABASE_URL"),
                f"postgresql+asyncpg://postgres:postgres@localhost:{planned_db_port}/postgres",
            )
            self.assertNotEqual(env.get("SQLALCHEMY_DATABASE_URL"), "postgresql://shell-leak")
            self.assertNotEqual(env.get("ASYNC_DATABASE_URL"), "postgresql://shell-leak")

    def test_frontend_api_env_overrides_stale_env_local_per_project_backend_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            frontend_dir = repo / "trees" / "feature-a" / "1" / "frontend"
            env_local = frontend_dir / ".env.local"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            frontend_dir.mkdir(parents=True, exist_ok=True)
            (frontend_dir / "package.json").write_text(
                json.dumps({"name": "frontend", "scripts": {"dev": "vite"}}),
                encoding="utf-8",
            )
            (frontend_dir / "node_modules" / ".bin").mkdir(parents=True, exist_ok=True)
            (frontend_dir / "node_modules" / ".bin" / "vite").write_text("#!/bin/sh\n", encoding="utf-8")
            env_local.write_text(
                "VITE_BACKEND_URL=http://localhost:9999\nVITE_API_URL=http://localhost:9999/api/v1\n",
                encoding="utf-8",
            )

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            plans = self._planned_ports(engine, "feature-a-1")
            expected_backend_url = f"http://localhost:{plans['backend'].final}"
            expected_api_url = f"http://localhost:{plans['backend'].final}/api/v1"
            env_local_contents = env_local.read_text(encoding="utf-8")
            self.assertEqual(
                env_local_contents,
                "VITE_BACKEND_URL=http://localhost:9999\nVITE_API_URL=http://localhost:9999/api/v1\n",
            )

            frontend_envs = [
                env
                for (_cmd, cwd), env in zip(fake_runner.start_background_calls, fake_runner.start_background_envs)
                if str(cwd).endswith("/frontend") and isinstance(env, dict)
            ]
            self.assertTrue(frontend_envs)
            self.assertEqual(frontend_envs[0].get("VITE_BACKEND_URL"), expected_backend_url)
            self.assertEqual(frontend_envs[0].get("VITE_API_URL"), expected_api_url)

    def test_frontend_api_env_uses_public_host_with_per_project_backend_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            frontend_dir = repo / "trees" / "feature-a" / "1" / "frontend"
            env_local = frontend_dir / ".env.local"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            frontend_dir.mkdir(parents=True, exist_ok=True)
            (frontend_dir / "package.json").write_text(
                json.dumps({"name": "frontend", "scripts": {"dev": "vite"}}),
                encoding="utf-8",
            )
            (frontend_dir / "node_modules" / ".bin").mkdir(parents=True, exist_ok=True)
            (frontend_dir / "node_modules" / ".bin" / "vite").write_text("#!/bin/sh\n", encoding="utf-8")
            env_local.write_text(
                "VITE_BACKEND_URL=http://localhost:9999\nVITE_API_URL=http://localhost:9999/api/v1\n",
                encoding="utf-8",
            )

            engine = PythonEngineRuntime(self._config(repo, runtime), env={"ENVCTL_PUBLIC_HOST": "203.0.113.10"})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            plans = self._planned_ports(engine, "feature-a-1")
            expected_backend_url = f"http://203.0.113.10:{plans['backend'].final}"
            expected_api_url = f"http://203.0.113.10:{plans['backend'].final}/api/v1"
            self.assertEqual(
                env_local.read_text(encoding="utf-8"),
                "VITE_BACKEND_URL=http://localhost:9999\nVITE_API_URL=http://localhost:9999/api/v1\n",
            )

            frontend_envs = [
                env
                for (_cmd, cwd), env in zip(fake_runner.start_background_calls, fake_runner.start_background_envs)
                if str(cwd).endswith("/frontend") and isinstance(env, dict)
            ]
            self.assertTrue(frontend_envs)
            self.assertEqual(frontend_envs[0].get("VITE_BACKEND_URL"), expected_backend_url)
            self.assertEqual(frontend_envs[0].get("VITE_API_URL"), expected_api_url)

