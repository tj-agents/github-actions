---
name: structure
description: Tommy's agreed GitHub Actions project structure — repository and module layout, visibility and wiring. Read before writing or reviewing GitHub Actions that touches it; nothing applies until it is recorded here.
kind: contract
domain: github-actions
profile: core
applicability: GitHub Actions projects
requires: github-actions
provenance: house
---

# GitHub Actions structure

Owns the repository and module layout, visibility, and where dependencies are wired.

## Agreed

- A deployed service has `pr.yml` (pull request verification and an optional preview), `ci.yml` (push to
  `main`: verify, then deploy to the shared non-production environment), `prod.yml` (tag-triggered
  production) and `pr-closed.yml` (preview teardown). A library, tool or plugin has `ci.yml` and, if it
  publishes, `release.yml`. Source: survey of production services and Tommy's repositories, 2026-10-12.
- A step sequence repeated across jobs is a composite action at `.github/actions/<kebab-name>/action.yml`;
  a whole job reused by several callers, such as a per-region deploy, is a reusable workflow
  (`on: workflow_call`). Use a composite where the caller's job name must remain the check context.
  Source: survey of production services and Tommy's repositories, 2026-10-12.
- Shared cross-repository workflows live in one pipeline repository, and callers pin them as
  `github-actions:security` requires.

## File structure

```text
.github/
  dependabot.yml
  actions/<name>/action.yml
  workflows/
    pr.yml  ci.yml  prod.yml  pr-closed.yml      deployed service
    ci.yml  release.yml                          library, tool or plugin
    <verb>-<object>.yml                          reusable workflows, e.g. deploy-region.yml
```

`github-actions:scaffold` owns the complete deployed-service workflow files and reusable job graph.
The app scaffold composes its pure file map with app and provider output; Azure supplies cloud-specific
steps and identity data. Source: Tommy's 2026-10-13 writer decision, superseding the conventions-only boundary.
