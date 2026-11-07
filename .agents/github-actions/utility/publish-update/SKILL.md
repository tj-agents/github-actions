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

This package owns the publisher action, canonical reusable publication workflow and protected credential
enrollment. The uniform caller renders a thin trigger workflow with explicitly mapped secrets. `UPDATE_TOPIC`
is private repository configuration: set the Actions variable and secret to the same value. The caller maps
the secret to the canonical workflow, which reads it only as an action input, so public workflow source does
not disclose it. Hints contain a repository and change categories, never file contents. Consumers
authenticate and authorize their own actions after re-reading GitHub; publication grants no authority.

On Windows use `python`; on Linux use `python3`. Render or install the publisher caller with the immutable
publisher commit to use:

```text
python -B scripts/caller.py --revision <40-character-sha> --project <repository>
```

The rendered caller pins the publisher commit and labels that pin `# main`. It listens for a completed `ci`
workflow run. The canonical workflow accepts only a successful `ci` run for a push on its own repository's
default branch; pull requests, forks and unsuccessful runs publish nothing. Before publishing, it re-reads
the current default-branch head and suppresses a run whose SHA is no longer current. The v1 hint includes
that verified SHA as well as the repository and change categories.

Observed sequence: source merge → regeneration commit → successful CI at the current default-branch head →
notification. A failed or superseded CI run produces no notification. Do not add a direct post-push
publisher call or a `published: 'true'` bypass; verified CI completion is the publication path.

Possession of the ntfy topic is not authentication or consumer authority. The receiver decides whether to
act, and this public workflow never merges code.

## Hosted dependency updates

Within the explicitly enrolled fleet, Mend Renovate is the single dependency-update producer. A repository
opts in by adding `.github/renovate.json` that extends
`github>tj-agents/github-actions:renovate-default`. Publisher enrollment does not configure or authorize
Renovate; the hosted service must separately have access to the repository.

The preset updates dependencies and pins GitHub Action digests; it does not grant merge authority. The
dependency check and any no-human-review path for Renovate-created pull requests are explicit ruleset and
check configuration owned by `tj-agents/github`'s `github:configuration` workspace. Ordinary source and
agent-authored pull requests retain the repository's merge policy. This utility neither configures Renovate
nor creates a merger, bypass, or service configuration.

## Owner setup and credential enrollment

An organization owner bootstraps publication once. Preview from this skill directory is offline and does
not validate owner authorization:

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
the clipboard. The owner executes it. The agent does not execute the owner command. The launcher opens an
interactive owner PowerShell window and invokes the locked Python setup. On Linux or macOS, the owner runs
the locked setup directly in their terminal:

```bash
uv run --locked --script "<absolute-skill-directory>/scripts/owner_setup.py" --owner tj-agents --apply --result-file "<absolute-local-result-file>"
```

Apply requires the owner's own GitHub sign-in and refuses agent sessions and token overrides. Incomplete
initial provisioning uses the App manifest, installation and local private-key flow in that interactive
window. The agent does not sign in for the owner or read private keys. Setup shows discovery and setup
progress per repository.

