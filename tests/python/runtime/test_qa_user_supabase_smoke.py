from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
import os
from types import SimpleNamespace
import unittest
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.qa_user_command_support import run_qa_user_command
from envctl_engine.state.models import RequirementsResult, RunState


@unittest.skipUnless(
    os.environ.get("ENVCTL_RUN_SUPABASE_QA_SMOKE") == "1"
    and os.environ.get("SUPABASE_URL")
    and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
    "set ENVCTL_RUN_SUPABASE_QA_SMOKE=1 with SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY to run managed Supabase auth smoke",
)
class QaUserSupabaseSmokeTests(unittest.TestCase):
    def test_ensured_qa_user_can_authenticate_with_password_grant(self) -> None:
        email = os.environ.get("ENVCTL_QA_SMOKE_EMAIL", "envctl-smoke@example.test")
        password = os.environ.get("ENVCTL_QA_SMOKE_PASSWORD", "envctl-local-smoke-password-123")
        state = RunState(run_id="run-supabase-smoke", mode="trees", requirements={"Main": RequirementsResult(project="Main")})
        runtime = SimpleNamespace(
            env={"SUPABASE_URL": os.environ["SUPABASE_URL"], "SUPABASE_SERVICE_ROLE_KEY": os.environ["SUPABASE_SERVICE_ROLE_KEY"]},
            config=SimpleNamespace(raw={}),
            runtime_root=os.getcwd(),
            _try_load_existing_state=lambda **_kwargs: state,
            _state_lookup_strict_mode_match=lambda _route: True,
            _emit=lambda *_args, **_kwargs: None,
        )
        route = Route(
            command="qa-user",
            mode="trees",
            projects=["Main"],
            passthrough_args=["ensure"],
            flags={"json": True, "email": email, "password": password, "update_password": True},
        )
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = run_qa_user_command(runtime, route)
        self.assertEqual(code, 0, stdout.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])

        body = urlencode({"email": email, "password": password}).encode("utf-8")
        request = Request(
            f"{os.environ['SUPABASE_URL'].rstrip('/')}/auth/v1/token?grant_type=password",
            data=body,
            headers={"apikey": os.environ["SUPABASE_SERVICE_ROLE_KEY"], "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urlopen(request, timeout=10) as response:  # noqa: S310 - gated local smoke against caller-provided Supabase URL
            auth_payload = json.loads(response.read().decode("utf-8"))
        self.assertIn("access_token", auth_payload)


if __name__ == "__main__":
    unittest.main()
