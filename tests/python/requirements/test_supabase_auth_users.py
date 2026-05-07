from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"

from envctl_engine.requirements.supabase import build_supabase_project_name, start_supabase_stack  # noqa: E402
from envctl_engine.shared.dependency_compose_assets import (  # noqa: E402
    DEFAULT_SUPABASE_JWT_SECRET,
    default_supabase_anon_key,
    default_supabase_service_role_key,
)
from envctl_engine.requirements.supabase_auth_users import (  # noqa: E402
    SupabaseAuthAdminClient,
    SupabaseAuthAdminError,
    sync_supabase_auth_users,
)
from envctl_engine.shared.process_runner import ProcessRunner  # noqa: E402


class _FakeResponse:
    def __init__(self, payload: object, *, status: int = 200) -> None:
        self.status = status
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None


class _FakeOpener:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = responses
        self.requests: list[object] = []

    def open(self, request, timeout=None):  # noqa: ANN001, ANN201
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected request")
        response = self.responses.pop(0)
        if response.status >= 400:
            raise HTTPError(
                request.full_url,
                response.status,
                "failed",
                hdrs=None,
                fp=BytesIO(response.read()),
            )
        return response


def _configured_user(
    name: str,
    email: str,
    *,
    password: str | None = "password",
    user_metadata: dict[str, object] | None = None,
    app_metadata: dict[str, object] | None = None,
    enabled: bool = True,
):
    suffix = name.upper().replace("-", "_")
    return SimpleNamespace(
        name=name,
        env_suffix=suffix,
        email=email,
        password=password,
        auto_confirm=True,
        user_metadata=user_metadata or {},
        app_metadata=app_metadata or {},
        enabled_for_mode=lambda _mode: enabled,
        expose_password=True,
    )


