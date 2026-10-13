# `tj-agents/github-actions` conventions package

Status: active, 2026-10-13. The host goal outside this repository keeps the private source list; this copy holds
everything else and is the one to keep current.

## Outcome

A `github-actions` plugin holding Tommy's canonical workflow conventions and the provider-agnostic
boilerplate writer for the complete deployed-service workflow set. Tommy's 2026-10-13 decision supersedes
the conventions-only scaffold boundary. Azure supplies only its cloud steps; this package owns the files,
job graph, reusable deploy/destroy shape, composite-action layout, immutable pins, Dependabot and lint.

Done when:

1. The repository exists from `kit:new-plugin` at kit 1.2.1, type `stack`, detecting `.github/workflows/*.yml`
   and `.github/workflows/*.yaml`, with the knowledge trio in place.
2. The contracts hold the conventions Tommy approved, seeded from a survey of modern production service
   workflows and Tommy's own repositories (Concertable, sandbox-azure, kit's `plugin-ci.yml`), and checked
   against current GitHub documentation. Each rule went through `github-actions:learning`'s convention
   procedure, with Tommy deciding in one batched question.
3. The generated-output check and `kit:check` pass, CI is green, the conventions PR is reviewed and merged, and
   a `tj-agents/marketplace` catalog PR is open.

## Boundary with `azure`

This package owns workflow YAML conventions and the complete generated workflow set. Azure owns Azure
resources, identity, federated-credential subjects and cloud-specific sign-in, Terraform foundation/instance,
deploy/readiness and teardown steps. Azure provides structured steps to this writer and does not render
generic workflow files or own a second action-pin catalog.

## Rules

- No employer identifiers anywhere in the repository; the deny-list audit runs before every commit and push.
- Going public needs a clean audit plus Tommy's yes. Contract rules need Tommy's decision.
- Delivery after the initial skeleton is through feature-branch PRs under `.agents/delivery-authorization.json`.

## Decisions

- 2026-10-12: `scaffold` stays the kit skeleton; superseded by Tommy on 2026-10-13.
- 2026-10-13, Tommy: the writer owns pr.yml, ci.yml, prod.yml, pr-closed.yml, reusable deploy/destroy,
  composite actions, Dependabot and lint. One prod-release setting defaults to on; deploy-preview label
  opts into previews. Scaffolds write only one canonical boilerplate shape.
- 2026-10-12, Tommy: approved all 34 rules in [PROPOSAL.md](PROPOSAL.md) as written. Choices: SHA pins with
  `# vX.Y.Z` comments plus grouped Dependabot (revisit `actions.lock` at GA); `azure/login` OIDC on hosted
  runners; semver-tag production releases. One new contract, `security`; the pipeline model lives in
  `domain-design`.
- 2026-10-12, Tommy: repository made public (deny-list audit clean) so CI runs like its siblings.

## Progress

