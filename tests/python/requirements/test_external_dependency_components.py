from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.requirements.external_env import ExternalDependencyEnvResolver
from envctl_engine.requirements.external_mode import ExternalDependencyModePolicy
from envctl_engine.requirements.external_probe import ExternalDependencyProbe


class ExternalDependencyComponentTests(unittest.TestCase):
    def test_env_resolver_preserves_envctl_precedence_over_application_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            backend = repo / "backend"
            backend.mkdir()
            backend.joinpath(".env").write_text(
                "SUPABASE_URL=https://backend.example.test\nSUPABASE_ANON_KEY=backend-anon\n",
                encoding="utf-8",
            )
            runtime = SimpleNamespace(
                env={},
                config=SimpleNamespace(
                    raw={
                        "SUPABASE_URL": "https://envctl.example.test",
                        "SUPABASE_ANON_KEY": "envctl-anon",
                    },
                    base_dir=repo,
                    backend_dir_name="backend",
                    frontend_dir_name="frontend",
                ),
            )

            resolved = ExternalDependencyEnvResolver(runtime).project_env("supabase")

            self.assertEqual(resolved["SUPABASE_URL"], "https://envctl.example.test")
            self.assertEqual(resolved["SUPABASE_ANON_KEY"], "envctl-anon")

    def test_mode_policy_keeps_explicit_external_mode_available_for_trees(self) -> None:
        runtime = SimpleNamespace(
            env={"ENVCTL_DEPENDENCY_REDIS_MODE": "external"},
            config=SimpleNamespace(raw={}),
        )

        self.assertTrue(ExternalDependencyModePolicy(runtime).external_mode("redis", mode="trees"))

    def test_probe_owner_skips_live_probe_when_disabled(self) -> None:
        runtime = SimpleNamespace(
            env={"ENVCTL_EXTERNAL_DEPENDENCY_PROBE": "false"},
            config=SimpleNamespace(raw={}),
        )

        self.assertIsNone(ExternalDependencyProbe(runtime).probe_error("redis"))


if __name__ == "__main__":
    unittest.main()
