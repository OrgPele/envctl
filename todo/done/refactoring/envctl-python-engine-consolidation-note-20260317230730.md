# Python Engine Consolidation Note

## What this consolidated

- Shared UI capability detection now lives in `python/envctl_engine/ui/capabilities.py`.
- Shared interactive command parsing now lives in `python/envctl_engine/ui/command_parsing.py`.
- Shared target-selection behavior now lives in `python/envctl_engine/ui/selection_support.py`.
- Shared startup/resume spinner and progress behavior now lives in `python/envctl_engine/startup/progress_shared.py`.
- Shared Textual list navigation now lives in `python/envctl_engine/ui/textual/list_controller.py`.
- Shared prompt-toolkit list execution now lives in `python/envctl_engine/ui/prompt_toolkit_list.py`.

## What remains intentionally duplicated

- Public compatibility wrappers remain where tests and legacy callers still reach them.
- Shell compatibility shims remain in place while the shell-prune work stays separate.
- Command-specific selector behavior remains local in the dashboard and action flows.

## Deferred

- Shell deletion waves and fallback removal.
- Removal of flat Python compatibility shims.
- Intentional behavior cleanup that would change current CLI or selector parity.
