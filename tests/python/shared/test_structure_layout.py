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

    def test_shell_runtime_tree_is_absent(self) -> None:
        self.assertFalse((REPO_ROOT / 'lib' / 'engine' / 'lib').exists())
        self.assertFalse((REPO_ROOT / 'lib' / 'engine' / 'main.sh').exists())
        self.assertFalse((REPO_ROOT / 'lib' / 'envctl.sh').exists())

    def test_bats_harness_is_absent(self) -> None:
        self.assertFalse((REPO_ROOT / 'tests' / 'bats').exists())

    def test_repo_local_launcher_is_python_script(self) -> None:
        launcher = REPO_ROOT / 'bin' / 'envctl'
        self.assertTrue(launcher.is_file())
        text = launcher.read_text(encoding='utf-8')
        self.assertTrue(text.startswith('#!/usr/bin/env python3'))


if __name__ == '__main__':
    unittest.main()
