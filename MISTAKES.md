# Mistakes

## M001: Initial command output discarded a live process handle

- Kind: mistake.
- Observed: 2026-10-13, during workflow-writer preparation, the coordinator printed only an execution
  result's output. A command with no initial output had returned a live process handle; omitting it
  prevented the coordinator from polling that command and led to an unsupported host-failure suspicion.
- Cause: confirmed caller error. The existing tool instructions require retaining and polling a returned
  process handle; that standard was violated.
- Impact and priority: delayed validation and inaccurate progress interpretation; P3, with no source
  mutation or delivery affected.
- Source owner: standards-finish execution, under plans/github-actions-package/GOAL.md.
- State: resolved.
- Repair link: plans/github-actions-package/GOAL.md.
- Prevention: inspect the complete execution result; retain every live process handle and poll it to
  completion before classifying empty output as a failure.
- Next action: apply this result-handling rule to remaining validation and delivery commands.
- Resolution condition: a subsequent command's live handle is retained and its terminal result observed.
- Verification evidence: the subsequent generator read returned its source output and a live handle;
  polling that handle observed exit 0. The capacity read was also polled to completion, and its blank
  capacity fields were treated as inconclusive.

## M002: Regression insertion produced shadowed duplicate test methods

- Kind: mistake.
- Observed: 2026-10-13, the workflow-writer composition repair inserted each of eight regression methods
  twice. Python silently shadowed the first definitions, so the passing test count did not expose them.
- Cause: unknown insertion mechanism. The writer logged one explicit multi-file patch invocation, which
  reported success; these logs do not establish a retry or an internal double application. A separate
  renderer patch reported failed matching after its changes were already present.
- Governing standard: classification is unknown; the logs do not establish a missing, ambiguous or
  violated rule as the cause. Runtime tests omitted a definition-uniqueness check; independent source
  inspection caught the issue as intended. No upstream tool cause is claimed.
- Impact and priority: redundant source and misleading coverage inspection; P3. Parent inspection caught
  the duplicates before the repair commit; no duplicate definitions were committed or published.
- Source owner: standards-finish workflow-writer execution.
- State: resolved.
- Repair link: Feature/WorkflowWriter, commit 18e0a3bfb330f728413d51847f0eb1bcc96e8567.
- Prevention: inspect actual file state after a mutation regardless of its reported status, use idempotent
  insertion markers, and check test-definition uniqueness before accepting regression additions.
- Next action: retain these checks for the remaining writer repairs.
- Resolution condition: one definition remains for each regression and the required runtime suite passes.
- Verification evidence: AST-based deduplication removed 113 redundant lines; the read-only class-method
  uniqueness check passed, all 36 tests passed with required Node and no skips, and whitespace/generated
  freshness checks passed before commit 18e0a3b.