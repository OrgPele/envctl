from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import shlex
import shutil
from typing import Any, Literal

from envctl_engine.config import EngineConfig
from envctl_engine.shared.parsing import parse_bool, parse_int_or_none

from envctl_engine.planning.plan_agent.constants import (
    _CLI_READY_DELAY_SECONDS_BY_CLI,
    _CODEX_BYPASS_FLAGS,
    _DEFAULT_CLI_READY_DELAY_SECONDS,
    _DEFAULT_PRESET,
    _DEFAULT_SHELL,
    _PLAN_AGENT_CODEX_CYCLE_CAP,
    _PLAN_AGENT_WORKFLOW_CODEX_CYCLES,
    _PLAN_AGENT_WORKFLOW_SINGLE_PROMPT,
    _SUPPORTED_PLAN_AGENT_CLIS,
)
from envctl_engine.planning.plan_agent.models import PlanAgentLaunchConfig


CommandAvailable = Callable[[str], object | None]


@dataclass(frozen=True, slots=True)
class PlanAgentLaunchPolicy:
    config: EngineConfig
    env: Mapping[str, str]
    route: object | None = None
    command_available: CommandAvailable = shutil.which

    @property
    def route_flags(self) -> Mapping[str, object]:
        return getattr(self.route, "flags", {}) or {}

    def resolve_launch_config(self) -> PlanAgentLaunchConfig:
        route_flags = self.route_flags
        cmux_launch_requested = bool(route_flags.get("cmux"))
        opencode_launch_requested = bool(route_flags.get("opencode"))
        cmux_alias_requested = self._bool_value("CMUX", False)
        cmux_workspace = self._string_value("ENVCTL_PLAN_AGENT_CMUX_WORKSPACE")
        current_cmux_workspace = self._string_value("CMUX_WORKSPACE_ID")
        configured_surface_transport = self._configured_surface_transport()

        surface_transport_warning = None
        if configured_surface_transport not in {"cmux", "tmux", "superset"}:
            surface_transport_warning = "invalid_surface_transport"
            configured_surface_transport = self.default_surface_transport()

        transport: Literal["cmux", "tmux", "omx", "superset"]
        if bool(route_flags.get("omx")):
            transport = "omx"
        elif bool(route_flags.get("tmux")):
            transport = "tmux"
        elif cmux_launch_requested or cmux_alias_requested or bool(cmux_workspace) or bool(current_cmux_workspace):
            transport = "cmux"
        elif opencode_launch_requested:
            transport = self.default_surface_transport()
        else:
            transport = configured_surface_transport  # type: ignore[assignment]

        cli = self._selected_cli(transport=transport)
        codex_yolo_enabled = self._bool_value("ENVCTL_PLAN_AGENT_CODEX_YOLO", True)
        cli_command = (
            self._string_value("ENVCTL_PLAN_AGENT_CLI_CMD")
            or default_plan_agent_cli_command(cli, codex_yolo_enabled=codex_yolo_enabled)
        )
        superset_project = self._string_value("ENVCTL_PLAN_AGENT_SUPERSET_PROJECT")
        superset_workspace = self._string_value("ENVCTL_PLAN_AGENT_SUPERSET_WORKSPACE")
        codex_cycles, codex_cycles_warning = parse_codex_cycles(self._value("ENVCTL_PLAN_AGENT_CODEX_CYCLES"))

        direct_prompt_enabled = self._bool_value(
            "ENVCTL_PLAN_AGENT_DIRECT_PROMPT",
            True if cli == "opencode" else False,
        )
        ulw_loop_prefix = self._bool_value(
            "ENVCTL_PLAN_AGENT_ULW_LOOP_PREFIX",
            True if (cli == "opencode" and direct_prompt_enabled) else False,
        )
        if bool(route_flags.get("ulw")):
            ulw_loop_prefix = True
            if cli == "opencode":
                direct_prompt_enabled = True
        if bool(route_flags.get("no_ulw_loop")):
            ulw_loop_prefix = False

        return PlanAgentLaunchConfig(
            enabled=self._launch_enabled(
                cmux_workspace=cmux_workspace,
                cmux_alias_requested=cmux_alias_requested,
                cmux_launch_requested=cmux_launch_requested,
                opencode_launch_requested=opencode_launch_requested,
                superset_project=superset_project,
                superset_workspace=superset_workspace,
            ),
            transport=transport,
            cli=cli,
            cli_command=cli_command,
            preset=self._string_value("ENVCTL_PLAN_AGENT_PRESET") or _DEFAULT_PRESET,
            codex_cycles=codex_cycles,
            codex_cycles_warning=codex_cycles_warning,
            browser_e2e_followup_enable=self._bool_value("ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE", False),
            pr_review_comments_followup_enable=self._bool_value(
                "ENVCTL_PLAN_AGENT_PR_REVIEW_COMMENTS_ENABLE",
                False,
            ),
            shell=self._string_value("ENVCTL_PLAN_AGENT_SHELL") or _DEFAULT_SHELL,
            require_cmux_context=self._bool_value("ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT", True),
            cmux_workspace=cmux_workspace,
            direct_prompt_enabled=direct_prompt_enabled,
            ulw_loop_prefix=ulw_loop_prefix,
            ulw_suffix=self._bool_value("ENVCTL_PLAN_AGENT_APPEND_ULW", False),
            omx_workflow=self._omx_workflow(),
            codex_goal_enable=self._codex_goal_enabled(cli),
            superset_project=superset_project,
            superset_workspace=superset_workspace,
            superset_host=self._string_value("ENVCTL_PLAN_AGENT_SUPERSET_HOST"),
            superset_local=self._bool_value("ENVCTL_PLAN_AGENT_SUPERSET_LOCAL", True),
            superset_open=self._bool_value("ENVCTL_PLAN_AGENT_SUPERSET_OPEN", True),
            surface_transport_warning=surface_transport_warning,
        )

    def prereq_commands(self) -> tuple[str, ...]:
        launch_config = self.resolve_launch_config()
        if not launch_config.enabled or launch_config.surface_transport_warning:
            return ()
        if launch_config.transport == "omx":
            return ("omx", "tmux", "script", "codex")
        if launch_config.transport == "superset":
            return ("superset", "codex")

        launcher = "tmux" if launch_config.transport == "tmux" else "cmux"
        if (
            launcher == "cmux"
            and self.command_available("cmux") is None
            and not self.cmux_transport_explicitly_requested()
        ):
            launcher = "tmux"

        cli_executable = command_executable(launch_config.cli_command)
        if not cli_executable:
            return (launcher,)
        return (launcher, cli_executable)

    def cmux_transport_explicitly_requested(self) -> bool:
        route_flags = self.route_flags
        explicit_config_keys = set(getattr(self.config, "explicit_keys", ()) or ())
        surface_transport = self._env_string("ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT").lower()
        config_surface_transport = self._config_string("ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT").lower()
        return any(
            (
                bool(route_flags.get("cmux")),
                self._bool_value("CMUX", False),
                bool(self._string_value("ENVCTL_PLAN_AGENT_CMUX_WORKSPACE")),
                bool(self._string_value("CMUX_WORKSPACE_ID")),
                surface_transport == "cmux",
                config_surface_transport == "cmux" and "ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT" in explicit_config_keys,
            )
        )

    def route_requests_ulw(self) -> bool:
        return bool(self.route_flags.get("ulw"))

    @staticmethod
    def ulw_route_supported(launch_config: PlanAgentLaunchConfig) -> bool:
        return launch_config.cli == "opencode"

    def default_surface_transport(self) -> Literal["cmux", "tmux"]:
        return default_plan_agent_surface_transport(command_available=self.command_available)

    def _configured_surface_transport(self) -> str:
        configured = self._string_value("ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT") or self.default_surface_transport()
        return normalize_plan_agent_surface_transport(configured)

    def _selected_cli(self, *, transport: str) -> str:
        route_flags = self.route_flags
        if bool(route_flags.get("opencode")):
            raw = "opencode"
        elif bool(route_flags.get("codex")) or transport == "omx":
            raw = "codex"
        else:
            raw = self._string_value("ENVCTL_PLAN_AGENT_CLI") or "codex"
        return str(raw).strip().lower() or "codex"

    def _launch_enabled(
        self,
        *,
        cmux_workspace: str,
        cmux_alias_requested: bool,
        cmux_launch_requested: bool,
        opencode_launch_requested: bool,
        superset_project: str,
        superset_workspace: str,
    ) -> bool:
        route_flags = self.route_flags
        return self._bool_value("ENVCTL_PLAN_AGENT_TERMINALS_ENABLE", False) or any(
            (
                bool(cmux_workspace),
                cmux_alias_requested,
                cmux_launch_requested,
                opencode_launch_requested,
                bool(superset_project or superset_workspace),
                bool(route_flags.get("tmux")) or bool(route_flags.get("omx")),
            )
        )

    def _omx_workflow(self) -> Literal["", "ultragoal", "ralph", "team"]:
        route_flags = self.route_flags
        if bool(route_flags.get("ultragoal")):
            return "ultragoal"
        if bool(route_flags.get("ralph")):
            return "ralph"
        if bool(route_flags.get("team")):
            return "team"
        return ""

    def _codex_goal_enabled(self, cli: str) -> bool:
        if cli != "codex":
            return False
        route_flags = self.route_flags
        enabled = self._bool_value("ENVCTL_PLAN_AGENT_CODEX_GOAL_ENABLE", True)
        if bool(route_flags.get("goal")) or bool(route_flags.get("codex_goal")):
            enabled = True
        if bool(route_flags.get("no_goal")) or bool(route_flags.get("no_codex_goal")):
            return False
        return enabled

    def _value(self, key: str) -> object:
        return self.env.get(key) or self.config.raw.get(key)

    def _string_value(self, key: str) -> str:
        return str(self._value(key) or "").strip()

    def _env_string(self, key: str) -> str:
        return str(self.env.get(key) or "").strip()

    def _config_string(self, key: str) -> str:
        return str(self.config.raw.get(key) or "").strip()

    def _bool_value(self, key: str, default: bool) -> bool:
        return parse_bool(self._value(key), default)


