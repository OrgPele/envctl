from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


class StatusGlyphContractTests(unittest.TestCase):
    def test_envctl_owned_ui_status_modules_do_not_emit_legacy_prefix_glyphs(self) -> None:
        targets = [
            "python/envctl_engine/ui/spinner_service.py",
            "python/envctl_engine/startup/progress_shared.py",
            "python/envctl_engine/ui/dashboard/rendering.py",
            "python/envctl_engine/state/action_orchestrator.py",
            "python/envctl_engine/runtime/lifecycle_cleanup_orchestrator.py",
        ]
        banned_patterns = [
            re.compile(r'description=f"[+!] \{line\}"'),
            re.compile(r'return\s+["\']!["\']'),
            re.compile(r'icon\s*=\s*["\']!["\']'),
            re.compile(r'print\(f?["\']\s*! '),
            re.compile(r'write\(f?["\']! '),
        ]

        violations: list[str] = []
        for relative in targets:
            path = REPO_ROOT / relative
            text = path.read_text(encoding="utf-8")
            for line_number, line in enumerate(text.splitlines(), start=1):
                if any(pattern.search(line) for pattern in banned_patterns):
                    violations.append(f"{relative}:{line_number}: {line.strip()}")

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
