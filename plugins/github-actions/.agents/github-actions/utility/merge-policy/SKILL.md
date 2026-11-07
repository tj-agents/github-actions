---
name: merge-policy
description: Render Tommy's personal repository merge policy from `.github/merge-policy.json` as its GitHub ruleset and report drift in CI. Use when creating a personal repository, changing whether it requires approval before merge, or protecting its default branch.
kind: utility
domain: github-actions
profile: scaffold
applicability: GitHub repositories
requires: github-actions
provenance: house
---

# Merge policy

This utility implements Tommy's personal merge arrangement. It applies only in explicitly personal
repositories under `tj-agents`, `Concertable` or `tomjseery`. Employer repositories keep their own
protections. Selecting GitHub Actions alone does not adopt this policy. Ruleset writes themselves are
owned by tj-agents/github's `github:configuration` Terraform workspace, not this utility.

A repository records whether a PR needs human approval before it can merge, not who is allowed to click
merge, in `.github/merge-policy.json`:

```json
{
  "requires_approval": true,
  "required_checks": ["ci-required"]
}
```

- `requires_approval: true`: every ordinary source or agent-authored PR needs one non-author approval before
  it merges. That approval remains valid after later pushes to the same PR; required checks and source review
  still apply to the current head. Agents push as the bot account, so the approver is Tommy. Once that approval
  and the required checks are in place, merging the PR — by Tommy or by an agent — is not separately gated; the
  ruleset only enforces that the approval and checks exist first.
- `ci_pushes_default_branch: true`: deploy keys may push to the default branch, for a post-merge job
  that commits generated files. GitHub rejects the GitHub Actions app as a repository ruleset bypass
  actor, so that job pushes with a write deploy key whose private key is a secret of an environment
  limited to the default branch; a workflow on any other branch cannot read it.
- `requires_approval: false`: no approval; a PR merges once `required_checks` and the optional
  `review_check` (an automated review job on the PR head) pass. A repository without the file has no gate.

Every policy requires a PR and blocks deletion and force-push of the default branch. The repository admin
role may bypass only through a PR; an organization owner does not hold that role, so in `tj-agents` a
PR Tommy pushed himself needs an approval from someone else. The bot account must never be an
admin: that, not this script, stops an agent from merging past the policy or applying a ruleset.
The ruleset is named `merge-policy`; other rulesets, such as a merge queue, are left alone.

The updater App's bypass on the merge-policy ruleset, for generated publication, is declared alongside the
rest of the ruleset in tj-agents/github's `github:configuration` Terraform workspace, not by this utility.
The [publication setup](../publish-update/SKILL.md#generated-updater-pull-requests) owns the narrowly scoped
automatic-merge exception for verified generator output, including bootstrap migrations. It does not turn off
approval for ordinary PRs. Merely finding an App with a conventional name or receiving a publication hint
grants no bypass or merge authority.

## Commands

Run from this skill directory, with `python` on Windows and `python3` on Linux/macOS. The `gh` CLI must
be signed in.

```text
python -B scripts/merge_policy.py render --policy <repo>/.github/merge-policy.json
python -B scripts/merge_policy.py check --repo OWNER/NAME --policy <repo>/.github/merge-policy.json
```

`render` prints the ruleset a policy implies, for review. Creating, updating and reconciling the ruleset
itself is Terraform's job in tj-agents/github's `github:configuration`, not this script.

`check` compares the rules GitHub enforces on the default branch with the policy. Every check it requires
must run on every PR, without path filters, or that PR can never merge. It exits 1 on drift and
2 on an invalid policy or failed API call. In CI, call the composite action pinned to a commit SHA:

```yaml
- uses: tj-agents/github-actions/.github/actions/merge-policy-check@<sha> # vX.Y.Z
```
