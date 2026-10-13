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
