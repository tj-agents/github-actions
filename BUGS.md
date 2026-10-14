# Bugs

## B001 - Scaffold rollback deletes a replacement file

- **Kind:** bug
- **Observed/reported:** 2026-10-14. At main a2e04b07cee412b27f8c626120973ea318f6c69f, a temporary-directory probe calls write_files with two outputs. Before the second output fails with OSError, it renames the first generated file aside and writes a caller-owned replacement at the same path. Rollback deletes that replacement. A second probe inserts a foreign file in a created directory before failure; rmdir raises an uncaught OSError rather than preserving the original WriteError diagnostic. Confirmed cause: write_files closes created streams, retains only pathnames, unlinks those names without live ownership proof, and does not contain cleanup errors at .agents/github-actions/utility/scaffold/scripts/scaffold.py:845-876.
- **Impact and priority:** P1; the public new command can delete another owner's file during failure cleanup. Cleanup errors can also mask the intended error diagnostic. The reproduction touched disposable directories only.
- **Source owner:** tj-agents/github-actions, scaffold public new-command write transaction.
- **State:** open
- **Repair link:** BUGS.md#B001 and the existing standards-finish handoff item0; separate from Azure B003, which owns Azure's combined transaction.
- **Next action:** repair the public writer's live ownership tracking and contained cleanup, with replacement, identity-lifetime, retained-directory and error-diagnostic regressions.
- **Resolution condition:** replacement files and foreign directory contents survive later injected failures, cleanup removes only proven owned outputs, and write/cleanup failures return the intended WriteError diagnostic on Linux and Windows.
- **Verification evidence:** two pure Python temporary-directory probes observed replacement absence after WriteError and an escaping WinError145 from rmdir, while foreign directory content survived. No source mutation, workflow execution, cloud command or application build was used. Azure's planned composition calls pure render rather than this new-command transaction.
