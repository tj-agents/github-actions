---
name: merge-policy
description: Render Tommy's personal repository merge policy from `.github/merge-policy.json` as its GitHub ruleset and report drift in CI. Use when creating a personal repository, changing who approves or merges its pull requests, or protecting its default branch.
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

A repository records who gates and who merges its pull requests in `.github/merge-policy.json`. A
repository without one takes its owner's default, `.github/merge-policy.json` in the `<owner>/.github`
repository; a repository file replaces that default entirely. Every field below except `required_checks`
is required, and any other field is rejected.

```json
{
  "approval": "human",
  "merge": "agents",
  "default_branch_push": "ci",
  "required_checks": ["ci-required"]
}
```

- `approval` — what a PR needs, besides `required_checks`, before it merges:
  - `human`: one non-author approval. It remains valid after later pushes to the same PR; required checks
    and source review still apply to the current head. Agents push as the bot account, so the approver is
    Tommy.
  - `automated`: no approval; the check named by `review_check` (an automated review job on the PR head)
    must pass as well. `review_check` is required with `automated` and rejected otherwise.
  - `none`: no approval; the PR merges once `required_checks` pass.
- `merge` — who merges once those gates pass:
  - `agents`: an agent or Tommy may merge; the ruleset only enforces that the gates are met first.
  - `human`: only Tommy merges. Agents in that repository are denied `gh pr merge` (Claude `Bash` and
    `PowerShell`, Codex prefix rules) and the GitHub MCP `merge_pull_request` tool through repository-scoped
    permissions. Run `harness`, then regenerate the repository's host settings with Agent's
    `agent:plugins` tooling, which commits the overlay into `.claude/settings.json` and the Codex rules.
    GitHub has no rule that stops one push-capable account merging, so this is an agent denial, not a
    ruleset rule.
- `default_branch_push` — `ci` lets deploy keys push to the default branch, for a post-merge job that
  commits generated files; `none` lets nobody push outside a PR. GitHub rejects the GitHub Actions app as a
  repository ruleset bypass actor, so that job pushes with a write deploy key whose private key is a secret
  of an environment limited to the default branch; a workflow on any other branch cannot read it.

Every policy requires a PR and blocks deletion and force-push of the default branch. The repository admin
role may bypass only through a PR; an organization owner does not hold that role, so in `tj-agents` a
PR Tommy pushed himself needs an approval from someone else. The bot account must never be an
admin: that, not this script, stops an agent from merging past the policy or applying a ruleset.
The ruleset is named `merge-policy`; other rulesets, such as a merge queue, are left alone.

Hosted Mend Renovate produces dependency PRs under its own installed identity. Its dependency check and any
no-human-review path are explicit configuration in tj-agents/github's `github:configuration` workspace;
they are not a ruleset bypass granted by this utility. Ordinary source and agent-authored PRs continue to
use the policy above. The existing protected generated-publication App grant is also declared by that
settings owner, separately from Renovate's check and no-human-review path. An App name or a Renovate event
grants no merge authority.

## Commands

Run from this skill directory, with `python` on Windows and `python3` on Linux/macOS (Python 3.12+). The
`gh` CLI must be signed in whenever the owner default is read or GitHub is checked.

```text
python -B scripts/merge_policy.py render --policy <repo>/.github/merge-policy.json [--repo OWNER/NAME]
python -B scripts/merge_policy.py harness --repo OWNER/NAME --policy <repo>/.github/merge-policy.json --harness <repo>/.agents/repository-harness.json
python -B scripts/merge_policy.py check --repo OWNER/NAME --policy <repo>/.github/merge-policy.json --harness <repo>/.agents/repository-harness.json
```

Each command reads the repository file when it exists, otherwise the owner default from GitHub; `--repo`
names the owner whose default applies. A missing or unreadable owner default is an error, never an empty
policy.

`render` prints the ruleset a policy implies, for review. Creating, updating and reconciling the ruleset
itself is Terraform's job in tj-agents/github's `github:configuration`, which resolves the same owner
default; this script never writes to GitHub.

`harness` adds the `merge: human` denials to `.agents/repository-harness.json`, creating it when needed, or
removes exactly those entries for `merge: agents`. The overlay's other entries are the repository's own and
are left as they are.

`check` compares the rules GitHub enforces on the default branch, and the harness overlay, with the policy.
Every check it requires must run on every PR, without path filters, or that PR can never merge. It exits 1
on drift and 2 on an invalid or missing policy or a failed API call. In CI, call the composite action pinned
to a commit SHA; its token must be able to read the `<owner>/.github` repository when the owner default
applies:

```yaml
- uses: tj-agents/github-actions/.github/actions/merge-policy-check@<sha> # vX.Y.Z
```
