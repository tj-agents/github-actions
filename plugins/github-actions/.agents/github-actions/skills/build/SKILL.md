---
name: build
description: Tommy's agreed GitHub Actions runners, toolchain versions and caching. Read before writing or reviewing GitHub Actions that touches it; nothing applies until it is recorded here.
kind: standard
domain: github-actions
profile: core
applicability: GitHub Actions projects
requires: github-actions
provenance: house
---

# GitHub Actions build

Owns runners, toolchain versions and caching.

## Agreed

- Jobs run on GitHub-hosted `ubuntu-latest` by default; a matrix adds `windows-latest` only for a
  cross-platform product.
- Toolchain versions come from repository files (`global-json-file`, `node-version-file`,
  `packageManager`), never from numbers duplicated in YAML. Terraform's version is pinned exactly.
- Dependency caching uses the setup actions' built-in `cache:`; `actions/cache` only covers what they
  cannot.

## Example

```yaml
jobs:
  verify:
    runs-on: ubuntu-latest
```