def parse_codex_cycles(raw: object) -> tuple[int, str | None]:
    normalized = str(raw or "").strip()
    if not normalized:
        return 0, None
    value = parse_int_or_none(normalized)
    if value is None or value < 0:
        return 0, "invalid_codex_cycles"
    if value > _PLAN_AGENT_CODEX_CYCLE_CAP:
        return _PLAN_AGENT_CODEX_CYCLE_CAP, "bounded_codex_cycles"
    return value, None


def workflow_mode_for_launch_config(launch_config: PlanAgentLaunchConfig) -> str:
    if codex_tui_queue_workflow_supported(launch_config) and launch_config.codex_cycles > 0:
        return _PLAN_AGENT_WORKFLOW_CODEX_CYCLES
    return _PLAN_AGENT_WORKFLOW_SINGLE_PROMPT


def codex_tui_queue_workflow_supported(launch_config: PlanAgentLaunchConfig) -> bool:
    return launch_config.cli == "codex" and launch_config.transport in {"cmux", "tmux", "omx"}


def uses_direct_submission(*, cli: str, direct_prompt_enabled: bool) -> bool:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli == "codex":
        return True
    return normalized_cli == "opencode" and direct_prompt_enabled


def cli_ready_delay_seconds(cli: str) -> float:
    return _CLI_READY_DELAY_SECONDS_BY_CLI.get(str(cli).strip().lower(), _DEFAULT_CLI_READY_DELAY_SECONDS)


