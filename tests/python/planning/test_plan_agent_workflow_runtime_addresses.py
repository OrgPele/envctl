from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from envctl_engine.config import load_config
from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree
from envctl_engine.planning.plan_agent.workflow_runtime_addresses import (
    RuntimeAddressPromptBuilder,
    _append_runtime_addresses_for_preset,
    _component_port,
    _dependency_address_lines,
    _runtime_addresses_prompt_section,
    _service_address_lines,
    _state_project_matches_worktree,
    _state_service_matches_worktree,
)
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord


class _StateRepositoryHarness:
    def __init__(self, state: RunState | None) -> None:
        self.state = state

    def load_latest(
        self,
        *,
        mode: str | None = None,
        strict_mode_match: bool = False,
        project_names: list[str] | None = None,
    ) -> RunState | None:
        _ = mode, strict_mode_match, project_names
        return self.state


class _RuntimeHarness:
    def __init__(self, state: RunState | None) -> None:
        self.config = load_config({"RUN_REPO_ROOT": "/tmp/repo", "RUN_SH_RUNTIME_DIR": "/tmp/runtime"})
        self.env = {}
        self.state_repository = _StateRepositoryHarness(state)


class PlanAgentWorkflowRuntimeAddressTests(unittest.TestCase):
    def test_worktree_address_lookup_retries_unfiltered_for_base_project_state(self) -> None:
        calls: list[list[str] | None] = []
        state = RunState(
            run_id="run-base",
            mode="trees",
            requirements={
                "feature-a": RequirementsResult(
                    project="feature-a",
                    redis={"enabled": True, "final": 6381},
                )
            },
        )

        class BaseProjectRepository:
            def load_latest(
                self,
                *,
                mode: str | None = None,
                strict_mode_match: bool = False,
                project_names: list[str] | None = None,
            ) -> RunState | None:
                _ = mode, strict_mode_match
                calls.append(project_names)
                return state if project_names is None else None

        runtime = SimpleNamespace(state_repository=BaseProjectRepository())
        worktree = CreatedPlanWorktree(
            name="feature-a-1",
            root=Path("/repo/trees/feature-a/1"),
            plan_file="feature-a.md",
        )

        section = _runtime_addresses_prompt_section(runtime, worktree=worktree)

        self.assertEqual(calls, [["feature-a-1"], None])
        self.assertIn("Redis (feature-a): redis://localhost:6381", section)

    def test_builder_renders_dependency_and_service_addresses_for_matching_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree_root = Path(tmpdir) / "repo" / "trees" / "feature-a-1"
            worktree_root.mkdir(parents=True)
            state = RunState(
                run_id="run-1",
                mode="trees",
                requirements={
                    "feature-a": RequirementsResult(
                        project="feature-a",
                        db={"enabled": True, "final": 54329},
                        redis={"enabled": True, "actual": 6380},
                    ),
                    "other": RequirementsResult(
                        project="other",
                        db={"enabled": True, "final": 54330},
                    ),
                },
                services={
                    "feature-a-1 backend": ServiceRecord(
                        name="feature-a-1 backend",
                        type="backend",
                        cwd=str(worktree_root / "backend"),
                        actual_port=8100,
                    ),
                    "other frontend": ServiceRecord(
                        name="other frontend",
                        type="frontend",
                        cwd="/tmp/other",
                        actual_port=3200,
                    ),
                },
            )
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="feature-a.md")

            section = RuntimeAddressPromptBuilder(_RuntimeHarness(state), worktree=worktree).prompt_section()

        self.assertIn("## Current envctl runtime addresses", section)
        self.assertIn("Postgres (feature-a): localhost:54329", section)
        self.assertIn("Redis (feature-a): redis://localhost:6380", section)
        self.assertIn("Backend (feature-a-1 backend): http://localhost:8100", section)
        self.assertNotIn("54330", section)
        self.assertNotIn("other frontend", section)

    def test_dependency_rows_are_deduplicated_by_dependency_and_port(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="trees",
            requirements={
                "feature-a": RequirementsResult(project="feature-a", redis={"enabled": True, "final": 6379}),
                "feature-b": RequirementsResult(project="feature-b", redis={"enabled": True, "actual": 6379}),
            },
        )

        self.assertEqual(_dependency_address_lines(state), ["Redis (feature-a): redis://localhost:6379"])

    def test_append_runtime_addresses_only_for_implement_task_preset(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="trees",
            requirements={
                "Main": RequirementsResult(project="Main", n8n={"enabled": True, "resources": {"primary": 5678}}),
            },
        )
        runtime = _RuntimeHarness(state)

        self.assertEqual(
            _append_runtime_addresses_for_preset(runtime, preset="review_worktree", prompt_text="Review"),
            "Review",
        )
        self.assertIn(
            "n8n (Main): http://localhost:5678",
            _append_runtime_addresses_for_preset(runtime, preset="implement_task", prompt_text="Implement"),
        )

    def test_matching_and_port_helpers_cover_stale_or_partial_state(self) -> None:
        worktree = CreatedPlanWorktree(name="feature-a-2", root=Path("/tmp/repo/trees/feature-a-2"), plan_file="")
        matching_service = ServiceRecord(
            name="backend",
            type="backend",
            cwd="/tmp/repo/trees/feature-a-2/apps/api",
            requested_port=8000,
        )
        metadata_service = ServiceRecord(
            name="Opaque API Process",
            type="backend",
            cwd="/tmp/outside-project-root",
            requested_port=8100,
            project="feature-a",
        )
        stale_service = ServiceRecord(name="feature-b backend", type="backend", cwd="", actual_port=9000)

        self.assertTrue(_state_project_matches_worktree("feature-a", worktree))
        self.assertFalse(_state_project_matches_worktree("feature-b", worktree))
        self.assertTrue(_state_service_matches_worktree(matching_service, worktree))
        self.assertTrue(_state_service_matches_worktree(metadata_service, worktree))
        self.assertFalse(_state_service_matches_worktree(stale_service, worktree))
        self.assertEqual(_component_port({"requested": "0", "resources": {"primary": "49152"}}), 49152)
        self.assertEqual(
            _service_address_lines(RunState(run_id="run-1", mode="trees", services={"api": matching_service})),
            ["Backend (backend): http://localhost:8000"],
        )

    def test_runtime_section_uses_legacy_state_loader_when_repository_is_unavailable(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="main",
            requirements={"Main": RequirementsResult(project="Main", supabase={"enabled": True, "actual": 54321})},
        )
        runtime = SimpleNamespace(
            state_repository=None,
            _try_load_existing_state=lambda *, mode, strict_mode_match: state if mode == "main" else None,
        )

        section = _runtime_addresses_prompt_section(runtime)

        self.assertIn("Supabase (Main): http://localhost:54321", section)


if __name__ == "__main__":
    unittest.main()
