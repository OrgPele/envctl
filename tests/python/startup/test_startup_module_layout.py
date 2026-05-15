from __future__ import annotations

import ast
import inspect
import textwrap
import unittest
from pathlib import Path

from envctl_engine.startup.startup_orchestrator import StartupOrchestrator


REPO_ROOT = Path(__file__).resolve().parents[3]
STARTUP_ROOT = REPO_ROOT / "python" / "envctl_engine" / "startup"


class StartupModuleLayoutTests(unittest.TestCase):
    def _imports_for(self, path: Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        return imports

    def test_orchestrator_imports_startup_owner_modules(self) -> None:
        imports = self._imports_for(STARTUP_ROOT / "startup_orchestrator.py")

        self.assertIn("envctl_engine.startup.execution_plan", imports)
        self.assertIn("envctl_engine.startup.run_reuse_application", imports)
        self.assertIn("envctl_engine.startup.project_execution", imports)

    def test_run_reuse_application_stays_out_of_ui_and_dashboard_rendering(self) -> None:
        imports = self._imports_for(STARTUP_ROOT / "run_reuse_application.py")

        forbidden = {
            name for name in imports if name.startswith("envctl_engine.ui") or name.startswith("envctl_engine.ui.dashboard")
        }
        self.assertEqual(forbidden, set())

    def test_project_execution_does_not_import_finalization_or_dashboard_rendering(self) -> None:
        imports = self._imports_for(STARTUP_ROOT / "project_execution.py")

        self.assertNotIn("envctl_engine.startup.finalization", imports)
        self.assertFalse(any(name.startswith("envctl_engine.ui.dashboard") for name in imports))

    def test_orchestrator_reuse_and_execution_methods_are_thin_wrappers(self) -> None:
        for name in ("_resolve_run_reuse", "_start_selected_contexts"):
            with self.subTest(name=name):
                source = inspect.getsource(getattr(StartupOrchestrator, name))
                tree = ast.parse(textwrap.dedent(source))
                function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef))
                branch_nodes = (
                    ast.If,
                    ast.For,
                    ast.While,
                    ast.Try,
                    ast.With,
                    ast.Match,
                    ast.BoolOp,
                )
                branches = [node for node in ast.walk(function) if isinstance(node, branch_nodes)]
                self.assertLessEqual(len(branches), 1, source)


if __name__ == "__main__":
    unittest.main()
