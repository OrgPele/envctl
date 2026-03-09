# Envctl User-Facing CLI Packaging and UX Readiness Plan

## Goal (user experience)
`envctl` should be easy to understand, install, run, upgrade, and remove whether the user:

- clones the repository and wants a local developer install,
- installs from a package manager path such as `pip` or `pipx`,
- runs `envctl --help` before configuring anything,
- needs a clean first-run bootstrap flow,
- wants clear docs that match the real file structure and runtime behavior.

The user-facing experience should not require understanding the current shell launcher, `PYTHONPATH` tricks, or repo-internal layout in order to succeed.

## Current behavior (verified in code)
- Install is currently repo-relative and shell-based:
  - [README.md](/Users/kfiramar/projects/envctl/README.md)
  - [docs/user/getting-started.md](/Users/kfiramar/projects/envctl/docs/user/getting-started.md)
  - [docs/reference/commands.md](/Users/kfiramar/projects/envctl/docs/reference/commands.md)
  - [scripts/install.sh](/Users/kfiramar/projects/envctl/scripts/install.sh)
- The public entrypoint is a Bash wrapper, not a package-installed Python console script:
  - [bin/envctl](/Users/kfiramar/projects/envctl/bin/envctl)
  - [lib/envctl.sh](/Users/kfiramar/projects/envctl/lib/envctl.sh)
  - [lib/engine/main.sh](/Users/kfiramar/projects/envctl/lib/engine/main.sh)
- The Python runtime is launched by the shell wrapper and depends on repo-relative `PYTHONPATH` injection:
  - [lib/engine/main.sh](/Users/kfiramar/projects/envctl/lib/engine/main.sh)
  - [python/envctl_engine/runtime/cli.py](/Users/kfiramar/projects/envctl/python/envctl_engine/runtime/cli.py)
- There is currently no root packaging metadata for normal `pip install .` / `pipx install .` flows:
  - no `pyproject.toml`
  - no `setup.py`
  - no `setup.cfg`
- The runtime expects repo context and usually a repo-local `.envctl` for operational commands:
  - [docs/user/python-engine-guide.md](/Users/kfiramar/projects/envctl/docs/user/python-engine-guide.md)
  - [docs/reference/configuration.md](/Users/kfiramar/projects/envctl/docs/reference/configuration.md)
  - [python/envctl_engine/config/__init__.py](/Users/kfiramar/projects/envctl/python/envctl_engine/config/__init__.py)
- Existing tests lock the current launcher/install contract, but not modern packaging flows:
  - [tests/bats/envctl_cli.bats](/Users/kfiramar/projects/envctl/tests/bats/envctl_cli.bats)
  - [tests/python/runtime/test_cli_router.py](/Users/kfiramar/projects/envctl/tests/python/runtime/test_cli_router.py)
  - [tests/python/runtime/test_command_exit_codes.py](/Users/kfiramar/projects/envctl/tests/python/runtime/test_command_exit_codes.py)

## Root cause(s) / gaps
- The product currently exposes two mental models at once:
  - repo-cloned shell-installed tool
  - Python-first runtime hidden behind a shell launcher
- Packaging/distribution is not yet a first-class product surface.
- The docs explain how to use `envctl`, but not a clean supported matrix of:
  - clone install,
  - editable install,
  - regular `pip` install,
  - `pipx` install,
  - upgrade,
  - uninstall.
- User-facing file structure and implementation structure are still optimized around migration and shell compatibility rather than the cleanest public story.
- There is no explicit decision yet on whether the public command should continue to depend on the repo checkout at runtime or become a normal installed CLI package.

## Reading objective
Before implementation begins, we need enough evidence to answer these questions with no guesswork:

1. What exactly is the current user contract?
2. Which parts of the current UX are intentional versus migration leftovers?
3. What packaging model should `envctl` support first:
   - clone-only,
   - clone + editable,
   - regular `pip`,
   - `pipx`,
   - PyPI/TestPyPI publication,
   - VCS installs from Git?
4. Which file structure changes are required to support that model cleanly?
5. Which docs, commands, tests, and release steps must change together so the UX stays coherent?

## Sequenced implementation-readiness reading plan

### Phase 1: Establish the current public promise
Read these first, in order:

