# Contributing

Contributions are welcome.

This repository is Python-first at runtime. Most behavior changes therefore need two checks:

- is the Python runtime contract correct and documented?
- did the change accidentally break the supported Python runtime contract?

## Workflow
1. Create a branch from `main`.
2. Keep changes scoped to one objective.
3. Install the CLI in editable mode:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
```

4. Run validation locally:

```bash
.venv/bin/python -m unittest discover -s tests/python -p 'test_*.py'
```

5. For Python engine changes, run Python unit tests:

```bash
.venv/bin/python -m unittest discover -s tests/python -p 'test_*.py'
```

6. Use conventional commits (`type(scope): subject`).
7. Open a PR with:
- `Summary`
- `Validation`
- `Impact`

## Before Opening a PR

Confirm the change is reflected in the right doc layer:

- user docs if operators will use or notice it
- reference docs if the command, flag, or config contract changed
- developer docs if internal architecture or extension rules changed
- planning or migration docs if cutover governance meaning changed

## Documentation Changes
When behavior changes, update:
- `docs/reference/.envctl.example`
- relevant file in `docs/`
- root `README.md` (only if entrypoint/quick start changed)

For Python runtime behavior changes, check whether these docs also need updates:

- `docs/user/python-engine-guide.md`
- `docs/developer/python-runtime-guide.md`
- `docs/developer/config-and-bootstrap.md`
- `docs/developer/command-surface.md`
- `docs/developer/ui-and-interaction.md`
- `docs/developer/runtime-lifecycle.md`
- `docs/developer/state-and-artifacts.md`
- `docs/developer/debug-and-diagnostics.md`
- `docs/developer/python-runtime-guide.md`
- `docs/developer/testing-and-validation.md`
