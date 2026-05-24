# ruff: noqa: F403,F405
from __future__ import annotations

import unittest

from tests.python.requirements.requirements_adapter_contract_support import *


class SupabaseStackCoreContractTests(unittest.TestCase):
    def test_supabase_stack_starts_compose_services_and_waits_for_db_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")

            runner = _FakeRunner()
            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_TWO_PHASE_STARTUP": "false"},
            )
            self.assertTrue(result.success)
            compose_project = build_supabase_project_name(project_root=root, project_name="feature-a-1")
            self.assertEqual(result.container_name, compose_project)
            self.assertTrue(
                any(
                    cmd[:5] == ["docker", "compose", "-p", compose_project, "-f"] and "config" in cmd
                    for cmd in runner.commands
                )
            )
            self.assertTrue(
                any(
                    cmd[:5] == ["docker", "compose", "-p", compose_project, "-f"]
                    and cmd[-5:] == ["up", "-d", "supabase-db", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )

    def test_supabase_stack_starts_full_graph_before_auth_health_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")

            runner = _FakeRunner()
            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
            )

            self.assertTrue(result.success)
            graph_ups = [
                cmd
                for cmd in runner.commands
                if cmd[:2] == ["docker", "compose"]
                and cmd[-5:] == ["up", "-d", "supabase-db", "supabase-auth", "supabase-kong"]
            ]
            self.assertEqual(len(graph_ups), 1)
            self.assertFalse(
                any(
                    cmd[:2] == ["docker", "compose"] and cmd[-4:] == ["up", "-d", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )
            stage_names = [str(item.get("stage", "")) for item in result.stage_events or []]
            self.assertIn("supabase.graph.up", stage_names)
            self.assertIn("supabase.db.probe", stage_names)
            self.assertIn("supabase.auth.probe", stage_names)

    def test_supabase_stack_uses_discovered_alternative_service_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text(
                "services:\n  db: {}\n  auth: {}\n  kong: {}\n", encoding="utf-8"
            )

            runner = _FakeRunner()
            runner.compose_services_stdout = "db\nauth\nkong\n"

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
            )
            self.assertTrue(result.success)
            compose_project = build_supabase_project_name(project_root=root, project_name="feature-a-1")
            self.assertTrue(
                any(
                    cmd[:5] == ["docker", "compose", "-p", compose_project, "-f"]
                    and cmd[-5:] == ["up", "-d", "db", "auth", "kong"]
                    for cmd in runner.commands
                )
            )

    def test_supabase_stack_fails_when_compose_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result = start_supabase_stack(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                db_port=5432,
            )
            self.assertFalse(result.success)
            self.assertIn("missing supabase compose file", result.error or "")

    def test_supabase_stack_uses_unique_compose_project_name_per_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = root / "trees" / "feature-a" / "1"
            second = root / "trees" / "feature-b" / "1"
            for path in (first, second):
                supabase_dir = path / "supabase"
                supabase_dir.mkdir(parents=True, exist_ok=True)
                (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            first_runner = _FakeRunner()
            second_runner = _FakeRunner()

            first_result = start_supabase_stack(
                process_runner=first_runner,
                project_root=first,
                project_name="feature-a-1",
                db_port=5432,
            )
            second_result = start_supabase_stack(
                process_runner=second_runner,
                project_root=second,
                project_name="feature-b-1",
                db_port=5433,
            )

            self.assertTrue(first_result.success)
            self.assertTrue(second_result.success)
            self.assertNotEqual(first_result.container_name, second_result.container_name)

    def test_supabase_stack_condenses_container_name_conflict_into_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_returncode["up -d supabase-db supabase-auth supabase-kong"] = 1
            runner.compose_stderr["up -d supabase-db supabase-auth supabase-kong"] = (
                "Container supabase-supabase-db-1 Error response from daemon: Conflict. "
                'The container name "/supabase-supabase-db-1" is already in use by container "abc".\n'
                'Error response from daemon: Conflict. The container name "/supabase-supabase-db-1" is already in use by container "abc".'
            )

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
            )

            self.assertFalse(result.success)
            self.assertIn("supabase compose namespace conflict", result.error or "")
            self.assertIn("supabase-supabase-db-1", result.error or "")

    def test_supabase_project_env_exports_database_url_and_password(self) -> None:
        class _Runtime:
            @staticmethod
            def _command_override_value(key: str) -> str | None:
                return {
                    "SUPABASE_ANON_KEY": "anon-secret",
                    "SUPABASE_SERVICE_ROLE_KEY": "service-secret",
                    "SUPABASE_JWT_SECRET": "jwt-secret",
                }.get(key)

        class _Context:
            ports = {"db": type("Plan", (), {"final": 5432})()}

        class _Requirements:
            @staticmethod
            def component(name: str) -> dict[str, object]:
                assert name == "supabase"
                return {"final": 5432, "requested": 5432}

        env_projector = dependency_definition("supabase").env_projector
        assert env_projector is not None
        env = env_projector(runtime=_Runtime(), context=_Context(), requirements=_Requirements(), route=None)

        self.assertEqual(env["DB_HOST"], "localhost")
        self.assertEqual(env["DB_PORT"], "5432")
        self.assertEqual(env["DB_USER"], "postgres")
        self.assertEqual(env["DB_PASSWORD"], "supabase-db-password")
        self.assertIn("supabase-db-password", env["DATABASE_URL"])
        self.assertEqual(env["DATABASE_URL"], env["SQLALCHEMY_DATABASE_URL"])
        self.assertEqual(env["DATABASE_URL"], env["ASYNC_DATABASE_URL"])
        self.assertEqual(env["SUPABASE_URL"], "http://localhost:5432")
        self.assertEqual(env["SUPABASE_ANON_KEY"], "anon-secret")
        self.assertEqual(env["SUPABASE_SERVICE_ROLE_KEY"], "service-secret")
        self.assertEqual(env["SUPABASE_JWT_SECRET"], "jwt-secret")
        self.assertEqual(env["SUPABASE_JWKS_URL"], "http://localhost:5432/auth/v1/.well-known/jwks.json")


if __name__ == "__main__":
    unittest.main()
