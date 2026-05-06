from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_release_workflow_runs_shipability_gate_before_version_bump() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    gate_index = workflow.index("scripts/release_shipability_gate.py --repo .")
    bump_index = workflow.index("python scripts/prepare_release.py apply")

    assert gate_index < bump_index


def test_release_workflow_cleans_dist_before_uploading_artifacts() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    clean_index = workflow.index("rm -rf dist build *.egg-info")
    build_index = workflow.index(".venv/bin/python -m build --wheel --sdist")
    release_index = workflow.index("gh release create")

    assert clean_index < build_index < release_index
