# Shell Runtime Retirement

## Summary

This is the follow-up mechanical cleanup plan that runs only after the runtime readiness contract says Bash retirement is safe.

At this point:

- Python is the only supported runtime engine.
- launcher/help/install behavior is Python-owned
- shell fallback is no longer a supported product contract
- shell governance/cutover machinery is removed
- `.envctl.sh` compatibility, if retained, is Python-owned only

This plan therefore focuses on deleting dead shell runtime code, not on making new behavioral decisions.

## Preconditions

Before starting:

- `contracts/python_runtime_gap_report.json` reports:
  - `gap_count = 0`
  - `high_or_medium_gap_count = 0`
  - `shell_retirement_blockers.ready_for_shell_retirement = true`
- full Python unittest discovery passes
- full BATS suite passes

If any of those are false, stop and return to the cutover-readiness work first.

## Deletion Steps

1. Delete the runtime/domain shell tree under `lib/engine/lib/**`.
2. Remove `lib/engine/main.sh` if `lib/envctl.sh` or the installed launcher can exec Python directly without it.
3. Reduce `lib/envctl.sh` to the smallest acceptable bootstrap wrapper, or remove it if the package-installed entrypoint is sufficient.
4. Delete any remaining shell-only compatibility shims that exist only to source deleted runtime modules.
5. Remove docs that still mention deleted shell runtime files.
6. Remove tests that only existed to assert deleted shell wrapper file presence.

## Validation

After deletion:

```bash
python3 -m unittest discover -s tests/python -p 'test_*.py'
bats tests/bats/*.bats
```

Then run a reference sweep:

```bash
rg -n "lib/engine/lib/|lib/engine/main\\.sh|ENVCTL_ENGINE_SHELL_FALLBACK|shell_prune|envctl-shell-ownership-ledger" .
```

Expected result:

- no active product code/docs/tests reference deleted shell runtime paths
- only historical changelog or archived planning documents may still mention removed names

## Success Criteria

- no runtime/domain Bash code remains
- any remaining shell files are trivial launcher/install wrappers only
- Python remains the sole supported runtime path
