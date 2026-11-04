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

An organization owner bootstraps publication once. Preview from this skill directory is offline and
does not validate owner authorization:

```text
python -B scripts/owner_setup.py --owner tj-agents
```

For a new Windows attempt, use `cli:clip`'s existing `user_command.py` mechanism to prepare the owner's
native `!` Bash command. Resolve the skill directory, a new local result file and the command specification
to absolute paths. Write a specification like:

```json
{
  "shell": "bash",
  "unset": ["TJ_AGENT", "GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR", "GH_PROMPT_DISABLED"],
  "steps": [{
    "argv": [
      "powershell.exe", "-NoProfile", "-File",
      "<absolute-skill-directory>/scripts/owner_setup.ps1",
      "-Owner", "tj-agents", "-ResultFile", "<absolute-local-result-file>"
    ]
  }]
}
```

Issue it through the installed CLI helper at `~/.agents-state/bin/cli/user_command.py`:

```text
python -B "<installed-cli-directory>/user_command.py" issue --spec "<absolute-command-specification>"
```

Relay the helper's exact native command; it constructs the command, copies it as plain text and verifies
the clipboard. The owner executes it. The agent does not execute the owner command. The launcher opens
an interactive owner PowerShell window and invokes the locked Python setup. On Linux or macOS, the owner
runs the locked setup directly in their terminal:

```bash
uv run --locked --script "<absolute-skill-directory>/scripts/owner_setup.py" --owner tj-agents --apply --result-file "<absolute-local-result-file>"
```

Apply requires the owner's own GitHub sign-in and refuses agent sessions and token overrides. Incomplete
initial provisioning uses the App manifest, installation and local private-key flow in that interactive
window. The agent does not sign in for the owner or read private keys. Setup shows discovery and setup
progress per repository.

When discovery finds no legacy secret metadata, an existing setup resumes through its protected central
credentials after verifying the existing Apps, organization and repository identities, exact central
environment default-branch protections and both protected secret metadata records. Setup dispatches the
existing `enroll-publishers.yml` on the central repository's current default branch with `bootstrap=false`
to enroll and authenticate the stored credentials before caller bootstrap. It verifies the exact returned
run and attempt. Its `enroll` job, `Mint controller installation token` step and
`Enroll eligible repositories` step must all succeed. Aggregate workflow success alone is insufficient.
The owner process then reconciles organization ruleset bypasses and dispatches `bootstrap=true` for the
full enrollment and caller-bootstrap flow, requiring the same exact-run, attempt, job and step evidence.
The boolean `bootstrap` dispatch input defaults to true; normal scheduled, push and manual runs retain
the full flow.

Before dispatch, setup checks the existing App installations. Valid installations require no browser
action. If an installation needs repository access or permission acceptance, setup opens its exact
installation settings page and waits for the owner. Both cases reuse the protected keys without local
PEM or key generation prompts. A failed or skipped required job or step, workflow failure, timeout or
mismatched run stops with the structured run URL; it never falls through to requesting fresh keys.
Secret metadata alone proves neither a usable key nor installed runtime adoption; the enrollment
workflow must authenticate the stored credentials.

```text
Existing protected provisioning verified, no legacy secret metadata:
dispatch bootstrap=false -> verify exact run/attempt and successful enroll job and required steps
reconcile organization ruleset bypasses
dispatch bootstrap=true -> verify exact run/attempt and successful enroll job and required steps -> complete
either dispatch: waiting_for_enrollment carries its returned run URL
failed/skipped evidence or timeout -> failed with run URL, no new key request
```

The native `!` command returning zero proves only that the Windows launcher returned successfully. Read
the exact result file, whose atomic JSON contains `schema_version: 1`, `owner`, `pid`, `state`, `phase`,
`exit_code`, `observed_at` and optional `error` and `action` fields. An action contains `kind`, `summary`,
`locations`, `steps` and `url`; its kind is `identify_legacy_app`, `rotate_updater_keys` or
`waiting_for_enrollment`. Relay the returned action's summary, locations, steps and URL exactly, without
asking for console pastes. Reuse a running attempt and its result file; do not restart it to pick up newer
scripts. Diagnose a failed attempt from its phase and error. A missing result or a `running` state leaves
setup unverified. Only `complete` for the
requested owner with `exit_code: 0` proves setup returned success; verified CI and publication remain
rollout acceptance conditions.

Legacy secret metadata indicates possible exposure; neither a secret name nor its location proves the
issuing App's identity or that a key was copied. Setup verifies the updater App's organization ownership,
permissions and organization `UPDATE_APP_CLIENT_ID` variable. The owner must then identify all listed
credentials from original provisioning records and confirm `credentials belong to <verified-app-slug>`.
Missing, mismatched or unresolved identity stops setup before any revocation request. Only after that
confirmation does setup open the verified App's specific private-key page, request deletion of previously
distributed keys and require `revoked <verified-app-slug>`. Deleting an Actions secret cannot revoke a copied key.
Generate a new key after revocation and select the downloaded local PEM at the next prompt; legacy
rotation refuses a pre-supplied `--updater-key-file`. Never read, paste or send the PEM contents.

```text
Result: state=running, action.kind=identify_legacy_app, action.url=null
Relay: the returned summary, each credential location and the provisioning-record steps.
If ownership cannot be established: stop without requesting key deletion.
After owner confirmation: relay rotate_updater_keys and its verified App URL and exact steps.
```

The locked environment supplies its cryptographic verifier. Setup configures `<owner>-pin-updater` for
contents, pull requests and workflows write, plus a
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
bypass grants. Key values never appear in diagnostics or local enrollment state.

Trusted central automation uses `scripts/enrollment.py` to enroll repositories and open a caller-bootstrap
pull request through the same implementation. It checks only the central default branch, uses separate
controller and repository-scoped updater tokens, and never executes consumer code. Its apply path requires
the central repository's current default branch and a controller installation token. First token minting,
post-merge publication and installed startup still require actual rollout verification; successful source
checks do not establish them.

For an existing fleet, `scripts/prepare_callers.py --inventory <json> --revision <sha> --output <directory>`
prepares each repository caller without cloning repositories. Preparation writes caller files for review;
it does not edit GitHub or activate a channel.
