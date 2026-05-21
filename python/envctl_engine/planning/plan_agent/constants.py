from __future__ import annotations

import re
from pathlib import Path

_SUPPORTED_PLAN_AGENT_CLIS = frozenset({"codex", "opencode"})
_CODEX_BYPASS_FLAGS = "--dangerously-bypass-approvals-and-sandbox"
_PROMPT_SHAPING_COMMAND_TOKEN_RE = re.compile(r"^/[A-Za-z][A-Za-z0-9:_-]*$")
_DEFAULT_PRESET = "implement_task"
_DEFAULT_SHELL = "zsh"
_SURFACE_READY_DELAY_SECONDS = 0.15
_DEFAULT_CLI_READY_DELAY_SECONDS = 0.35
_CLI_READY_DELAY_SECONDS_BY_CLI = {
    "codex": 5.0,
    "opencode": 15.0,
}
_CLI_READY_POLL_INTERVAL_SECONDS = 0.1
_READ_SCREEN_LINE_COUNT = 80
_PROMPT_PRE_SUBMIT_DELAY_SECONDS = 0.3
_PROMPT_SUBMIT_READY_DELAY_SECONDS = 0.15
_PROMPT_SUBMIT_READY_TIMEOUT_SECONDS = 1.0
_PROMPT_SUBMIT_READY_POLL_INTERVAL_SECONDS = 0.1
_TMUX_WINDOW_READY_TIMEOUT_SECONDS = 1.0
_TMUX_WINDOW_READY_POLL_INTERVAL_SECONDS = 0.05
_OMX_SESSION_READY_TIMEOUT_SECONDS = 12.0
_OMX_SESSION_READY_POLL_INTERVAL_SECONDS = 0.1
_OMX_SESSION_STATE_RELATIVE_PATH = Path(".omx") / "state" / "session.json"
_OMX_TMUX_EXTENDED_KEYS_RELATIVE_PATH = Path(".omx") / "state" / "tmux-extended-keys"
_OMX_TMUX_LOCK_STALE_SECONDS = 30.0
_OMX_SPAWN_OUTPUT_EXCERPT_CHARS = 1000
_CODEX_QUEUE_READY_TIMEOUT_SECONDS = 10.0
_CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS = 0.1
_CODEX_QUEUE_MAX_TAB_ATTEMPTS = 2
_PLAN_AGENT_TAB_TITLE_MAX_LEN = 36
_LOW_SIGNAL_TAB_TITLE_WORDS = frozenset({"and", "origin"})
_PLAN_AGENT_WORKFLOW_SINGLE_PROMPT = "single_prompt"
_PLAN_AGENT_WORKFLOW_CODEX_CYCLES = "codex_cycles"
_OMX_WORKFLOW_KEYWORDS = frozenset({"ultragoal", "ralph", "team"})
_PROMPT_TEMPLATE_PACKAGE = "envctl_engine.runtime.prompt_templates"
_FINALIZATION_INSTRUCTION_TEMPLATE = "_plan_agent_finalization_instruction"
_FIRST_CYCLE_COMPLETION_TEMPLATE = "_plan_agent_first_cycle_completion"
_INTERMEDIATE_CYCLE_COMPLETION_TEMPLATE = "_plan_agent_intermediate_cycle_completion"
_BROWSER_E2E_FOLLOWUP_TEMPLATE = "_plan_agent_browser_e2e_followup"
_PR_REVIEW_COMMENTS_FOLLOWUP_TEMPLATE = "_plan_agent_pr_review_comments_followup"
_PLAN_AGENT_CODEX_CYCLE_CAP = 3
_REVIEW_WORKTREE_PRESET = "review_worktree_imp"
_WORKTREE_PROVENANCE_PATH = Path(".envctl-state") / "worktree-provenance.json"
_PLANNING_ROOT = Path("todo") / "plans"
_DONE_PLANNING_ROOT = Path("todo") / "done"
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CODEX_READY_PROMPT_RE = re.compile(r"^[ \t]*[>›][ \t]*.*$")
_CODEX_LOADING_MARKERS = (
    "booting mcp server",
    "starting mcp server",
    "model:     loading",
    "model: loading",
)
_CODEX_READY_MARKERS = (
    "openai codex",
    "model:",
    "directory:",
)
_CODEX_QUEUE_READY_HINT = "tab to queue message"
_CODEX_QUEUE_CONFIRMED_MARKERS = (
    "queued follow-up",
    "queued follow-up messages",
    "follow-up inputs",
)
_OPENCODE_READY_PROMPT_RE = re.compile(r"^[ \t]*[>›❯»][ \t]*.*$")
_OPENCODE_LOADING_MARKERS = (
    "loading",
    "starting",
    "initializing",
    "please wait",
)
_OPENCODE_READY_MARKERS = (
    "ask anything",
    "ctrl+p commands",
    "/status",
)
_AI_CLI_SHELL_FAILURE_MARKERS = (
    "command not found",
    "not recognized",
    "no such file",
    "traceback",
)


__all__ = tuple(name for name in globals() if not name.startswith("__"))
