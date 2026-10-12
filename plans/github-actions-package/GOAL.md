# `tj-agents/github-actions` conventions package

Status: active, 2026-10-12. The host goal outside this repository keeps the private source list; this copy holds
everything else and is the one to keep current.

## Outcome

A `github-actions` plugin holding Tommy's canonical conventions for GitHub Actions workflow YAML, so every
repository's CI/CD is written the same way. Conventions are the deliverable; `scaffold` stays kit's skeleton
(Tommy: "not a scaffolder"). Workflow files are emitted by the scaffold that owns the deploy target, such as
`azure:scaffold --into`, and follow these contracts.

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

This package owns workflow YAML conventions. `azure` owns Azure resources, identity, federated-credential
subjects, deploy commands and the workflow files its scaffold emits; those files follow this package.

## Rules

- No employer identifiers anywhere in the repository; the deny-list audit runs before every commit and push.
- Going public needs a clean audit plus Tommy's yes. Contract rules need Tommy's decision.
- Delivery after the initial skeleton is through feature-branch PRs under `.agents/delivery-authorization.json`.

## Decisions

- `scaffold` stays the kit skeleton.
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

## Next Steps

1. Record Tommy's decisions; write the contracts and `direction` on `Feature/Conventions`.
2. Deny-list audit, checks, review, PR, merge.
3. Marketplace catalog PR; report to Tommy.
