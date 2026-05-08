from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from envctl_engine.requirements.supabase_auth_users import SupabaseAuthUserRecord
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.qa_user_command_support import run_qa_user_command
from envctl_engine.state.models import RequirementsResult, RunState


def _state() -> RunState:
    return RunState(
        run_id="run-qa",
        mode="trees",
        metadata={"dependency_mode": "isolated", "shared_dependencies": False},
        requirements={
            "feature-a-1": RequirementsResult(
                project="feature-a-1",
                supabase={
                    "enabled": True,
                    "success": True,
                    "resources": {"db": 5432, "api": 54321, "primary": 5432},
                },
            )
        },
    )


class _FakeClient:
    existing: SupabaseAuthUserRecord | None = None
    created: list[dict[str, object]] = []

    def __init__(self, *, base_url: str, service_role_key: str) -> None:
        self.base_url = base_url
        self.service_role_key = service_role_key

    def find_user_by_email(self, email: str):  # noqa: ANN201
        _ = email
        return self.existing

    def create_user(self, **kwargs):  # noqa: ANN201
        self.created.append(kwargs)
        return SupabaseAuthUserRecord(id="user-created", email=str(kwargs["email"]))

    def update_user(self, user_id: str, **kwargs):  # noqa: ANN201
        return SupabaseAuthUserRecord(id=user_id, email="qa@example.test")


class QaUserCommandSupportTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeClient.existing = None
        _FakeClient.created = []

    def _runtime(self, *, seed_cmd: str | None = None):  # noqa: ANN201
        raw = {"ENVCTL_QA_USER_SEED_CRM_CMD": seed_cmd} if seed_cmd else {}
        return SimpleNamespace(
            env={},
            config=SimpleNamespace(raw=raw, runtime_scope_dir=Path("/tmp/envctl-runtime-test")),
            runtime_root=Path("/tmp/envctl-runtime-test"),
            _command_override_value=lambda _key: None,
            _try_load_existing_state=lambda **_kwargs: _state(),
            _state_lookup_strict_mode_match=lambda _route: True,
            _emit=lambda *_args, **_kwargs: None,
        )

    def test_ensure_creates_missing_user_and_returns_credentials_json(self) -> None:
        route = Route(
            command="qa-user",
            mode="trees",
            projects=["feature-a-1"],
            passthrough_args=["ensure"],
            flags={"json": True, "email": "qa@example.test", "password": "secret", "seed": ["crm", "calendar"]},
        )
        stdout = StringIO()

        with patch("envctl_engine.runtime.qa_user_command_support.SupabaseAuthAdminClient", _FakeClient):
            with redirect_stdout(stdout):
                code = run_qa_user_command(self._runtime(), route)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["project"], "feature-a-1")
        self.assertEqual(payload["run_id"], "run-qa")
        self.assertEqual(payload["dependency_mode"], "isolated")
        self.assertEqual(payload["user"], {"id": "user-created", "email": "qa@example.test"})
        self.assertEqual(payload["credentials"], {"email": "qa@example.test", "password": "secret"})
        self.assertTrue(payload["created"])
        self.assertFalse(payload["reused"])
        self.assertEqual([result["status"] for result in payload["seed_results"]], ["skipped", "skipped"])
        self.assertEqual(payload["seed_results"][0]["reason"], "no_seed_hook_configured")
        self.assertEqual(_FakeClient.created[0]["email"], "qa@example.test")
        self.assertEqual(_FakeClient.created[0]["password"], "secret")
        self.assertTrue(_FakeClient.created[0]["email_confirm"])

    def test_ensure_reuses_existing_user(self) -> None:
        _FakeClient.existing = SupabaseAuthUserRecord(id="user-existing", email="qa@example.test")
        route = Route(
            command="qa-user",
            mode="trees",
            projects=["feature-a-1"],
            passthrough_args=["ensure"],
            flags={"json": True, "email": "qa@example.test", "password": "secret"},
        )
        stdout = StringIO()

        with patch("envctl_engine.runtime.qa_user_command_support.SupabaseAuthAdminClient", _FakeClient):
            with redirect_stdout(stdout):
                code = run_qa_user_command(self._runtime(), route)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertFalse(payload["created"])
        self.assertTrue(payload["reused"])
        self.assertEqual(payload["user"]["id"], "user-existing")
        self.assertEqual(_FakeClient.created, [])

    def test_requires_project_when_multiple_projects_are_active(self) -> None:
        state = RunState(
            run_id="run-qa-multi",
            mode="trees",
            requirements={
                "feature-a-1": RequirementsResult(project="feature-a-1"),
                "feature-b-1": RequirementsResult(project="feature-b-1"),
            },
        )
        runtime = self._runtime()
        runtime._try_load_existing_state = lambda **_kwargs: state
        route = Route(
            command="qa-user",
            mode="trees",
            passthrough_args=["ensure"],
            flags={"json": True, "email": "qa@example.test", "password": "secret"},
        )
        stdout = StringIO()

        with redirect_stdout(stdout):
            code = run_qa_user_command(runtime, route)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "project_required")
        self.assertEqual(payload["active_projects"], ["feature-a-1", "feature-b-1"])

    def test_missing_project_fails_closed_before_supabase_connection(self) -> None:
        route = Route(
            command="qa-user",
            mode="trees",
            projects=["missing"],
            passthrough_args=["ensure"],
            flags={"json": True, "email": "qa@example.test", "password": "secret"},
        )
        stdout = StringIO()

        with redirect_stdout(stdout):
            code = run_qa_user_command(self._runtime(), route)

        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout.getvalue())["error"], "requested_project_not_running")


if __name__ == "__main__":
    unittest.main()
