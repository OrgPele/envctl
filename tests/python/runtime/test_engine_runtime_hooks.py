from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.engine_runtime import ProjectContext  # noqa: E402
from envctl_engine.runtime.engine_runtime_hooks import (  # noqa: E402
    hook_bridge_enabled,
    invoke_envctl_hook,
    requirements_result_from_hook_payload,
    run_supabase_reinit,
    services_from_hook_payload,
    supabase_fingerprint_path,
)
from envctl_engine.requirements.supabase import build_supabase_project_name  # noqa: E402
from envctl_engine.shared.hooks import HookInvocationResult  # noqa: E402
from envctl_engine.state.models import PortPlan  # noqa: E402


class EngineRuntimeHooksTests(unittest.TestCase):
    def _context(self, root: Path) -> ProjectContext:
        return ProjectContext(
            name="feature/a-1",
            root=root,
            ports={
                "db": PortPlan(project="feature/a-1", requested=5432, assigned=5432, final=5432, source="assigned"),
                "redis": PortPlan(project="feature/a-1", requested=6379, assigned=6379, final=6379, source="assigned"),
                "n8n": PortPlan(project="feature/a-1", requested=5678, assigned=5678, final=5678, source="assigned"),
                "backend": PortPlan(
                    project="feature/a-1", requested=8000, assigned=8000, final=8000, source="assigned"
                ),
                "frontend": PortPlan(
                    project="feature/a-1", requested=9000, assigned=9000, final=9000, source="assigned"
                ),
            },
        )

    def test_hook_bridge_enabled_honors_env_override(self) -> None:
        runtime = SimpleNamespace(env={"ENVCTL_ENABLE_HOOK_BRIDGE": "0"}, config=SimpleNamespace(raw={}))

        self.assertFalse(hook_bridge_enabled(runtime))

    def test_invoke_envctl_hook_emits_bridge_event(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(
            env={},
            config=SimpleNamespace(raw={}),
            _command_env=lambda *, port: {"PORT": str(port)},
            _emit=lambda event, **payload: events.append((event, payload)),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            context = self._context(Path(tmpdir))
            expected = HookInvocationResult(
                hook_name="envctl_setup_infrastructure",
                found=True,
                success=True,
                stdout="ok",
                stderr="",
                payload={"skip_default_requirements": True},
            )
            with patch("envctl_engine.runtime.engine_runtime_hooks.run_envctl_hook", return_value=expected) as run_mock:
                result = invoke_envctl_hook(runtime, context=context, hook_name="envctl_setup_infrastructure")

        self.assertIs(result, expected)
        run_mock.assert_called_once()
        self.assertEqual(events[0][0], "hook.bridge.invoke")
        self.assertEqual(events[0][1]["project"], "feature/a-1")
        self.assertTrue(bool(events[0][1]["has_payload"]))

    def test_requirements_result_from_hook_payload_updates_final_ports(self) -> None:
        runtime = SimpleNamespace(
            _requirement_enabled=lambda name, mode: name != "supabase",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            context = self._context(Path(tmpdir))

            result = requirements_result_from_hook_payload(
                runtime,
                context=context,
                mode="trees",
                payload={
                    "requirements": {
                        "postgres": {"final": 5544, "retries": 2, "success": True},
                        "redis": {"final": 6390, "success": False},
                        "n8n": {"final": 5688, "simulated": True, "success": True},
                    }
                },
            )

        self.assertEqual(result.db["final"], 5544)
        self.assertEqual(result.redis["final"], 6390)
        self.assertEqual(result.n8n["final"], 5688)
        self.assertEqual(context.ports["db"].final, 5544)
        self.assertEqual(context.ports["redis"].final, 6390)
        self.assertEqual(context.ports["n8n"].final, 5688)
        self.assertEqual(result.health, "degraded")
        self.assertEqual(result.failures, ["redis:hook_failure"])

    def test_services_from_hook_payload_builds_records_and_updates_service_ports(self) -> None:
        runtime = SimpleNamespace()
        with tempfile.TemporaryDirectory() as tmpdir:
            context = self._context(Path(tmpdir))

            records = services_from_hook_payload(
                runtime,
                context=context,
                payload={
                    "services": [
                        {
                            "name": "feature/a-1 Backend",
                            "type": "backend",
                            "pid": 101,
                            "requested_port": 8000,
                            "actual_port": 8010,
                        },
                        {
                            "name": "feature/a-1 Frontend",
                            "type": "frontend",
                            "pid": 102,
                            "port": 9010,
                            "status": "healthy",
                        },
                    ]
                },
            )

        self.assertEqual(sorted(records.keys()), ["feature/a-1 Backend", "feature/a-1 Frontend"])
        self.assertEqual(records["feature/a-1 Backend"].actual_port, 8010)
        self.assertEqual(records["feature/a-1 Frontend"].requested_port, 9010)
        self.assertEqual(context.ports["backend"].final, 8010)
        self.assertEqual(context.ports["frontend"].final, 9010)

    def test_supabase_fingerprint_path_sanitizes_project_name(self) -> None:
        runtime = SimpleNamespace(runtime_root=Path("/tmp/runtime-root"))

        path = supabase_fingerprint_path(runtime, "feature/a name")

        self.assertEqual(path, Path("/tmp/runtime-root/supabase_fingerprints/feature_a_name.json"))

    def test_run_supabase_reinit_uses_managed_compose_assets(self) -> None:
        commands: list[list[str]] = []

        def _run(cmd, **_kwargs):  # noqa: ANN001
            commands.append([str(part) for part in cmd])
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        runtime = SimpleNamespace(
            runtime_root=Path("/tmp/runtime-root"),
            process_runner=SimpleNamespace(run=_run),
            _command_env=lambda *, port: {"PORT": str(port)},
            _wait_for_requirement_listener=lambda _port: True,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            error = run_supabase_reinit(runtime, project_root=project_root, project_name="feature/a-1", db_port=5432)

        self.assertIsNone(error)
        project_name = build_supabase_project_name(project_root=project_root, project_name="feature/a-1")
        self.assertTrue(commands)
        self.assertTrue(any(cmd[:4] == ["docker", "compose", "-p", project_name] for cmd in commands))
        self.assertTrue(
            any(
                "dependency_compose" in token and token.endswith("docker-compose.yml")
                for cmd in commands
                for token in cmd
            )
        )


if __name__ == "__main__":
    unittest.main()
