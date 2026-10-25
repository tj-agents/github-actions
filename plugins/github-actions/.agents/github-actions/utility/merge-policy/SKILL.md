---
name: merge-policy
description: Apply or check Tommy's personal repository merge policy from `.github/merge-policy.json` as its GitHub ruleset and report drift in CI. Use when creating a personal repository, changing who may merge in it, or protecting its default branch.
kind: utility
domain: github-actions
profile: scaffold
applicability: GitHub repositories
requires: github-actions
provenance: house
---

# Merge policy

This utility implements Tommy's personal merge arrangement. Apply it only in explicitly personal
repositories under `tj-agents`, `Concertable` or `tomjseery`; `apply`, `sync` and `reconcile` reject
other owners before contacting GitHub. Employer repositories keep their own protections. Selecting
GitHub Actions alone does not adopt this policy.

A repository records who may merge in `.github/merge-policy.json`:

```json
{
  "agents_may_merge": false,
  "required_checks": ["ci-required"]
}
```

- `agents_may_merge: false`: every PR needs one non-author approval. That approval remains valid after
  later pushes to the same PR; required checks and source review still apply to the current head. Agents
  push as the bot account, so the approver is Tommy.
- `ci_pushes_default_branch: true`: deploy keys may push to the default branch, for a post-merge job
  that commits generated files. GitHub rejects the GitHub Actions app as a repository ruleset bypass
  actor, so that job pushes with a write deploy key whose private key is a secret of an environment
  limited to the default branch; a workflow on any other branch cannot read it.
- `agents_may_merge: true`: no approval; agents merge once `required_checks` and the optional
  `review_check` (an automated review job on the PR head) pass. A repository without the file has no gate.

Every policy requires a PR and blocks deletion and force-push of the default branch. The repository admin
role may bypass only through a PR; an organization owner does not hold that role, so in `tj-agents` a
PR Tommy pushed himself needs an approval from someone else. The bot account must never be an
admin: that, not this script, stops an agent from merging past the policy or applying a ruleset.
The ruleset is named `merge-policy`; other rulesets, such as a merge queue, are left alone.

## Commands

Run from this skill directory, with `python` on Windows and `python3` on Linux/macOS. The `gh` CLI must
be signed in.

```text
python -B scripts/merge_policy.py render --policy <repo>/.github/merge-policy.json
python -B scripts/merge_policy.py apply --repo OWNER/NAME --policy <repo>/.github/merge-policy.json --dry-run
python -B scripts/merge_policy.py check --repo OWNER/NAME --policy <repo>/.github/merge-policy.json
```

`apply` enables auto-merge, so an approval or passing checks land a PR without a merge click, then
creates or updates the ruleset. It needs repository admin rights. Tommy runs it, at repository
creation and whenever the flag changes; agents use `--dry-run` only. GitHub Free enforces repository
rulesets only on public repositories, so `apply` fails on a private repository in a Free organization.

`sync --owner X [--owner Y]` covers every public, non-fork repository of those accounts: it reads each
repository's `.github/merge-policy.json` and applies it wherever GitHub has drifted; a repository without
the file is left alone. Declaring or changing the file is a PR, so turning a gate off needs Tommy's approval. It needs admin rights, so it
runs as Tommy, never as an agent.

`check` compares the rules GitHub enforces on the default branch with the policy. Every check it requires
must run on every PR, without path filters, or that PR can never merge. It exits 1 on drift and
2 on an invalid policy or failed API call. In CI, call the composite action pinned to a commit SHA:

```yaml
- uses: tj-agents/github-actions/.github/actions/merge-policy-check@<sha> # vX.Y.Z
```

`reconcile --repo OWNER/NAME` is the background subscriber entry point. It resolves the current default-branch commit from GitHub, validates the policy at that commit and applies only a declared policy. It compares the complete owned ruleset before writing, including bypass actors. Core setup runs it as Tommy in response to hints and after an offline interval. The hint supplies no policy or ref.
