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

1. Complete independent immutable review and exact-head CI for the implemented workflow writer, then merge it.
2. Review and merge it, then separately integrate Azure with the writer and remove generic duplication.
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
