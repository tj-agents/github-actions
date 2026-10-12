# Proposed GitHub Actions conventions

Status: proposed 2026-10-12, awaiting Tommy's decision. Evidence: a survey of six modern production service
repositories ("services"), Tommy's own repositories (Concertable's pipeline and service repositories,
sandbox-azure, kit's `plugin-ci.yml`), and current GitHub documentation. Each rule names its owning contract.
Rules marked **[choice]** have a real alternative, listed under it.

## `security` (new contract)

1. Top-level `permissions: contents: read`; each job adds only the scopes it uses, and an aggregator job sets
   `permissions: {}`. Why: GitHub's least-privilege guidance; services and Concertable both do it, one legacy
   service granted the default and is the counter-example.
2. **[choice]** Every `uses:` of a remote action or reusable workflow is pinned to a full commit SHA with a
   trailing `# vX.Y.Z` comment; local `./` actions are exempt; never a branch ref such as `@main`. Dependabot's
   `github-actions` ecosystem moves the pins. Enable "Require actions to be pinned to a full-length commit SHA"
   where the repository or organization allows it. Why: tag moves are the tj-actions and trivy-action attack
   class; Concertable already pins by SHA, services pin by tag, and one uses `@main`.
   - Alt A: adopt GitHub's `actions.lock` lockfile (`gh actions-lock`) and keep tags in `uses:`. It covers
     transitive dependencies, but it is public preview and "subject to change".
   - Alt B: major tags plus Dependabot. Dependabot alerts only work on semver refs, but tags are mutable.
3. `actions/checkout` always sets `persist-credentials: false`. Why: a stored token is readable by every later
   step; it is the majority pattern in both estates.
4. Untrusted values (`github.event.*` text, `github.head_ref`, `inputs.*`) never appear as `${{ }}` inside `run:`
   or `script:`; pass them through `env:`. Why: GitHub's script-injection guidance.
5. No `pull_request_target` that checks out pull request code. Why: GitHub's guidance, and the 2026
   trivy-action compromise.
6. Secrets go in the `env:` of the step that uses them, never workflow-level `env:`. Identifiers that are not
   credentials (tenant, subscription and client IDs, storage account names) are `vars`, not `secrets`. Why:
   services already scope secrets per step; Tommy's two Terraform repositories split IDs inconsistently.
7. **[choice]** Cloud sign-in is OIDC federation with no stored credential: `azure/login` with `client-id`,
   `tenant-id` and `subscription-id` from `vars`, and `id-token: write` only on the job that signs in. The
   `azure` package owns the identity and federated-credential subjects.
   - Alt: a self-hosted runner's own workload identity, with no per-repository trust and no `id-token`. Services
     use it on their own Kubernetes runners; it needs an estate that runs runners.

## `structure`

8. A deployed service has `pr.yml` (pull request verification and an optional preview), `ci.yml` (push to `main`:
   verify, then deploy to the shared non-production environment), `prod.yml` (tag-triggered production) and
   `pr-closed.yml` (preview teardown). A library, tool or plugin has `ci.yml` and, if it publishes,
   `release.yml`. Why: these are the services' newest generation, which Tommy names as the main example.
9. A step sequence repeated across jobs is a composite action at `.github/actions/<kebab-name>/action.yml`; a
   whole job reused by several callers, such as a per-region deploy, is a reusable workflow
   (`on: workflow_call`). Use a composite where the caller's job name must remain the check context. Why:
   both estates split them this way; Concertable records the check-context reason.
10. Shared cross-repository workflows live in one pipeline repository, and callers pin them under rule 2.
11. `## File structure`:

```text
.github/
  dependabot.yml
  actions/<name>/action.yml
  workflows/
    pr.yml  ci.yml  prod.yml  pr-closed.yml      deployed service
    ci.yml  release.yml                          library, tool or plugin
    <verb>-<object>.yml                          reusable workflows, e.g. deploy-region.yml
```

## `style`

