# Config and Bootstrap

This guide explains how the Python runtime discovers repo-local configuration, decides when bootstrap is required, and persists the managed `.envctl` contract.

Use it when you are changing `.envctl` semantics, adding config keys, changing bootstrap safety rules, or touching the interactive/headless `config` command flow.

## The Config Problem the Runtime Solves

The Python runtime needs three things at once:

- a stable repo-local configuration file for normal operation
- compatibility with legacy shell-era config sources during migration
- a safe way to inspect or bootstrap a repo before that file exists

That is why config behavior is split across discovery, parsing, bootstrap policy, and persistence instead of living in one flat module.

## Canonical Files and Discovery

Config discovery starts in `python/envctl_engine/config/__init__.py`.

Important constants:

- canonical file: `.envctl`
- legacy-prefill files: `.envctl.sh`, `.supportopia-config`

Discovery produces `LocalConfigState`, which carries:

- base directory
- canonical config path
- whether the canonical file exists
- which source won (`envctl`, `legacy_prefill`, or `defaults`)
- active legacy source path when relevant
- parsed values and original file text

This object is the handoff between discovery and all later config flows.

## Two Different Config Stories

There are two related but different config stories in the codebase:

1. load effective values for runtime behavior
2. persist the managed repo-local config contract

They overlap, but they are not the same thing.

Effective load concerns:

- merge defaults, repo-local config, compatibility aliases, and environment overrides
- build `EngineConfig`
- expose typed helpers such as per-mode service and dependency enablement

Persistence concerns:

- decide which keys are managed
- render a stable managed block into `.envctl`
- preserve non-managed user content around that block
- validate structured config payloads from the wizard or headless input

Keep those responsibilities separate when making changes.

## `EngineConfig` Is the Runtime Contract

`load_config()` returns `EngineConfig`.

`EngineConfig` is the typed config contract the runtime consumes for:

- runtime roots and scope ids
- planning directory resolution
- port defaults
- per-mode service enablement
- per-mode dependency enablement
- truth, compatibility, and cutover policy

If a new setting materially changes runtime behavior, it probably belongs in `EngineConfig` rather than as an ad hoc environment read inside an orchestrator.

## Managed Values Layer

`python/envctl_engine/config/persistence.py` introduces a structured managed-values layer on top of raw key-value config.

Important types:

- `ManagedConfigValues`
- `ConfigSaveResult`
- `ValidationResult`

`ManagedConfigValues` is the persistence-oriented shape used by:

- the Textual config wizard
- `config --stdin-json`
- `config --set ...`
- save and validation flows

It centers around:

- `default_mode`
- `main_profile`
- `trees_profile`
- `port_defaults`
- backend and frontend directory names

That is the main developer-facing contract for config editing.

## Managed Block Semantics

The canonical `.envctl` file contains a managed block delimited by:

- `# >>> envctl managed startup config >>>`
- `# <<< envctl managed startup config <<<`

Persistence rules matter here:

- only managed keys should be rewritten inside the managed block
- user-authored surrounding content should survive save operations
- canonical keys should be rendered in a stable order

If you change persistence behavior, verify round-tripping rather than only checking that one save path works.

## Canonical Keys and Compatibility Aliases

The code now prefers canonical Python-era keys such as:

- `MAIN_POSTGRES_ENABLE`
- `TREES_REDIS_ENABLE`
- `MAIN_N8N_ENABLE`

Compatibility aliases from the shell era are still accepted when loading config.

Important consequence:

- loading is more permissive than saving

The wizard and managed persistence should write canonical keys. Compatibility aliases exist to absorb old configs, not to remain the preferred authoring format indefinitely.

## Dependency-Driven Config

The config system is now partly driven by the requirements registry.

That means persistence and validation do not hard-code every dependency key in one place. They derive some behavior from:

- `requirements/core/registry.py`
- dependency definitions and resource specs
- `managed_enable_keys()`
- `dependency_port_keys()`

When adding a new built-in dependency, config work usually includes:

1. dependency definition
2. managed enable keys
3. resource port keys
4. defaults
5. wizard and docs updates

## Bootstrap Policy

Bootstrap policy is enforced from `python/envctl_engine/runtime/cli.py` and `python/envctl_engine/config/wizard_domain.py`.

The critical rule is:

- inspection commands can run without a repo-local `.envctl`
- normal operational commands cannot

When `.envctl` is missing:

- inspect-only commands proceed with defaults
- operational commands call `ensure_local_config()`
- non-interactive environments fail with a clear error instead of guessing

That policy is part of the runtime contract. Do not weaken it casually.

## Why Route Parsing Happens Before Bootstrap

The runtime parses the route once before config bootstrap so it can decide whether the requested command is bootstrap-safe.

Then it loads config and reparses with the final environment view.

This is why config bootstrap changes and command-surface changes are coupled:

- adding a new command may require bootstrap-policy work
- changing bootstrap-safe rules may require parser-aware updates

## Interactive Bootstrap Flow

Interactive config bootstrap/editing lives in `python/envctl_engine/config/wizard_domain.py`.

Important entrypoints:

- `ensure_local_config()`
- `edit_local_config()`

These functions:

- discover local state
- enforce TTY/Textual availability
- launch the Textual config wizard
- return structured save/cancel outcomes
- emit config-related runtime events

Important design detail:

- bootstrap and edit share the same wizard stack, but they are not the same policy decision

Bootstrap failure is fatal for operational commands. Edit cancellation is not.

## Headless Config Flow

Headless config handling lives in `python/envctl_engine/config/command_support.py`.

Supported shapes include:

- `envctl config --stdin-json`
- `envctl config --set KEY=VALUE`
- passthrough `KEY=VALUE` tokens accepted by the config command

The headless flow:

1. loads current managed values from local state
2. merges JSON or flat updates
3. validates and saves
4. returns either machine-readable JSON or human-readable save output

This is the path to update when automation-friendly config editing changes.

## Validation Rules

Validation in `config/persistence.py` currently enforces:

- `default_mode` is `main` or `trees`
- backend/frontend directory names are non-empty
- port values are positive integers
- profile booleans and dependency toggles are coherent enough to save

If you add a setting with real invariants, validation should usually happen here rather than only in wizard UI code.

## `.envctl` vs `.envctl.sh`

Current developer policy should stay explicit:

- `.envctl` is the canonical repo-local config file
- `.envctl.sh` remains a compatibility-prefill input, not the primary authoring surface
- Python runtime should safely parse compatibility inputs rather than executing arbitrary shell sourcing for normal config editing

Any change that makes `.envctl.sh` feel primary again is likely architectural drift.

## Changing Config Safely

Checklist:

1. Update defaults in `config/__init__.py` if the setting has a default.
2. Extend `EngineConfig` if runtime code should consume it as typed state.
3. Update managed persistence if the setting belongs in the saved `.envctl` contract.
4. Update bootstrap/edit flows if the wizard or headless config command should expose it.
5. Update `.envctl.example`.
6. Update user/reference docs and this guide if the behavior is part of the developer contract.

## Common Mistakes

- reading env vars directly in orchestrators when the setting belongs in `EngineConfig`
- adding compatibility aliases without deciding which canonical key should be saved
- changing bootstrap-safe command rules without updating the parser/lifecycle docs
- treating persistence formatting as incidental when user-edited `.envctl` files must round-trip cleanly
- documenting `.envctl.sh` as if it were still the primary config surface
