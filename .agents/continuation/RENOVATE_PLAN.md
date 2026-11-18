# Renovate replacement

Canonical work item: https://github.com/tj-agents/github-actions/issues/54

Current execution owner: Codex session `01a1b1a3-4c69-7742-ab39-874804797a09`.
Original design owner: Codex session `01a1b175-2a44-72d3-ab32-236a4c8095b6`.
Execution checkout: `C:/Users/TommySeery/source/repos/tj-agents/github-actions.worktrees/Feature-RenovateReplacement`.
Original design branch: `Feature/RenovateReplacement`, based on `d151019c0beed2ccfcd734eadb4ffea82ff1a05e`.
Current delivery checkout, branch, exact candidate and next action are recorded once in the progress ledger.
Progress: [RENOVATE_PROGRESS.md](RENOVATE_PROGRESS.md).

## Outcome and authority

Current explicit user clarification, November 6, 2026: "always machine agnostic aka all machines".
Configuration must be usable across supported machines, with shared durable operational state and locking;
workstation-only Terraform state is not an eligible design or a pending user choice. Preserve per-user
authentication and secret boundaries. Backend implementation stays with the existing configuration owner.

The user's November 6, 2026 instruction adopts the independent Renovate handoff at
`github-actions/.git/agent-workflow/handoffs/github28-renovate/prompt.md`. Own the Renovate replacement,
not github issue 28 or the separate Core planning-policy correction. Resolve the architecture and
implementation-ready cutover plan first. The requested end state is live, verified replacement: Renovate
owns discovery, SHA/version updates, grouping, schedules, stale-branch refresh and automatic merges after
checks, without human approval for trusted automated dependency PRs. Ordinary source review stays intact.

Preserve current Apps, installations, protected credentials, independent enrollment and generated
publication. Never read private key contents or use owner credentials. Remove superseded automation after
replacement proof. No permanent second updater or custom merger. Working planning state stays local.

## Observed baseline

- First observed action: read the exact handoff, then inspect the starting checkout and worktree inventory.
  The starting checkout remained on `Fix/AutomaticUpdaterMerges`; its three modified settings files were
  preserved. This independent checkout was created from current remote main before deliverable writes.
- No existing Renovate GitHub issue, branch or separately responsible local session was found. Issue 54
  was created with stable request ID `renovate-replacement-01a1b175-20261106`; board placement reported an
  access error, so issue creation must not be repeated.
- Remote main is `d151019c0beed2ccfcd734eadb4ffea82ff1a05e`, containing source PR 53 and generated PR 52.
- Live GitHub API confirms github PR 30 merged at `2026-11-06T15:14:47Z` by
  `tj-agents-pin-updater[bot]`, with an empty reviews list. Existing no-human-review delivery is proven.
- The old action opens its PR only when its local updater reports a new diff. This leaves an otherwise
  unchanged stale branch without guaranteed refresh.
- The handoff's `scripts/updater.py` path is stale: the actual implementation is
  `.github/actions/update-pins/update_pins.py`. Generated package copies are not authored owners.
- Current public repository rules show required reviews and checks combined in `merge-policy`. Bypass
  metadata is not visible to this agent token. Organization ruleset enumeration returns 403; preserve that
  distinction and verify protected-runtime authority before any cutover.

## Completed solution assessment

Assessment complete on November 6, 2026. Adopt the existing hosted Mend Renovate App. Public GitHub App
metadata verifies `id=2740`, `slug=renovate`, owner `mend`. Do not self-host Renovate, fork it, or retain a
custom dependency merger. This decision is based on current documentation and source inspection, not live
Renovate execution. The original updater App `5548045` remains the protected generated-publication identity;
the enrollment-controller retains its current duties. Neither existing App/key is recreated or rotated.

The useful benefits are one supported dependency service for discovery, updates, grouping and refresh;
GitHub-enforced checks before automatic merging; and removal of the custom dependency runner/merger. Hosted
installation requires an organization owner to authorize the new third-party App on the selected repositories.
Prepare and review the concrete source/configuration change before that owner action. Hosted processing is
eventual, not a promise of a merge immediately or within ten minutes of a green check.

