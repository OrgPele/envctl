from __future__ import annotations

from typing import Sequence

from envctl_engine.actions.actions_test_models import (
    SuggestionConfidence,
    SuggestionTarget,
    TestCommandSpec,
    TestCommandSuggestion,
)


def command_text(command: Sequence[str]) -> str:
    return " ".join(str(part) for part in command)


def test_command_suggestion(
    spec: TestCommandSpec,
    *,
    target: SuggestionTarget,
    is_default: bool,
) -> TestCommandSuggestion:
    labels = {
        "backend_pytest": "Backend pytest",
        "root_pytest": "Root pytest",
        "root_unittest": "Root unittest discover",
        "frontend_package_test": "Frontend package test",
        "package_test": "Root package test",
        "configured": "Configured test command",
    }
    confidence_by_source: dict[str, SuggestionConfidence] = {
        "backend_pytest": "high",
        "root_pytest": "high",
        "root_unittest": "medium",
        "frontend_package_test": "high",
        "package_test": "medium",
        "configured": "high",
    }
    reasons = {
        "backend_pytest": "Detected backend pytest from backend/tests plus backend Python metadata.",
        "root_pytest": "Detected root pytest from tests/ plus pytest configuration.",
        "root_unittest": "Detected root tests/ without pytest metadata; unittest discover is the safe fallback.",
        "frontend_package_test": "Detected frontend package test script from frontend/package.json.",
        "package_test": "Detected root package test script from package.json.",
        "configured": "Configured test command.",
    }
    return TestCommandSuggestion(
        command_text=command_text(spec.command),
        command=list(spec.command),
        cwd=spec.cwd,
        source=spec.source,
        label=labels.get(spec.source, "Test command"),
        confidence=confidence_by_source.get(spec.source, "medium"),
        reason=reasons.get(spec.source, "Detected from local project files."),
        target=target,
        is_default=is_default,
    )
