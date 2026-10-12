---
name: scaffold
description: Deliberately creates nothing — GitHub Actions workflows are written by the scaffold that owns a repository's deploy target, into the File structure `github-actions:structure` records. Use to find which scaffold writes a project's workflows.
kind: utility
domain: github-actions
profile: scaffold
applicability: new GitHub Actions projects
requires: github-actions
provenance: house
---

# GitHub Actions project scaffold

Creates nothing: this package holds conventions, not a scaffolder. Workflows come from the scaffold that owns the
deploy target, such as `azure:scaffold`, and follow this package's contracts.

## Create a project

Run the owning package's scaffold; it writes `.github/` into the File structure `github-actions:structure`
records.

## Build and adapt

Change generated workflows only within this package's contracts.

## Validation and publication

`github-actions:testing` owns workflow validation.
