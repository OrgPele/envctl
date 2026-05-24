from __future__ import annotations

from pathlib import Path
from typing import Any

from envctl_engine.runtime_feature_contracts import (
    build_python_runtime_gap_report as build_python_runtime_gap_report,
    build_runtime_feature_matrix_from_definitions,
    default_timestamp as default_timestamp,
    render_python_runtime_gap_closure_plan as render_python_runtime_gap_closure_plan,
    validate_python_runtime_gap_report_payload as validate_python_runtime_gap_report_payload,
    validate_runtime_feature_matrix_payload as validate_runtime_feature_matrix_payload,
)
from envctl_engine.runtime_feature_definitions import (
    COMMAND_DEFINITIONS,
    EXTRA_FEATURES,
    FeatureDefinition as FeatureDefinition,
)


def build_runtime_feature_matrix(*, repo_root: Path, generated_at: str) -> dict[str, Any]:
    return build_runtime_feature_matrix_from_definitions(
        repo_root=repo_root,
        generated_at=generated_at,
        command_definitions=COMMAND_DEFINITIONS,
        extra_features=EXTRA_FEATURES,
    )
