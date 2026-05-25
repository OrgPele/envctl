from __future__ import annotations

from envctl_engine.runtime.command_models import RouteError


def parse_projects(raw: str) -> list[str]:
    values = [part.strip() for part in raw.split(",")]
    return [value for value in values if value]


def boolean_flag_name(token: str) -> str:
    mapping = {
        "--all": "all",
        "--untested": "untested",
        "--failed": "failed",
        "--load-state": "load_state",
        "--command-resume": "load_state",
        "--skip-startup": "skip_startup",
        "--command-only": "skip_startup",
        "--logs-follow": "logs_follow",
        "--logs-no-color": "logs_no_color",
        "--dashboard-interactive": "dashboard_interactive",
        "--interactive": "interactive",
        "--headless": "batch",
        "--batch": "batch",
        "--json": "json",
        "--stdin-json": "stdin_json",
        "--non-interactive": "batch",
        "--no-interactive": "batch",
        "-b": "batch",
        "-f": "force",
        "--dry-run": "dry_run",
        "--run": "run",
        "--yes": "yes",
        "--force": "force",
        "--deps-parallel": "requirements_parallel",
        "--parallel-deps": "requirements_parallel",
        "--requirements-parallel": "requirements_parallel",
        "--parallel-trees": "parallel_trees",
        "--test-parallel": "test_parallel",
        "--service-parallel": "service_parallel",
        "--service-prep-parallel": "service_prep_parallel",
        "--refresh-cache": "refresh_cache",
        "--fast": "fast",
        "--fast-startup": "fast",
        "--docker": "docker",
        "--stop-docker-on-exit": "docker_temp",
        "--docker-temp": "docker_temp",
        "--temp-docker": "docker_temp",
        "--keep-plan": "keep_plan",
        "--clear-port-state": "clear_port_state",
        "--clear-ports": "clear_port_state",
        "--clear-port-cache": "clear_port_state",
        "--debug-trace": "debug_trace",
        "--debug-trace-no-xtrace": "debug_trace_no_xtrace",
        "--debug-trace-no-stdio": "debug_trace_no_stdio",
        "--debug-trace-no-interactive": "debug_trace_no_interactive",
        "--main-services-local": "main_services_local",
        "--main-local": "main_services_local",
        "--main-services-remote": "main_services_remote",
        "--main-remote": "main_services_remote",
        "--key-debug": "key_debug",
        "--debug-ui": "debug_ui",
        "--debug-ui-deep": "debug_ui_deep",
        "--debug-ui-include-doctor": "debug_ui_include_doctor",
        "--reuse-existing-worktree": "setup_worktree_existing",
        "--setup-worktree-existing": "setup_worktree_existing",
        "--recreate-existing-worktree": "setup_worktree_recreate",
        "--setup-worktree-recreate": "setup_worktree_recreate",
        "--seed-requirements-from-base": "seed_requirements_from_base",
        "--copy-db-storage": "seed_requirements_from_base",
        "--no-resume": "no_resume",
        "--no-auto-resume": "no_resume",
        "--cmux": "cmux",
        "--tmux": "tmux",
        "--omx": "omx",
        "--ultragoal": "ultragoal",
        "--ralph": "ralph",
        "--team": "team",
        "--goal": "goal",
        "--codex-goal": "codex_goal",
        "--no-goal": "no_goal",
        "--no-codex-goal": "no_codex_goal",
        "--codex": "codex",
        "--opencode": "opencode",
        "--ulw": "ulw",
        "--no-ulw-loop": "no_ulw_loop",
        "--new-session": "new_session",
        "--with-codex-skills": "with_codex_skills",
        "--confirm": "confirm",
        "--strict": "strict",
        "--update-password": "update_password",
        "--update-metadata": "update_metadata",
    }
    return mapping[token]


def store_value_flag(flags: dict[str, object], token: str, value: str) -> None:
    mapping = {
        "--service": "services",
        "--set": "set_values",
        "--pr-base": "pr_base",
        "--review-base": "review_base",
        "-m": "commit_message",
        "--commit-message": "commit_message",
        "--commit-message-file": "commit_message_file",
        "--analyze-mode": "analyze_mode",
        "--review-mode": "analyze_mode",
        "--logs-tail": "logs_tail",
        "--logs-duration": "logs_duration",
        "--parallel-trees-max": "parallel_trees_max",
        "--debug-trace-log": "debug_trace_log",
        "--include-existing-worktrees": "include_existing_worktrees",
        "--setup-include-worktrees": "include_existing_worktrees",
        "--log-profile": "log_profile",
        "--log-level": "log_level",
        "--backend-log-profile": "backend_log_profile",
        "--backend-log-level": "backend_log_level",
        "--frontend-log-profile": "frontend_log_profile",
        "--frontend-log-level": "frontend_log_level",
        "--frontend-test-runner": "frontend_test_runner",
        "--test-parallel-max": "test_parallel_max",
        "--cli": "cli",
        "--preset": "preset",
        "--session-id": "session_id",
        "--run-id": "run_id",
        "--scope-id": "scope_id",
        "--output-dir": "output_dir",
        "--timeout": "timeout",
        "--debug-capture": "debug_capture",
        "--debug-auto-pack": "debug_auto_pack",
        "--mode": "mode_override",
        "--email": "email",
        "--password": "password",
        "--metadata-json": "metadata_json",
        "--app-metadata-json": "app_metadata_json",
        "--locale": "locale",
        "--seed": "seed",
    }
    key = mapping[token]
    if key == "mode_override":
        normalized = str(value).strip().lower()
        if normalized not in {"main", "trees"}:
            raise RouteError("--mode must be main or trees")
        flags[key] = normalized
        return
    if key in {"services", "include_existing_worktrees", "set_values", "seed"}:
        existing = flags.get(key)
        values = [value] if key == "set_values" else parse_projects(value)
        if isinstance(existing, list):
            existing.extend(values)
            return
        flags[key] = values
        return
    flags[key] = value


def store_pair_flag(flags: dict[str, object], token: str, first: str, second: str) -> None:
    key = "setup_worktrees" if token == "--setup-worktrees" else "setup_worktree"
    entry = {"feature": first, "count": second} if key == "setup_worktrees" else {"feature": first, "iteration": second}
    existing = flags.get(key)
    if isinstance(existing, list):
        existing.append(entry)
        return
    flags[key] = [entry]


def store_inline_pair_flag(flags: dict[str, object], token: str, raw: str) -> None:
    parts = [part.strip() for part in raw.split(",", 1)]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise RouteError(f"Missing value for {token}")
    store_pair_flag(flags, token, parts[0], parts[1])
