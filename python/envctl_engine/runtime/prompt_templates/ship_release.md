You are preparing and shipping a production release end-to-end.
Authoritative sources of truth: the repo's version files, release notes/changelog files, build/release scripts, CI/release workflows, git tags, and the verified commit history since the last shipped release.
First, read the relevant release/build/versioning docs and scripts before changing anything.
Ask questions only if a blocking ambiguity remains after deep repo review, or if credentials/permissions required for PR merge, tag push, or release publication are unavailable.
Final output must include: release branch name, version change and rationale, files changed, release-notes summary, PR URL/status, merge commit, tag name, artifact paths, release URL/status, tests/build commands run, and any material assumptions or residual risks.

## Inputs
Additional release instructions (optional):
$ARGUMENTS

Interpret `$ARGUMENTS` as optional scope, timing, or versioning constraints. If it conflicts with verified repo release conventions, follow repo evidence unless the user explicitly overrides those conventions.

## Release objectives
- Create a new release branch using the repo's existing naming/versioning conventions.
- Increase the version by patch/hotfix or minor as needed.
- Update release notes thoroughly by reviewing everything merged since the last release.
- Create a PR with a complete release summary.
- Merge the PR using repo conventions after required checks pass.
- Create the new release tag for the chosen version.
- Build the release artifact(s).
- Create and publish the GitHub release with the artifact(s) attached.

## Defaults (apply unless repo evidence or $ARGUMENTS says otherwise)
- Source branch to release from:
  - use the repo's documented release source branch
  - if no convention is documented, prefer the current checked-out branch when it is clearly the release-ready branch; otherwise prefer `main`, then `master`
- Release branch naming:
  - follow existing repo naming if one exists
  - otherwise use `release/v<version>` when tags use a `v` prefix, else `release/<version>`
- Version bump policy:
  - use patch/hotfix when the unreleased changes are fixes, regressions, docs-only release packaging, or internal maintenance that should not advertise new functionality
  - use minor when the unreleased changes include user-facing features or additive capabilities
  - never choose a major version unless explicit repo evidence or user instruction requires it
- PR merge policy:
  - follow the repo's normal merge strategy (`merge`, `squash`, or `rebase`)
- Tag naming:
  - match the existing tag format exactly
- Release publishing:
  - publish the GitHub release immediately instead of creating a draft
  - mark the new release as the latest/main release when the forge supports that flag and repo conventions do not say otherwise

## Non-negotiables
- Read enough repo context to understand the release process before acting:
  - version source(s)
  - release note location(s)
  - build scripts
  - artifact outputs
  - CI/release workflows
  - prior tags/releases
- Be thorough about release notes:
  - inspect commits since the last release tag
  - inspect merged PRs if the repo convention depends on PR titles/bodies
  - group changes into useful sections
  - call out fixes, features, operational changes, dependency updates, migrations, and any breaking or rollout-sensitive behavior
- Keep the release PR and release notes concrete and complete.
- Use best-practice release hygiene:
  - verify the working tree state before branching
  - verify the target base branch is up to date
  - avoid tagging unmerged or unverified code
  - wait for required checks when the repo uses them
- Prefer the repo's existing automation:
  - Makefile targets
  - package scripts
  - release/build shell scripts
  - CI workflow wrappers
  - `gh` commands when the repo already uses GitHub/GitHub CLI
- Do not stop after creating the branch or PR. Continue through merge, tag, build, and published release creation unless blocked.

## Required repo review
1. Find the current version source(s):
   - package metadata
   - Python/Node/Rust/Go version files
   - changelog/release note headers
   - build manifests
2. Find the last shipped release:
   - latest reachable release tag
   - existing GitHub releases if needed
   - release notes files if tags are missing or ambiguous
3. Find release/build/repo conventions:
   - README
   - docs/
   - Makefile
   - package.json scripts
   - pyproject.toml
   - CI workflow files
   - scripts/ or tooling folders
4. Review commits since the last release:
   - use git history, not guesswork
   - capture every material change for release notes
5. Determine the correct version bump and branch/tag naming from repo evidence.

## Workflow
### 1) Prepare the release branch
- Confirm the clean baseline and the source branch to release from.
- Create the release branch from the correct source branch.
- Name it according to repo convention or the default described above.

### 2) Choose and apply the version bump
- Determine whether this release is patch/hotfix or minor.
- Update every repo-controlled version source consistently.
- If generated lockfiles or manifests must change with the version bump, update them too.

### 3) Write thorough release notes
- Diff from the last release tag to the release branch HEAD.
- Review commit subjects, commit bodies, and merged PR metadata when available.
- Update the repo's release notes/changelog file(s) with a complete summary.
- Include:
  - major themes of the release
  - fixes
  - new capabilities
  - developer/operator-facing changes
  - migrations or manual steps
  - notable risks or follow-up items

### 4) Validate the release candidate
- Run the relevant tests and/or verification commands that the repo release process expects.
- Run the build command that produces the release artifact(s).
- Confirm the artifact paths and filenames.
- Do not merge or tag if the release build is failing.

### 5) Create and merge the release PR
- Push the release branch.
- Create the PR with:
  - clear title
  - release summary
  - version bump details
  - release note highlights
  - validation/build results
  - risks, migrations, or operator notes
- Wait for required checks/review state if the repo demands it.
- Merge the PR with the repo's normal merge strategy.

### 6) Tag the merged release
- Sync to the merged target branch state.
- Create the release tag matching repo conventions.
- Prefer an annotated tag when the repo does not dictate otherwise.
- Push the tag if required for the release publication flow.

### 7) Publish the release with artifacts attached
- Create and publish the GitHub release for the new tag.
- Use the updated release notes as the release body, adapted as needed for the forge.
- Attach the built artifact(s).
- Confirm the published release exists and capture its URL or identifier.

## Tooling guidance
- Prefer `gh pr create`, `gh pr merge`, and `gh release create` when GitHub CLI is available and consistent with the repo.
- Prefer repo-local build wrappers over ad hoc commands.
- Prefer exact git ranges like `<last-tag>..HEAD` when collecting commits.

## Deliverables (required)
- New release branch created and pushed.
- Version updated consistently.
- Release notes/changelog updated thoroughly.
- Release PR created and merged.
- New release tag created.
- Release artifact(s) built.
- Published GitHub release created with artifact(s) attached.

## Final response format
1. Release version and bump rationale.
2. Release branch, PR, merge, and tag details.
3. Files changed.
4. Release notes coverage summary.
5. Verification/build commands run and results.
6. Artifact paths and release URL/status.
7. Risk register (only if needed).

## Self-check
- Version bump matches repo evidence and the unreleased change set.
- Release notes are based on actual commits since the last release, not a shallow summary.
- PR includes release details and was merged.
- Tag format matches repo history.
- Artifact(s) were actually built and attached to a published release.
- Final response includes every release handle/URL/path needed for follow-up.
