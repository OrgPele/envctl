from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from tests.python.actions.actions_parity_test_support import (
    PythonEngineRuntime,
    RequirementsResult,
    RunState,
    ServiceRecord,
    _ActionsParityTestCase,
    _FakeRunner,
    load_config,
    parse_route,
)


class ActionsMigrateParityTests(_ActionsParityTestCase):
    def test_migrate_action_uses_local_dot_venv_python_when_backend_venv_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (target / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (target / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            target.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["migrate", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertTrue(fake_runner.run_calls)
            command = fake_runner.run_calls[0][0]
            self.assertEqual(Path(command[0]).resolve(), (target / ".venv" / "bin" / "python").resolve())
            self.assertEqual(command[1:4], ("-m", "alembic", "upgrade"))

    def test_migrate_action_falls_back_to_system_python_when_local_venv_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            target.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            with patch(
                "envctl_engine.actions.action_utils.shutil.which",
                side_effect=lambda name: "/usr/bin/python3" if name in {"python3.12", "python3", "python"} else None,
            ):
                route = parse_route(["migrate", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertTrue(fake_runner.run_calls)
            self.assertEqual(fake_runner.run_calls[0][0][:3], ("/usr/bin/python3", "-m", "alembic"))

    def test_migrate_action_loads_backend_env_file_and_exports_app_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            backend_dir = target / "backend"
            backend_env_file = backend_dir / ".env"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (backend_dir / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (backend_dir / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            backend_env_file.write_text(
                "CUSTOM_BACKEND_FLAG=enabled\nREDIS_URL=redis://legacy:6379/0\n",
                encoding="utf-8",
            )

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["migrate", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertTrue(fake_runner.run_calls)
            self.assertEqual(Path(fake_runner.run_calls[0][1]).resolve(), backend_dir.resolve())
            env = fake_runner.run_envs[0] or {}
            self.assertEqual(env.get("APP_ENV_FILE"), str(backend_env_file.resolve()))
            self.assertEqual(env.get("CUSTOM_BACKEND_FLAG"), "enabled")
            self.assertEqual(env.get("REDIS_URL"), "redis://legacy:6379/0")

    def test_migrate_action_honors_backend_env_file_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            backend_dir = target / "backend"
            override_file = repo / "config" / "backend.override.env"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (backend_dir / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (backend_dir / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            (backend_dir / ".env").write_text("CUSTOM_BACKEND_FLAG=default\n", encoding="utf-8")
            override_file.parent.mkdir(parents=True, exist_ok=True)
            override_file.write_text("CUSTOM_BACKEND_FLAG=override-enabled\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"BACKEND_ENV_FILE_OVERRIDE": str(override_file)},
            )
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["migrate", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            env = fake_runner.run_envs[0] or {}
            self.assertEqual(Path(str(env.get("APP_ENV_FILE", ""))).resolve(), override_file.resolve())
            self.assertEqual(env.get("CUSTOM_BACKEND_FLAG"), "override-enabled")

    def test_migrate_action_honors_main_env_file_path_in_main_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "backend"
            main_env_file = repo / "config" / "main.backend.env"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (backend_dir / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (backend_dir / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            main_env_file.parent.mkdir(parents=True, exist_ok=True)
            main_env_file.write_text("CUSTOM_BACKEND_FLAG=main-enabled\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_DEFAULT_MODE": "main",
                    }
                ),
                env={"MAIN_ENV_FILE_PATH": str(main_env_file)},
            )
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["migrate", "--main"], env={"ENVCTL_DEFAULT_MODE": "main"})
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            env = fake_runner.run_envs[0] or {}
            self.assertEqual(Path(str(env.get("APP_ENV_FILE", ""))).resolve(), main_env_file.resolve())
            self.assertEqual(env.get("CUSTOM_BACKEND_FLAG"), "main-enabled")

    def test_migrate_action_uses_current_requirements_projection_when_state_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            backend_dir = target / "backend"
            backend_env_file = backend_dir / ".env"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (backend_dir / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (backend_dir / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            backend_env_file.write_text(
                "DATABASE_URL=postgresql+psycopg2://legacy:legacy@db.internal/legacy\n"
                "REDIS_URL=redis://legacy:6379/0\n",
                encoding="utf-8",
            )

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            self._save_state(
                engine,
                RunState(
                    run_id="run-migrate-env",
                    mode="trees",
                    services={
                        "feature-a-1 Backend": ServiceRecord(
                            name="feature-a-1 Backend",
                            type="backend",
                            cwd=str(backend_dir),
                            pid=1001,
                            requested_port=8000,
                            actual_port=8000,
                            status="running",
                        )
                    },
                    requirements={
                        "feature-a-1": RequirementsResult(
                            project="feature-a-1",
                            db={"enabled": True, "success": True, "final": 5544},
                            redis={"enabled": True, "success": True, "final": 6399},
                            health="healthy",
                            failures=[],
                        )
                    },
                ),
            )
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["migrate", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            env = fake_runner.run_envs[0] or {}
            self.assertEqual(
                env.get("DATABASE_URL"),
                "postgresql+asyncpg://postgres:postgres@localhost:5544/postgres",
            )
            self.assertEqual(env.get("REDIS_URL"), "redis://localhost:6399/0")
            self.assertEqual(env.get("APP_ENV_FILE"), str(backend_env_file.resolve()))

    def test_migrate_action_scrubs_inherited_shell_backend_env_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            backend_dir = target / "backend"
            backend_env_file = backend_dir / ".env"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (backend_dir / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (backend_dir / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            backend_env_file.write_text("CUSTOM_BACKEND_FLAG=enabled\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            self._save_state(
                engine,
                RunState(
                    run_id="run-migrate-shell-scrub",
                    mode="trees",
                    services={
                        "feature-a-1 Backend": ServiceRecord(
                            name="feature-a-1 Backend",
                            type="backend",
                            cwd=str(backend_dir),
                            pid=1001,
                            requested_port=8000,
                            actual_port=8000,
                            status="running",
                        )
                    },
                    requirements={
                        "feature-a-1": RequirementsResult(
                            project="feature-a-1",
                            db={"enabled": True, "success": True, "final": 5544},
                            redis={"enabled": True, "success": True, "final": 6399},
                            health="healthy",
                            failures=[],
                        )
                    },
                ),
            )
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            with patch.dict(
                "os.environ",
                {
                    "APP_ENV_FILE": "/tmp/leaked.env",
                    "DATABASE_URL": "postgresql://shell-leak",
                    "SQLALCHEMY_DATABASE_URL": "postgresql://shell-leak",
                    "ASYNC_DATABASE_URL": "postgresql://shell-leak",
                },
                clear=False,
            ):
                route = parse_route(["migrate", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            env = fake_runner.run_envs[0] or {}
            self.assertEqual(env.get("APP_ENV_FILE"), str(backend_env_file.resolve()))
            self.assertEqual(
                env.get("DATABASE_URL"),
                "postgresql+asyncpg://postgres:postgres@localhost:5544/postgres",
            )
            self.assertNotEqual(env.get("SQLALCHEMY_DATABASE_URL"), "postgresql://shell-leak")
            self.assertNotEqual(env.get("ASYNC_DATABASE_URL"), "postgresql://shell-leak")
            self.assertEqual(env.get("CUSTOM_BACKEND_FLAG"), "enabled")

    def test_migrate_action_reconciles_full_db_url_family_for_default_backend_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            backend_dir = target / "backend"
            backend_env_file = backend_dir / ".env"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (backend_dir / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (backend_dir / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            backend_env_file.write_text(
                "DATABASE_URL=postgresql+psycopg2://legacy:legacy@db.internal/legacy\n"
                "SQLALCHEMY_DATABASE_URL=postgresql+psycopg2://legacy:legacy@db.internal/legacy\n"
                "ASYNC_DATABASE_URL=postgresql+psycopg2://legacy:legacy@db.internal/legacy\n",
                encoding="utf-8",
            )

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            self._save_state(
                engine,
                RunState(
                    run_id="run-migrate-db-family",
                    mode="trees",
                    services={
                        "feature-a-1 Backend": ServiceRecord(
                            name="feature-a-1 Backend",
                            type="backend",
                            cwd=str(backend_dir),
                            pid=1001,
                            requested_port=8000,
                            actual_port=8000,
                            status="running",
                        )
                    },
                    requirements={
                        "feature-a-1": RequirementsResult(
                            project="feature-a-1",
                            supabase={"enabled": True, "success": True, "final": 5544},
                            health="healthy",
                            failures=[],
                        )
                    },
                ),
            )
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["migrate", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            env = fake_runner.run_envs[0] or {}
            expected_database_url = "postgresql+asyncpg://postgres:supabase-db-password@localhost:5544/postgres"
            self.assertEqual(env.get("DATABASE_URL"), expected_database_url)
            self.assertEqual(env.get("SQLALCHEMY_DATABASE_URL"), expected_database_url)
            self.assertEqual(env.get("ASYNC_DATABASE_URL"), expected_database_url)

    def test_migrate_action_preserves_override_env_file_database_url_when_skip_local_db_applies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            backend_dir = target / "backend"
            override_file = repo / "config" / "backend.override.env"
            override_database_url = "postgresql+psycopg2://override_user:override_pass@db.internal/override_db"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (backend_dir / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (backend_dir / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            override_file.parent.mkdir(parents=True, exist_ok=True)
            override_file.write_text(
                f"DATABASE_URL={override_database_url}\nCUSTOM_BACKEND_FLAG=override\n",
                encoding="utf-8",
            )

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"BACKEND_ENV_FILE_OVERRIDE": str(override_file)},
            )
            self._save_state(
                engine,
                RunState(
                    run_id="run-migrate-override",
                    mode="trees",
                    services={
                        "feature-a-1 Backend": ServiceRecord(
                            name="feature-a-1 Backend",
                            type="backend",
                            cwd=str(backend_dir),
                            pid=1001,
                            requested_port=8000,
                            actual_port=8000,
                            status="running",
                        )
                    },
                    requirements={
                        "feature-a-1": RequirementsResult(
                            project="feature-a-1",
                            db={"enabled": True, "success": True, "final": 5544},
                            redis={"enabled": True, "success": True, "final": 6399},
                            health="healthy",
                            failures=[],
                        )
                    },
                ),
            )
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["migrate", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            env = fake_runner.run_envs[0] or {}
            self.assertEqual(env.get("DATABASE_URL"), override_database_url)
            self.assertEqual(env.get("CUSTOM_BACKEND_FLAG"), "override")
            self.assertEqual(Path(str(env.get("APP_ENV_FILE", ""))).resolve(), override_file.resolve())

    def test_migrate_action_preserves_override_db_url_family_when_explicit_override_is_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            backend_dir = target / "backend"
            override_file = repo / "config" / "backend.override.env"
            override_database_url = "postgresql+psycopg2://override_user:override_pass@db.internal/override_db"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (backend_dir / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (backend_dir / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            override_file.parent.mkdir(parents=True, exist_ok=True)
            override_file.write_text(
                f"DATABASE_URL={override_database_url}\n"
                f"SQLALCHEMY_DATABASE_URL={override_database_url}\n"
                f"ASYNC_DATABASE_URL={override_database_url}\n",
                encoding="utf-8",
            )

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"BACKEND_ENV_FILE_OVERRIDE": str(override_file)},
            )
            self._save_state(
                engine,
                RunState(
                    run_id="run-migrate-override-family",
                    mode="trees",
                    services={
                        "feature-a-1 Backend": ServiceRecord(
                            name="feature-a-1 Backend",
                            type="backend",
                            cwd=str(backend_dir),
                            pid=1001,
                            requested_port=8000,
                            actual_port=8000,
                            status="running",
                        )
                    },
                    requirements={
                        "feature-a-1": RequirementsResult(
                            project="feature-a-1",
                            supabase={"enabled": True, "success": True, "final": 5544},
                            health="healthy",
                            failures=[],
                        )
                    },
                ),
            )
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["migrate", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            env = fake_runner.run_envs[0] or {}
            self.assertEqual(env.get("DATABASE_URL"), override_database_url)
            self.assertEqual(env.get("SQLALCHEMY_DATABASE_URL"), override_database_url)
            self.assertEqual(env.get("ASYNC_DATABASE_URL"), override_database_url)

    def test_migrate_action_accepts_repo_root_relative_backend_env_override_for_tree_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            backend_dir = target / "backend"
            override_file = repo / "config" / "backend.override.env"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (backend_dir / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (backend_dir / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            override_file.parent.mkdir(parents=True, exist_ok=True)
            override_file.write_text("CUSTOM_BACKEND_FLAG=repo-relative\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"BACKEND_ENV_FILE_OVERRIDE": "config/backend.override.env"},
            )
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["migrate", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            env = fake_runner.run_envs[0] or {}
            self.assertEqual(Path(str(env.get("APP_ENV_FILE", ""))).resolve(), override_file.resolve())
            self.assertEqual(env.get("CUSTOM_BACKEND_FLAG"), "repo-relative")

    def test_migrate_action_uses_distinct_env_contracts_for_each_target_in_multi_target_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            first_target = repo / "trees" / "feature-a" / "1"
            second_target = repo / "trees" / "feature-b" / "1"
            first_backend = first_target / "backend"
            second_backend = second_target / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            for backend_dir, marker in ((first_backend, "a"), (second_backend, "b")):
                (backend_dir / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
                (backend_dir / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
                (backend_dir / ".env").write_text(f"PROJECT_MARKER={marker}\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            self._save_state(
                engine,
                RunState(
                    run_id="run-migrate-multi-target",
                    mode="trees",
                    services={
                        "feature-a-1 Backend": ServiceRecord(
                            name="feature-a-1 Backend",
                            type="backend",
                            cwd=str(first_backend),
                            pid=1001,
                            requested_port=8000,
                            actual_port=8000,
                            status="running",
                        ),
                        "feature-b-1 Backend": ServiceRecord(
                            name="feature-b-1 Backend",
                            type="backend",
                            cwd=str(second_backend),
                            pid=1002,
                            requested_port=8001,
                            actual_port=8001,
                            status="running",
                        ),
                    },
                    requirements={
                        "feature-a-1": RequirementsResult(
                            project="feature-a-1",
                            supabase={"enabled": True, "success": True, "final": 5544},
                            health="healthy",
                            failures=[],
                        ),
                        "feature-b-1": RequirementsResult(
                            project="feature-b-1",
                            supabase={"enabled": True, "success": True, "final": 6644},
                            health="healthy",
                            failures=[],
                        ),
                    },
                ),
            )
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["migrate", "--all", "--yes"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(len(fake_runner.run_envs), 2)
            first_env = fake_runner.run_envs[0] or {}
            second_env = fake_runner.run_envs[1] or {}
            self.assertEqual(first_env.get("APP_ENV_FILE"), str((first_backend / ".env").resolve()))
            self.assertEqual(second_env.get("APP_ENV_FILE"), str((second_backend / ".env").resolve()))
            self.assertEqual(first_env.get("PROJECT_MARKER"), "a")
            self.assertEqual(second_env.get("PROJECT_MARKER"), "b")
            self.assertEqual(
                first_env.get("DATABASE_URL"),
                "postgresql+asyncpg://postgres:supabase-db-password@localhost:5544/postgres",
            )
            self.assertEqual(
                second_env.get("DATABASE_URL"),
                "postgresql+asyncpg://postgres:supabase-db-password@localhost:6644/postgres",
            )
            self.assertEqual(first_env.get("SQLALCHEMY_DATABASE_URL"), first_env.get("DATABASE_URL"))
            self.assertEqual(second_env.get("SQLALCHEMY_DATABASE_URL"), second_env.get("DATABASE_URL"))