1. [README.md](/Users/kfiramar/projects/envctl/README.md)
2. [docs/README.md](/Users/kfiramar/projects/envctl/docs/README.md)
3. [docs/user/getting-started.md](/Users/kfiramar/projects/envctl/docs/user/getting-started.md)
4. [docs/reference/commands.md](/Users/kfiramar/projects/envctl/docs/reference/commands.md)
5. [docs/reference/configuration.md](/Users/kfiramar/projects/envctl/docs/reference/configuration.md)
6. [docs/user/python-engine-guide.md](/Users/kfiramar/projects/envctl/docs/user/python-engine-guide.md)
7. [docs/reference/important-flags.md](/Users/kfiramar/projects/envctl/docs/reference/important-flags.md)
8. [docs/operations/troubleshooting.md](/Users/kfiramar/projects/envctl/docs/operations/troubleshooting.md)
9. [.envctl.example](/Users/kfiramar/projects/envctl/.envctl.example)

Questions this phase must answer:
- What does a brand-new user see first?
- Which commands are positioned as the happy path?
- What install path is officially documented today?
- How much repo knowledge is assumed?
- Which first-run failures are expected and which are considered bugs?

Required output from this phase:
- a current-state UX matrix with rows:
  - `clone + install`
  - `help`
  - `doctor`
  - `first config`
  - `start`
  - `daily operation`
  - `upgrade`
  - `uninstall`

### Phase 2: Read the actual launcher/install/runtime boundaries
Read these next:

1. [bin/envctl](/Users/kfiramar/projects/envctl/bin/envctl)
2. [lib/envctl.sh](/Users/kfiramar/projects/envctl/lib/envctl.sh)
3. [lib/engine/main.sh](/Users/kfiramar/projects/envctl/lib/engine/main.sh)
4. [scripts/install.sh](/Users/kfiramar/projects/envctl/scripts/install.sh)
5. [python/envctl_engine/runtime/cli.py](/Users/kfiramar/projects/envctl/python/envctl_engine/runtime/cli.py)
6. [python/envctl_engine/runtime/command_router.py](/Users/kfiramar/projects/envctl/python/envctl_engine/runtime/command_router.py)
7. [python/envctl_engine/config/__init__.py](/Users/kfiramar/projects/envctl/python/envctl_engine/config/__init__.py)
8. [python/requirements.txt](/Users/kfiramar/projects/envctl/python/requirements.txt)

Questions this phase must answer:
- What currently owns `envctl` as a command?
- What breaks if the repo is not present on disk at runtime?
- Where are install assumptions encoded?
- Where is Python 3.12 enforced?
- What does the runtime require before operational commands work?
- Which user-visible behavior belongs to the launcher versus the Python engine?

Required output from this phase:
- a dependency map for:
  - launcher ownership,
  - engine ownership,
  - repo-root detection,
  - config bootstrap,
  - Python dependency installation,
  - shell fallback.

### Phase 3: Read the architecture docs that constrain refactors
Read these after the entrypoints:

1. [docs/developer/architecture-overview.md](/Users/kfiramar/projects/envctl/docs/developer/architecture-overview.md)
2. [docs/developer/python-runtime-guide.md](/Users/kfiramar/projects/envctl/docs/developer/python-runtime-guide.md)
3. [docs/developer/module-layout.md](/Users/kfiramar/projects/envctl/docs/developer/module-layout.md)
4. [docs/planning/README.md](/Users/kfiramar/projects/envctl/docs/planning/README.md)
5. [docs/developer/contributing.md](/Users/kfiramar/projects/envctl/docs/developer/contributing.md)

Questions this phase must answer:
- Which current file layout choices are intentional architecture boundaries?
- Which compatibility shims must survive for now?
- What documentation update policy already exists?
- What release/validation expectations apply when the entrypoint or install story changes?

Required output from this phase:
- a refactor safety memo listing:
  - files that are public contract,
  - files that are compatibility shims,
  - files that can be reorganized with low user impact.

### Phase 4: Read the user-facing test contract
Read these next:

1. [tests/bats/envctl_cli.bats](/Users/kfiramar/projects/envctl/tests/bats/envctl_cli.bats)
2. [tests/python/runtime/test_cli_router.py](/Users/kfiramar/projects/envctl/tests/python/runtime/test_cli_router.py)
3. [tests/python/runtime/test_command_exit_codes.py](/Users/kfiramar/projects/envctl/tests/python/runtime/test_command_exit_codes.py)

Then inspect by search where install and launcher behavior are referenced:

- `rg -n "install|uninstall|doctor --repo|bin/envctl|ENVCTL_ENGINE_PYTHON_V1|RUN_REPO_ROOT" tests python lib docs`

