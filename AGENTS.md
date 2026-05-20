## Serena

This project is configured for Serena symbolic code navigation via `.serena/project.yml`.

Rules:
- Codex and opencode can use the globally configured Serena MCP server; activate this repo with Serena when doing code navigation or architecture work.
- Before answering architecture or codebase questions, activate the current project with Serena and prefer Serena symbol/reference tools over text search.
- For cross-module dependency questions, use Serena symbol discovery and reference lookup before falling back to grep.
- After structural code changes, let Serena refresh its index automatically; run `serena project health-check` from the repo root if the symbol tools look stale.
- Use `.serena/project.local.yml` for machine-specific Serena overrides; keep `.serena/project.yml` versioned.
- This main checkout uses the main Serena project identity and CGC context. Envctl-generated worktrees use generated
  Serena project names and CGC contexts recorded in `.envctl-state/code-intelligence.json`; use those generated CGC
  contexts for worktree-local graph queries.
