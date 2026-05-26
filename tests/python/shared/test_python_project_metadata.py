from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from envctl_engine.shared.python_project_metadata import pyproject_has_tool_table
from envctl_engine.shared.python_project_metadata import pyproject_project_name
from envctl_engine.shared.python_project_metadata import pyproject_project_version
from envctl_engine.shared.python_project_metadata import pyproject_uses_poetry


class PythonProjectMetadataTests(unittest.TestCase):
    def test_project_name_reads_pep621_project_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject = Path(tmpdir) / "pyproject.toml"
            pyproject.write_text("[project]\nname = ' envctl '\n", encoding="utf-8")

            self.assertEqual(pyproject_project_name(pyproject), "envctl")

    def test_project_version_reads_pep621_project_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject = Path(tmpdir) / "pyproject.toml"
            pyproject.write_text("[project]\nversion = ' 1.2.3 '\n", encoding="utf-8")

            self.assertEqual(pyproject_project_version(pyproject), "1.2.3")

    def test_project_version_ignores_missing_invalid_or_non_string_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            missing = root / "missing.toml"
            invalid = root / "invalid.toml"
            invalid_encoding = root / "invalid-encoding.toml"
            non_string = root / "non-string.toml"
            invalid.write_text("[project\n", encoding="utf-8")
            invalid_encoding.write_bytes(b"\xff")
            non_string.write_text("[project]\nversion = 123\n", encoding="utf-8")

            self.assertIsNone(pyproject_project_version(missing))
            self.assertIsNone(pyproject_project_version(invalid))
            self.assertIsNone(pyproject_project_version(invalid_encoding))
            self.assertIsNone(pyproject_project_version(non_string))

    def test_project_name_ignores_missing_invalid_or_non_string_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            missing = root / "missing.toml"
            invalid = root / "invalid.toml"
            invalid_encoding = root / "invalid-encoding.toml"
            non_string = root / "non-string.toml"
            invalid.write_text("[project\n", encoding="utf-8")
            invalid_encoding.write_bytes(b"\xff")
            non_string.write_text("[project]\nname = 123\n", encoding="utf-8")

            self.assertIsNone(pyproject_project_name(missing))
            self.assertIsNone(pyproject_project_name(invalid))
            self.assertIsNone(pyproject_project_name(invalid_encoding))
            self.assertIsNone(pyproject_project_name(non_string))

    def test_tool_table_detection_requires_a_real_tool_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pytest_project = root / "pytest.toml"
            pdm_project = root / "pdm.toml"
            quoted_marker = root / "quoted.toml"
            pytest_project.write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']\n", encoding="utf-8")
            pdm_project.write_text("[tool.pdm]\nname = 'backend'\n", encoding="utf-8")
            quoted_marker.write_text("description = '[tool.pytest] is just text'\n", encoding="utf-8")

            self.assertTrue(pyproject_has_tool_table(pytest_project, "pytest"))
            self.assertFalse(pyproject_has_tool_table(pdm_project, "pytest"))
            self.assertFalse(pyproject_has_tool_table(quoted_marker, "pytest"))

    def test_poetry_detection_uses_tool_poetry_table_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            poetry_project = root / "poetry.toml"
            pdm_project = root / "pdm.toml"
            quoted_marker = root / "quoted.toml"
            invalid = root / "invalid.toml"
            poetry_project.write_text("[tool.poetry]\nname = 'backend'\n", encoding="utf-8")
            pdm_project.write_text("[tool.pdm]\nname = 'backend'\n", encoding="utf-8")
            quoted_marker.write_text("description = '[tool.poetry] is just text'\n", encoding="utf-8")
            invalid.write_text("[tool.poetry\n", encoding="utf-8")

            self.assertTrue(pyproject_uses_poetry(poetry_project))
            self.assertFalse(pyproject_uses_poetry(pdm_project))
            self.assertFalse(pyproject_uses_poetry(quoted_marker))
            self.assertFalse(pyproject_uses_poetry(invalid))


if __name__ == "__main__":
    unittest.main()
