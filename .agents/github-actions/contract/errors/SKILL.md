---
name: errors
description: Tommy's agreed GitHub Actions failure, cancellation and concurrency policy. Read before writing or reviewing GitHub Actions that touches it; nothing applies until it is recorded here.
kind: contract
domain: github-actions
profile: core
applicability: GitHub Actions projects
requires: github-actions
provenance: house
---

# GitHub Actions errors

Owns failure, cancellation and concurrency policy.

## Agreed

- Every workflow sets `concurrency:`. Verification groups on
  `${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}` with
  `cancel-in-progress: true`. Deploys, applies and teardowns use a fixed group per environment with
  `cancel-in-progress: false`. A teardown shares its preview's group.
- A workflow that cancels runs which hold infrastructure state has an `if: cancelled()` job that releases
  the leaked lock.
- Every job sets `timeout-minutes`.
- A job that depends on a deploy uses `if: ${{ !cancelled() && needs.<job>.result == 'success' }}`.
  Annotations use `::error file=…::` so a failure points at its cause.
