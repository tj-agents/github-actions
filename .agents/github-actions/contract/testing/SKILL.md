---
name: testing
description: Tommy's agreed GitHub Actions workflow validation, required-check gate, test-job layout and test artifacts. Read before writing or reviewing GitHub Actions that touches it; nothing applies until it is recorded here.
kind: contract
domain: github-actions
profile: core
applicability: GitHub Actions projects
requires: github-actions
provenance: house
---

# GitHub Actions testing

Owns workflow validation, the required-check gate, test-job layout and test artifacts.

## Agreed

- Workflows are validated in CI by `actionlint` (correctness) and `zizmor` (security).
  Enforced by Template's shared `plugin-ci.yml` workflow gate. Source: actionlint; zizmor.
- Required checks aggregate into one `ci-complete` job (`if: always()`, `needs:` every gate, fails unless
  all succeeded). The ruleset requires only that context. Why: lets jobs be added without touching the
  ruleset. Source: survey of production services and Tommy's repositories, 2026-10-12.
- Test jobs are split by layer so a red check names the layer. Unit and container-backed integration
  tests run on the pull request; end-to-end runs against a deployed environment.
- Uploaded artifacts set `if-no-files-found` (`error` for evidence, `warn` for diagnostics) and an
  explicit `retention-days`.

After a workflow edit, run the same checks locally for immediate feedback; `template:check` owns its
workflow standards checker. Use the repository's `.github/zizmor.yml` when present; otherwise use
`<template-check-directory>/scripts/zizmor.yml` as `<zizmor-config>`. Existing public API and required
check names use exact baselines with reasons.

```text
actionlint
uvx --python 3.12 zizmor==1.32.0 --offline --pedantic --config <zizmor-config> .github
uv run --python 3.12 --with pyyaml==6.0.3 python <template-check-directory>/scripts/check_workflows.py --root .
```
