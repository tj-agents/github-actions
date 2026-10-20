---
name: merge-policy
description: Apply or check a repository's merge policy, from `.github/merge-policy.json` (may agents merge without Tommy?), as its GitHub ruleset, and report drift in CI. Use when creating a repository, changing who may merge, or protecting a default branch.
kind: utility
domain: github-actions
profile: scaffold
applicability: GitHub repositories
requires: github-actions
provenance: house
---

# Merge policy

A repository records who may merge in `.github/merge-policy.json`:

```json
{
  "agents_may_merge": false,
  "required_checks": ["ci-required"]
}
```

- `agents_may_merge: false`: every PR needs one approval of its most recent push. Agents push as the bot
  account, so the approver is Tommy.
- `agents_may_merge: true`: no approval, but `review_check` (the automated review job on the PR head) must
  pass, along with `required_checks`.

Every policy requires a PR, blocks deletion and force-push of the default branch, and grants no bypass.
The ruleset is named `merge-policy`; other rulesets, such as a merge queue, are left alone.

## Commands

Run from this skill directory, with `python` on Windows and `python3` on Linux/macOS. The `gh` CLI must
be signed in.

```text
python -B scripts/merge_policy.py render --policy <repo>/.github/merge-policy.json
python -B scripts/merge_policy.py apply --repo OWNER/NAME --policy <repo>/.github/merge-policy.json --dry-run
python -B scripts/merge_policy.py check --repo OWNER/NAME --policy <repo>/.github/merge-policy.json
```

`apply` creates or updates the ruleset and needs repository admin rights. Tommy runs it, at repository
creation and whenever the flag changes; agents use `--dry-run` only. GitHub Free enforces repository
rulesets only on public repositories, so `apply` fails on a private repository in a Free organization.

`check` compares the rules GitHub enforces on the default branch with the policy. It exits 1 on drift and
2 on an invalid policy or failed API call. In CI, call the composite action pinned to a commit SHA:

```yaml
- uses: tj-agents/github-actions/.github/actions/merge-policy-check@<sha> # vX.Y.Z
```
