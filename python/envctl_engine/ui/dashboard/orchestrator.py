from __future__ import annotations

import re
import shlex
from typing import Any, cast

from envctl_engine.runtime.command_router import Route, parse_route
from envctl_engine.state.models import RunState
from envctl_engine.ui.command_aliases import normalize_interactive_command
from envctl_engine.ui.debug_anomaly_rules import detect_dispatch_anomaly
from envctl_engine.ui.dashboard_loop_support import run_legacy_dashboard_loop


class DashboardOrchestrator:
    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    def execute(self, route: Route) -> int:
        rt: Any = self.runtime
        state = rt._try_load_existing_state(  # type: ignore[attr-defined]
            mode=route.mode,
            strict_mode_match=rt._state_lookup_strict_mode_match(route),  # type: ignore[attr-defined]
        )
        if state is None:
            rt._emit("dashboard.snapshot.source", reason="reload-failed", mode=route.mode)  # type: ignore[attr-defined]
            print("No active run state found.")
            return 0
        rt._emit("dashboard.snapshot.source", reason="fresh-load", mode=state.mode, run_id=state.run_id)  # type: ignore[attr-defined]
        if rt.config.runtime_truth_mode == "strict" and rt._state_has_synthetic_services(state):  # type: ignore[attr-defined]
            rt._emit(  # type: ignore[attr-defined]
                "synthetic.execution.blocked",
                command="dashboard",
                reason_code="synthetic_state_detected",
            )
            rt._emit(  # type: ignore[attr-defined]
                "cutover.gate.fail_reason",
                gate="command_parity",
                reason="synthetic_state_detected",
                scope="dashboard",
            )
            print("Dashboard blocked: synthetic placeholder defaults detected.")
            return 1
        if rt._should_enter_dashboard_interactive(route):  # type: ignore[attr-defined]
            interactive_runner = getattr(rt, "_run_interactive_dashboard_loop", None)
            if callable(interactive_runner):
                return cast(int, interactive_runner(state))
            return self.run_interactive_dashboard_loop(state, rt)
        if bool(route.flags.get("interactive")) or bool(route.flags.get("dashboard_interactive")):
            print("Interactive dashboard requires a TTY; showing snapshot.")
        rt._print_dashboard_snapshot(state)  # type: ignore[attr-defined]
        return 0

    def run_interactive_dashboard_loop(self, state: RunState, rt: object) -> int:
        runtime_any = cast(Any, rt)
        return run_legacy_dashboard_loop(
            state=state,
            runtime=runtime_any,
            fallback_handler=self._run_interactive_command,
            sanitize=self._sanitize_interactive_input,
        )

    def _run_interactive_command(self, raw: str, state: RunState, rt: object) -> tuple[bool, RunState]:
        runtime_any = cast(Any, rt)
        """Process a single interactive command."""
        raw = self._sanitize_interactive_input(raw)
        if not raw:
            return True, state

        command_tokens = self._parse_interactive_command(raw)
        if command_tokens is None:
            return True, state
        if not command_tokens:
            return True, state

        command = command_tokens[0]
        if command in {"q", "quit", "exit"}:
            return False, state
        if command in {"help", "?"}:
            return True, state

        normalized = normalize_interactive_command(command)
        command_tokens[0] = normalized

        try:
            route = parse_route(command_tokens, env={**runtime_any.config.raw, **runtime_any.env})
        except Exception as exc:
            runtime_any._emit(
                "ui.command.parse.failed",
                component="dashboard_orchestrator",
                error=str(exc),
                raw=raw,
            )
            anomaly = detect_dispatch_anomaly(parse_failed=True, raw=raw, sanitized=raw)
            if anomaly is not None:
                runtime_any._emit(anomaly["event"], component="dashboard_orchestrator", **anomaly)
            print(f"Invalid command: {exc}")
            return True, state

        if not self._tokens_set_mode(command_tokens):
            route = Route(
                command=route.command,
                mode=state.mode,
                raw_args=route.raw_args,
                passthrough_args=route.passthrough_args,
                projects=route.projects,
                flags=route.flags,
            )
        if route.command != "blast-all":
            route.flags = {**route.flags, "batch": True, "interactive_command": True}

        route = self._apply_interactive_target_selection(route, state, rt)
        if route is None:
            return True, state

        if route.command == "restart":
            route = self._apply_restart_selection(route, state, rt)
            if route is None:
                return True, state

        if route.command == "dashboard":
            runtime_any._print_dashboard_snapshot(state)
            return True, state

        code = runtime_any.dispatch(route)
        runtime_any._emit(
            "ui.command.dispatch.result",
            component="dashboard_orchestrator",
            command=route.command,
            code=code,
        )
        if code != 0 and route.command not in {"test", "pr", "commit", "analyze", "migrate"}:
            print(f"Command failed (exit {code}).")

        if route.command in {"stop-all", "blast-all"}:
            return False, state

        refreshed = runtime_any._try_load_existing_state(mode=state.mode, strict_mode_match=True)
        if refreshed is None:
            return False, state
        return True, refreshed

    def _apply_interactive_target_selection(self, route: Route, state: RunState, rt: object) -> Route | None:
        if route.command == "restart":
            return route
        if route.command not in self._dashboard_owned_target_selection_commands():
            return route

        if route.command in self._dashboard_owned_project_selection_commands():
            return self._apply_project_target_selection(route, state, rt)

        runtime_any = cast(Any, rt)
        if self._route_has_explicit_target(route, runtime_any):
            return route

        services = sorted(state.services.keys())
        projects = self._project_names_from_state(state, runtime_any)
        selection = runtime_any._select_grouped_targets(
            prompt=self._interactive_target_prompt(route.command),
            projects=projects,
            services=services,
            allow_all=True,
            multi=True,
        )
        if selection.cancelled:
            print(self._no_target_selected_message(route.command))
            return None
        if selection.all_selected:
            scoped_projects = [str(getattr(project, "name", "")).strip() for project in projects]
            scoped_projects = [project for project in scoped_projects if project]
            if scoped_projects:
                route.projects = scoped_projects
                route.flags = {key: value for key, value in route.flags.items() if key != "all"}
                runtime_any._emit(
                    "dashboard.target_scope.defaulted",
                    command=route.command,
                    mode=state.mode,
                    scope="run_state_all_selection",
                    project_count=len(scoped_projects),
                    projects=scoped_projects,
                )
                return route
            route.flags = {**route.flags, "all": True}
            return route
        if route.command == "test" and selection.service_names:
            route.flags = {**route.flags, "services": list(selection.service_names)}
            projects_for_services = runtime_any._projects_for_services(selection.service_names)
            if projects_for_services:
                route.projects = list(projects_for_services)
            selected_types = self._service_types_from_service_names(selection.service_names)
            if selected_types == {"backend"}:
                route.flags = {**route.flags, "backend": True, "frontend": False}
            elif selected_types == {"frontend"}:
                route.flags = {**route.flags, "backend": False, "frontend": True}
            return route
        if selection.project_names:
            route.projects = list(selection.project_names)
            return route
        if selection.service_names:
            route.flags = {**route.flags, "services": list(selection.service_names)}
            projects_for_services = runtime_any._projects_for_services(selection.service_names)
            if projects_for_services:
                route.projects = list(projects_for_services)
            return route
        print(self._no_target_selected_message(route.command))
        return None

    @staticmethod
    def _dashboard_owned_target_selection_commands() -> set[str]:
        # Commands that already have downstream interactive selectors should not
        # be pre-selected here; otherwise the dashboard changes their contract.
        return {
            "test",
            "pr",
            "commit",
            "analyze",
            "migrate",
            "blast-worktree",
        }

    @staticmethod
    def _dashboard_owned_project_selection_commands() -> set[str]:
        return {"pr", "commit", "analyze", "migrate", "blast-worktree"}

    def _apply_project_target_selection(self, route: Route, state: RunState, rt: object) -> Route | None:
        runtime_any = cast(Any, rt)
        if self._route_has_explicit_target(route, runtime_any):
            return route

        projects = self._project_names_from_state(state, runtime_any)
        selection = runtime_any._select_project_targets(
            prompt=self._interactive_target_prompt(route.command),
            projects=projects,
            allow_all=True,
            allow_untested=False,
            multi=True,
        )
        if selection.cancelled:
            print(self._no_target_selected_message(route.command))
            return None
        if selection.all_selected:
            scoped_projects = [str(getattr(project, "name", "")).strip() for project in projects]
            scoped_projects = [project for project in scoped_projects if project]
            if scoped_projects:
                route.projects = scoped_projects
                route.flags = {key: value for key, value in route.flags.items() if key != "all"}
                runtime_any._emit(
                    "dashboard.target_scope.defaulted",
                    command=route.command,
                    mode=state.mode,
                    scope="run_state_all_selection",
                    project_count=len(scoped_projects),
                    projects=scoped_projects,
                )
                return route
            route.flags = {**route.flags, "all": True}
            return route
        if selection.project_names:
            route.projects = list(selection.project_names)
            return route
        print(self._no_target_selected_message(route.command))
        return None

    @staticmethod
    def _interactive_target_prompt(command: str) -> str:
        label_map = {
            "stop": "Stop services",
            "test": "Run tests for",
            "logs": "Tail logs for",
            "clear-logs": "Clear logs for",
            "errors": "Errors for",
            "pr": "Create PR for",
            "commit": "Commit changes for",
            "analyze": "Analyze changes for",
            "migrate": "Run migrations for",
            "blast-worktree": "Blast and delete worktree for",
        }
        return label_map.get(command, f"Select {command} target")

    @staticmethod
    def _no_target_selected_message(command: str) -> str:
        label_map = {
            "logs": "log",
            "clear-logs": "log",
            "pr": "PR",
            "analyze": "analysis",
            "migrate": "migration",
            "blast-worktree": "worktree",
        }
        label = label_map.get(str(command).strip().lower(), str(command).strip().lower())
        return f"No {label} target selected."

    def _apply_restart_selection(self, route: Route, state: RunState, rt: object) -> Route | None:
        runtime_any = cast(Any, rt)
        if self._route_has_explicit_target(route, runtime_any):
            if bool(route.flags.get("all")):
                route.flags = {**route.flags, "restart_include_requirements": True}
            else:
                route.flags = {**route.flags, "restart_include_requirements": False}
            return route
        services = sorted(state.services.keys())
        projects = self._project_names_from_state(state, runtime_any)
        selection = runtime_any._select_grouped_targets(
            prompt="Restart",
            projects=projects,
            services=services,
            allow_all=True,
            multi=True,
        )
        if selection.cancelled:
            print("No restart target selected.")
            return None
        if selection.all_selected:
            scoped_projects = [str(getattr(project, "name", "")).strip() for project in projects]
            scoped_projects = [project for project in scoped_projects if project]
            if scoped_projects:
                route.projects = scoped_projects
                route.flags = {
                    **{key: value for key, value in route.flags.items() if key != "all"},
                    "restart_include_requirements": True,
                }
                runtime_any._emit(
                    "dashboard.target_scope.defaulted",
                    command="restart",
                    mode=state.mode,
                    scope="run_state_all_selection",
                    project_count=len(scoped_projects),
                    projects=scoped_projects,
                )
                return route
            route.flags = {
                **route.flags,
                "all": True,
                "restart_include_requirements": True,
            }
            return route
        if selection.project_names:
            route.projects = list(selection.project_names)
            route.flags = {**route.flags, "restart_include_requirements": False}
            return route
        if selection.service_names:
            projects = runtime_any._projects_for_services(selection.service_names)
            if projects:
                route.projects = list(projects)
            restart_service_types = self._restart_service_types_from_service_names(selection.service_names)
            route.flags = {
                **route.flags,
                "services": list(selection.service_names),
                "restart_service_types": restart_service_types,
                "restart_include_requirements": False,
            }
            return route
        print("No restart target selected.")
        return None

    def _default_interactive_targets(self, route: Route, state: RunState, rt: object) -> Route:
        _ = state, rt
        return route

    @staticmethod
    def _route_has_explicit_target(route: Route, runtime: object) -> bool:
        runtime_any = cast(Any, runtime)
        if bool(route.flags.get("all")):
            return True
        if route.projects:
            return True
        services = route.flags.get("services")
        if isinstance(services, list) and any(str(item).strip() for item in services):
            return True
        selectors_from_passthrough = getattr(runtime_any, "_selectors_from_passthrough", None)
        if callable(selectors_from_passthrough):
            selectors = selectors_from_passthrough(route.passthrough_args)
            if isinstance(selectors, set) and selectors:
                return True
        return False

    @staticmethod
    def _restart_service_types_from_service_names(service_names: list[str]) -> list[str]:
        types: list[str] = []
        seen: set[str] = set()
        for name in service_names:
            normalized = str(name).strip().lower()
            service_type = ""
            if normalized.endswith(" backend"):
                service_type = "backend"
            elif normalized.endswith(" frontend"):
                service_type = "frontend"
            if service_type and service_type not in seen:
                seen.add(service_type)
                types.append(service_type)
        return types

    @staticmethod
    def _service_types_from_service_names(service_names: list[str]) -> set[str]:
        types: set[str] = set()
        for name in service_names:
            normalized = str(name).strip().lower()
            if normalized.endswith(" backend") or normalized == "backend":
                types.add("backend")
            elif normalized.endswith(" frontend") or normalized == "frontend":
                types.add("frontend")
        return types

    @staticmethod
    def _project_names_from_state(state: RunState, rt: object) -> list[object]:
        runtime_any = cast(Any, rt)
        names: list[str] = []
        seen: set[str] = set()
        for name in state.services:
            project = runtime_any._project_name_from_service(name)
            if not project:
                continue
            lowered = project.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            names.append(project)
        return [SimpleProject(name) for name in names]

    @staticmethod
    def _sanitize_interactive_input(raw: str) -> str:
        """Sanitize interactive input by removing escape sequences."""
        if not isinstance(raw, str) or not raw:
            return ""
        cleaned = re.sub(r"\x1bO[ -~]", "", raw)
        cleaned = re.sub(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", cleaned)
        cleaned = re.sub(r"(?:(?<=^)|(?<=\s))\[(?:\d{1,3}(?:;\d{1,3})*)?[ABCD~]", " ", cleaned)
        cleaned = re.sub(r"(?:(?<=^)|(?<=\s))O[A-D](?=$|[a-z]|\s)", " ", cleaned)
        cleaned = re.sub(r"(?:(?<=^)|(?<=\s))\[(?=[a-z])", "", cleaned)
        cleaned = cleaned.replace("\x1b", "")
        cleaned = cleaned.replace("\r", " ").replace("\n", " ")
        cleaned = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = cleaned.strip()
        if cleaned:
            return cleaned
        return DashboardOrchestrator._recover_single_letter_command_from_escape_fragment(raw)

    @staticmethod
    def _recover_single_letter_command_from_escape_fragment(raw: str) -> str:
        """Recover single-letter commands from escape sequences."""
        if not isinstance(raw, str):
            return ""
        stripped = raw.strip()
        if not stripped:
            return ""
        allowed = {"s", "r", "t", "p", "c", "a", "m", "l", "h", "e", "d", "q"}

        ss3_match = re.fullmatch(r"\x1bO([A-Za-z])", stripped)
        if ss3_match:
            candidate = ss3_match.group(1).lower()
            return candidate if candidate in allowed else ""

        csi_modifier_match = re.fullmatch(r"\x1b\[[0-9;?]+([A-Za-z])", stripped)
        if csi_modifier_match:
            candidate = csi_modifier_match.group(1).lower()
            return candidate if candidate in allowed else ""
        return ""

    @staticmethod
    def _parse_interactive_command(raw: str) -> list[str] | None:
        """Parse interactive command from raw input."""
        try:
            return shlex.split(raw)
        except ValueError as exc:
            print(f"Invalid command syntax: {exc}")
            return None

    @staticmethod
    def _tokens_set_mode(tokens: list[str]) -> bool:
        """Check if tokens explicitly set mode."""
        for token in tokens:
            if token in {"--main", "main=true", "--tree", "--trees", "trees=true", "main=false", "trees=false"}:
                return True
        return False


class SimpleProject:
    def __init__(self, name: str) -> None:
        self.name = name
