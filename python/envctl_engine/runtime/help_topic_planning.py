from __future__ import annotations

from envctl_engine.runtime.help_topic_rendering import CommandHelpTopic


PLANNING_HELP_TOPICS: dict[str, CommandHelpTopic] = {
    "plan": CommandHelpTopic(
        command="plan",
        summary="create/reuse implementation worktrees from todo/plans selectors and optionally launch AI sessions",
        usage=(
            "envctl --plan <selector> [--headless] [--dry-run] "
            "[--cmux|--tmux|--omx] [--codex|--opencode] [--ulw|--no-ulw-loop]",
            "envctl --plan <selector> [--omx --ultragoal | --omx --ralph | --omx --team]",
        ),
        what_it_does=(
            "resolves the requested plan selector against todo/plans",
            "creates or reuses the matching implementation worktree(s) unless --dry-run is used",
            "optionally launches the implementation workflow in cmux, tmux, or OMX-managed Codex sessions",
            "can also use Superset's public workspace/agent CLI when configured with Superset project/workspace env",
        ),
        flags=(
            "--headless          stay non-interactive and print follow-up/attach guidance",
            "--dry-run           preview selected/reused/created worktrees without mutating git worktrees or trees/",
            "--only-backend|--only-frontend|--no-deps|--no-infra  skip local app/dependency launch pieces",
            "--cmux              launch the cmux plan-agent workflow; default when cmux is installed",
            "--tmux              envctl owns the tmux session/window and submits the workflow there",
            "--omx               envctl asks OMX to create/manage the detached Codex tmux session",
            "--ultragoal         requires --omx: start Ultragoal after optional Codex /goal framing",
            "--ralph             OMX-only compatibility option: start Ralph after optional Codex /goal framing",
            "--team              OMX-only: start the launched Codex session in Team mode",
            "--goal              enable Codex /goal framing for this launch",
            "--no-goal           disable Codex /goal framing for this launch",
            "--codex             force Codex for cmux/tmux launches",
            "--opencode          force OpenCode for cmux/tmux launches",
            "--ulw               OpenCode only: force /ulw-loop prefix (default for OpenCode)",
            "--no-ulw-loop       OpenCode only: disable the default /ulw-loop prefix",
            "--new-session  create a fresh cmux/tmux/OMX launch target instead of reusing an existing one",
            "SUPERSET_PROJECT=<id> or SUPERSET_WORKSPACE=<id> selects the Superset high-level transport",
        ),
        examples=(
            "envctl --plan feature/task --headless",
            "envctl --plan feature/task --headless --dry-run",
            "envctl --plan feature/task --cmux --headless",
            "envctl --plan feature/task --tmux --codex",
            "envctl --plan feature/task --tmux --opencode --headless",
            "envctl --plan feature/task --omx --ultragoal",
            "envctl --plan feature/task --omx --ralph",
            "envctl --plan feature/task --omx --team",
        ),
        aliases=("--plan", "parallel-plan", "sequential-plan", "--parallel-plan", "--sequential-plan"),
        related=("ensure-worktree", "list-trees", "install-prompts", "codex-tmux"),
    ),
    "import": CommandHelpTopic(
        command="import",
        summary="import an existing origin branch into a managed worktree and optionally launch AI sessions",
        usage=(
            "envctl --import <branch|origin/branch|refs/remotes/origin/branch> [--headless] "
            "[--cmux|--tmux|--omx] [runtime scope]",
            "envctl import <branch> [--tmux --codex --entire-system]",
        ),
        what_it_does=(
            "normalizes branch input to an existing origin branch",
            "fetches origin/<branch>, creates or reuses trees/imported/<branch-slug>, and checks out a "
            "tracking local branch",
            "updates reused imported worktrees by resetting them to origin/<branch>",
            "writes import provenance, links shared artifacts, prepares code intelligence, and can launch "
            "the plan-agent workflow",
        ),
        flags=(
            "--headless          stay non-interactive and print deterministic import/launch output",
            "--cmux|--tmux|--omx optionally launch the same plan-agent workflow used by --plan",
            "--codex|--opencode  choose AI CLI for envctl-owned cmux/tmux launches",
            "--entire-system|--no-infra|runtime scope flags  select local runtime/dependency startup scope",
            "--new-session       create a fresh launch target instead of reusing an existing one",
        ),
        notes=(
            "v1 supports only the origin remote and existing remote branches",
            "import never creates a remote branch, never seeds MAIN_TASK.md from todo/plans, and never "
            "force-resets local work",
            "dirty, diverged, wrong-branch, and checked-out-elsewhere worktrees fail with actionable diagnostics",
        ),
        examples=(
            "envctl --import feature/foo --headless",
            "envctl --import origin/feature/foo --cmux --entire-system --headless",
            "envctl import feature/foo --tmux --codex --entire-system",
        ),
        aliases=("--import",),
        related=("plan", "list-trees", "codex-tmux"),
    ),
    "delete-worktree": CommandHelpTopic(
        command="delete-worktree",
        summary="remove selected envctl-managed implementation worktrees",
        usage=("envctl delete-worktree --project <name> [--yes]", "envctl delete-worktree --all --yes"),
        what_it_does=(
            "removes selected worktree directories and unregisters them from git worktree state",
            "keeps deletion explicit and target-driven in headless mode to prevent accidental cleanup",
        ),
        flags=("--project <name>", "--all", "--yes | --force"),
        examples=("envctl delete-worktree --project feature-a-1 --yes", "envctl delete-worktree --all --yes"),
        aliases=("delete-worktrees", "remove-worktrees", "--delete-worktree", "--remove-worktrees"),
        related=("blast-worktree", "ensure-worktree", "list-trees"),
    ),
    "blast-worktree": CommandHelpTopic(
        command="blast-worktree",
        summary="stop/clean selected worktrees more aggressively than delete-worktree",
        usage=("envctl blast-worktree --project <name> [--yes|--force]",),
        what_it_does=(
            "runs worktree-scoped cleanup before removal, including supported Docker/dependency cleanup",
            "is intended for stale or broken implementation worktrees that need stronger cleanup",
        ),
        flags=("--project <name>", "--all", "--yes | --force"),
        examples=("envctl blast-worktree --project feature-a-1 --yes",),
        aliases=("blast-worktrees", "blastworktree", "--blast-worktree"),
        related=("delete-worktree", "blast-all", "list-trees"),
    ),
    "self-destruct-worktree": CommandHelpTopic(
        command="self-destruct-worktree",
        summary="remove the current envctl-managed worktree from inside itself",
        usage=("envctl self-destruct-worktree [--yes|--force]",),
        what_it_does=(
            "identifies the current checkout as an envctl-managed worktree and schedules/removes it safely",
            "exists for implementation sessions that need to clean up their own worktree after merging",
        ),
        flags=("--yes | --force",),
        examples=("envctl self-destruct-worktree --yes",),
        aliases=("--self-destruct-worktree",),
        related=("delete-worktree", "blast-worktree"),
    ),
    "list-trees": CommandHelpTopic(
        command="list-trees",
        summary="list envctl-managed implementation worktrees",
        usage=("envctl list-trees [--json]",),
        what_it_does=(
            "discovers tree-mode projects/worktrees without starting services",
            "helps choose --project values for test/pr/review/delete-worktree commands",
        ),
        flags=("--json",),
        examples=("envctl list-trees", "envctl list-trees --json"),
        aliases=("--list-trees",),
        related=("ensure-worktree", "delete-worktree", "plan"),
    ),
    "install-prompts": CommandHelpTopic(
        command="install-prompts",
        summary="install envctl AI workflow presets for supported AI CLIs",
        usage=(
            "envctl install-prompts --cli <codex|claude|opencode|all> [--preset <name>|all] [--dry-run]",
            "envctl install-prompts --cli codex --preset implement_task --json",
        ),
        what_it_does=(
            "installs envctl AI workflow surfaces for selected CLI targets",
            "Codex installs envctl workflows as skills under ~/.codex/skills",
            "Claude/OpenCode install prompt/command files in their respective config roots",
        ),
        flags=(
            "--cli <targets>        comma-separated target CLIs or all",
            "--preset <name>|all    choose one built-in preset or all presets",
            "--dry-run              preview written paths without changing files",
            "--json                 machine-readable output, including Codex skill invocation guidance",
            "--yes | --force        approve overwrites without prompting",
        ),
        notes=(
            "envctl-managed plan launches submit the rendered workflow automatically; "
            "manual $envctl-* invocation is only for direct Codex/OMX use",
            "Codex skills are installed below ~/.codex/skills and can be edited by the user after installation",
        ),
        examples=(
            "envctl install-prompts --cli codex --preset implement_task",
            "envctl install-prompts --cli codex --preset implement_task --dry-run --json",
            "envctl install-prompts --cli claude,opencode --preset all",
        ),
        aliases=("--install-prompts",),
        related=("plan", "codex-tmux"),
    ),
    "codex-tmux": CommandHelpTopic(
        command="codex-tmux",
        summary="launch or reuse a repo-scoped Codex/OMX tmux session",
        usage=(
            "envctl codex-tmux [codex args...]",
            "envctl codex-tmux --omx --ultragoal",
            "envctl codex-tmux --dry-run [--json] [codex args...]",
        ),
        what_it_does=(
            "creates or reuses a repo-scoped tmux session for Codex",
            "starts Codex with --dangerously-bypass-approvals-and-sandbox in that session",
            "attaches to the tmux session unless --dry-run is used",
            "with --omx --ultragoal, launches the repo through `omx ultragoal --tmux` instead of bare Codex",
            "with --omx --ralph, preserves the explicit Ralph compatibility workflow",
        ),
        flags=(
            "--dry-run              show the session command without starting/attaching",
            "--json                 JSON output; supported only with --dry-run",
            "--omx --ultragoal      launch an OMX-managed Ultragoal/Codex tmux session for this repo",
            "--omx --ralph          launch an OMX-managed Ralph/Codex tmux session for compatibility",
        ),
        notes=("extra Codex arguments are only applied when creating a new session",),
        examples=(
            "envctl codex-tmux",
            "envctl codex-tmux --omx --ultragoal",
            "envctl codex-tmux --omx --ralph",
            "envctl codex-tmux --dry-run --json review",
        ),
        aliases=("--codex-tmux",),
        related=("plan", "session", "install-prompts"),
    ),
    "ensure-worktree": CommandHelpTopic(
        command="ensure-worktree",
        summary="create or reuse one envctl-managed worktree without starting services",
        usage=("envctl ensure-worktree <selector> [--json]",),
        what_it_does=(
            "resolves one planning/worktree selector and ensures the corresponding worktree exists",
            "returns cheap automation-friendly metadata without launching runtime services",
        ),
        flags=("--json", "--reuse-existing-worktree", "--recreate-existing-worktree"),
        examples=("envctl ensure-worktree feature-a --json",),
        aliases=("--ensure-worktree",),
        related=("plan", "list-trees", "delete-worktree"),
    ),
}
