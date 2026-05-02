## 2026-05-02 - Dashboard configured-missing services and plan-agent handoff prompts

### Scope
Implemented project-scoped dashboard metadata for configured backend/frontend services that are not currently active, then hardened plan-agent handoff prompts for PR checks, browser E2E validation, and optional PR review-comment follow-up.

### Key behavior changes
- Interactive dashboards now show configured-but-missing backend/frontend rows as `not running [Stopped]` only for projects whose metadata says that service type is configured.
- Restart selection now offers configured-but-missing app services as explicit restart targets without requiring a prior `ServiceRecord`.
- Plan-agent Codex/OMX handoffs now wait for PR status checks, queue browser E2E validation, and can queue a final PR review-comments pass.
- Added `ENVCTL_PLAN_AGENT_PR_REVIEW_COMMENTS_ENABLE`, defaulting to `true`; set it to a false boolean value in `.envctl` or the environment to skip the final PR review-comments follow-up when comment handling is manual.
- Plan-agent follow-up prompts are now backed by private bundled markdown templates so queue text can be edited without changing Python code.

### Verification
- `uv tool run ruff check python tests scripts` -> passed
- `git diff --check` -> passed
- `pytest -q` -> 1967 passed, 12 skipped, 4 warnings, 234 subtests passed
