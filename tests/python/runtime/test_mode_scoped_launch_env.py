from __future__ import annotations

import unittest
from types import SimpleNamespace

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.engine_runtime_env import project_service_env
from envctl_engine.state.models import RequirementsResult


class ModeScopedLaunchEnvTests(unittest.TestCase):
    def test_mode_specific_frontend_env_overrides_generic_frontend_env(self) -> None:
        config = SimpleNamespace(
            dependency_env_section_present=False,
            backend_dependency_env_section_present=False,
            frontend_dependency_env_section_present=True,
            frontend_dependency_env_templates=(
                SimpleNamespace(name="VITE_SUPABASE_URL", template="http://generic.example.test", line_number=1),
            ),
            frontend_dependency_env_template_errors=(),
            main_frontend_dependency_env_section_present=True,
            main_frontend_dependency_env_templates=(
                SimpleNamespace(name="VITE_SUPABASE_URL", template="http://main.example.test", line_number=2),
            ),
            main_frontend_dependency_env_template_errors=(),
            trees_frontend_dependency_env_section_present=True,
            trees_frontend_dependency_env_templates=(
                SimpleNamespace(name="VITE_SUPABASE_URL", template="${ENVCTL_SOURCE_SUPABASE_URL}", line_number=3),
            ),
            trees_frontend_dependency_env_template_errors=(),
        )
        runtime = SimpleNamespace(config=config, env={}, _command_override_value=lambda _key: None)
        context = SimpleNamespace(name="Tree Alpha")
        requirements = RequirementsResult(
            project="Tree Alpha",
            components={
                "supabase": {
                    "enabled": True,
                    "resources": {"primary": 5657},
                    "final": 5657,
                }
            },
            health="healthy",
            failures=[],
        )

        main_env = project_service_env(
            runtime,
            context,
            requirements=requirements,
            route=Route(command="start", mode="main"),
            service_name="frontend",
        )
        trees_env = project_service_env(
            runtime,
            context,
            requirements=requirements,
            route=Route(command="start", mode="trees"),
            service_name="frontend",
        )

        self.assertEqual(main_env["VITE_SUPABASE_URL"], "http://main.example.test")
        self.assertEqual(trees_env["VITE_SUPABASE_URL"], "http://localhost:5657")


if __name__ == "__main__":
    unittest.main()
