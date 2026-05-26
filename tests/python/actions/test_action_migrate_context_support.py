from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from envctl_engine.actions.action_migrate_context_support import (
    migrate_backend_cwd,
    migrate_component_port,
    migrate_project_context,
    migrate_requirements_for_target,
)
from envctl_engine.state.models import RequirementsResult


class ActionMigrateContextSupportTests(unittest.TestCase):
    def test_migrate_project_context_projects_dependency_ports_from_requirements_state(self) -> None:
        result = RequirementsResult(
            project="feature-a-1",
            components={
                "postgres": {"final": 15432},
                "redis": {"requested": 16379},
                "n8n": {"assigned": 15678},
                "supabase": {"final": 25432},
            },
        )

        context = migrate_project_context(
            project_name="feature-a-1",
            project_root=Path("/repo"),
            requirements=result,
        )

        self.assertEqual(context.name, "feature-a-1")
        self.assertEqual(context.root, Path("/repo"))
        self.assertEqual(context.ports["db"].final, 15432)
        self.assertEqual(context.ports["redis"].final, 16379)
        self.assertEqual(context.ports["n8n"].final, 15678)
        self.assertNotIn("supabase", context.ports)
        self.assertEqual(migrate_component_port({"final": 0, "requested": "2222", "assigned": 3333}), 2222)

    def test_migrate_requirements_for_target_matches_project_name_case_insensitively(self) -> None:
        result = RequirementsResult(project="Feature-A-1")
        state = SimpleNamespace(requirements={"Feature-A-1": result})
        runtime = SimpleNamespace(load_existing_state=lambda *, mode: state)
        route = SimpleNamespace(mode="trees")

        self.assertIs(
            migrate_requirements_for_target(runtime=runtime, route=route, project_name="feature-a-1"),
            result,
        )

    def test_migrate_backend_cwd_prefers_backend_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.assertEqual(migrate_backend_cwd(root), root)
            (root / "backend").mkdir()
            self.assertEqual(migrate_backend_cwd(root), root / "backend")


if __name__ == "__main__":
    unittest.main()