def default_plan_agent_cli_command(cli: str, *, codex_yolo_enabled: bool = True) -> str:
    normalized = str(cli).strip().lower()
    if normalized == "codex":
        if codex_yolo_enabled:
            return f"codex {_CODEX_BYPASS_FLAGS}"
        return "codex"
    return normalized or "codex"


def default_plan_agent_surface_transport(
    *,
    command_available: CommandAvailable = shutil.which,
) -> Literal["cmux", "tmux"]:
    return "cmux" if command_available("cmux") else "tmux"


def normalize_plan_agent_surface_transport(raw: str) -> str:
    return str(raw or "").strip().lower()


def guidance_attach_command(session_name: str) -> tuple[str, ...]:
    return ("tmux", "attach", "-t", session_name)


def command_executable(raw_command: str) -> str | None:
    try:
        parsed = shlex.split(raw_command)
    except ValueError:
        return None
    if not parsed:
        return None
    return str(parsed[0]).strip() or None


def missing_launch_commands(runtime: Any, launch_config: PlanAgentLaunchConfig) -> list[str]:
    if launch_config.transport == "omx":
        required = ["omx", "tmux", "script", "codex"]
    elif launch_config.transport == "superset":
        required = ["superset", "codex"]
    else:
        required = ["tmux" if launch_config.transport == "tmux" else "cmux"]
        cli_executable = command_executable(launch_config.cli_command)
        shell_executable = command_executable(launch_config.shell)
        if cli_executable:
            required.append(cli_executable)
        if shell_executable:
            required.append(shell_executable)
        if launch_config.cli not in _SUPPORTED_PLAN_AGENT_CLIS and not command_executable(launch_config.cli_command):
            required.append(launch_config.cli)
    missing: list[str] = []
    for command in required:
        if command in missing:
            continue
        if runtime._command_exists(command):
            continue
        missing.append(command)
    return missing


__all__ = tuple(name for name in globals() if not name.startswith("__"))