When discovery finds no legacy secret metadata, an existing setup resumes through its protected central
credentials after verifying the Apps, organization and repository identities, exact central environment
default-branch protections and both protected secret metadata records. It dispatches
`enroll-publishers.yml` once on the central repository's current default branch, with no workflow inputs,
to enroll and authenticate the stored credentials. It verifies the exact returned run and attempt against
that branch's current head. Its `enroll` job, `Mint controller installation token` step and `Enroll eligible
repositories` step must all succeed before setup completes. Aggregate workflow success alone is
insufficient. Scheduled, push and manual runs perform enrollment only; they do not render callers or
configure dependency updates.

Before dispatch, setup checks existing App installations. Valid installations require no browser action. If
an installation needs repository access or permission acceptance, setup opens its exact installation settings
page and waits for the owner. Both cases reuse the protected keys without local PEM or key generation
prompts. A failed or skipped required job or step, workflow failure, timeout or mismatched run stops with
the structured run URL; it never falls through to requesting fresh keys. Secret metadata alone proves
neither a usable key nor installed runtime adoption; the enrollment workflow must authenticate the stored
credentials.

```text
Existing protected provisioning verified, no legacy secret metadata:
dispatch once: ref=main, return_run_details=true, no inputs -> GitHub returns run 123
waiting_for_enrollment carries https://github.com/tj-agents/github-actions/actions/runs/123
matching run 123/current head/attempt + successful enroll job and both required steps -> complete
wrong identity, failed/skipped evidence or timeout -> failed with run URL, no new key request
```

The native `!` command returning zero proves only that the Windows launcher returned successfully. Read the
exact result file, whose atomic JSON contains `schema_version: 1`, `owner`, `pid`, `state`, `phase`,
`exit_code`, `observed_at` and optional `error` and `action` fields. An action contains `kind`, `summary`,
`locations`, `steps` and `url`; its kind is `identify_legacy_app`, `rotate_updater_keys` or
`waiting_for_enrollment`. Relay the returned action's summary, locations, steps and URL exactly, without
asking for console pastes. Reuse a running attempt and its result file; do not restart it to pick up newer
scripts. Diagnose a failed attempt from its phase and error. A missing result or a `running` state leaves
setup unverified. Only `complete` for the requested owner with `exit_code: 0` proves setup returned success;
verified CI and publication remain rollout acceptance conditions.

Legacy secret metadata indicates possible exposure; neither a secret name nor its location proves the
issuing App's identity or that a key was copied. Setup verifies the existing credential App's organization
ownership, permissions and organization `UPDATE_APP_CLIENT_ID` variable. The owner must identify all listed
credentials from original provisioning records and select `1` to confirm they all belong to the displayed
verified App, or select `2` to cancel safely. Missing, mismatched or unresolved identity stops setup before
any revocation request. Only after that confirmation does setup open the verified App's specific private-key
page and guide rotation of previously distributed keys. In Credentials -> Key pairs -> New key, create a
replacement first and keep its downloaded PEM. Delete all older keys while keeping that replacement, then
confirm revocation. Deleting an Actions secret cannot revoke a copied key. The next local prompt selects that
same replacement PEM without generating another key. At the rotation prompt, select `1` only after that work
is complete; select `2` to cancel before credential migration. Invalid or blank input asks again without
remote writes. Legacy rotation refuses a pre-supplied `--updater-key-file`. Never read, paste or send the
PEM contents.

```text
Result: state=running, action.kind=identify_legacy_app, action.url=null
Relay: the returned summary, each credential location and the provisioning-record steps.
Choice 1: every listed credential belongs to the displayed verified App.
Choice 2: cancel safely without requesting key deletion.
After choice 1: relay rotate_updater_keys and its verified App URL and exact steps.
New key -> keep downloaded replacement PEM -> delete all older keys, keep replacement -> choice 1.
Next local prompt: select that replacement PEM; no second key generation.
```

The existing `<owner>-pin-updater` App is the protected credential source for publisher enrollment; its name
does not enable a dependency updater. The separate `<owner>-enrollment-controller` has contents and secret
metadata read, administration and environments write. The controller key stays in
`<owner>/github-actions`' protected `update-enrollment` environment. The existing `update-pins` environment
and `UPDATE_APP_*` names remain credential-storage identifiers for enrolled publishers, restricted to the
default branch; they do not activate an updater. When an existing credential App gains required read
permissions, the owner accepts that installation update once; setup reuses the protected keys and
installation, without key rotation or another onboarding flow.

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
branch restrictions before uploading a key and preserves additional deployment protections. Each supplied
key authenticates as its intended App before upload. Owner setup removes legacy unprotected credential
secrets after replacements are read back. Key values never appear in diagnostics or local enrollment state.

Trusted central automation uses `scripts/enrollment.py` only to enroll repositories. Its apply path requires
the central repository's current default branch and a controller installation token; the protected credential
App authenticates before upload, and consumer code is never executed. First token minting, post-merge
publication and installed startup still require actual rollout verification; successful source checks do not
establish them.

For an existing fleet, `scripts/prepare_callers.py --inventory <json> --revision <sha> --output <directory>`
prepares publisher callers without cloning repositories. Preparation writes caller files for review; it does
not edit GitHub or activate a channel.
