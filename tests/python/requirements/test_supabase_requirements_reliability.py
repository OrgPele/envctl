from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import ProjectContext, PythonEngineRuntime
from envctl_engine.requirements.supabase import (
    SupabaseReliabilityContract,
    build_supabase_project_name,
    evaluate_supabase_reliability_contract,
)


def _write_supabase_files(repo: Path, *, static_network_name: bool = False, bootstrap_sql: str = "CREATE SCHEMA IF NOT EXISTS auth;\n") -> None:
    supabase_dir = repo / "supabase"
    init_dir = supabase_dir / "init"
    init_dir.mkdir(parents=True, exist_ok=True)
    network_block = "  supabase-net:\n    name: fallback\n" if static_network_name else "  supabase-net: {}\n"
    compose = (
        "services:\n"
        "  supabase-auth:\n"
        "    environment:\n"
        "      GOTRUE_DB_DATABASE_URL: postgres://postgres:postgres@supabase-db:5432/postgres?search_path=auth,public\n"
        "      GOTRUE_DB_NAMESPACE: auth\n"
        "      DB_NAMESPACE: auth\n"
        "    volumes:\n"
        "      - ./kong.yml:/home/kong/kong.yml:ro\n"
        "      - ./init/01-create-n8n-db.sql:/docker-entrypoint-initdb.d/01-create-n8n-db.sql:ro\n"
        "      - ./init/02-bootstrap-gotrue-auth.sql:/docker-entrypoint-initdb.d/02-bootstrap-gotrue-auth.sql:ro\n"
        "networks:\n"
        f"{network_block}"
    )
    (supabase_dir / "docker-compose.yml").write_text(compose, encoding="utf-8")
    (supabase_dir / "kong.yml").write_text("_format_version: \"3.0\"\n", encoding="utf-8")
    (init_dir / "01-create-n8n-db.sql").write_text("select 1;\n", encoding="utf-8")
    (init_dir / "02-bootstrap-gotrue-auth.sql").write_text(bootstrap_sql, encoding="utf-8")


