# Envctl plan-agent startup failure handoff output

## Summary

- Added a degraded plan-agent handoff path when `envctl --plan --tmux/--omx` starts an implementation AI session but local app startup fails because service commands cannot be resolved.
- The terminal now reports that the implementation session is running, preserves copy-pastable tmux attach/kill guidance when available, and explains the local startup failure separately.
- Runtime metadata/events now record the degraded handoff so debug artifacts can distinguish it from plain startup failure.
- Strict runtime truth mode now skips post-start service reconciliation for degraded handoffs, so it does not overwrite the handoff with a misleading fatal `service truth degraded after startup` summary.

## Verification

- `PYTHONPATH=python python -m unittest tests.python.startup.test_startup_orchestrator_flow tests.python.runtime.test_engine_runtime_real_startup -k plan`
- `PYTHONPATH=python python -m unittest discover -s tests/python -p 'test_*.py'`
- `python -m py_compile python/envctl_engine/startup/session.py python/envctl_engine/startup/startup_orchestrator.py python/envctl_engine/startup/finalization.py`
