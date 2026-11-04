---
name: publish-update
description: Publish a configured repository's verified default-branch update hint for an independently authorized consumer. Use when enrolling a repository or rendering its shared publisher workflow.
kind: utility
domain: github-actions
profile: core
applicability: GitHub repositories
requires: python
provenance: house
---

# Publish update

Enroll publishers explicitly. Selecting the GitHub Actions package or scaffolding a service does not
enroll a repository.

This package owns the publisher action, updater action and canonical reusable workflows. The uniform
caller renders generated thin trigger workflow files that call those canonical workflows with explicitly
mapped secrets. `UPDATE_TOPIC` is private repository configuration: set the Actions variable and secret to
the same value. The caller maps the secret to the canonical workflow, which reads it only in the action
input, so public workflow source does not disclose it. Hints contain a repository and change categories,
never file contents. Consumers authenticate and authorize their own actions after re-reading GitHub;
publication grants no authority.

On Windows use `python`; on Linux use `python3`. Render or install the caller with the immutable publisher
commit to use:

```text
python -B scripts/caller.py --revision <40-character-sha> --project <repository>
```

Render the scheduled pin updater with an explicit action-repository allowlist:

```text
python -B scripts/caller.py --updater --revision <40-character-sha> --repositories <owner/repository>[,<owner/repository>]
```

The thin publisher caller listens for a completed `ci` workflow run. The canonical workflow accepts only a
successful `ci` run for a push on its own repository's default branch; pull requests, forks and unsuccessful
runs publish nothing. Before publishing, it re-reads the current default-branch head and suppresses a run
whose SHA is no longer current. The v1 hint includes that verified SHA as well as the repository and change
categories.

Observed sequence: source merge → regeneration commit → successful CI at the current default-branch head →
notification. A failed or superseded CI run produces no notification. Do not add a direct post-push publisher
call or a `published: 'true'` bypass; the verified CI completion is the publication path.

Possession of the ntfy topic is not authentication or consumer authority. The receiver decides whether to
act, and this public workflow never merges code.

The colocated `update-pins` action updates full-SHA `uses:` references in tracked `.github` YAML only when
the referenced action or workflow content changes. When advancing the GitHub Actions revision, it also
regenerates an already enrolled thin `publish-update.yml` through the same caller generator, so its trigger
matches the verified-CI caller; it preserves CRLF and refuses regeneration that would discard custom jobs or
settings. It then opens a pull request with a repository-scoped App token. Both pin updates and Template's
regeneration select the caller's `update-pins` environment, restricted to its exact default branch.
`UPDATE_APP_CLIENT_ID` is an organization variable. `UPDATE_APP_PRIVATE_KEY` is an environment secret;
the caller still passes it by name to the reusable workflow. Core CI computes export and digest hashes;
this action does not update them.

An organization owner bootstraps publication once from this skill directory:

```text
python -B scripts/owner_setup.py --owner tj-agents
uv run --locked --script scripts/owner_setup.py --owner tj-agents --apply
```

Preview is offline. Apply's locked environment supplies its cryptographic verifier on Windows and Linux.
It requires the owner's own GitHub sign-in and refuses agent sessions and token
overrides. It configures `<owner>-pin-updater` for contents, pull requests and workflows write, plus a
separate `<owner>-enrollment-controller` for contents and secret metadata read, administration and
environments write. The controller key stays in `<owner>/github-actions`' protected `update-enrollment`
environment. Only the updater key reaches consumer `update-pins` environments.

Enrollment selects same-owner, non-fork, non-archived repositories whose default branch either has a
matching `.agents/plugins/template.json` or declares custom generated-file publication in
`.github/update-enrollment.json`. A custom publisher owns generation and opts in with this exact file:

```json
{
  "schema_version": 1,
  "repository": "tj-agents/core"
}
```

The central workflow checks both declarations at the same verified default-branch commit. It verifies exact
branch restrictions before uploading a key, preserves additional deployment protections, and reconciles
each declared merge policy with the verified updater App bypass. Each supplied key authenticates as its
intended App before upload.
Bootstrap removes legacy unprotected updater secrets after replacements are read back and before new
bypass grants. An organization-wide exposure requires the owner to revoke previously distributed keys
and supply a fresh one; deleting a secret cannot revoke a copied key. Key values never appear in
diagnostics or local enrollment state.

Trusted central automation uses `scripts/enrollment.py` to enroll repositories and open a caller-bootstrap
pull request through the same implementation. It checks only the central default branch, uses separate
controller and repository-scoped updater tokens, and never executes consumer code. Its apply path requires
the central repository's current default branch and a controller installation token. First token minting,
post-merge publication and installed startup still require actual rollout verification; successful source
checks do not establish them.

For an existing fleet, `scripts/prepare_callers.py --inventory <json> --revision <sha> --output <directory>`
prepares each repository caller without cloning repositories. Preparation writes caller files for review;
it does not edit GitHub or activate a channel.
