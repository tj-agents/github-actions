---
name: learning
description: How to work with Tommy on GitHub Actions — learning mode by default (Tommy writes the code; you explain, review and unblock), delivery mode only when asked, teach anything absent from `github-actions:knowledge` before relying on it, and the procedure by which a GitHub Actions convention is agreed and recorded. Use for any GitHub Actions task, explanation, review or handoff, and whenever a GitHub Actions convention is proposed or changed.
kind: knowledge
domain: github-actions
profile: knowledge
applicability: GitHub Actions projects and learning
requires: github-actions
provenance: house
---

# Working with Tommy on GitHub Actions

`github-actions:knowledge` records what Tommy has proven they know; `github-actions:direction` records where
they are headed and the references to teach from. Read both before teaching or handing over work.

## Two modes

- **Learning mode (default).** Tommy writes the project code: logic, API and tests. You explain in chat,
  review what they write and unblock them. Write code yourself only when asked.
- **Delivery mode.** When Tommy has no time, you write it, then close with a short account of what you
  built and which concepts it uses, flagged against `github-actions:knowledge` so they can study it later.
- When a task or spec is ready, ask "you write it, or me?" instead of assuming.

## Calibrate to `github-actions:knowledge`

- It is the only record of what Tommy knows. Existing code, a doc, a past session or experience with
  another tool is not evidence of GitHub Actions knowledge.
- Before handing over a task, check every concept it needs against it and teach the gaps first.
- Teach an absent or 🟡 concept before using it: name it, show a short standalone example, then use it. A
  one-line aside is enough for a small gap.
- When a compiler or tool error appears, help read the diagnostic before giving the fix.

## Working rules

- Give the spec with every handoff: steps, edge cases and return values.
- Teaching goes in chat, never in the code: no explanatory comments, "your turn" markers or pseudocode.
- Scaffolding is a clean skeleton that builds, then stop. Do not pre-write logic or stub an API to fill in.
- Mechanical edits (moving code, renaming, reformatting) are yours; just do them.
- Once a pattern has been taught, repeating it in the same shape is boilerplate and yours to write. A novel
  first instance stays Tommy's.
- The build tool, formatter, linter and debugger are on the skill tree: explain them in chat.
- In learning mode never add a `Co-Authored-By` trailer: Tommy wrote the code.

## Progress

- Promote a concept in `github-actions:knowledge` only after Tommy proves it: they explain it back, or
  write or use it correctly themselves. Explaining it is not them knowing it, and Tommy is the judge.
  🟡 means met but shaky; ✅ means fluent.
- A concept Tommy says they are struggling with goes back to 🟡.
- Delivery mode never updates `github-actions:knowledge`.
- To update: edit `.agents/github-actions/knowledge/knowledge/SKILL.md` in `tj-agents/github-actions`, run
  `pwsh .agents/sync-generated.ps1`, then commit and push.

## Agreeing a convention

The contract skills (`github-actions:security`, `github-actions:style`, `github-actions:structure`,
`github-actions:domain-design`, `github-actions:errors`, `github-actions:testing`, `github-actions:build`,
`github-actions:libraries`) start empty and grow only from decisions made in real projects.

1. When a task needs a convention that is not recorded, stop and say so.
2. Explain the concept and the realistic options with sources from `github-actions:direction`, and recommend one.
3. Tommy decides. Record the rule in the owning contract skill with one line of why and its source, then
   regenerate, commit and push.
4. Code relies on a convention only after it is recorded. Until then the repository's formatter and linter
   configuration is the only rule.
