## Serena

This project is configured for Serena symbolic code navigation via `.serena/project.yml`.

Use Serena for precise, symbol-aware code work:
- Finding where a class, function, method, or variable is defined.
- Reading a symbol body without opening a whole file.
- Finding references or implementations before a refactor.
- Checking diagnostics for files you changed.
- Making targeted symbol-level edits when the editing tool supports it.

How to use Serena:
- Codex and opencode can use the globally configured Serena MCP server; activate
  this repo with Serena when doing code navigation or architecture work.
- In Codex, call Serena's `initial_instructions` once, then activate this repo
  with `/Users/kfiramar/projects/envctl` before architecture or navigation work.
- In opencode, use the globally configured `serena` MCP server; it starts with
  `serena start-mcp-server --context=ide --project-from-cwd`.
- Start with `get_symbols_overview` when you know the file but not the symbol.
- Use `find_symbol` when you know the symbol name.
- Use `find_referencing_symbols` before changing public or cross-module symbols.
- Use `get_diagnostics_for_file` after editing Python files.

Serena boundaries:
- Prefer Serena over `rg` for structural questions such as "where is this
  defined?", "what references this?", and "what would this rename affect?".
- Use `rg` for literal text only: log strings, comments, config keys, CLI flags,
  docs prose, and error messages.
- For cross-module dependency questions, use Serena symbol discovery and
  reference lookup before falling back to grep.
- After structural code changes, let Serena refresh automatically. If results
  look stale, run `serena project health-check` from the repo root.
- Use `.serena/project.local.yml` for machine-specific overrides; keep
  `.serena/project.yml` versioned.

## CodeGraphContext

This project uses CodeGraphContext (`cgc`) for repo-wide graph analysis. Do not
use the old `codegraph` CLI or `.codegraph/` indexes in this repo.

Use CGC for broad graph questions:
- Repo-wide stats and inventory.
- Complexity hotspots and god nodes.
- Dead-code candidates.
- Cross-module coupling and dependency reports.
- Cypher-style graph queries across many files.
- Generating a persistent analysis report for planning or review.

How to use CGC in this checkout:
- This main checkout uses the main Serena project identity and CGC context.
  Envctl-generated worktrees use generated Serena project names, but by default
  inherit the already-indexed source CGC context recorded as
  `cgc_active_context` in `.envctl-state/code-intelligence.json`. Use that
  active context for broad graph queries unless the worktree metadata says
  `cgc_context_managed: true`, which means envctl created or reused an isolated
  worktree CGC context.
- Health check: `cgc doctor`
- Confirm the indexed repo: `cgc list --context Envctl`
- Get graph stats: `cgc stats --context Envctl`
- Generate a report: `cgc report --context Envctl`
- Re-index after structural changes in the checkout whose context you are using:
  `cgc index . --context Envctl`
- Run a read-only query:
  `cgc query "MATCH (r:Repository) RETURN r.name, r.path" --context Envctl`

CGC boundaries:
- Prefer Serena for exact symbol navigation, references, diagnostics, and code
  edits.
- Prefer CGC when the question crosses many files or needs aggregate graph
  data.
- Do not use CGC query output as the only proof for a line-level edit; use
  Serena or direct file reads once CGC has identified the relevant files.
- Keep `.cgcignore` repo-local so generated worktrees inherit CGC ignore
  behavior.
- If CGC looks unhealthy, run `cgc doctor` before relying on graph results.
