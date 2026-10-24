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
other owners and `tj-agents/infonetica` before contacting GitHub. Employer repositories keep their own protections. Selecting
GitHub Actions alone does not adopt this policy.

A repository records who may merge in `.github/merge-policy.json`:

```json
{
  "enabled": true,
  "agents_may_merge": false,
  "required_checks": ["ci-required"]
}
```

- `enabled` defaults to `true`. Set it to `false` to disable the owned `merge-policy` ruleset and
  repository auto-merge. Keep the declaration: deleting it relinquishes management and leaves existing
  GitHub settings unchanged. Other repository and organization rulesets remain authoritative.
- `agents_may_merge: false`: every PR needs one approval of its most recent push. Agents push as the bot
  account, so the approver is Tommy.
- `ci_pushes_default_branch: true`: deploy keys may push to the default branch, for a post-merge job
  that commits generated files. GitHub rejects the GitHub Actions app as a repository ruleset bypass
  actor, so that job pushes with a write deploy key whose private key is a secret of an environment
  limited to the default branch; a workflow on any other branch cannot read it.
- `agents_may_merge: true`: no approval; agents merge once `required_checks` and the optional
  `review_check` (an automated review job on the PR head) pass. A repository without the file has no gate.

Every enabled policy requires a PR and blocks deletion and force-push of the default branch. The repository admin
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

`apply` converges repository auto-merge and the complete owned ruleset, including bypass actors and
its enabled state. It performs no writes when current. With the policy enabled, an approval or passing
checks land an armed PR without a merge click. It needs repository admin rights. Tommy runs it, at repository
creation and whenever the flag changes; agents use `--dry-run` only. GitHub Free enforces repository
rulesets only on public repositories, so `apply` fails on a private repository in a Free organization.

`sync --owner X [--owner Y]` covers every public, non-fork repository of those accounts, excluding the
known employer project: it delegates each repository to `reconcile`, pins the policy to the current
default-branch commit, and compares the complete owned ruleset and repository auto-merge setting. A
repository without the file is left alone. Declaring or changing the file is a PR, so turning a gate off needs Tommy's approval. It needs admin rights, so it
runs as Tommy, never as an agent.

`check` compares the rules GitHub enforces on the default branch with the policy. Every check it requires
must run on every PR, without path filters, or that PR can never merge. It exits 1 on drift and
2 on an invalid policy or failed API call. In CI, call the composite action pinned to a commit SHA:

```yaml
- uses: tj-agents/github-actions/.github/actions/merge-policy-check@<sha> # vX.Y.Z
```

`reconcile --repo OWNER/NAME` is the background subscriber entry point. Add `--check` for a read-only
comparison: exit 0 means current or undeclared, 1 means drift, and 2 means invalid configuration or API
failure. Core setup uses this check before deciding whether to converge settings. It resolves the current default-branch commit from GitHub, validates the policy at that commit and applies only a declared policy. It compares the complete owned ruleset before writing, including bypass actors. Core owns machine setup and catch-up; it delegates policy convergence here. The hint supplies no policy
or ref. Agents may edit and validate the reviewed configuration, but never obtain Tommy's admin token to
apply it. Keep admin sync in Tommy's separately controlled session or service identity. Concertable's
pipeline-managed rulesets retain their existing owner; do not add a competing personal declaration.

For example, Tommy can explicitly converge the declared personal policies with one command on Windows
(use `python3` on Linux/macOS):

```text
python -B scripts/merge_policy.py sync --owner tj-agents --owner tomjseery
```

After changing `enabled` to `false` in a reviewed policy, that same sync disables only this utility's
owned ruleset and repository auto-merge. Repeating the command reports current without writes.

Complete owned-policy verification requires ruleset write access because GitHub hides bypass actors from other identities. Missing bypass evidence fails verification; it is not reported as confirmed drift. Run that check through Tommy's separately controlled admin path.
