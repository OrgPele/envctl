from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import subprocess

from envctl_engine.requirements.supabase_auth_users import SupabaseAuthUserRecord
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.qa_user_command_support import run_qa_user_command
from envctl_engine.state.models import RequirementsResult, RunState


def _macos_public_tmp_path(raw: str) -> str:
    if raw.startswith("/private/var/"):
        return raw.removeprefix("/private")
    return raw


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
    updated: list[dict[str, object]] = []

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
        self.updated.append({"user_id": user_id, **kwargs})
        return SupabaseAuthUserRecord(id=user_id, email="qa@example.test")


class QaUserCommandSupportTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeClient.existing = None
        _FakeClient.created = []
        _FakeClient.updated = []

    def _runtime(self, *, seed_cmd: str | None = None, runtime_root: Path | None = None, state: RunState | None = None):  # noqa: ANN201
        root = runtime_root or Path("/tmp/envctl-runtime-test")
        raw = {"ENVCTL_QA_USER_SEED_CRM_CMD": seed_cmd} if seed_cmd else {}
        events: list[dict[str, object]] = []
        return SimpleNamespace(
            env={},
            config=SimpleNamespace(raw=raw, runtime_scope_dir=root),
            runtime_root=root,
            state_repository=SimpleNamespace(run_dir_path=lambda run_id: root / "runs" / run_id),
            _command_override_value=lambda _key: None,
            _try_load_existing_state=lambda **_kwargs: state or _state(),
            _state_lookup_strict_mode_match=lambda _route: True,
            _emit=lambda event, **payload: events.append({"event": event, **payload}),
            events=events,
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


    def test_ensure_writes_redacted_artifact_and_resolution_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._runtime(runtime_root=Path(tmpdir))
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
                    code = run_qa_user_command(runtime, route)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertIn("artifact_path", payload)
            self.assertEqual(
                payload["project_resolution"],
                {
                    "requested_projects": ["feature-a-1"],
                    "selected_projects": ["feature-a-1"],
                    "active_projects": ["feature-a-1"],
                },
            )
            artifact = json.loads(Path(payload["artifact_path"]).read_text(encoding="utf-8"))
            self.assertEqual(artifact["project"], "feature-a-1")
            self.assertEqual(artifact["run_id"], "run-qa")
            self.assertEqual(artifact["credentials"], {"email": "qa@example.test", "password": "<redacted>"})
            self.assertNotIn("secret", json.dumps(artifact))
            events = [event for event in runtime.events if event.get("event") == "qa_user.ensure"]
            self.assertEqual(len(events), 1, msg=runtime.events)
            self.assertEqual(events[0]["email_hash"], "603ba7ede2fef2a532e27f0bfcd60efbe67c1a0494f8756635779f4d8b56da7b")
            self.assertNotIn("secret", json.dumps(events))

    def test_ensure_reuses_existing_user_without_update_by_default(self) -> None:
        _FakeClient.existing = SupabaseAuthUserRecord(id="user-existing", email="qa@example.test")
        with tempfile.TemporaryDirectory() as tmpdir:
            route = Route(
                command="qa-user",
                mode="trees",
                projects=["feature-a-1"],
                passthrough_args=["ensure"],
                flags={"json": True, "email": "qa@example.test", "password": "secret", "metadata_json": '{"locale":"he-IL"}'},
            )
            stdout = StringIO()

            with patch("envctl_engine.runtime.qa_user_command_support.SupabaseAuthAdminClient", _FakeClient):
                with redirect_stdout(stdout):
                    code = run_qa_user_command(self._runtime(runtime_root=Path(tmpdir)), route)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(payload["reused"])
        self.assertFalse(payload["updated"])
        self.assertEqual(payload["updated_fields"], [])
        self.assertEqual(_FakeClient.updated, [])

    def test_update_flags_mutate_existing_user_only_for_requested_fields(self) -> None:
        _FakeClient.existing = SupabaseAuthUserRecord(id="user-existing", email="qa@example.test")
        with tempfile.TemporaryDirectory() as tmpdir:
            route = Route(
                command="qa-user",
                mode="trees",
                projects=["feature-a-1"],
                passthrough_args=["ensure"],
                flags={
                    "json": True,
                    "email": "qa@example.test",
                    "password": "new-secret",
                    "metadata_json": '{"locale":"he-IL"}',
                    "app_metadata_json": '{"role":"qa"}',
                    "update_password": True,
                    "update_metadata": True,
                },
            )
            stdout = StringIO()

            with patch("envctl_engine.runtime.qa_user_command_support.SupabaseAuthAdminClient", _FakeClient):
                with redirect_stdout(stdout):
                    code = run_qa_user_command(self._runtime(runtime_root=Path(tmpdir)), route)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(payload["updated"])
        self.assertEqual(payload["updated_fields"], ["password", "user_metadata", "app_metadata"])
        self.assertEqual(_FakeClient.updated[0]["user_id"], "user-existing")
        self.assertEqual(_FakeClient.updated[0]["password"], "new-secret")
        self.assertEqual(_FakeClient.updated[0]["user_metadata"], {"locale": "he-IL"})
        self.assertEqual(_FakeClient.updated[0]["app_metadata"], {"role": "qa"})

    def test_seed_hook_runs_from_project_root_with_dependency_env_and_redacted_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            project_root = root / "project"
            project_root.mkdir()
            state = _state()
            state.metadata["project_roots"] = {"feature-a-1": str(project_root)}
            state.requirements["feature-a-1"].supabase = {
                "enabled": True,
                "success": True,
                "resources": {"api": 54321, "db": 5432},
                "env": {"SUPABASE_URL": "http://127.0.0.1:54321", "SUPABASE_SERVICE_ROLE_KEY": "service-secret"},
            }
            script = root / "seed.py"
            script.write_text(
                "import os, pathlib\n"
                "pathlib.Path('seed.cwd').write_text(os.getcwd())\n"
                "print(os.environ['ENVCTL_PROJECT_NAME'])\n"
                "print(os.environ['ENVCTL_QA_USER_EMAIL'])\n"
                "print(os.environ.get('SUPABASE_URL', 'missing'))\n"
                "print(os.environ.get('SUPABASE_SERVICE_ROLE_KEY', 'missing'))\n",
                encoding="utf-8",
            )
            runtime = self._runtime(seed_cmd=f"{sys.executable} {script}", runtime_root=root / "runtime", state=state)
            route = Route(
                command="qa-user",
                mode="trees",
                projects=["feature-a-1"],
                passthrough_args=["ensure"],
                flags={"json": True, "email": "qa@example.test", "password": "secret", "seed": ["crm"]},
            )
            stdout = StringIO()

            with patch("envctl_engine.runtime.qa_user_command_support.SupabaseAuthAdminClient", _FakeClient):
                with redirect_stdout(stdout):
                    code = run_qa_user_command(runtime, route)

            payload = json.loads(stdout.getvalue())
            result = payload["seed_results"][0]
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["exit_code"], 0)
            self.assertEqual(result["cwd"], str(project_root))
            self.assertIn("feature-a-1", result["stdout"])
            self.assertIn("http://127.0.0.1:54321", result["stdout"])
            self.assertNotIn("service-secret", json.dumps(payload))
            self.assertEqual(
                _macos_public_tmp_path((project_root / "seed.cwd").read_text(encoding="utf-8")),
                str(project_root),
            )

    def test_seed_hook_runs_with_timeout_and_reports_timeout_failure(self) -> None:
        route = Route(
            command="qa-user",
            mode="trees",
            projects=["feature-a-1"],
            passthrough_args=["ensure"],
            flags={"json": True, "email": "qa@example.test", "password": "secret", "seed": ["crm"]},
        )
        stdout = StringIO()
        captured: dict[str, object] = {}

        def fake_run(*args, **kwargs):  # noqa: ANN001
            captured.update(kwargs)
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

        with (
            patch("envctl_engine.runtime.qa_user_command_support.SupabaseAuthAdminClient", _FakeClient),
            patch("envctl_engine.runtime.qa_user_command_support.subprocess.run", side_effect=fake_run),
        ):
            with redirect_stdout(stdout):
                code = run_qa_user_command(self._runtime(seed_cmd=f"{sys.executable} -c pass"), route)

        payload = json.loads(stdout.getvalue())
        result = payload["seed_results"][0]
        self.assertEqual(code, 1)
        self.assertGreater(captured["timeout"], 0)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "timeout")

    def test_explicit_env_fallback_keeps_service_role_key_out_of_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = self._runtime(runtime_root=Path(tmpdir))
            runtime.env.update({"SUPABASE_URL": "http://127.0.0.1:54321", "SUPABASE_SERVICE_ROLE_KEY": "service-secret"})
            state = _state()
            state.requirements["feature-a-1"].supabase = {"enabled": False, "success": False}
            runtime._try_load_existing_state = lambda **_kwargs: state
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
                    code = run_qa_user_command(runtime, route)

        rendered = stdout.getvalue()
        payload = json.loads(rendered)
        self.assertEqual(code, 0)
        self.assertIn("project_resolution", payload)
        self.assertNotIn("service-secret", rendered)

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
