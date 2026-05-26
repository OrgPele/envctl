from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.startup.dependency_bootstrap import prepare_project_dependencies
from envctl_engine.state.models import RequirementsResult


class DependencyBootstrapTests(unittest.TestCase):
    def test_prepare_project_dependencies_normalizes_empty_internal_project_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend = root / "backend"
            backend.mkdir()
            (backend / "requirements.txt").write_text("requests\n", encoding="utf-8")
            prepared_backend_envs: list[dict[str, str]] = []

            runtime = SimpleNamespace(
                config=SimpleNamespace(backend_dir_name="backend", frontend_dir_name="frontend"),
                _run_dir_path=lambda run_id: root / ".runs" / run_id,
                _project_service_env_internal=lambda context, requirements, route: None,
                _project_service_env=lambda context, requirements, route, service_name=None: {
                    "SERVICE": service_name or "default"
                },
                _resolve_backend_env_file=lambda context, backend_cwd: (None, False),
                _resolve_frontend_env_file=lambda context, frontend_cwd: None,
                _prepare_backend_runtime=lambda **kwargs: prepared_backend_envs.append(
                    dict(kwargs["project_env_base"])
                ),
                _prepare_frontend_runtime=lambda **kwargs: None,
            )
            context = SimpleNamespace(name="Main", root=root, ports={})

            result = prepare_project_dependencies(
                runtime,
                context=context,
                route=None,
                run_id="run-1",
                requirements=RequirementsResult(project="Main", health="ok"),
            )

        self.assertTrue(result.prepared)
        self.assertEqual(prepared_backend_envs, [{}])


if __name__ == "__main__":
    unittest.main()
