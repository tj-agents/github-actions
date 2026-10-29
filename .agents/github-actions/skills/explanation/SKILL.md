---
name: explanation
description: How workflow YAML is quoted when explaining GitHub Actions. Use when an explanation shows a workflow or action definition.
kind: standard
domain: github-actions
profile: core
applicability: GitHub Actions projects
requires: github-actions
provenance: house
---

# Explaining GitHub Actions

Owns how workflow YAML is quoted in an explanation.

Quote each file in its own top-level `yaml` block, never indented inside a list item, under a
`path:line` line. Copy the YAML verbatim and replace checkout and setup steps, permissions, env blocks
and other keys the point does not need with `...`.

## Example

`.github/workflows/ci.yml:9`
```yaml
jobs:
  verify:
    uses: tj-agents/template/.github/workflows/plugin-ci.yml@main
    with:
      template_ref: main
    ...
```
