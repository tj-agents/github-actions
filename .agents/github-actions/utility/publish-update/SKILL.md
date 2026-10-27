---
name: publish-update
description: Publish a configured repository's default-branch update hint for an independently authorized consumer. Use when enrolling a repository or rendering its shared publisher workflow.
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

The publisher caller runs on every push, and the canonical workflow publishes only the repository's default
branch from the push payload. Shared generation pipelines invoke the publisher directly after their
generated-file push.
A job that pushes generated plugins with `GITHUB_TOKEN` must also call the same action after its push
with `published: 'true'`, because that push does not trigger another workflow.

Possession of the ntfy topic is not authentication or consumer authority. The receiver decides whether to
act, and this public workflow never merges code.

The colocated `update-pins` action updates full-SHA `uses:` references in tracked `.github` YAML only when
the referenced action or workflow content changes, then opens a pull request with a repository-scoped App
token. The canonical workflow owns its `update-pins`
environment, which holds the private App credential and restricts it to the default branch. Configure
`UPDATE_APP_CLIENT_ID` as an Actions variable and `UPDATE_APP_PRIVATE_KEY` as an environment secret.
Install the App only in selected repositories; generated trigger workflows explicitly map the private-key
secret while the canonical workflow requests a token for its current repository. Core CI computes export
and digest hashes; this action does not update them.

For an existing fleet, `scripts/prepare_callers.py --inventory <json> --revision <sha> --output <directory>`
prepares each repository caller without cloning repositories. Preparation writes caller files for review;
it does not edit GitHub or activate a channel.