- 2026-10-12: skeleton generated from kit 1.2.1; all checks pass; initial commit pushed to private `main`.
- CI did not start while private (Actions billing); resolved by going public. Run 38257503514 green on `main`.
- 2026-10-12: survey done (production services + Tommy's own); proposal approved; contracts, `security`,
  `direction` references, a conventions-only `scaffold` and `.agents/delivery-authorization.json` written on
  `Feature/Conventions`. sync `-Check`, `kit:check`, skill-reference and tier-payload checks pass; audit clean.

- 2026-10-12: two independent reviews. Fixed: job-level `permissions` replaces rather than adds; citations
  map onto `direction`'s references; `learning` no longer claims contracts start empty. Kept: the 2025-08-15
  changelog date (verified) and kit's required `## Validation and publication` heading.
- 2026-10-12: marketplace PR 6 merged at `291edc7`, so `github-actions` is listed in the catalog.

## Follow-ups outside this repository (not authorized here)

- kit: `plugin-ci.yml` and the vendored `ci.yml` reference actions and the reusable workflow by tag, with no
  `permissions:` or `persist-credentials: false`. They predate `github-actions:security`. Resolved when a
  kit release pins by SHA and sets least-privilege permissions.
- sandbox-azure `terraform.yml` and Concertable's config `apply.yml` use tag refs and keep IDs in `secrets`.
  Resolved when each adopts `github-actions:security`.

## Current execution - 2026-10-13

Feature/WorkflowWriter starts at 706a817563f1cb27b5b6db90375a5388b482cfd0 in an isolated checkout.
The existing Template-workflow checkout belongs to another owner and will not be edited.
Implementation is L4: the boundary is decided and neutral-provider tests, actionlint and zizmor can verify it.
Tommy authorized available models for implementation and independent review; no additional native sessions.

Assessment is complete from the read-only survey of modern production services, excluding legacy iframe
hosting. Useful patterns: typed reusable interfaces, tested-run artifact promotion, per-PR and fixed
concurrency, cancellation/unlock recovery, federated identity and non-persisted checkout credentials.
The approved contracts supply SHA pins, label/fork trust gates, mandatory success aggregation, timeouts and
scoped lint/Dependabot where the surveyed workflows had gaps. No identifiers or source content are copied.

The writer is a stdlib Python complete-file-map renderer with a JSON CLI. Providers supply named phases
of structured steps, environment/OIDC data and workload/build metadata; they cannot supply whole jobs or
workflows. Prospective repository files and declared working roots allow toolchain setup from version files
before any write. Do not infer versions by parsing command strings or hardcode stack SDK versions.
Terraform command/foundation/backend rendering remains Azure's cloud-specific responsibility.

Acceptance for this slice:
- Complete workflow set conforms to all 34 approved rules, including mandatory ci-complete aggregation,
  preview label/fork trust, release assertion and shared deploy/destroy concurrency.
- One boolean prod-release setting defaults on. Data inputs are not a scaffold options matrix.
- CLI validates before writing, refuses collisions and rolls back partial writes; pure render supports
  Azure's later outer atomic file composition.
- Neutral-provider tests exercise both release settings, trusted/untrusted preview paths, job dependencies,
  toolchain metadata, malformed provider input, no-write/collision/rollback and release assertion behavior.
- Source harness declares the shipped Python commands in the same change; generated hosts stay fresh.
- Focused tests, pinned kit conformance, independent immutable review and exact-head CI pass.
- Every commit passes the private employer deny-list scan.

## Next Steps

1. Repair WW-8/9 expression trust, then WW-10 shared setup cache; complete fresh incremental review and exact-head CI.
2. Merge the writer, then separately integrate Azure with it and remove generic duplication.
3. Follow with dotnet's one Web API boilerplate shape and the remaining canonical handoff items.

### Slice size and boundary - 2026-10-13

The initial writer implementation has approximately 649 Python lines and 132 lines of shared runtime
helpers before focused tests and documentation. The CLI/schema, six workflow graphs, required-check
aggregation, reusable interfaces and release assertion form one executable/security boundary, so this
writer is one atomic slice. Generated host copies are not independent authored implementations.
Azure integration/removal of its generic renderer and dotnet boilerplate remain separate delivery slices.
Reassess if implementation grows beyond this complete-writer boundary; do not accumulate later repairs.

### Implementation validation - 2026-10-13

The source writer is complete and its sole implementation worker has stopped writes. It renders the full
workflow set, structured provider phases/composites, metadata-driven SDK setup for declared phase roots,
immutable artifact promotion, release assertions, and atomic CLI output. Close cleanup keeps the fork and
readiness guards while remaining independent of the current preview label. Preview deploy, destroy and
recovery share one serialized PR key; GitHub environment identities remain fixed.

Final source checks passed under workflow run standards-workflow-writer-20261013: 28 focused tests (three
JavaScript tests skipped locally because Node is absent), actionlint 1.7.11 and zizmor 1.23.1 over full,
no-build, prod-off and production-matrix outputs plus composites and own CI, canonical generation,
generated freshness and pinned kit 1.2.1 conformance. The shipped two-OS writer CI requires the JavaScript
assertions and lints those emitted variants; it is the authoritative remaining runtime gate.

The final renderer is 702 lines; its scaffold resources, tests and own CI total 1,475 lines before existing
contract/harness edits and generated copies. The same complete writer boundary justifies this one slice.
Independent ordinary correctness/contract review selects L4; production artifact/OIDC security review
selects L2 because an incorrect approval can expose credentials or deploy an unverified commit.
Parent-only commit/push is clerical L7. Available-model routing is authorized by Tommy; no native session
will be added beyond the session limit.

Tommy separately approved publishing the scoped M001 operator record directly to main at
7812f8a25f139c230f847b77091fd87fc39ed0f2. Final review synchronizes once with that record-only base movement.
Azure composition remains the next separate delivery slice; no Azure renderer code is changed here.

### Completed independent review and repair owner - 2026-10-13

Source checkpoint 29c7687ac9984cf725dabf246c0cd3960c8ee9dc passed the staged deny-list. The single
pre-review synchronization with the approved record-only main movement froze head
8cf9a69f297e07d78358e7a418c43c322cb31e1d against 7812f8a25f139c230f847b77091fd87fc39ed0f2.
The independent native-general, API-contract and security evidence plus parent workflow review completed
with seven findings, deduplicated in reviews/Feature-WorkflowWriter.md. Both source-host coverage checks
passed. No candidate push or PR yet. Address-review is active with a sole L4 source writer, starting with
the tightly coupled assembled-ID and phase-env defects. Parent owns review state, commits and delivery.
After each verified repair group: staged deny-list audit and local checkpoint. Then fresh incremental
review and two-OS exact-head CI before merge. The existing owning-account Node runtime permits executing
the release-helper regression tests locally; no runtime installation or live cloud commands occurred.
### Review repair checkpoints - 2026-10-13

WW-1/2 composition repairs are committed at 18e0a3bfb330f728413d51847f0eb1bcc96e8567; WW-3/4
expression guards and lint-before-plan at 37043119b1c2b2134d7ba8a18d2d9089616d46d7. Both staged
private deny-list checks passed. All 43 focused tests pass with required Node/no skips, AST test-name
uniqueness and 69-file freshness. No writer push or PR yet. The immutable full-review judgment remains
changes-requested until fresh incremental synthesis after all seven dispositions.

WW-5/7 lifecycle repair is in final parent acceptance. Default pending replacement requires preserving
closed cleanup inside every surviving preview deploy/recovery entrant; no nested lock acquisition or
unsupported queue field is emitted. First lifecycle suite passed 50 tests. Parent acceptance adds a
successful prerequisite checkpoint while preserving provider status-function semantics, and keeps
concrete implementation behavior in scaffold ABI docs. WW-6 moved-tag trigger assertion follows.

The M002 source-insertion incident is retained in the primary shared register and delivered separately
as docs PR 2, merged e6a0dd160b57f0be68bba7386e13d2366e0dff8f. Independent full/delta review and
exact-head CI 38462956959 passed; primary base clean. This record-only base movement is reconciled at
writer preflight without another source synchronization or changing the frozen review identity.

Lifecycle repairs WW-5/7 accepted: 52 required-Node tests pass without skips, including emitted provider
status guards under failed lifecycle/prerequisites, legitimate provider errors and cancelled recovery.
AST uniqueness, 72 generated files/freshness and whitespace passed. Preview GitHub identity matches
its configured environment. The approved never-cancel clarification is the only contract change.
Next separate group is WW-6, binding peeled tag commit to immutable triggering context.sha.

Final repair acceptance: WW-6 compares peeled tag SHA with immutable context.sha before any CI/artifact
lookup. Moved lightweight/annotated refs reject a newer green commit without promotion calls or outputs.
Matching refs and the 16-level bound pass. All 54 required-Node tests pass without skips; AST uniqueness,
72-file generation/freshness, whitespace and pinned kit 1.2.1 conformance pass. Full emitted variants
passed actionlint 1.7.11 and zizmor 1.23.1. No cloud or application build ran locally.

Reassessed authored size: renderer 845 lines, total scaffold resources/tests/own CI approximately 2,180
lines. Added lines repair composition, expression safety and shared preview lifecycle within the same
complete executable/security boundary; those guards cannot be split into an independently safe writer.
Azure composition/removal, dotnet boilerplate and later repairs remain separate slices. Fresh incremental
review selects L4 correctness/API and L2 security; parent delivery is clerical L7. Source writer stopped.

Fresh review froze 8cf9a69f297e07d78358e7a418c43c322cb31e1d..c2712ec4c5f0805a11e0fd02df76cbed175291f9
(20 changed paths). API-contract and parent native fallback confirm one bare-step-condition context
validation defect; the full-trunk security lens remains active at the same head. Canonical work order
is in-progress/pending and preserves the previous watermark. No source remediation or PR publication
starts before this pass's synthesis. Both frozen exports remain available for the active review.

Incremental pass completed at c2712ec with WW-8 (MEDIUM bare-condition validation), WW-9 (HIGH
env-alias script injection), WW-10 (HIGH shared setup cache in independently privileged build).
Parent reproduced all three using only frozen pure rendering. Speculative cancelled-prerequisite
reachability was withdrawn and excluded. Source-host coverage passed; completed pass/watermarks
recorded in the canonical work order. Serial address-review starts with coupled expression WW-8/9.

WW-8/9 accepted: bare and wrapped conditions use identical quote-aware validation; command/script
aliases are resolved through effective phase, invocation and step environments, including transitive
aliases and composite overrides. Unsafe, secret or unresolved aliases reject before any write;
literal/trusted values and environment-variable consumption remain supported. All 62 required-Node
tests passed without skips, AST uniqueness and 72-file generation/freshness passed, and parent inspected
the canonical renderer/docs/tests diff. WW-10 shared setup cache is the next separate source group.
