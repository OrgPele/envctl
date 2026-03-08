from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]


class StructureLayoutTests(unittest.TestCase):
    def test_python_domain_directories_exist(self) -> None:
        expected = [
            'python/envctl_engine/actions',
            'python/envctl_engine/config',
            'python/envctl_engine/debug',
            'python/envctl_engine/planning',
            'python/envctl_engine/requirements',
            'python/envctl_engine/runtime',
            'python/envctl_engine/shared',
            'python/envctl_engine/shell',
            'python/envctl_engine/startup',
            'python/envctl_engine/state',
            'python/envctl_engine/ui/dashboard',
            'python/envctl_engine/ui/textual/screens/selector',
        ]
        for rel in expected:
            self.assertTrue((REPO_ROOT / rel).is_dir(), rel)

    def test_test_domain_directories_exist(self) -> None:
        expected = [
            'tests/python/actions',
            'tests/python/config',
            'tests/python/debug',
            'tests/python/planning',
            'tests/python/requirements',
            'tests/python/runtime',
            'tests/python/shared',
            'tests/python/shell',
            'tests/python/startup',
            'tests/python/state',
            'tests/python/test_output',
            'tests/python/ui',
        ]
        for rel in expected:
            self.assertTrue((REPO_ROOT / rel).is_dir(), rel)

    def test_shell_domain_directories_exist(self) -> None:
        expected = [
            'lib/engine/lib/actions',
            'lib/engine/lib/config',
            'lib/engine/lib/debug',
            'lib/engine/lib/docker',
            'lib/engine/lib/git',
            'lib/engine/lib/planning',
            'lib/engine/lib/requirements',
            'lib/engine/lib/runtime',
            'lib/engine/lib/services',
            'lib/engine/lib/shared',
            'lib/engine/lib/state',
            'lib/engine/lib/ui',
            'lib/engine/lib/worktrees',
        ]
        for rel in expected:
            self.assertTrue((REPO_ROOT / rel).is_dir(), rel)

    def test_shell_root_shims_source_grouped_files(self) -> None:
        samples = {
            'lib/engine/lib/actions.sh': '/actions/actions.sh',
            'lib/engine/lib/config.sh': '/config/config.sh',
            'lib/engine/lib/planning.sh': '/planning/planning.sh',
            'lib/engine/lib/requirements.sh': '/requirements/requirements.sh',
        }
        for rel, needle in samples.items():
            text = (REPO_ROOT / rel).read_text()
            self.assertIn(needle, text, rel)


if __name__ == '__main__':
    unittest.main()
