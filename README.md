# github-actions

Tommy's GitHub Actions conventions and canonical deployed-service workflow writer.

Published as plugin `github-actions` from this repository's `github-actions-agents` marketplace.

## Skills

- Knowledge: `github-actions:direction`, `github-actions:knowledge`, `github-actions:learning`.
- Contracts: `github-actions:build`, `github-actions:domain-design`, `github-actions:errors`,
  `github-actions:libraries`, `github-actions:security`, `github-actions:structure`,
  `github-actions:style`, `github-actions:testing`.
- Utility: [github-actions:scaffold](.agents/github-actions/utility/scaffold/SKILL.md), a Python 3.9+
  stdlib writer with a JSON CLI and pure complete-file-map API. Providers supply cloud steps and data;
  this package owns the workflow set, reusable graph, pins, composites, Dependabot and lint.

## Authoring and verification

```text
python -B -m unittest discover -s .agents/tests -p test_scaffold.py
python -B .agents/tests/verify_workflows.py
python -B .agents/sync_generated.py --root .
python -B .agents/sync_generated.py --root . --check
```

The layout, vendored generator and base CI come from [kit](https://github.com/tj-agents/kit).
The additional writer verification runs on Windows and Ubuntu; it lints emitted workflows and executes
release assertions against a mocked GitHub API without running app/cloud toolchains.
