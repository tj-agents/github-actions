---
name: libraries
description: Tommy's agreed GitHub Actions dependency policy — which actions to depend on and how they are kept current. Read before writing or reviewing GitHub Actions that touches it; nothing applies until it is recorded here.
kind: standard
domain: github-actions
profile: core
applicability: GitHub Actions projects
requires: github-actions
provenance: house
---

# GitHub Actions libraries

Owns which actions to depend on and how they are kept current.

## Agreed

- Prefer first-party `actions/*`, then the vendor's own action (`azure/*`, `docker/*`, `hashicorp/*`). A
  community action needs a reason, and a short script beats a single-purpose marketplace action. Use
  `actions/github-script` for GitHub API calls.
- `.github/dependabot.yml` updates the `github-actions` ecosystem weekly in one grouped pull request.

## Example

```yaml
version: 2
updates:
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
    groups:
      github-actions:
        patterns:
          - '*'
```