| Option | Decision and limiting evidence |
| --- | --- |
| Hosted Renovate | Selected. No new locally managed credential or scheduled runner; native managers cover the current updater's dependency work. |
| Self-host using App 5548045 | Rejected. The App's independently necessary default-branch publication bypass includes required checks. Renovate's present-status evaluation is not a substitute for enforcing every required context. |
| Self-host with a new separate App | Credible fallback only if a future demonstrated requirement cannot use the selected hosted service. Adds credentials and execution infrastructure without a current need. |
| Hosted plus permanent generator/merger | Rejected. Current publisher callers need only pin updates; arbitrary hosted commands require operator/plan permission. Keeping another merger defeats the objective. |
| Fork or selectively reimplement Renovate | Rejected. Native GitHub policy can provide the necessary merge restrictions. Reuse only the existing independent publisher renderer and enrollment logic. |
| Keep existing service | Rejected by the explicit replacement objective and its stale-branch gap. |

Primary references (retrieved November 6, 2026):

- [GitHub Actions manager](https://docs.renovatebot.com/modules/manager/github-actions/): reusable workflows,
  immutable references, and the disabled bare-SHA case without a tracking annotation.
- [Custom regex managers](https://docs.renovatebot.com/modules/manager/regex/): available for genuine additional
  dependency fields, not selected as a second whole-file generator.
- [Automerge concepts](https://docs.renovatebot.com/key-concepts/automerge/) and
  [configuration](https://docs.renovatebot.com/configuration-options/): PR automerge, refresh and schedules.
- [Hosted overview](https://docs.renovatebot.com/mend-hosted/overview/),
  [hosted configuration](https://docs.renovatebot.com/mend-hosted/configuration/) and
  [self-hosted configuration](https://docs.renovatebot.com/self-hosted-configuration/): hosted command limits
  versus operator-owned `allowedCommands`. No `postUpgradeTasks` are selected.
- [GitHub rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)
  and [available rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets):
  independent rule enforcement, bypass scopes and native branch-write restrictions.
- [Workflow action syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax):
  the `$/` action form uses the called workflow's repository at its running commit; this is a github.com
  design, not a GHES compatibility commitment.
- [Preset syntax](https://docs.renovatebot.com/config-presets/) and
  [pin helper](https://docs.renovatebot.com/presets-helpers/): native shared configuration and digest pinning.

Upstream source evidence is frozen at Renovate `44.221.6`, the release observed at 13:56:24Z on November 6.
Copies live under `github-actions/.git/agent-workflow/runs/renovate-replacement/upstream/`:

- `github-44.221.6.ts`, SHA256 `a1875212004799907f8ed29b646cb200f307103b457779590c7aeb9458663584`:
  `getBranchStatus` at line 1199 evaluates present statuses/checks; its merge request does not include an
  expected-head SHA. GitHub must therefore enforce required contexts, and bot branches must exclude other writers.
- `automerge-44.221.6.ts`, SHA256 `c6554e1cb57867b523cefd68fd0a21c77bdbb73f69f7b18c70432ab486c56a15`:
  native PR automerge checks branch status and modification before invoking the platform merge operation.
- `github-actions/parse.ts` was inspected from the same tag. `$/` without `@` returns no repository
  dependency, so it cannot create a self-update dependency. This is source inspection, not a hosted dry run.

## Scope and implementation standards

The initial fleet is the 16 repositories captured in the machine-local `fleet-inventory.json`, with exact
heads and workflow/policy bodies: personal, dotnet, cli, github-actions, agent, github, learning, azure,
template, react, nvim, rust, python, work, core and work-items, all under `tj-agents`. This is an inventory,
not authority to enroll unrelated repositories or employer accounts. Template/custom publication eligibility
and Renovate installation/configuration remain distinct opt-ins.

Current inventory shows `agent` has approval but no required check declaration, and `learning` has no merge
policy. Before enabling automerge there, add their observed three Template check contexts. Preserve `agent`'s
approval requirement and `learning`'s existing no-human-approval policy. Missing publisher files in other
repositories are not invented as a prerequisite for this dependency replacement.

| Implementation area | Standards actually read |
| --- | --- |
| All paths and delivery | This checkout's AGENTS.md; personal clean-cut/proportionate implementation; workflow:plan, plan-artifacts, session; engineering:plans, branching, open-worktree, merging; base:solution-assessment; agent:lanes |
| Workflows/actions/configuration | github-actions:security, build, libraries, style, testing, errors, structure; publish-update and merge-policy scope owners |
| Modified Python and tests | python:style, domain-design, imports, testing; existing pyproject.toml is the tooling contract |
| Plan review | engineering:docs-review and engineering:review, including its implementation-design gate |

The user's explicit Renovate selection supersedes the older Dependabot updater preference for this task.
Do not edit knowledge/progress records or invent broader contract decisions. The existing Template `@main`
and `template_ref: main` contract is deliberately preserved; this migration must not turn that edge into a
new pinned reverse dependency. Machine-readable pin annotations are functional Renovate input, not design
narration. Newly authored code has no explanatory comments by default.

Before implementation touches an authored SKILL.md, load skill:update and its required creator/check flow.
Do not treat this plan as having executed that stage. Before changing Template-owned files, obtain the
current Template source and its owner instructions; make the authored change there, then use template:update.
The current plan does not require a Template emitter/CI-format change.

## Chosen mechanisms

### 1. Preserve publisher generation and eliminate self-update loops

`.github/workflows/publish-update.yml` currently self-pins its composite action. Replace only that action
reference, retaining the existing verified-CI event, repository/head checks, topic handling and permissions:

```yaml
- name: Publish repository update
  uses: $/.github/actions/publish-update
  with:
    topic: ${{ secrets.UPDATE_TOPIC }}
```

Retain `caller.py:render` and its explicit `--revision`/`--project` CLI for initial publisher setup. Keep its
output unchanged in A: the live old updater admits callers by exact comparison against this renderer, and
adding an annotation early would reject every existing unannotated caller as custom. During each consumer's
C cutover, settle its old generated PRs and withdraw its old producer before adding the functional tracking
annotation to its publisher reference. Change the canonical renderer atomically with old generator/merger
retirement in D. The final supported output is:

```yaml
uses: tj-agents/github-actions/.github/workflows/publish-update.yml@d151019c0beed2ccfcd734eadb4ffea82ff1a05e # main
```

The shown SHA is a concrete inspected example, not the rollout's eventual release pin. During cutover resolve
the reviewed, merged producer commit once and write that full SHA. For vendor action pins, verify the existing
SHA's actual release/tag before adding its version annotation; do not invent a version or silently switch a
vendor dependency to tracking `main`.

`generated_publisher()` currently returns the recognized current caller unchanged; its structural rewrites
serve two legacy trigger shapes. Template CI secret forwarding and the scheduled updater caller migrations
are likewise bootstrap work, not a continuing need for arbitrary post-update commands. Drain any still-needed
supported migration through the old trusted automation before deleting it. Future publisher interface changes
ship as source changes with their actual callers; no permanent legacy rewrite service is retained.

Leave the existing `tj-agents/template/...@main` plus `template_ref: main` pairing intact and exclude that
package from Renovate. Pinning it would create a `github-actions -> Template -> github-actions` update cycle.
Template continues to consume the GitHub Actions publisher at an immutable tracked SHA. No new release/tag
service is introduced. Reject any new digest-tracking cycle found in the actual fleet inventory before rollout.

### 2. Shared native Renovate configuration

Add root `renovate-default.json` as the single authored shared preset. Use native manager discovery for the
repositories' supported dependency manifests; no custom commands, executable presets or regex whole-file
renderers. This is the exact intended configuration shape to validate with the official validator:

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:recommended", "helpers:pinGitHubActionDigests"],
  "automerge": true,
  "automergeType": "pr",
  "automergeStrategy": "squash",
  "platformAutomerge": false,
  "rebaseWhen": "behind-base-branch",
  "updateNotScheduled": true,
  "dependencyDashboardApproval": false,
  "timezone": "Europe/London",
  "schedule": ["* 0-5 * * *"],
  "packageRules": [
    {
      "matchUpdateTypes": ["minor", "patch", "digest", "pin", "pinDigest"],
      "groupName": "non-major dependencies"
    },
    {
      "matchManagers": ["github-actions"],
      "matchPackageNames": ["tj-agents/template"],
      "enabled": false
    }
  ],
  "lockFileMaintenance": {"enabled": true}
}
```

Every selected consumer's `.github/renovate.json` contains:

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["github>tj-agents/github-actions:renovate-default"]
}
```

Majors remain separate PRs and inherit automerge; no `dependencyDashboardApproval`, age or manual label gate
is added. The native dashboard reports failures and updates. The creation window limits new branches;
existing branches can refresh outside it. For the canary only, temporarily override `schedule` with
`["at any time"]` to exercise the proof, then remove that override with the cutover.

Start installed discovery with `automerge: false` as a temporary repository override until complete ruleset
read-back and preactivation probes pass. Then remove that override for the controlled live negative tests
below, before allowing the successful canary merge. It is not a permanent mode.
Do not enable `ignoreTests`, null `statusCheckNames`, `automergeType: branch`, or platform automerge.

Execution ordering correction, November 7, 2026: the temporary required acceptance context applies to
every PR targeting the default branch, while its probe deliberately rejects ordinary source branches.
Consequently, adding that context before the source activation PR would deadlock activation. After the
namespace and review-only rules have applied and converged, land the ordinary reviewed source PR removing
the automerge:false override while the unchanged combined merge-policy still requires one human approval
and all five real checks. Renovate has NO bypass on that combined rule, so it cannot merge at this point.
Then apply the separately reviewed third configuration change: combined approvals1→0, strict current-base
checks, and the temporary missing acceptance context in ONE native ruleset update. There is never a state
with zero approval and no temporary gate. Record the source commit moving the canary base, unchanged
dependency targets and Renovate's actual branch refresh. Only after that protected apply and full readback
exercise missing/pending/failing/success. Remove the temporary context through protected configuration
before trying to land later ordinary canary source cleanup. This explicit ordering supersedes the older
source-override sequencing above; it does not waive any namespace, review, real-check or live-proof gate.

### 3. Configuration ownership and native policy contract

Tommy explicitly confirmed on November 6 that Renovate owns dependency updates and automatic merges, while
`github:configuration` owns GitHub settings, rules, environments and permissions. Existing setup is general
configuration within that capability's scope. Do not extend `merge_policy.py` into a competing settings
reconciler or add a new Renovate-specific configuration engine here.

The existing configuration owner is Claude session `9e2d51ec-4222-4065-b135-1642702ec4a0`, title
`github-config-as-code`, checkout `C:/Users/TommySeery/source/repos/tj-agents/github.worktrees/Feature-Configuration`.
Its canonical plan is `C:/Users/TommySeery/.claude/plans/tj-agents/github-config-as-code-plan.md`. Read on
November 6 at source `d7b0ce0cb3fc1fc6bd6cf2c59e4bca7fc80686f0`: declaration parsing currently supports packages
and the CLI supports browser login. The planned Terraform API-settings half, ruleset schema and state backend
are not implemented or settled. This is an explicit dependency, not an available published capability.

That owner owns generic declaration/schema, settings plan/apply/read-back, state/locking, and retirement of
`merge_policy.py` apply/reconcile/sync, enrollment `protected`/`reconcile_policy`, and owner-setup variable and
ruleset reconciliation. It also owns migration of the installed Core settings subscriber. Renovate owns the
dependency preset, pin annotations, publisher self-reference, dependency producers and their retirement,
plus the required desired-state contract below. Repository/owner-specific declaration data belongs in the
location selected by the configuration owner; this plan does not invent its unfinished schema or path.

Before editing a shared file, reconcile the exact existing owner and obtain a recorded nonoverlapping lease
or completed upstream change. In particular, `owner_setup.py` bootstrap retirement overlaps a file the other
owner is replacing: sequence it through that owner rather than editing concurrently. Do not launch another
configuration owner or modify its checkout. No cross-host notification or agreement has yet been observed;
the current messaging skill supports Codex recipients, not this Claude session. The exact named owner's
acknowledgment or published integrated change is the ownership gate for those shared paths. Independent
Renovate source work may proceed now. Configuration source/state-backend decisions remain with their owner
and Tommy; no fallback custom reconciler is authorized.

The integration contract is generic native GitHub ruleset data. Preserve each repository's declared review
count and exact required contexts. The canary retains `verify / hosts`, `verify / verify (ubuntu-latest)`,
`verify / verify (windows-latest)`, and both `Verify the portable workflow writer` platform contexts.
Require at least one nonempty required context before dependency automerge. Configuration must converge and
read back these three rulesets only for the explicitly selected repositories:

| Name | Rules | Renovate 2740 | Existing publication 5548045 |
| --- | --- | --- | --- |
| `merge-policy` | PR with zero approvals; default deletion/force-push protection; all declared checks with strict current-base policy | No bypass | Preserve verified existing always-bypass for protected direct publication |
| `merge-policy-review` | PR requiring the policy's human approval; absent when requires_approval is false | `pull_request` bypass only | Preserve publication bypass |
| `renovate-branches` | Restrict creation, updates and deletion on refs/heads/renovate/**/* | Sole `always` bypass | No bypass |

Preserve the current admin/deploy-key policy on default-branch rulesets. The Renovate branch namespace has
only Renovate's verified Integration actor; neither source agent bot nor ordinary repository writers gain it.
GitHub ruleset payloads use these exact native fragments:

```json
{
  "name": "renovate-branches",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["refs/heads/renovate/**/*"], "exclude": []}},
  "bypass_actors": [{"actor_type": "Integration", "actor_id": 2740, "bypass_mode": "always"}],
  "rules": [{"type": "creation"}, {"type": "update"}, {"type": "deletion"}]
}
```

```json
{
  "type": "required_status_checks",
  "parameters": {
    "strict_required_status_checks_policy": true,
    "required_status_checks": [{"context": "verify / hosts"}]
  }
}
```

The last fragment is illustrative of one context; the declaration carries the complete required list. Do not
replace it with whichever checks happen to have reported. Current ordinary source policies remain one review
or zero as declared; a bot dependency PR is exempt only because the hosted App is the merge actor.

Before the first split or rollback, the configuration owner must prove that enrollment, installed Core and
local legacy administrative writers are retired or quiescent, and that the selected generic writer serializes
changes using its state/locking contract. Refreshing versions alone is insufficient. A stale opt-in apply
must not interleave with opt-out rollback and remove the last approval rule. Reject a stale source revision
and test the competing-apply case in the owning configuration implementation. Never run old and new settings
reconcilers concurrently during this transition.

Within that exclusive transition, apply order is security-relevant: install namespace restrictions, then install the review-only ruleset with
the existing review count, then update `merge-policy` to retain checks/PR/branch safety and remove its review
count. Read back each step and stop on error. A partial transition may over-restrict; it must never leave a
gap with neither review protection nor check protection. Reverting the opt-in restores the combined base
review rule before removing review-only/namespace rules. This is rollback of a selected feature, not a second
dependency implementation.

Use `github:configuration`'s adopted protected settings route for administration, once delivered by its owner.
Verify the public hosted App identity and installed actor through that route's apply/read-back; the source
agent must not call administrative apply with owner credentials. Existing protected credentials and App
management remain in their current independent scope. If an organization rule also imposes reviews, report
its exact identity and let configuration manage that authorized desired state. Never give Renovate
always-bypass on an organization ruleset containing checks. Current central/agent effective rule reads showed
repository rules only; remaining fleet/organization authority is an execution-time read-back gate.

The migration inventory includes `render`, `apply`, `sync`, `reconcile`, `check`, enrollment's
`reconcile_policy`, Core's installed owner-context subscriber, and `.github/actions/merge-policy-check/action.yml`.
The configuration owner must replace or coherently adapt those entry points; Renovate must not keep a second
mutation path. Preserve the publication grant only after verifying immutable App identity and enrolled
protection from complete actor metadata. Missing optional CLI arguments do not mean revoke an existing grant.
New grants retain enrollment's existing proof. Unreadable metadata is an error, never an empty list.
The resulting read-only drift check must enumerate full owned rulesets, including each actor/bypass mode,
strictness and namespace. Aggregate effective branch rules cannot prove the absence of a check bypass.
Preserve the current required CI check contract until its coordinated replacement is merged and installed.

### 4. Keep protected publication; retire dependency production

Keep the `update-pins` environment and `UPDATE_APP_*` variable/secret identities where Template/Core still
consume them for generated publication. Those surviving names are intentional credentials for an independent
capability, not compatibility aliases. Do not delete credentials because the updater workflow has gone.

Retain enrollment eligibility, authenticated App checks, key upload and generated-publication behavior.
Environment, branch-policy and ruleset settings move to the configuration owner without losing their
protection. Drain supported caller migrations before deleting the `bootstrap` workflow job and dispatch
input, together with owner-setup bootstrap dispatch/verification paths. This removal is a pre-activation
barrier for the first canary, not deferred until final cleanup: current bootstrap recreates missing updater
callers. Drain or cancel queued/running bootstrap runs from older revisions and verify no remaining trigger
can recreate them. Configured owner setup should
continue using the existing protected controller and authenticating the same stored credentials. App permission
reduction is not part of the initial replacement; it must not trigger new setup or key rotation.

Future Renovate activation is explicit: add the reviewed policy/config to the repository and ensure the
hosted installation covers it. Tommy confirmed the existing All repositories installation on November 7;
accept that setting rather than imposing repeated canary-only installation changes. Actual source changes,
producer withdrawal and merge-policy rollout remain scoped to the 16 personal repositories above. Installation
access alone does not authorize changes to employer repositories or unrelated onboarding PRs.
The Template marker alone never installs a third-party App.
The existing publisher renderer remains available when the repository explicitly chooses publication.

## Delivery map and dependency order

November7 user override: disregard the small-PR/sequential-slicing default for the remaining Renovate work.
Combine coherent remaining changes instead of creating a PR per procedural step. Preserve actual protected
apply/readback, old-producer withdrawal/drain, required source approval and per-repository ownership gates.
No cross-repository PR is possible; repository boundaries do not justify further tiny PRs within each cutover.
The branching standard itself is not edited by this Renovate task.

Implementation graph: inspected central source -> independent Renovate config/publisher changes -> checks
and source review; configuration owner's generic capability + shared-path reconciliation -> integrated
settings contract and legacy-writer withdrawal -> canary -> fleet adaptations -> old-path deletion.
Delivery graph: ordinary source approval -> current main CI/publication -> delivered configuration capability,
exclusive settings writer and hosted selected-repository installation -> protected ruleset read-back -> live canary -> fleet rollout
-> final removal/current-entrypoint verification. Owner installation/approval gates do not block preparing
and testing source. No independent source repository change is required merely to deliver this plan.

| Slice | Included work and consumer contract | Gate / size assessment |
| --- | --- | --- |
| A: independent central capability | Shared preset and publisher self-pin removal; focused tests and accurate skill guidance. Keep caller rendering unchanged while the old updater uses exact-shape admission. No new settings reconciler. | About 100-250 substantive lines; reassess actual numstat before review. Official validator, publisher tests, generation and CI. Commit this independently while the configuration dependency proceeds. |
| B: integrated pre-activation barrier | Configuration owner delivers generic settings/declarations and retires competing writers. Reconcile/rebase shared paths and review the integration. Drain supported migrations, remove central bootstrap and owner-setup bootstrap paths, drain their old runs. Install hosted App only after reviewable source exists. | Exact owner coordination, settled state/locking route, full rule read-back, preserved credentials/publication, no bootstrap resurrection. This is gated by the named configuration owner; do not implement its work in parallel here. |
| C: canary, then fleet cutover | Reviewed per-repository config/declaration/annotation changes, including agent/learning check contexts. Delete each old updater caller and drain queued/running old updater executions before Renovate begins creating dependency branches. | Initial discovery has automerge disabled; after settings read-back, enable it for controlled failing/pending/missing cases and then success. Observe ordinary source approval, zero-review merge and stale refresh. Prove each repo's CI/discovery; at most one dependency producer per repo. |
| D: retire central old paths | Delete updater action/code, central merger and obsolete caller/bootstrap helper code, tests/guidance/dependencies; update canonical publisher rendering with the tracking annotation in the same cut. Preserve credential/publication/enrollment support. | No remaining active bespoke schedule/caller; source/installed grep and fleet proof; full targeted CI and generation check. Bootstrap workflow removal was already mandatory in B. |

Initial configuration/policy installation PRs are ordinary agent-authored source work and keep their normal
review gate. Existing and new generated dependency PRs never receive a human-approval workaround. Drain old
supported migrations through their existing trusted owner; close superseded pin-only branches only after
equivalent Renovate coverage is established. Do not adopt or close the predecessor's whole goal.

The central canary's `.github/workflows/update-pins.yml` is also the reusable workflow used by the remaining
fleet. For this repository's cutover, remove its `schedule` and direct `workflow_dispatch` triggers and drain
their queued/running executions, while retaining `workflow_call` for unmigrated callers. Other repositories
delete their thin caller when they cut over. Delete the central reusable file in D only after no active
caller remains. Pinned historical workflow revisions are not active producers without a remaining caller.

The cutover is sequential, with a bounded migration window. It is not a second permanent service: the ledger
records each repository's active dependency producer, and Slice D is part of the same completion condition.
Failure stops the affected activation; fix source/configuration, preserve checks, and resume. Do not switch
back to keeping bespoke automation permanently or bypass CI as a rollback shortcut.

## Concrete removal and caller inventory

Remove in the staged order above; final completion requires all of these absent:

- `.github/workflows/merge-updater-prs.yml` and `scripts/merge_updater_prs.py`;
- `.github/workflows/update-pins.yml`, consumer counterparts, and `.github/actions/update-pins/`;
- `caller.render_updater`, `--updater`/`--repositories` updater-only CLI behavior;
- enrollment workflow's bootstrap matrix and owner-setup bootstrap dispatch/check paths;
- old bootstrap legacy-shape functions and tests whose sole subject is the retired updater;
- updater-only ruff/mypy entries, dependencies, README/SKILL examples and generated mirrors.

Keep and adapt their surviving invariant tests: untrusted/custom caller refusal during the one-time migration,
explicit personal adoption, no generic scaffold enrollment, protected credential boundaries, publisher exact
current-head CI verification, and generated publication's explicit path/default-ref/race checks.
`test_merge_policy.py`, `test_enrollment.py`, `test_owner_setup.py`, `test_publish_update.py`,
`test_publish_generated.py` and `test_scaffold.py` remain relevant. Author changes once and regenerate mirrors.

## Verification and acceptance evidence

Local checks use the selected locked project tools and repository Node 24. Validate the preset with
`npx --yes --package renovate@44.221.6 -- renovate-config-validator --strict --no-global renovate-default.json`.
Retain the exact command/version/output. Validate `.github/renovate.json` with the same flags after the shared
preset is on the producer's default branch; before publication its remote `extends` cannot resolve the new
file. `--no-global` is necessary because explicit custom filenames otherwise default to global config mode.

Planning validation passed Python `jsonschema` against the retrieved official schema. The attempt to obtain
the official npm validator exhausted this workstation's Node heap before the validator started; it did not
pass. Execute the full validator with Node 24 in CI or a suitable environment rather than treating schema
validation as equivalent. Plan host-coverage validation passed; no production source test has been run yet.

The configuration owner's evidence must cover split apply/rollback ordering, exclusive-writer and stale
revision rejection, opt-in scope, drift repair, metadata failures, identity mismatch, missing checks and
publication preservation. Integration review checks that contract, rather than reimplementing its tests in
this repo. Include the existing CI drift-check action and full owned-rule/actor inspection. Run focused
publisher/caller tests here. Tests must prove behavior. Run `pwsh .agents/sync-generated.ps1`
and `pwsh .agents/sync-generated.ps1 -Check`, plus affected locked lint/type/test commands. The schema
validator and source tests do not establish live GitHub acceptance.

Required live proof ledger, with exact repository/PR/head/run/attempt and timestamps:

1. Hosted identity 2740 opens a dependency PR in the protected namespace. It merges with all exact required
   contexts successful and `reviews: []`. Record actual merge actor and commit.
2. Before enabling automerge, read back every native rule/actor and prove namespace denial. For controlled
   check cases, add one temporary required acceptance context to the canary through reviewed configuration;
   keep every real required check intact. The temporary `.github/workflows/renovate-acceptance.yml`
   uses `pull_request: types: [labeled]`, not `workflow_dispatch`: GitHub excludes manually dispatched job
   checks from PR ruleset evaluation (official troubleshooting-required-status-checks, checked November 6,
   2026). Before labeling the designated same-repository `renovate/` PR, the context is missing. Add label
   `renovate-acceptance:pending` for a 180-second real running job that ends in failure, wait for it to
   finish, then add `renovate-acceptance:fail` for failure and finally `renovate-acceptance:pass` for success.
   Do not overlap runs; record each actual PR head, test-merge SHA, run, attempt and check-suite association.
   Every run validates the same-repository Renovate branch and fails closed on other labels or branches;
   no job-level conditional may turn an invalid probe into a skipped-success check.
   Enable native automerge while the additional context is still missing, then observe the missing, pending
   and failing cases remain unmerged. Record native required-check blocking and Renovate processing evidence.
   Pending/failing cases normally show client abstention, not a merge API refusal; do not claim an API request
   occurred. Retain a refusal if the hosted missing-context case actually attempts one. Only after those
   cases pass, run the acceptance check successfully and observe the zero-review merge with all real checks
   green. Remove the temporary context/workflow via reviewed source/configuration after evidence is recorded.
   This briefly strengthens the gate; never remove real checks or fabricate success statuses for the proof.
3. Move the canary base with an authorized source commit while its dependency version stays unchanged.
   Observe Renovate update the branch and fresh checks, then merge without a new producer dependency change.
4. A normal source-agent PR with green checks still requires review. Normal agent creation and mutation of
   `renovate/...` is rejected by the native namespace rule; use a disposable designated probe and retain refusal.
5. Invoking the reusable publisher from a consumer uses the central `$/` action successfully. Verified
   default-head CI publishes once; failed/superseded/fork events do not publish. Check actionlint support as
   a concrete validator gate; do not weaken security validation to accept the syntax.
6. Template/Core generated publication still authenticates existing credentials, writes only its supported
   generated paths to the exact default branch, and produces the expected subsequent CI/publication.
7. All 16 selected repos have correct installation/configuration and effective required checks; no active
   old updater caller or custom merger schedule survives. No dormant old branch is counted as delivered.
8. Fresh Windows and Linux supported configuration/caller entry points and the installed Core settings
   binding resolve to the selected current implementation and preserve the split rules. Retired settings
   commands must have no installed caller. Verify actual behavior, not just a version command.

Failures require diagnosis at their true source. Dotnet's pre-existing Template hook conformance problem is
not an App/token onboarding failure. Preserve other owners' work and evidence; a new failure elsewhere does
not authorize unrelated repairs. Resolve task-caused failures before advancing the affected repository.

## Review, execution lanes and transfer

L1 design reason: runner trust, publication authority, native check enforcement and the fleet cutover interact.
L4 owns specified Renovate implementation; use L2 for privilege/migration review and L4 for local code
concerns. The existing configuration owner keeps its settings work. Parent design advice was independently
assessed by `/root/renovate_design`. Independent reviews found and resolved bootstrap resurrection,
concurrent settings transitions, negative-proof mechanics, missing drift-check coverage, validator details,
ownership overlap, central reusable-trigger withdrawal and premature renderer changes. Followability review
cleared review-2; security review cleared final review-4 for independent Slice A. Frozen review-4 SHA256:
`d9634c62a69350a0cfc7b4105a009e31f33ffd3778aefabadab44b609b3869e2`. Evidence:
`github-actions/.git/agent-workflow/runs/renovate-replacement/design-review.md`.

This is substantial multi-repository design followed by a separate sustained implementation phase. After
that review, use workflow:handoff's verified pickup to one fresh Codex owner at L4 in this exact checkout.
The plan and compact ledger remain canonical; do not create a new issue or competing plan. The successor
starts by reconciling current remote/source ownership and implementing independent Slice A, not by repeating
the completed solution assessment. Shared settings/source edits wait on the named configuration owner.
Actual review, source approvals and hosted owner installation remain their own gates.

```agent-host-coverage
{
  "schema_version": 1,
  "shared_source": ".agents/github-actions/utility/publish-update/SKILL.md",
  "hosts": [
    {
      "host": "claude",
      "behavior": "uses shared Renovate publication and merge-policy guidance",
      "source": ".claude/skills/publish-update/SKILL.md",
      "mapping": "generated github-actions Claude skill",
      "verification": {"level": "planned", "result": "pending", "evidence": "Slice A generation and host checks; Slice D installed acceptance"}
    },
    {
      "host": "codex",
      "behavior": "uses shared Renovate publication and merge-policy guidance",
      "source": ".codex/skills/publish-update/SKILL.md",
      "mapping": "generated github-actions Codex skill",
      "verification": {"level": "planned", "result": "pending", "evidence": "Slice A generation and host checks; Slice D installed acceptance"}
    }
  ]
}
```

## Execution readiness

Verdict, November7 execution update: shared capability, generic configuration integration, live canary
and temporary-probe cleanup are delivered. Fleet namespace43 merged asd9668b106462c49c7554ef5e5e7b630b6273258a;
protected apply42406899718 added15 namespace rulesets with no changes/deletions. Full provider refresh
run-oYuo1W3nCqCcbq8A reports No changes and merged-head CI42406899995passed. Review-only44 then merged
as92f0c02408e0d9dba48b9f5e126efaf72bc69981; protectedapply42410159653 added14 reviewbarriers,
fullprovider run-jou43p8oKaL8SAyo reportsNochanges and mainCI42410160011passed. Learning remainswithout
a review-only rule. Next update14 combinedapprovalcounts to0 andrequire strictactualchecks; addmissing
Agent/Learning3Templatecontexts, preservingpublication/actors. Learningenrollment/readback and real token/publication
steps verified. Consumerwithdrawal/drain/activation follows checkpolicyapply/readback. All15oldcallersremainuntilcutover.
Authority provenance: user's instruction to follow the exact handoff and its requested replacement end state.
Source/standards: baseline, primary references, implementation mapping and mechanisms above; configuration
source/plan inspected at d7b0ce0, with Tommy's explicit settings-ownership correction incorporated.
Constraints: preserve ordinary source review, protected publication and explicit enrollment; no private keys
or owner credentials in agent commands; no Core planning-policy edits; no permanent second updater/merger.
Budget: one active implementation owner; one bounded writer at a time in this checkout unless exact disjoint
leases are recorded; five-minute read-only pickup observation budget if transfer is prepared.
Stop/escalation: unknown owner, unreadable policy actors, unsafe hosted identity/bypass, cyclic pin graph,
genuine test failure or unavailable runtime proof. Slice B specifically waits for the existing configuration
owner's generic API capability, backend/locking decision, shared-path coordination and legacy-writer retirement.
Observable resume condition: its reviewed delivered capability and exact integration contract/ownership
evidence exist. Continue independent Slice A while that dependency is outstanding; no custom substitute.
Execution lane: L4, specified implementation; L2 privilege/migration review.
Transfer reason: substantial design is complete; a fresh owner can implement the concrete sequential map.
Exact next action: follow the current Next Steps in the existing progress ledger; do not repeat Slice A
or the completed architecture assessment. Continue the fleet and central retirement under the same owner.