Questions this phase must answer:
- Which parts of the current UX are already enforced by tests?
- Which packaging/installation flows are missing test coverage entirely?
- Which behaviors can be changed safely versus which need compatibility transitions?

Required output from this phase:
- a gap list of missing automated coverage for:
  - `pip install .`
  - `pip install -e .`
  - `pipx install .`
  - VCS install
  - `envctl --help` from installed command
  - upgrade and uninstall paths

### Phase 5: Read the official packaging docs from primary sources
These are required because the repository currently lacks packaging metadata and the desired UX includes `pip`/`pipx` installation.

Read these in order:

1. Python Packaging User Guide, "Packaging Python Projects"
   - https://packaging.python.org/en/latest/tutorials/packaging-projects
2. Python Packaging User Guide, "Writing your `pyproject.toml`"
   - https://packaging.python.org/en/latest/guides/writing-pyproject-toml/
3. Python Packaging User Guide, "`pyproject.toml` specification"
   - https://packaging.python.org/specifications/declaring-project-metadata/
4. Python Packaging User Guide, "Entry points specification"
   - https://packaging.python.org/specifications/entry-points/
5. Python Packaging User Guide, "Creating and packaging command-line tools"
   - https://packaging.python.org/en/latest/guides/creating-command-line-tools/
6. Python Packaging User Guide, "Installing stand alone command line tools"
   - https://packaging.python.org/guides/installing-stand-alone-command-line-tools/index.html
7. Python Packaging User Guide, "Making a PyPI-friendly README"
   - https://packaging.python.org/en/latest/guides/making-a-pypi-friendly-readme/
8. Python Packaging User Guide, "Is `setup.py` deprecated?"
   - https://packaging.python.org/en/latest/discussions/setup-py-deprecated/
9. pip docs, "Local project installs"
   - https://pip.pypa.io/en/stable/topics/local-project-installs/
10. pip docs, "VCS Support"
   - https://pip.pypa.io/en/stable/topics/vcs-support/
11. pipx docs
   - https://pipx.pypa.io/stable/

Questions this phase must answer:
- What is the modern baseline for Python CLI packaging?
- What does `pip` expect from a local project install?
- What does `pipx` require from an installable CLI package?
- How should console scripts be declared?
- Which metadata is needed for a clean PyPI/TestPyPI presence?
- What installation commands should replace repo-specific shell install advice?

Required output from this phase:
- a packaging decision memo covering:
  - build backend choice,
  - package layout choice,
  - console script strategy,
  - editable install support,
  - `pipx` support,
  - VCS install support,
  - whether PyPI publication is in scope now or later.

### Phase 6: Make the product-level UX decisions before touching code
After reading Phases 1-5, write and review decisions for:

1. Supported install matrix
   - `clone + ./bin/envctl install`
   - `python -m pip install -e .`
   - `python -m pip install .`
   - `pipx install .`
   - `pipx install git+...`
2. Public entrypoint model
   - keep shell wrapper as public command,
   - replace with Python console script,
   - keep shell wrapper only for repo-clone compatibility.
3. Runtime ownership model
   - repo-relative source execution,
   - installed package execution,
   - hybrid compatibility period.
4. File layout strategy
   - keep `python/envctl_engine`,
   - move to `src/`,
   - introduce wrapper package,
   - keep existing layout temporarily and package from it.
5. Dependency strategy
   - always install Rich/Textual dependencies,
   - move optional UI dependencies into extras,
   - split minimal CLI vs full interactive extras.
6. Uninstall and upgrade story
   - shell-file PATH block,
   - `pip uninstall`,
   - `pipx uninstall`,
   - compatibility messaging during migration.

Required output from this phase:
- one signed-off target UX spec with command examples for each install path.

## Sequenced implementation plan

### 1. Define the supported installation matrix
Decide and document the minimum supported paths for the next release:

- local clone developer install,
- editable install,
- regular package install,
- `pipx` install,
- VCS install from Git.

This decision is required before changing code or docs, otherwise the UX will remain internally contradictory.

### 2. Introduce proper Python packaging metadata
Implementation will likely require:

- new `pyproject.toml` at repo root,
- declared project metadata,
- declared dependencies,
- declared `requires-python`,
- declared console script entrypoint,
- optional extras if UI/runtime dependencies need separation.

The exact backend choice should follow the packaging decision memo rather than habit.

### 3. Normalize the public command entrypoint
Choose one canonical public entrypoint and make everything else a compatibility shim.

