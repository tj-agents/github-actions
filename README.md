# github-actions

Tommy's GitHub Actions conventions and canonical deployed-service workflow writer.

Published as plugin `tj-agents/github-actions` from the `tj-agents` marketplace.

## Skills

- Knowledge: `github-actions:direction`, `github-actions:knowledge`, `github-actions:learning`.
- Contracts: `github-actions:build`, `github-actions:domain-design`, `github-actions:errors`,
  `github-actions:libraries`, `github-actions:security`, `github-actions:structure`,
  `github-actions:style`, `github-actions:testing`.
- Utility: [github-actions:scaffold](.agents/github-actions/utility/scaffold/SKILL.md), a Python 3.9+
  stdlib writer with a JSON CLI and pure complete-file-map API. Providers supply cloud steps and data;
  this package owns the workflow set, reusable graph, pins, composites, Dependabot and lint.
- Utility: [github-actions:merge-policy](.agents/github-actions/utility/merge-policy/SKILL.md) applies
  Tommy's personal `.github/merge-policy.json` as the repository's GitHub ruleset; its composite action
  `.github/actions/merge-policy-check` reports drift in CI.

- Utility: [github-actions:machine-events](.agents/github-actions/utility/machine-events/SKILL.md)
  prepares explicitly adopted publishers for the personal machine channel. Core owns the listener and
  [refresh lifecycle](https://github.com/tj-agents/core#machine-setup-and-updates).

## Personal automation and employer projects

Selecting this package makes its utilities available; it does not invoke them or adopt their personal
configuration. The generic scaffold generates CI and deployment files without a personal publisher or
merge-policy declaration. Publisher enrollment and personal ruleset application follow their linked
utility scopes and owner checks. For example, scaffolding an employer service produces no
`machine-events.yml` or `.github/merge-policy.json`.

Local agent adoption belongs to
[machine:plugin-selection](https://github.com/tj-agents/core/blob/main/.agents/machine/utility/plugin-selection/SKILL.md),
including employer-project settings and Git metadata exclusions for linked worktrees. Refreshing an
already selected plugin updates its installed code; it does not change the project's adopted profile.

## Authoring and verification

```text
python -B -m unittest discover -s .agents/tests -p test_scaffold.py
python -B -m unittest discover -s .agents/tests -p test_merge_policy.py
python -B -m unittest discover -s .agents/tests -p test_machine_events.py
python -B .agents/tests/verify_workflows.py
python -B .agents/sync_generated.py --root .
python -B .agents/sync_generated.py --root . --check
```

The layout, vendored generator and base CI come from [Template](https://github.com/tj-agents/template).
The additional writer verification runs on Windows and Ubuntu; it lints emitted workflows and executes
release assertions against a mocked GitHub API without running app/cloud toolchains.
