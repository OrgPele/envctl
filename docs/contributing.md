# Contributing

Contributions are welcome.

## Workflow
1. Create a branch from `main`.
2. Keep changes scoped to one objective.
3. Run validation locally:

```bash
bats tests/bats/*.bats
```

4. For Python engine changes, use a local venv and run Python unit tests:

```bash
python3.12 -m venv .venv
.venv/bin/python -m unittest discover -s tests/python -p 'test_*.py'
```

5. Use conventional commits (`type(scope): subject`).
6. Open a PR with:
- `Summary`
- `Validation`
- `Impact`

## Documentation Changes
When behavior changes, update:
- `.envctl.example`
- relevant file in `docs/`
- root `README.md` (only if entrypoint/quick start changed)
