from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from envctl_engine.shared.dependency_compose_assets import (  # noqa: E402
    DEFAULT_SUPABASE_JWT_SECRET,
    default_supabase_service_role_key,
)
from envctl_engine.runtime.supabase_user_command_support import (
    _resolve_supabase_admin_connection,
    run_supabase_user_command,
)
from envctl_engine.state.models import RequirementsResult, RunState


def _managed_supabase_state() -> RunState:
    return RunState(
        run_id="run-1",
        mode="main",
        requirements={
            "Main": RequirementsResult(
                project="Main",
                supabase={
                    "enabled": True,
                    "success": True,
                    "resources": {"db": 5432, "api": 54321, "primary": 5432},
                },
                health="healthy",
                failures=[],
            )
        },
    )


class SupabaseUserCommandSupportTests(unittest.TestCase):
    def test_resolves_managed_connection_from_loaded_state(self) -> None:
        state = _managed_supabase_state()
        runtime = SimpleNamespace(
            env={},
            config=SimpleNamespace(raw={}, runtime_scope_dir=Path("/tmp/envctl-runtime-test")),
            _command_override_value=lambda key: None,
            _try_load_existing_state=lambda **kwargs: state,
        )

        base_url, service_role_key = _resolve_supabase_admin_connection(runtime, mode="main")

        self.assertEqual(base_url, "http://localhost:54321")
        self.assertEqual(service_role_key, default_supabase_service_role_key(secret=DEFAULT_SUPABASE_JWT_SECRET))

    def test_list_command_uses_loaded_state_connection(self) -> None:
        class _FakeClient:
            seen: list[tuple[str, str]] = []

            def __init__(self, *, base_url: str, service_role_key: str) -> None:
                self.seen.append((base_url, service_role_key))

            def list_users(self):  # noqa: ANN201
                return []

        state = _managed_supabase_state()
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = SimpleNamespace(
                env={},
                config=SimpleNamespace(raw={}, runtime_scope_dir=Path(tmpdir), supabase_auth_users=()),
                runtime_root=Path(tmpdir),
                _command_override_value=lambda key: None,
                _try_load_existing_state=lambda **kwargs: state,
            )
            route = SimpleNamespace(
                command="supabase-user",
                mode="main",
                flags={"json": True},
                passthrough_args=["list"],
            )
            stdout = StringIO()

            with (
                patch(
                    "envctl_engine.runtime.supabase_user_command_support.SupabaseAuthAdminClient",
                    _FakeClient,
                ),
                redirect_stdout(stdout),
            ):
                code = run_supabase_user_command(runtime, route)

        self.assertEqual(code, 0)
        self.assertEqual(
            _FakeClient.seen,
            [("http://localhost:54321", default_supabase_service_role_key(secret=DEFAULT_SUPABASE_JWT_SECRET))],
        )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["command"], "list")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["users"], [])


if __name__ == "__main__":
    unittest.main()
