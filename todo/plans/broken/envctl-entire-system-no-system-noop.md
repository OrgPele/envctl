# Envctl Entire-System No-System Noop

When a user runs an AI plan-agent launch with `--entire-system` in a repository
that has no local app system configured, envctl should say that no local system
is configured and continue with the AI session only. It should not render this
as "local app startup failed" when the only selected app services are
backend/frontend defaults with no explicit command and no autodetectable repo
layout.

Verification:

```bash
envctl --plan broken/envctl-entire-system-no-system-noop --cmux --preset implement_task --entire-system --headless --new-session
```

Expected result:

- Codex/plan-agent session launches.
- Output says no local app system is configured and envctl is running without
  local services.
- No `missing_service_start_command` appears for the no-system case.
- No backend/frontend background process is started.
