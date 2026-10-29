---
name: scaffold
description: Generate the canonical deployed-service workflow set from structured provider steps and repository metadata. Use when an app scaffold needs GitHub Actions verification, previews, deployment and optional production releases.
kind: operation
domain: github-actions
profile: scaffold
applicability: deployed-service GitHub Actions projects
requires: github-actions
provenance: house
---

# GitHub Actions project scaffold

The stdlib Python writer makes `pr.yml`, `ci.yml`, `pr-closed.yml`, reusable deploy/destroy workflows,
provider composite actions, Dependabot and workflow lint. `prod.yml` is included by default; the sole
option is `prod-release=false`. It writes one canonical shape. Azure supplies cloud-specific steps and
identity data; this package owns the workflow files and job graph.

## Create a project

Run from this skill directory, using an existing project directory and a provider JSON configuration:

```text
python -B scripts/scaffold.py options
python -B scripts/scaffold.py render --config service.json --repository-files prospective-files.json
python -B scripts/scaffold.py new --project /path/to/repository --config service.json --dry-run
python -B scripts/scaffold.py new --project /path/to/repository --config service.json --set prod-release=false
```

`render` prints a complete JSON file map without writing. App scaffolds import `render(config,
repository_files)` and compose its result into their own atomic transaction. The optional
`--repository-files` JSON file maps repository-relative POSIX paths to prospective file contents;
these override on-disk metadata for `new`. The writer does not write that input overlay.

See [the input contract](docs/input.md) and [the neutral example](examples/service.json). The example
expects the app to supply its test, build and deployment scripts; it is an interface example, not a
runnable app scaffold. The writer runs on Python 3.9+ on Windows, Linux and macOS with no dependencies.

## Build and adapt

Versions come from repository metadata under declared working roots, including ancestors. Toolchain
commands are never parsed. Declare `global.json` for .NET and `package.json` with `engines.node` or a
Node version file; `packageManager` selects an exactly versioned package manager. Include prospective
version files in the file-map API before an outer scaffold writes the app.

The CLI validates before writing, refuses every existing output, uses exclusive file creation and
rolls back the files and directories it created on failure. Existing files remain intact. It records
`.scaffold.github-actions.json`. Invalid input exits 2; write/collision failures exit 1. `--dry-run`
prints resolved options and the file list with no write. `--set prod-release=true|false` overrides the
configuration; defaults apply first. There are no presets or component choices.

## Validation and publication

From the package repository:

```text
python -B -m unittest discover -s .agents/tests -p test_scaffold.py
python -B .agents/tests/verify_workflows.py
python -B .agents/sync_generated.py --root . --check
```

The emitted lint script runs actionlint and zizmor. The package verification workflow runs the writer
checks on Windows and Ubuntu and requires the JavaScript release-assertion tests. Configure the consuming
repository ruleset to require `ci-complete`, and configure production environments to allow `v*` tags.