class SupabaseRequirementsReliabilityTests(unittest.TestCase):
    def test_contract_rejects_static_network_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _write_supabase_files(repo, static_network_name=True)
            contract = evaluate_supabase_reliability_contract(repo)
            self.assertFalse(contract.ok)
            self.assertTrue(any("static network name" in err for err in contract.errors))

    def test_contract_fingerprint_changes_when_bootstrap_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _write_supabase_files(repo, bootstrap_sql="CREATE SCHEMA IF NOT EXISTS auth;\n")
            first = evaluate_supabase_reliability_contract(repo)
            _write_supabase_files(repo, bootstrap_sql="CREATE SCHEMA IF NOT EXISTS auth;\nALTER ROLE postgres IN DATABASE postgres SET search_path = auth, public;\n")
            second = evaluate_supabase_reliability_contract(repo)
            self.assertTrue(first.ok)
            self.assertTrue(second.ok)
            self.assertNotEqual(first.fingerprint, second.fingerprint)

    def test_runtime_blocks_supabase_start_when_contract_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime_dir = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime_dir),
                    "SUPABASE_MAIN_ENABLE": "true",
                }
            )
            runtime = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_REQUIREMENT_SUPABASE_CMD": "sh -lc true",
                },
            )
            context = ProjectContext(name="Main", root=repo, ports=runtime.port_planner.plan_project_stack("Main", index=0))

            with patch(
                "envctl_engine.startup.requirements_startup_domain.evaluate_managed_supabase_reliability_contract",
                return_value=SupabaseReliabilityContract(
                    ok=False,
                    fingerprint="invalid",
                    errors=["supabase compose defines static network name; use project-scoped network names instead"],
                    compose_path=Path("/managed/supabase/docker-compose.yml"),
                ),
            ):
                outcome = runtime._start_requirement_component(
                    context,
                    "supabase",
                    context.ports["db"],
                    reserve_next=lambda port: port,
                )
            self.assertFalse(outcome.success)
            self.assertIn("static network name", outcome.error or "")

    def test_runtime_requires_reinit_when_supabase_contract_fingerprint_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime_dir = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            _write_supabase_files(repo)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime_dir),
                    "SUPABASE_MAIN_ENABLE": "true",
                }
            )
            runtime = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_REQUIREMENT_SUPABASE_CMD": "sh -lc true",
                },
            )
            runtime._wait_for_requirement_listener = lambda _port: True  # type: ignore[method-assign]
            context = ProjectContext(name="Main", root=repo, ports=runtime.port_planner.plan_project_stack("Main", index=0))

            with patch(
                "envctl_engine.startup.requirements_startup_domain.evaluate_managed_supabase_reliability_contract",
                side_effect=[
                    SupabaseReliabilityContract(ok=True, fingerprint="v1", errors=[], compose_path=Path("/managed/supabase/docker-compose.yml")),
                    SupabaseReliabilityContract(ok=True, fingerprint="v2", errors=[], compose_path=Path("/managed/supabase/docker-compose.yml")),
                ],
            ):
                first = runtime._start_requirement_component(
                    context,
                    "supabase",
                    context.ports["db"],
                    reserve_next=lambda port: port,
                )
                self.assertTrue(first.success)
                second = runtime._start_requirement_component(
                    context,
                    "supabase",
                    context.ports["db"],
                    reserve_next=lambda port: port,
                )
            self.assertFalse(second.success)
            self.assertIn("reinit workflow", second.error or "")

    def test_runtime_auto_reinit_runs_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime_dir = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            _write_supabase_files(repo)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime_dir),
                    "SUPABASE_MAIN_ENABLE": "true",
                }
            )
            runtime = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_REQUIREMENT_SUPABASE_CMD": "sh -lc true",
                    "ENVCTL_SUPABASE_AUTO_REINIT": "true",
                },
            )
            runtime._wait_for_requirement_listener = lambda _port: True  # type: ignore[method-assign]
            context = ProjectContext(name="Main", root=repo, ports=runtime.port_planner.plan_project_stack("Main", index=0))

            commands: list[list[str]] = []

            def fake_run(cmd, **_kwargs):
                commands.append(list(cmd))
                return subprocess.CompletedProcess(cmd, 0, "", "")

            runtime.process_runner.run = fake_run  # type: ignore[method-assign]
            with patch(
                "envctl_engine.startup.requirements_startup_domain.evaluate_managed_supabase_reliability_contract",
                side_effect=[
                    SupabaseReliabilityContract(ok=True, fingerprint="v1", errors=[], compose_path=Path("/managed/supabase/docker-compose.yml")),
                    SupabaseReliabilityContract(ok=True, fingerprint="v2", errors=[], compose_path=Path("/managed/supabase/docker-compose.yml")),
                ],
            ):
                first = runtime._start_requirement_component(
                    context,
                    "supabase",
                    context.ports["db"],
                    reserve_next=lambda port: port,
                )
                second = runtime._start_requirement_component(
                    context,
                    "supabase",
                    context.ports["db"],
                    reserve_next=lambda port: port,
                )
            self.assertTrue(first.success)
            self.assertTrue(second.success)
            self.assertTrue(any("down" in cmd and "-v" in cmd for cmd in commands))
            self.assertTrue(any("supabase-db" in cmd for cmd in commands))
            self.assertTrue(any("supabase-auth" in cmd for cmd in commands))

    def test_runtime_uses_native_supabase_adapter_when_enabled_and_not_synthetic(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime_dir = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime_dir),
                    "SUPABASE_MAIN_ENABLE": "true",
                }
            )
            runtime = PythonEngineRuntime(config, env={})
            context = ProjectContext(name="Main", root=repo, ports=runtime.port_planner.plan_project_stack("Main", index=0))

            commands: list[list[str]] = []

            def fake_run(cmd, **_kwargs):
                command = [str(part) for part in cmd]
                commands.append(command)
                if command[:2] == ["docker", "compose"] and "config" in command and "--services" in command:
                    return subprocess.CompletedProcess(command, 0, "supabase-db\nsupabase-auth\nsupabase-kong\n", "")
                return subprocess.CompletedProcess(command, 0, "", "")

            runtime.process_runner.run = fake_run  # type: ignore[method-assign]
            runtime.process_runner.wait_for_port = lambda _port, timeout=30.0, host="127.0.0.1": True  # type: ignore[method-assign]
            runtime._command_exists = lambda command: command == "docker"  # type: ignore[method-assign]

            outcome = runtime._start_requirement_component(
                context,
                "supabase",
                context.ports["db"],
                reserve_next=lambda port: port,
            )

            self.assertTrue(outcome.success)
            expected_project = build_supabase_project_name(project_root=repo, project_name="Main")
            self.assertTrue(
                any(
                    expected_project in " ".join(cmd)
                    and "supabase-db" in " ".join(cmd)
                    and cmd[0] == "docker"
                    for cmd in commands
                )
            )
            self.assertTrue(any("dependency_compose" in token for cmd in commands for token in cmd))


if __name__ == "__main__":
    unittest.main()