12. Workflow `name:` is short Title Case (`PR`, `CI`, `Release (Production)`). Job ids are kebab-case. Every job
    has a sentence-case `name:` saying what it proves or does ("Deploy the PR environment"). Steps are named
    unless they are a bare setup `uses:` or a self-evident one-line `run:`.
13. Inputs and outputs of actions, reusable workflows and `workflow_dispatch` are kebab-case. Secrets and
    environment variables are SCREAMING_SNAKE. Why: matches GitHub's own actions (`persist-credentials`); both
    estates currently mix camelCase, kebab-case and snake_case.
14. Multi-line bash `run:` blocks start with `set -euo pipefail`.
15. YAML comments follow the global zero-comment rule: only a *why* the line itself cannot show (an ordering
    constraint, a platform limitation).

## `domain-design` (the pipeline model)

16. Every deploy references an immutable artifact: an image by digest (`repo@sha256:…`) or a versioned package,
    never a mutable tag. Why: services and Concertable both state "what was verified is what ships".
17. **[choice]** Production is released by pushing a semver tag (`v[0-9]+.[0-9]+.[0-9]+`). The release
    workflow's first job asserts the tag's commit is the latest green `ci.yml` run on `main`.
    - Alt: release on merge, where `ci.yml` chains straight into production after the non-production deploy (most
      services do this).
18. One GitHub environment per deploy target (`ci`, `preview`, `prod` or `<region>-prod`). It holds that
    target's `vars`, secrets and protection rules. Production environments allow deployments from `v*` tags only.
19. Several regions deploy as a matrix over regions with `fail-fast: false` and `environment: <region>-prod`, so
    each region's settings share names inside its own environment. Why: most services use a matrix; the
    named-job variant duplicates each job per region.
20. Per-pull-request preview environments are opt-in through a `deploy-preview` label and named
    `pr-<number>`, with their own state key. `pr-closed.yml` destroys them on close, whether merged or not.
    Why: cost; this is the main example's shape.
21. A deploy job succeeds only once the new revision or slot is serving, not merely ready.

## `errors` (failure, cancellation, concurrency)

22. Every workflow sets `concurrency:`. Verification groups on
    `${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}` with
    `cancel-in-progress: true`. Deploys, applies and teardowns use a fixed group per environment with
    `cancel-in-progress: false`. A teardown shares its preview's group.
23. A workflow that cancels runs which hold infrastructure state has an `if: cancelled()` job that releases the
    leaked lock.
24. Every job sets `timeout-minutes`.
25. A job that depends on a deploy uses `if: ${{ !cancelled() && needs.<job>.result == 'success' }}`.
    Annotations use `::error file=…::` so a failure points at its cause.

## `testing`

26. Workflows are validated in CI by `actionlint` (correctness) and `zizmor` (security). Why: neither estate
    lints workflows; both tools are the 2026 standard.
27. Required checks aggregate into one `ci-complete` job (`if: always()`, `needs:` every gate, fails unless all
    succeeded). The ruleset requires only that context. Why: Concertable's pattern lets jobs be added without
    touching the ruleset.
28. Test jobs are split by layer so a red check names the layer. Unit and container-backed integration tests run
    on the pull request; end-to-end runs against a deployed environment.
29. Uploaded artifacts set `if-no-files-found` (`error` for evidence, `warn` for diagnostics) and an explicit
    `retention-days`.

## `build`

30. Jobs run on GitHub-hosted `ubuntu-latest` by default; a matrix adds `windows-latest` only for a
    cross-platform product.
31. Toolchain versions come from repository files (`global-json-file`, `node-version-file`, `packageManager`),
    never from numbers duplicated in YAML. Terraform's version is pinned exactly.
32. Dependency caching uses the setup actions' built-in `cache:`; `actions/cache` only covers what they cannot.

## `libraries`

33. Prefer first-party `actions/*`, then the vendor's own action (`azure/*`, `docker/*`, `hashicorp/*`). A
    community action needs a reason, and a short script beats a single-purpose marketplace action. Use
    `actions/github-script` for GitHub API calls.
34. `.github/dependabot.yml` updates the `github-actions` ecosystem weekly in one grouped pull request.
