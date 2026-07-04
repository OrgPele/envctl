# envctl 1.10.0

## What's Changed
* Require active Codex goal before cmux plan prompt by @kfiramar in https://github.com/OrgPele/envctl/pull/236
* Launch Superset Codex goals through real TUI by @kfiramar in https://github.com/OrgPele/envctl/pull/238
* Add Superset plan-agent launch transport by @kfiramar in https://github.com/OrgPele/envctl/pull/231
* [codex] Protect the shipped create_plan prompt contract by @kfiramar in https://github.com/OrgPele/envctl/pull/119
* Require active Codex goal before cmux prompt by @kfiramar in https://github.com/OrgPele/envctl/pull/240
* Add --cmux plan-agent launch flag by @kfiramar in https://github.com/OrgPele/envctl/pull/241
* Respect --cmux for existing plan launches by @kfiramar in https://github.com/OrgPele/envctl/pull/242
* Honor --cmux when launching OpenCode by @kfiramar in https://github.com/OrgPele/envctl/pull/243
* Limit Codex plan cycles to three by @kfiramar in https://github.com/OrgPele/envctl/pull/250
* Add envctl workflow identity, test planning, and ship handoff by @kfiramar in https://github.com/OrgPele/envctl/pull/248
* Refactoring envctl deep codebase refactor 4 by @kfiramar in https://github.com/OrgPele/envctl/pull/252
* [codex] Reuse CGC context for generated worktrees by @kfiramar in https://github.com/OrgPele/envctl/pull/244
* Complete envctl deep runtime orchestrator decomposition by @kfiramar in https://github.com/OrgPele/envctl/pull/245
* Extract project action git state owner by @kfiramar in https://github.com/OrgPele/envctl/pull/253
* Refactor envctl runtime and UI ownership boundaries by @kfiramar in https://github.com/OrgPele/envctl/pull/254
* Complete envctl refactor and ship workflow by @kfiramar in https://github.com/OrgPele/envctl/pull/255
* Envctl Remaining Runtime Orchestrator Decomposition by @kfiramar in https://github.com/OrgPele/envctl/pull/256
* Envctl Remaining Runtime Orchestrator Decomposition by @kfiramar in https://github.com/OrgPele/envctl/pull/257
* [codex] Handle no-system plan-agent startup by @kfiramar in https://github.com/OrgPele/envctl/pull/260
* Fix Codex cycle goal queueing by @kfiramar in https://github.com/OrgPele/envctl/pull/264
* [codex] Add remote branch import worktrees by @kfiramar in https://github.com/OrgPele/envctl/pull/258
* [codex] Report cmux plan-agent handoff targets by @kfiramar in https://github.com/OrgPele/envctl/pull/261
* Envctl Runtime Orchestrator Decomposition Completion Audit by @kfiramar in https://github.com/OrgPele/envctl/pull/273
* Envctl Runtime Orchestrator Decomposition Completion Audit by @kfiramar in https://github.com/OrgPele/envctl/pull/274
* [codex] Fix imported worktree discovery by @kfiramar in https://github.com/OrgPele/envctl/pull/278
* Add interactive remote branch import selector by @kfiramar in https://github.com/OrgPele/envctl/pull/279
* [codex] Make worktree graph tooling opt in by @kfiramar in https://github.com/OrgPele/envctl/pull/282
* [codex] Add default tree dependency scope config by @kfiramar in https://github.com/OrgPele/envctl/pull/283
* [codex] Clarify PR handoff verification prompt guidance by @kfiramar in https://github.com/OrgPele/envctl/pull/284
* Accept live listener after stale startup progress by @kfiramar in https://github.com/OrgPele/envctl/pull/285
* Accept HTTP-ready services during startup progress by @kfiramar in https://github.com/OrgPele/envctl/pull/286
* Use conventional deployment URL for browser follow-up by @kfiramar in https://github.com/OrgPele/envctl/pull/287
* Move PR preview controller into envctl by @kfiramar in https://github.com/OrgPele/envctl/pull/288
* Refresh legacy PR preview envctl config by @kfiramar in https://github.com/OrgPele/envctl/pull/289
* Use stable PR preview QA user by @kfiramar in https://github.com/OrgPele/envctl/pull/290
* Stop preview dependency containers on label removal by @kfiramar in https://github.com/OrgPele/envctl/pull/291
* Remove preview label after delete cleanup by @kfiramar in https://github.com/OrgPele/envctl/pull/292
* Project explicit source env into launch templates by @kfiramar in https://github.com/OrgPele/envctl/pull/293
* Harden PR preview redeploy and cleanup by @kfiramar in https://github.com/OrgPele/envctl/pull/294
* Envctl Test Suite Consolidation And Quality Plan by @kfiramar in https://github.com/OrgPele/envctl/pull/297
* Envctl Fullstack PR URL E2E Prompt Flag Plan by @kfiramar in https://github.com/OrgPele/envctl/pull/295
* Envctl Fullstack PR URL E2E Prompt Flag Plan by @kfiramar in https://github.com/OrgPele/envctl/pull/298
* Refresh PR preview TTL on branch pushes by @kfiramar in https://github.com/OrgPele/envctl/pull/300
* Strip GitHub Actions cleanup env from service launches by @kfiramar in https://github.com/OrgPele/envctl/pull/301
* Preserve active services when refreshing PR previews by @kfiramar in https://github.com/OrgPele/envctl/pull/302
* Pass PR preview Paddle env to app startups by @kfiramar in https://github.com/OrgPele/envctl/pull/299
* Clean PR preview redeploy environment by @kfiramar in https://github.com/OrgPele/envctl/pull/303
* Tolerate empty pre-start preview stops by @kfiramar in https://github.com/OrgPele/envctl/pull/304
* Propagate Paddle env into PR preview start commands by @kfiramar in https://github.com/OrgPele/envctl/pull/305
* Propagate Creem env into PR previews by @kfiramar in https://github.com/OrgPele/envctl/pull/306
* Make PR preview failed-start cleanup idempotent by @kfiramar in https://github.com/OrgPele/envctl/pull/307
* Delete imported branch refs with PR previews by @kfiramar in https://github.com/OrgPele/envctl/pull/308
* Remove stale wrong-branch PR preview import targets by @kfiramar in https://github.com/OrgPele/envctl/pull/309
* Make PR preview starts idempotent per head by @kfiramar in https://github.com/OrgPele/envctl/pull/310
* [codex] Make preview source env forwarding generic by @kfiramar in https://github.com/OrgPele/envctl/pull/311
* Recover imported worktrees after force pushes by @kfiramar in https://github.com/OrgPele/envctl/pull/312
* Ship JSON PR Checks and Deployment URL Plan by @kfiramar in https://github.com/OrgPele/envctl/pull/313
* Quiet Successful Test Focused Output Plan by @kfiramar in https://github.com/OrgPele/envctl/pull/314
* Handle manual release PR fallback without failing CI by @kfiramar in https://github.com/OrgPele/envctl/pull/316
* Quiet Successful Test Focused Output Plan by @kfiramar in https://github.com/OrgPele/envctl/pull/317
* Fix release workflow PR-rule publishing by @kfiramar in https://github.com/OrgPele/envctl/pull/318


**Full Changelog**: https://github.com/OrgPele/envctl/compare/1.9.2...1.10.0
