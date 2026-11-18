---
name: merge-policy
description: Render Tommy's personal repository merge policy from the `merge` section of `.agents/repository.json` as its GitHub ruleset and report drift in CI. Use when creating a personal repository, changing who approves or merges its pull requests, or protecting its default branch.
kind: utility
domain: github-actions
profile: scaffold
applicability: GitHub repositories
requires: github-actions
provenance: house
---

# Merge policy

Read and follow the [canonical definition](../../.agents/github-actions/utility/merge-policy/SKILL.md) in full.
This discovery entry is generated; edit the referenced `.agents/` definition.