def _docker_supabase_smoke_enabled() -> bool:
    raw = os.environ.get("ENVCTL_RUN_SUPABASE_AUTH_DOCKER_SMOKE", "").strip().lower()
    if raw not in {"1", "true", "yes"}:
        return False
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=8.0,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class SupabaseAuthUserTests(unittest.TestCase):
    def test_admin_client_constructs_list_create_update_delete_requests(self) -> None:
        opener = _FakeOpener(
            [
                _FakeResponse({"users": []}),
                _FakeResponse({"id": "created-id", "email": "e2e@example.test"}),
                _FakeResponse({"id": "created-id", "email": "e2e@example.test"}),
                _FakeResponse({}),
            ]
        )
        client = SupabaseAuthAdminClient(
            base_url="http://localhost:54321/",
            service_role_key="service-role-secret",
            opener=opener,
        )

        self.assertEqual(client.list_users(page=1, per_page=2), [])
        created = client.create_user(
            email="e2e@example.test",
            password="secret-password",
            email_confirm=True,
            user_metadata={"company": "E2E"},
            app_metadata={"role": "tester"},
        )
        self.assertEqual(created.id, "created-id")
        client.update_user(
            "created-id",
            password="new-password",
            email_confirm=True,
            user_metadata={"company": "Updated"},
            app_metadata={"role": "tester"},
        )
        client.delete_user("created-id")

        list_request, create_request, update_request, delete_request = opener.requests
        self.assertEqual(list_request.get_method(), "GET")
        self.assertEqual(
            list_request.full_url,
            "http://localhost:54321/auth/v1/admin/users?page=1&per_page=2",
        )
        self.assertEqual(create_request.get_method(), "POST")
        self.assertEqual(create_request.full_url, "http://localhost:54321/auth/v1/admin/users")
        self.assertEqual(create_request.headers["Authorization"], "Bearer service-role-secret")
        self.assertEqual(create_request.headers["Apikey"], "service-role-secret")
        create_payload = json.loads(create_request.data.decode("utf-8"))
        self.assertEqual(create_payload["email"], "e2e@example.test")
        self.assertEqual(create_payload["password"], "secret-password")
        self.assertTrue(create_payload["email_confirm"])
        self.assertEqual(create_payload["user_metadata"], {"company": "E2E"})
        self.assertEqual(create_payload["app_metadata"], {"role": "tester"})
        self.assertEqual(update_request.get_method(), "PUT")
        self.assertEqual(update_request.full_url, "http://localhost:54321/auth/v1/admin/users/created-id")
        self.assertEqual(delete_request.get_method(), "DELETE")
        self.assertEqual(delete_request.full_url, "http://localhost:54321/auth/v1/admin/users/created-id")

    def test_admin_client_errors_redact_service_key_and_password(self) -> None:
        opener = _FakeOpener(
            [
                _FakeResponse(
                    {
                        "message": "service-role-secret rejected for password secret-password",
                    },
                    status=400,
                )
            ]
        )
        client = SupabaseAuthAdminClient(
            base_url="http://localhost:54321",
            service_role_key="service-role-secret",
            opener=opener,
        )

        with self.assertRaises(SupabaseAuthAdminError) as raised:
            client.create_user(
                email="e2e@example.test",
                password="secret-password",
                email_confirm=True,
                user_metadata={},
                app_metadata={},
            )

        message = str(raised.exception)
        self.assertIn("HTTP 400", message)
        self.assertIn("/auth/v1/admin/users", message)
        self.assertNotIn("service-role-secret", message)
        self.assertNotIn("secret-password", message)

    def test_sync_creates_updates_skips_failures_and_writes_runtime_artifact(self) -> None:
        class _FakeClient:
            def __init__(self) -> None:
                self.records = {
                    "update@example.test": SimpleNamespace(
                        id="existing-update-id",
                        email="update@example.test",
                        user_metadata={"company": "Old"},
                        app_metadata={},
                    ),
                    "same@example.test": SimpleNamespace(
                        id="same-id",
                        email="same@example.test",
                        user_metadata={"company": "Same"},
                        app_metadata={},
                    ),
                    "unconfirmed@example.test": SimpleNamespace(
                        id="unconfirmed-id",
                        email="unconfirmed@example.test",
                        confirmed_at="",
                        user_metadata={},
                        app_metadata={},
                    ),
                }
                self.created: list[str] = []
                self.updated: list[str] = []

            def find_user_by_email(self, email: str):  # noqa: ANN001, ANN201
                if email == "fail@example.test":
                    raise SupabaseAuthAdminError("HTTP 500 /auth/v1/admin/users: failed")
                return self.records.get(email)

            def create_user(self, **payload):  # noqa: ANN003, ANN201
                email = str(payload["email"])
                self.created.append(email)
                record = SimpleNamespace(
                    id=f"created-{email}",
                    email=email,
                    user_metadata=dict(payload.get("user_metadata") or {}),
                    app_metadata=dict(payload.get("app_metadata") or {}),
                )
                self.records[email] = record
                return record

            def update_user(self, user_id: str, **payload):  # noqa: ANN003, ANN201
                self.updated.append(user_id)
                for record in self.records.values():
                    if record.id == user_id:
                        record.user_metadata = dict(payload.get("user_metadata") or record.user_metadata)
                        record.app_metadata = dict(payload.get("app_metadata") or record.app_metadata)
                        return record
                raise AssertionError("unknown user")

        users = (
            _configured_user("missing", "missing@example.test", user_metadata={"company": "New"}),
            _configured_user("update", "update@example.test", user_metadata={"company": "Updated"}),
            _configured_user("same", "same@example.test", password=None, user_metadata={"company": "Same"}),
            _configured_user("unconfirmed", "unconfirmed@example.test", password=None),
            _configured_user("off", "off@example.test", enabled=False),
            _configured_user("fail", "fail@example.test"),
        )
        client = _FakeClient()
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_root = Path(tmpdir)

            result = sync_supabase_auth_users(
                mode="main",
                configured_users=users,
                base_url="http://localhost:54321",
                service_role_key="service-role-secret",
                runtime_root=runtime_root,
                client=client,
            )

            artifact = json.loads((runtime_root / "supabase_auth_users.json").read_text(encoding="utf-8"))

        statuses = {item.name: item.status for item in result.results}
        self.assertEqual(statuses["missing"], "created")
        self.assertEqual(statuses["update"], "updated")
        self.assertEqual(statuses["same"], "unchanged")
        self.assertEqual(statuses["unconfirmed"], "updated")
        self.assertEqual(statuses["off"], "skipped")
        self.assertEqual(statuses["fail"], "failed")
        self.assertFalse(result.success)
        self.assertEqual(client.created, ["missing@example.test"])
        self.assertEqual(client.updated, ["existing-update-id", "unconfirmed-id"])
        self.assertEqual(artifact["users"]["missing"]["id"], "created-missing@example.test")
        self.assertEqual(artifact["users"]["same"]["id"], "same-id")
        self.assertNotIn("service-role-secret", json.dumps(artifact))
        self.assertNotIn("password", json.dumps(artifact).lower())

    @unittest.skipUnless(
        _docker_supabase_smoke_enabled(),
        "set ENVCTL_RUN_SUPABASE_AUTH_DOCKER_SMOKE=1 with Docker available to run managed Supabase Auth smoke",
    )
    def test_docker_managed_supabase_sync_user_can_sign_in_with_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            runtime_root = Path(tmpdir) / "runtime"
            root.mkdir()
            db_port = _free_local_port()
            public_port = _free_local_port()
            project_name = "auth-smoke"
            compose_project = build_supabase_project_name(project_root=root, project_name=project_name)
            compose_path = runtime_root / "dependency_compose" / "supabase" / project_name / "docker-compose.yml"
            jwt_secret = os.environ.get("ENVCTL_SUPABASE_SMOKE_JWT_SECRET", DEFAULT_SUPABASE_JWT_SECRET)
            env = {
                "SUPABASE_PUBLIC_PORT": str(public_port),
                "SUPABASE_PUBLIC_URL": f"http://localhost:{public_port}",
                "SUPABASE_ANON_KEY": os.environ.get(
                    "ENVCTL_SUPABASE_SMOKE_ANON_KEY", default_supabase_anon_key(secret=jwt_secret)
                ),
                "SUPABASE_SERVICE_ROLE_KEY": os.environ.get(
                    "ENVCTL_SUPABASE_SMOKE_SERVICE_ROLE_KEY",
                    default_supabase_service_role_key(secret=jwt_secret),
                ),
                "SUPABASE_JWT_SECRET": jwt_secret,
                "ENVCTL_SUPABASE_COMPOSE_UP_TIMEOUT_SECONDS": "180",
                "ENVCTL_SUPABASE_DB_PROBE_ATTEMPTS": "6",
                "ENVCTL_SUPABASE_DB_PROBE_TIMEOUT_SECONDS": "10",
                "ENVCTL_SUPABASE_AUTH_PROBE_TIMEOUT_SECONDS": "45",
            }

            try:
                start_result = start_supabase_stack(
                    process_runner=ProcessRunner(),
                    project_root=root,
                    project_name=project_name,
                    db_port=db_port,
                    public_port=public_port,
                    runtime_root=runtime_root,
                    env=env,
                )
                self.assertTrue(start_result.success, start_result.error)
                auth_user = _configured_user("e2e", "e2e@example.test", password="local-password-123")

                sync_result = sync_supabase_auth_users(
                    mode="main",
                    configured_users=(auth_user,),
                    base_url=f"http://localhost:{public_port}",
                    service_role_key=env["SUPABASE_SERVICE_ROLE_KEY"],
                    runtime_root=runtime_root,
                )

                self.assertTrue(sync_result.success, [item.error for item in sync_result.results])
                request = Request(
                    f"http://localhost:{public_port}/auth/v1/token?grant_type=password",
                    data=json.dumps({"email": auth_user.email, "password": auth_user.password}).encode("utf-8"),
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {env['SUPABASE_ANON_KEY']}",
                        "apikey": env["SUPABASE_ANON_KEY"],
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with urlopen(request, timeout=10.0) as response:
                    payload = json.loads(response.read().decode("utf-8"))

                self.assertIn("access_token", payload)
                self.assertEqual(payload.get("user", {}).get("email"), auth_user.email)
            finally:
                if compose_path.is_file():
                    subprocess.run(
                        [
                            "docker",
                            "compose",
                            "-p",
                            compose_project,
                            "-f",
                            str(compose_path),
                            "down",
                            "-v",
                            "--remove-orphans",
                        ],
                        cwd=compose_path.parent,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        check=False,
                        timeout=90.0,
                    )


if __name__ == "__main__":
    unittest.main()
