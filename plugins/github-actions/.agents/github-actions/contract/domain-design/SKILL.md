---
name: domain-design
description: Tommy's agreed GitHub Actions pipeline design — artifacts, releases, environments, regions, previews and cutover. Read before writing or reviewing GitHub Actions that touches it; nothing applies until it is recorded here.
kind: contract
domain: github-actions
profile: core
applicability: GitHub Actions projects
requires: github-actions
provenance: house
---

# GitHub Actions pipeline design

Owns the pipeline model: artifacts, releases, environments, regions, previews and cutover.

## Agreed

- Every deploy references an immutable artifact: an image by digest (`repo@sha256:…`) or a versioned
  package, never a mutable tag. Why: what was verified is what ships. Source: survey of production
  services and Tommy's repositories, 2026-10-12.
- Production is released by pushing a semver tag (`v[0-9]+.[0-9]+.[0-9]+`). The release workflow's first
  job asserts the tag's commit is the latest green `ci.yml` run on `main`.
  The writer promotes a declared deployment artifact from that verified run by immutable artifact ID;
  a provider without an artifact declaration resolves its immutable image/package from the same verified
  commit. This implements the existing verified-artifact rule, not an additional release setting.
- One GitHub environment per deploy target (`ci`, `preview`, `prod` or `<region>-prod`), holding that
  target's `vars`, secrets and protection rules. Production environments allow deployments from `v*` tags
  only.
- Several regions deploy as a matrix over regions with `fail-fast: false` and `environment: <region>-prod`,
  so each region's settings share names inside its own environment. Why: the named-job variant duplicates
  each job per region. Source: survey of production services and Tommy's repositories, 2026-10-12.
- Per-pull-request preview instances are opt-in through a `deploy-preview` label and named
  `pr-<number>`, with their own state key. `pr-closed.yml` destroys them on close, whether merged or not.
  Why: cost.
- A deploy job succeeds only once the new revision or slot is serving, not merely ready.
