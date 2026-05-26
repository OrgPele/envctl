from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    area: str
    feature: str
    user_visible: bool
    shell_source_of_truth: tuple[str, ...]
    python_source_of_truth: tuple[str, ...]
    evidence_tests: tuple[str, ...]
    parity_status: str
    notes: str
    current_behavior: str = ""
    missing_python_behavior: str = ""
    python_owner_module: str = ""
    proposed_tests: tuple[str, ...] = ()
    severity: str = ""
    rollout_risk: str = ""
    wave: str = ""