Likely target:
- installed command `envctl` comes from package metadata,
- repo clone still supports `./bin/envctl`,
- shell PATH editing becomes optional compatibility guidance, not the primary install story.

### 4. Rework docs around install/use/upgrade/uninstall
After packaging is decided, update all user-facing docs together:

- [README.md](/Users/kfiramar/projects/envctl/README.md)
- [docs/user/getting-started.md](/Users/kfiramar/projects/envctl/docs/user/getting-started.md)
- [docs/reference/commands.md](/Users/kfiramar/projects/envctl/docs/reference/commands.md)
- [docs/reference/configuration.md](/Users/kfiramar/projects/envctl/docs/reference/configuration.md)
- [docs/user/python-engine-guide.md](/Users/kfiramar/projects/envctl/docs/user/python-engine-guide.md)
- [docs/operations/troubleshooting.md](/Users/kfiramar/projects/envctl/docs/operations/troubleshooting.md)
- [docs/developer/contributing.md](/Users/kfiramar/projects/envctl/docs/developer/contributing.md)

The docs must explicitly separate:
- installing the tool,
- using the tool in a managed repo,
- configuring a target repo,
- troubleshooting install issues,
- upgrading and uninstalling.

### 5. Simplify file-structure explanations
If the runtime still needs compatibility wrappers, explain them as internal compatibility layers, not as the primary mental model.

The public story should reduce to:
- install `envctl`,
- run `envctl --help`,
- point it at a repo or run it inside one,
- bootstrap `.envctl` when needed,
- use the documented command surface.

### 6. Add automated coverage for every supported installation path
Add or extend tests for:

- package metadata validity,
- console-script generation,
- local editable install,
- local regular install,
- `pipx` install if supported in CI/dev harness,
- installed-command `--help`,
- installed-command `doctor`,
- upgrade/uninstall behavior where practical.

## Tests to add or extend
- Extend [tests/bats/envctl_cli.bats](/Users/kfiramar/projects/envctl/tests/bats/envctl_cli.bats) with compatibility cases if shell install remains supported.
- Add packaging/install tests for:
  - `python -m pip install -e .`
  - `python -m pip install .`
  - installed `envctl --help`
  - installed `envctl doctor --repo <path>`
- Add metadata validation checks for:
  - `pyproject.toml`
  - console script entrypoint
  - `requires-python`
  - dependency installation
- If `pipx` is a supported path, add at least one CI or release-gate smoke test for `pipx install` and `pipx run`.

## Rollout / verification

### Stage 1: Discovery complete
Done when the outputs from Phases 1-6 exist and the target UX spec is approved.

### Stage 2: Packaging path works locally
Done when a contributor can:

- run `python -m pip install -e .`,
- run `envctl --help`,
- run `envctl doctor --repo /path/to/repo`,
- uninstall cleanly.

### Stage 3: User docs match reality
Done when the documented install commands work exactly as written for:

- clone users,
- editable install users,
- regular `pip` users,
- `pipx` users if in scope.

### Stage 4: Compatibility cleanup
If shell install remains temporarily supported, mark it as compatibility-only in docs and tests.

## Definition of done
- There is one clearly documented primary installation path for end users.
- If multiple install paths are supported, each is explicitly documented and tested.
- `envctl` can be installed without relying on manual PATH edits as the primary story.
- The public command surface works from an installed command, not only from a cloned repo checkout.
- Docs no longer require users to infer architecture details to get started.
- Upgrade and uninstall instructions exist and are accurate.
- Contributor docs explain how to develop and test the packaged CLI.

## Risk register
- Risk: packaging the project exposes hidden runtime assumptions on repo-relative paths.
  - Mitigation: Phase 2 must map every repo-relative assumption before implementation.
- Risk: `pipx` support may conflict with runtime assumptions that require local repo source layout.
  - Mitigation: decide explicitly whether `pipx` is a first-class path or deferred.
- Risk: keeping both shell install and package install stories creates user confusion.
  - Mitigation: choose one primary story and label the other as compatibility-only.
- Risk: docs drift during migration.
  - Mitigation: update all install/use docs in one change set and back them with smoke tests.
- Risk: tests may continue to validate only the old shell install path.
  - Mitigation: require new packaging/install tests before considering the work complete.

## Immediate next actions
1. Produce the current-state UX matrix from Phases 1-2.
2. Produce the packaging decision memo from Phase 5.
3. Approve the supported install matrix.
4. Implement packaging metadata and installed command entrypoint.
5. Update docs and tests in the same change series.
