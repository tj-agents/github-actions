---
name: security
description: Tommy's agreed GitHub Actions security — token permissions, action pinning, credentials, untrusted input and cloud sign-in. Read before writing or reviewing GitHub Actions that touches it; nothing applies until it is recorded here.
kind: contract
domain: github-actions
profile: core
applicability: GitHub Actions projects
requires: github-actions
provenance: house
---

# GitHub Actions security

Owns token permissions, action pinning, credentials, untrusted input and cloud sign-in.

## Agreed

- Top-level `permissions: contents: read`; each job adds only the scopes it uses, and an aggregator job
  sets `permissions: {}`. Source: GitHub secure-use reference; survey of production services and Tommy's
  repositories, 2026-10-12.
- Every `uses:` of a remote action or reusable workflow is pinned to a full commit SHA with a trailing
  `# vX.Y.Z` comment; local `./` actions are exempt; never a branch ref such as `@main`. Dependabot's
  `github-actions` ecosystem moves the pins; enable "Require actions to be pinned to a full-length commit
  SHA" where the repository or organization allows it. Revisit GitHub's `actions.lock` lockfile when it
  leaves preview. Why: tag moves are the tj-actions and trivy-action attack class. Source: GitHub
  changelog 2025-08-15; survey of production services and Tommy's repositories, 2026-10-12.
- `actions/checkout` always sets `persist-credentials: false`. Why: a stored token is readable by every
  later step. Source: survey of production services and Tommy's repositories, 2026-10-12.
- Untrusted values (`github.event.*` text, `github.head_ref`, `inputs.*`) never appear as `${{ }}` inside
  `run:` or `script:`; pass them through `env:`. Source: GitHub secure-use reference.
- No `pull_request_target` that checks out pull request code. Why: GitHub's guidance, and the 2026
  trivy-action compromise. Source: GitHub secure-use reference.
- Secrets go in the `env:` of the step that uses them, never workflow-level `env:`. Identifiers that are
  not credentials (tenant, subscription and client IDs, storage account names) are `vars`, not `secrets`.
  Source: survey of production services and Tommy's repositories, 2026-10-12.
- Cloud sign-in on hosted runners is OIDC federation with no stored credential: `azure/login` with
  `client-id`, `tenant-id` and `subscription-id` from `vars`, and `id-token: write` only on the job that
  signs in. The `azure` package owns the identity and federated-credential subjects. Source: GitHub OIDC
  in Azure guide.
