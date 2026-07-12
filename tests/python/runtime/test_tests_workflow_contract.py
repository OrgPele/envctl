from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def _tests_workflow() -> str:
    return (REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")


def test_tests_workflow_uses_uv_without_third_party_setup_actions() -> None:
    workflow = _tests_workflow()

    assert "useblacksmith/stickydisk" not in workflow
    assert "astral-sh/setup-uv" not in workflow
    assert "blacksmith-" not in workflow
    assert "runs-on: ubuntu-24.04" in workflow
    assert "path: /home/runner/.cache/uv" in workflow
    assert "envctl-uv-${{ runner.os }}-${{ hashFiles('uv.lock') }}" in workflow
    assert "python -m pip install --upgrade uv" in workflow
    assert "UV_CACHE_DIR: /home/runner/.cache/uv" in workflow


def test_tests_workflow_keeps_pr_checks_split_by_signal_type() -> None:
    workflow = _tests_workflow()

    assert "name: pytest" in workflow
    assert "name: build & shipability" in workflow
    assert "name: ruff" in workflow
    assert "uv run --extra dev pytest -q" in workflow
    assert "uv run --extra dev python -m build" in workflow
    assert "uv tool run ruff check python tests scripts" in workflow


def test_tests_workflow_runs_for_dev_and_main_pull_requests() -> None:
    workflow = _tests_workflow()

    assert "pull_request:\n    branches:\n      - dev\n      - main" in workflow
