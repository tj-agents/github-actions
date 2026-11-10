---
name: style
description: Tommy's agreed GitHub Actions style — naming, formatting, comments and lint policy. Read before writing or reviewing GitHub Actions that touches it; nothing applies until it is recorded here.
kind: contract
domain: github-actions
profile: core
applicability: GitHub Actions projects
requires: github-actions
provenance: house
---

# GitHub Actions style

Owns naming, formatting, comments and lint policy.

## Agreed

- Workflow `name:` is short Title Case (`PR`, `CI`, `Release (Production)`); job ids are kebab-case. Every
  job has a sentence-case `name:` saying what it proves or does. Steps are named unless a bare setup
  `uses:` or a self-evident one-line `run:`. Enforced by Template `check_workflows.py` for initial
  capitals, job ids and required names; review Title Case and whether names explain the work.
- Inputs and outputs of actions, reusable workflows and `workflow_dispatch` are kebab-case; secrets and
  environment variables are SCREAMING_SNAKE. Why: matches GitHub's own actions (`persist-credentials`).
  Source: survey of production services and Tommy's repositories, 2026-10-12.
  Enforced by Template `check_workflows.py`.
- Multi-line bash `run:` blocks start with `set -euo pipefail`. Enforced by Template `check_workflows.py`.
- A YAML comment carries only a *why* the line itself cannot show, such as an ordering constraint or a
  platform limitation.

```yaml
name: CI
jobs:
  unit-tests:
    name: Run unit tests
    runs-on: ubuntu-latest
    steps:
      - name: Run checks
        run: |
          set -euo pipefail
          npm run lint
          npm test
```
