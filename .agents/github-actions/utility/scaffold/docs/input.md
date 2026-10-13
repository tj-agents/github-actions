# Workflow writer input

`schema_version` is 1. `prod-release` is the only option and defaults to true. All remaining fields
are workload/provider data; they do not select template variants. Unknown fields fail validation.

`roots` is a nonempty list of repository-relative working roots and defaults to `["."]`. Verification
and build phases can declare their own roots. The pure renderer receives version metadata as a separate
file map; the CLI reads known metadata files from those roots and their ancestors. The prospective overlay
wins over disk. Paths cannot be absolute or contain traversal.

`verify.unit` is required. `verify.integration` adds a separate required check; `verify.end-to-end`
runs only after a deployment succeeds. Every verification phase has a nonempty `steps` list and optional
`roots`, scalar `env`, and a typed `matrix` of named string lists. Mandatory checks require success;
`cloud-gates` separately proves whether explicitly optional operations ran or skipped as expected.

`build` is optional for foundation-only profiles or providers that resolve already immutable references.
When present it has `steps`, optional `roots`, an `artifact.path`, and optional `oidc` (default false).
The app builds a versioned package or manifest of immutable image digests; the writer uploads it as
`deployment`, and reusable deploy downloads that exact artifact ID from its source run. Deploy does not
build it again. Production first verifies the latest green main CI commit, then selects that same run's
retained artifact when declared. With no build artifact, the provider must resolve the immutable package
or image from the verified `SOURCE_SHA`; it must not rebuild or deploy a mutable tag.

`provider` contains:

- `name`: a kebab-case provider identifier, recorded in scaffold metadata.
- `oidc`: whether plan, deploy, teardown and recovery jobs need `id-token: write` (default false).
- `ready`: `true` (default) or `vars.NAME == 'true'`. This gates PR plan, preview and recovery; main CI can
  bootstrap its foundation. A cloud-backed build on a PR uses the same trust/readiness gate.
- `environments`: optional literal `ci`, `preview` and `prod` GitHub environment identities, defaulting
  to those names. `prod` can also be a nonempty list of region-prod environment identities; the writer
  supplies a production matrix with `fail-fast: false`. Preview instance/state identity is separately `pr-<number>` through `PREVIEW_NUMBER`;
  a fixed preview environment can retain provider federation subjects, vars and protection rules.
- `phases`: required `validate`, `plan`, `deploy`, `readiness`, `destroy`, `recover`, and optional `setup`.
  Each has structured `steps` with optional `roots` and scalar `env`. Validate and plan may declare
  typed matrices; production target matrices come from the environment data. `setup`
  supplies repeated tool setup and sign-in calls, wrapped once as the writer-owned `cloud-setup` composite. Use
  writer env data in setup steps, since the sequence is shared by several workflow contexts. Azure keeps Terraform commands, foundation/backend behavior,
  deployment, serving-revision checks and teardown in these phases.
- `composites`: optional kebab-case action names. Each has a description, input definitions
  (`description`, boolean `required`, optional string `default`) and structured steps. The writer owns
  the composite envelope and resolves remote action pins. Local actions must be declared here.

A step has a `name` and exactly one of `run` or `uses`, plus optional `id`, `env`, `if`. Run steps can
set `working-directory`; the canonical shell is bash and multiline commands receive strict mode.
Action steps can set `with`. Remote `uses` values are names in the writer's immutable pin catalog,
not provider-owned refs; local refs are `./.github/actions/<name>`. The catalog includes first-party
checkout, GitHub API, artifact and toolchain actions, plus the vendor-owned pnpm, Terraform and Azure
sign-in actions. Untrusted expression values belong in step `env`, never command/script bodies.
Secrets also stay in step `env`; phase/job `env` cannot contain secrets. Artifact uploads declare
`if-no-files-found` and `retention-days`.

Expression guards recognize case-insensitive context names, dot access, literal bracket access and
whole-context references. Secret-context references are allowed only in the consuming step's `env`.
`inputs`, `github.event`, `github.head_ref`, whole `github` and computed GitHub property access must
pass through step `env` before a command or GitHub script consumes them. Trusted GitHub metadata and
quoted expression literals remain allowed. PR planning waits for both lint and infrastructure
validation to succeed before provider setup and commands run.

Phase `env` applies only to that phase's steps, with explicit step values taking precedence. Setup
`env` applies to its `cloud-setup` invocation; explicit env on steps inside that composite takes
precedence. Writer-owned deployment variables remain at job scope. Step IDs must be distinct across
each assembled job, including joined deploy/readiness steps and the writer's `artifact` upload step.
IDs and their references are preserved.

Reusable deploy exposes `environment`, `preview-number`, `source-sha`, `source-run-id`, and optional
`artifact-id`. Provider deployment steps receive `DEPLOY_ENVIRONMENT`, `PREVIEW_NUMBER`, `SOURCE_SHA`,
`SOURCE_RUN_ID` and `ARTIFACT_DIRECTORY` as environment variables. Teardown and recovery receive the
first two. `PREVIEW_NUMBER` contains the complete PR number; provider-specific resource naming budgets
and state paths remain provider logic. Preview deploy, destroy and cancellation recovery share the
`deploy-pr-<number>` concurrency group without cancelling an in-flight operation. Cloud planning and
preview/recovery run only for same-repository pull requests; preview deployment additionally needs the
`deploy-preview` label. Required cloud operations cannot silently skip after an upstream failure.

Providers cannot supply workflow triggers, jobs, permissions, concurrency, checkout behavior or
whole workflow YAML. Linting the emitted workflows checks provider step expressions against their actual
contexts. The writer creates no identity, GitHub environment protection, repository ruleset or cloud
resource itself.

Node metadata supports npm and pnpm. Unsupported package managers fail before writing. Dependency caches
use setup actions only in verification and unprivileged build jobs; cloud jobs do not restore caches.

Close cleanup keeps the trust/readiness gate and does not depend on the current preview label. Provider
destroy steps must be idempotent for absent instances, including pull requests whose label was removed.
