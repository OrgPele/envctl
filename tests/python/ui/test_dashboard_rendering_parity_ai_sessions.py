# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.ui.dashboard_rendering_parity_test_support import *


class DashboardRenderingAiSessionParityTests(DashboardRenderingParityTestCase):
    def test_dashboard_renders_matching_ai_session_inline_for_active_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo),
                        requested_port=9000,
                        actual_port=9004,
                        pid=1234,
                        status="running",
                    ),
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )

            buffer = io.StringIO()
            with (
                patch(
                    "envctl_engine.runtime.session_management.list_tmux_sessions",
                    return_value=[
                        {
                            "name": "omx-supportopia-main",
                            "windows": "sh",
                            "paths": str(repo),
                            "attach": "tmux attach-session -t omx-supportopia-main",
                            "kill": "tmux kill-session -t omx-supportopia-main",
                        }
                    ],
                ),
                patch(
                    "envctl_engine.ui.dashboard.rendering._dashboard_current_tmux_target",
                    return_value=("", ""),
                ),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("Frontend: http://localhost:9004", output)
            self.assertIn("AI session: tmux attach-session -t omx-supportopia-main (detached)", output)
            self.assertNotIn("Run AI:", output)
            self.assertLess(output.index("Frontend:"), output.index("AI session:"))

    def test_dashboard_renders_run_ai_row_when_launch_command_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "features_feature_a" / "1"
            provenance_dir = project_root / ".envctl-state"
            plan_path = repo / "todo" / "plans" / "features" / "feature-a.md"
            provenance_dir.mkdir(parents=True, exist_ok=True)
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan\n", encoding="utf-8")
            (provenance_dir / "worktree-provenance.json").write_text(
                '{"plan_file": "features/feature-a.md"}',
                encoding="utf-8",
            )
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={},
                metadata={
                    "project_roots": {"features_feature_a-1": str(project_root)},
                    "dashboard_configured_service_types": ["backend"],
                    "dashboard_runs_disabled": True,
                    "dashboard_banner": "envctl runs are disabled for trees; planning and action commands remain available.",
                },
            )

            buffer = io.StringIO()
            with (
                patch(
                    "envctl_engine.runtime.session_management.list_tmux_sessions",
                    return_value=[
                        {
                            "name": "envctl-codex-envctl-pr98-197bdc97",
                            "windows": "features_feature_a-1",
                            "paths": str(project_root),
                            "attach": "tmux attach-session -t envctl-codex-envctl-pr98-197bdc97",
                            "kill": "tmux kill-session -t envctl-codex-envctl-pr98-197bdc97",
                        }
                    ],
                ),
                patch(
                    "envctl_engine.ui.dashboard.rendering._dashboard_current_tmux_target",
                    return_value=("envctl-codex-envctl-pr98-197bdc97", str(project_root)),
                ),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn(
                "AI session: tmux attach-session -t envctl-codex-envctl-pr98-197bdc97 (attached)",
                output,
            )
            self.assertNotIn(
                f"○ Run AI: envctl --repo {repo} --plan features/feature-a.md "
                "--tmux --opencode --headless --new-session",
                output,
            )
            self.assertNotIn("command:", output)

    def test_dashboard_renders_omx_ai_session_matching_feature_slug_even_when_iteration_differs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project = "broken_dashboard_configured_missing_service_visibility-2"
            project_root = repo / "trees" / "broken_dashboard_configured_missing_service_visibility" / "2"
            plan_path = repo / "todo" / "plans" / "broken" / "dashboard-configured-missing-service-visibility.md"
            project_root.mkdir(parents=True, exist_ok=True)
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan\n", encoding="utf-8")
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]
            state = RunState(
                run_id="run-1",
                mode="trees",
                services={},
                metadata={
                    "project_roots": {project: str(project_root)},
                    "dashboard_configured_service_types": ["backend"],
                    "dashboard_runs_disabled": True,
                    "dashboard_banner": "envctl runs are disabled for trees; planning and action commands remain available.",
                },
            )

            buffer = io.StringIO()
            with (
                patch(
                    "envctl_engine.runtime.session_management.list_tmux_sessions",
                    return_value=[
                        {
                            "name": "omx-1-broken-dashboard-configured-missing-service-visibility-1-1777741524847-dhd0zk",
                            "windows": "zsh",
                            "paths": str(repo),
                            "attach": (
                                "tmux attach-session -t "
                                "omx-1-broken-dashboard-configured-missing-service-visibility-1-1777741524847-dhd0zk"
                            ),
                            "kill": (
                                "tmux kill-session -t "
                                "omx-1-broken-dashboard-configured-missing-service-visibility-1-1777741524847-dhd0zk"
                            ),
                        }
                    ],
                ),
                patch(
                    "envctl_engine.ui.dashboard.rendering._dashboard_current_tmux_target",
                    return_value=("", ""),
                ),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn(
                "AI session: tmux attach-session -t "
                "omx-1-broken-dashboard-configured-missing-service-visibility-1-1777741524847-dhd0zk (detached)",
                output,
            )
            self.assertNotIn("○ Run AI:", output)

    def test_dashboard_renders_envctl_plan_agent_session_by_generated_session_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "pele-monorepo"
            runtime = Path(tmpdir) / "runtime"
            project = "features_interactive_onboarding_configuration_flow-1"
            project_root = repo / "trees" / "features_interactive_onboarding_configuration_flow" / "1"
            plan_path = repo / "todo" / "plans" / "features" / "interactive-onboarding-configuration-flow.md"
            project_root.mkdir(parents=True, exist_ok=True)
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan\n", encoding="utf-8")
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]
            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    f"{project} Backend": ServiceRecord(
                        name=f"{project} Backend",
                        type="backend",
                        cwd=str(project_root / "backend"),
                        requested_port=8000,
                        actual_port=8004,
                        pid=1234,
                        status="running",
                    ),
                },
                metadata={"project_roots": {project: str(project_root)}},
            )

            buffer = io.StringIO()
            with (
                patch(
                    "envctl_engine.runtime.session_management.list_tmux_sessions",
                    return_value=[
                        {
                            "name": "envctl-pele-monorepo-trees-features_interactive_onboarding_configuration_flow-1-codex",
                            "windows": "zsh",
                            "paths": str(repo),
                            "attach": (
                                "tmux attach-session -t "
                                "envctl-pele-monorepo-trees-features_interactive_onboarding_configuration_flow-1-codex"
                            ),
                            "kill": (
                                "tmux kill-session -t "
                                "envctl-pele-monorepo-trees-features_interactive_onboarding_configuration_flow-1-codex"
                            ),
                        }
                    ],
                ),
                patch(
                    "envctl_engine.ui.dashboard.rendering._dashboard_current_tmux_target",
                    return_value=("", ""),
                ),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn(
                "AI session: tmux attach-session -t "
                "envctl-pele-monorepo-trees-features_interactive_onboarding_configuration_flow-1-codex "
                "(detached)",
                output,
            )
            self.assertNotIn("○ Run AI:", output)

    def test_dashboard_renders_worktree_ai_launcher_when_plan_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "pele-monorepo"
            runtime = Path(tmpdir) / "runtime"
            project = "features_interactive_onboarding_configuration_flow-1"
            project_root = repo / "trees" / "features_interactive_onboarding_configuration_flow" / "1"
            provenance_dir = project_root / ".envctl-state"
            provenance_dir.mkdir(parents=True, exist_ok=True)
            (project_root / "MAIN_TASK.md").write_text("# Task\n", encoding="utf-8")
            (provenance_dir / "worktree-provenance.json").write_text(
                json.dumps({"plan_file": "features/interactive-onboarding-configuration-flow.md"}),
                encoding="utf-8",
            )
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]
            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    f"{project} Backend": ServiceRecord(
                        name=f"{project} Backend",
                        type="backend",
                        cwd=str(project_root / "backend"),
                        requested_port=8000,
                        actual_port=8004,
                        pid=1234,
                        status="running",
                    ),
                },
                metadata={"project_roots": {project: str(project_root)}},
            )

            buffer = io.StringIO()
            with (
                patch("envctl_engine.runtime.session_management.list_tmux_sessions", return_value=[]),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn(f"○ Run AI: envctl --repo {project_root} codex-tmux", output)
            self.assertNotIn("AI session:", output)

    def test_dashboard_renders_run_ai_row_only_when_no_matching_session_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "features_feature_a" / "1"
            provenance_dir = project_root / ".envctl-state"
            plan_path = repo / "todo" / "plans" / "features" / "feature-a.md"
            provenance_dir.mkdir(parents=True, exist_ok=True)
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan\n", encoding="utf-8")
            (provenance_dir / "worktree-provenance.json").write_text(
                '{"plan_file": "features/feature-a.md"}',
                encoding="utf-8",
            )
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={},
                metadata={
                    "project_roots": {"features_feature_a-1": str(project_root)},
                    "dashboard_configured_service_types": ["backend"],
                    "dashboard_runs_disabled": True,
                    "dashboard_banner": "envctl runs are disabled for trees; planning and action commands remain available.",
                },
            )

            buffer = io.StringIO()
            with (
                patch("envctl_engine.runtime.session_management.list_tmux_sessions", return_value=[]),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn(
                f"○ Run AI: envctl --repo {repo} --plan features/feature-a.md "
                "--tmux --opencode --headless --new-session",
                output,
            )
            self.assertNotIn("AI session:", output)

    def test_dashboard_renders_run_ai_row_for_running_worktree_without_ai_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "features_feature_a" / "1"
            provenance_dir = project_root / ".envctl-state"
            plan_path = repo / "todo" / "plans" / "features" / "feature-a.md"
            provenance_dir.mkdir(parents=True, exist_ok=True)
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan\n", encoding="utf-8")
            (provenance_dir / "worktree-provenance.json").write_text(
                '{"plan_file": "features/feature-a.md"}',
                encoding="utf-8",
            )
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine._dashboard_reconcile_for_snapshot = lambda _state: []  # type: ignore[method-assign]

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "features_feature_a-1 Backend": ServiceRecord(
                        name="features_feature_a-1 Backend",
                        type="backend",
                        cwd=str(project_root),
                        requested_port=8000,
                        actual_port=8004,
                        pid=1234,
                        status="running",
                    ),
                    "features_feature_a-1 Frontend": ServiceRecord(
                        name="features_feature_a-1 Frontend",
                        type="frontend",
                        cwd=str(project_root),
                        requested_port=9000,
                        actual_port=9004,
                        pid=1235,
                        status="running",
                    ),
                },
                metadata={"project_roots": {"features_feature_a-1": str(project_root)}},
            )

            buffer = io.StringIO()
            with (
                patch("envctl_engine.runtime.session_management.list_tmux_sessions", return_value=[]),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("Backend: http://localhost:8004", output)
            self.assertIn("Frontend: http://localhost:9004", output)
            self.assertIn(
                f"○ Run AI: envctl --repo {repo} --plan features/feature-a.md "
                "--tmux --opencode --headless --new-session",
                output,
            )
            self.assertNotIn("AI session:", output)

    def test_dashboard_prefers_attach_when_window_matches_but_session_path_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "features_feature_a" / "1"
            provenance_dir = project_root / ".envctl-state"
            plan_path = repo / "todo" / "plans" / "features" / "feature-a.md"
            provenance_dir.mkdir(parents=True, exist_ok=True)
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan\n", encoding="utf-8")
            (provenance_dir / "worktree-provenance.json").write_text(
                '{"plan_file": "features/feature-a.md"}',
                encoding="utf-8",
            )
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={},
                metadata={
                    "project_roots": {"features_feature_a-1": str(project_root)},
                    "dashboard_configured_service_types": ["backend"],
                    "dashboard_runs_disabled": True,
                    "dashboard_banner": "envctl runs are disabled for trees; planning and action commands remain available.",
                },
            )

            buffer = io.StringIO()
            with (
                patch(
                    "envctl_engine.runtime.session_management.list_tmux_sessions",
                    return_value=[
                        {
                            "name": "envctl-codex-envctl-pr98-197bdc97",
                            "windows": "features_feature_a-1",
                            "paths": str(repo / "somewhere_else"),
                            "attach": "tmux attach-session -t envctl-codex-envctl-pr98-197bdc97",
                            "kill": "tmux kill-session -t envctl-codex-envctl-pr98-197bdc97",
                        }
                    ],
                ),
                patch(
                    "envctl_engine.ui.dashboard.rendering._dashboard_current_tmux_target",
                    return_value=("", ""),
                ),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn(
                "AI session: tmux attach-session -t envctl-codex-envctl-pr98-197bdc97 (detached)",
                output,
            )
            self.assertNotIn(
                f"○ Run AI: envctl --repo {repo} --plan features/feature-a.md "
                "--tmux --opencode --headless --new-session",
                output,
            )

    def test_dashboard_renders_run_ai_plan_command_when_selector_does_not_resolve_for_quoted_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_name = "feature with spaces;and-symbols"
            project_root = repo / "trees" / project_name / "1"
            project_root.mkdir(parents=True, exist_ok=True)
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={},
                metadata={
                    "project_roots": {project_name: str(project_root)},
                    "dashboard_configured_service_types": ["backend"],
                    "dashboard_runs_disabled": True,
                    "dashboard_banner": "envctl runs are disabled for trees; planning and action commands remain available.",
                },
            )

            buffer = io.StringIO()
            with (
                patch("envctl_engine.runtime.session_management.list_tmux_sessions", return_value=[]),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn(
                f"○ Run AI: envctl --repo {repo} --plan 'feature with spaces;and-symbols.md' "
                "--tmux --opencode --headless --new-session",
                output,
            )
            self.assertNotIn("codex-tmux", output)
            self.assertNotIn("AI session:", output)

    def test_dashboard_renders_run_ai_plan_command_when_no_plan_selector_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "feature_without_plan" / "1"
            project_root.mkdir(parents=True, exist_ok=True)
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={},
                metadata={
                    "project_roots": {"feature_without_plan-1": str(project_root)},
                    "dashboard_configured_service_types": ["backend"],
                    "dashboard_runs_disabled": True,
                    "dashboard_banner": "envctl runs are disabled for trees; planning and action commands remain available.",
                },
            )

            buffer = io.StringIO()
            with (
                patch("envctl_engine.runtime.session_management.list_tmux_sessions", return_value=[]),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn(
                f"○ Run AI: envctl --repo {repo} --plan feature_without_plan.md "
                "--tmux --opencode --headless --new-session",
                output,
            )
            self.assertNotIn("codex-tmux", output)
            self.assertNotIn("AI session:", output)

    def test_dashboard_infers_plan_from_parent_repo_for_git_worktree_without_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "refactoring_supportopia_to_pele_complete_repo_rename" / "1"
            plan_path = repo / "todo" / "plans" / "refactoring" / "supportopia-to-pele-complete-repo-rename.md"
            project_root.mkdir(parents=True, exist_ok=True)
            (project_root / "todo").mkdir(parents=True, exist_ok=True)
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan\n", encoding="utf-8")
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "bin").mkdir(parents=True, exist_ok=True)
            (repo / "bin" / "envctl").write_text("#!/bin/sh\n", encoding="utf-8")
            (project_root / ".git").write_text("gitdir: ignored\n", encoding="utf-8")
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={},
                metadata={
                    "project_roots": {"refactoring_supportopia_to_pele_complete_repo_rename-1": str(project_root)},
                    "dashboard_configured_service_types": ["backend"],
                    "dashboard_runs_disabled": True,
                    "dashboard_banner": "envctl runs are disabled for trees; planning and action commands remain available.",
                },
            )

            buffer = io.StringIO()
            with (
                patch("envctl_engine.runtime.session_management.list_tmux_sessions", return_value=[]),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn(
                f"○ Run AI: envctl --repo {repo} "
                "--plan refactoring/supportopia-to-pele-complete-repo-rename.md "
                "--tmux --opencode --headless --new-session",
                output,
            )
            self.assertNotIn("codex-tmux", output)

    def test_dashboard_renders_run_ai_row_for_worktree_using_created_from_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "test_headless_tmux_headless_check" / "1"
            provenance_dir = project_root / ".envctl-state"
            plan_path = repo / "todo" / "plans" / "test-headless" / "tmux-headless-check.md"
            provenance_dir.mkdir(parents=True, exist_ok=True)
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan\n", encoding="utf-8")
            (provenance_dir / "worktree-provenance.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "created_from_repo": str(repo),
                        "plan_file": "test-headless/tmux-headless-check.md",
                    }
                ),
                encoding="utf-8",
            )
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={},
                metadata={
                    "project_roots": {"test_headless_tmux_headless_check-1": str(project_root)},
                    "dashboard_configured_service_types": ["backend"],
                    "dashboard_runs_disabled": True,
                    "dashboard_banner": "envctl runs are disabled for trees; planning and action commands remain available.",
                },
            )

            buffer = io.StringIO()
            with (
                patch("envctl_engine.runtime.session_management.list_tmux_sessions", return_value=[]),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn(
                f"○ Run AI: envctl --repo {repo} --plan test-headless/tmux-headless-check.md "
                "--tmux --opencode --headless --new-session",
                output,
            )
            self.assertNotIn(" --project", output)

    def test_dashboard_renders_run_ai_row_when_active_plan_and_archived_copy_both_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "features_task"
            active_plan = repo / "todo" / "plans" / "features" / "task.md"
            archived_plan = repo / "todo" / "done" / "features" / "task.md"
            project_root.mkdir(parents=True, exist_ok=True)
            active_plan.parent.mkdir(parents=True, exist_ok=True)
            archived_plan.parent.mkdir(parents=True, exist_ok=True)
            active_plan.write_text("# active\n", encoding="utf-8")
            archived_plan.write_text("# archived\n", encoding="utf-8")
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={},
                metadata={
                    "project_roots": {"features_task": str(project_root)},
                    "dashboard_configured_service_types": ["backend"],
                    "dashboard_runs_disabled": True,
                    "dashboard_banner": "envctl runs are disabled for trees; planning and action commands remain available.",
                },
            )

            buffer = io.StringIO()
            with (
                patch("envctl_engine.runtime.session_management.list_tmux_sessions", return_value=[]),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn(
                f"○ Run AI: envctl --repo {repo} --plan features/task.md "
                "--tmux --opencode --headless --new-session",
                output,
            )
            self.assertNotIn(" --project", output)

    def test_dashboard_does_not_render_workspace_rows_for_running_services(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "feature-a-1 Frontend": ServiceRecord(
                        name="feature-a-1 Frontend",
                        type="frontend",
                        cwd=str(repo),
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
                metadata={"project_roots": {"feature-a-1": str(repo)}},
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertNotIn("workspace backend:", output)
            self.assertNotIn("workspace frontend:", output)
