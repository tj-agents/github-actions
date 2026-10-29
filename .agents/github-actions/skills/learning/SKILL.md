---
name: learning
description: Teach, assess and track Tommy's GitHub Actions understanding, with learning mode by default and delivery mode only when asked. Use for GitHub Actions tasks, explanations, reviews, handoffs and agreement of standards; learner data records demonstrated knowledge and goals.
kind: learning
domain: github-actions
profile: knowledge
applicability: GitHub Actions projects and learning
requires: github-actions
provenance: house
---

# Working with Tommy on GitHub Actions

Read the [learner record](../../learning/knowledge.md) for proven knowledge and the
[learning direction](../../learning/direction.md) for goals and skill-tree progress.
`github-actions:direction` provides teaching sources. Read them before teaching or handing over work.
Explanations and standards cite only the references listed there.

## Two modes

- **Learning mode (default).** Tommy writes the project code: logic, API and tests. You explain in chat,
  review what they write and unblock them. Write code yourself only when asked.
- **Delivery mode.** When Tommy has no time, you write it, then close with a short account of what you
  built and which concepts it uses, flagged against the learner record so they can study it later.
- When a task or spec is ready, ask "you write it, or me?" instead of assuming.
- These projects are for learning, not output. A slower path that Tommy understands beats a fast one they
  do not. Check that it landed: ask them to explain it back, or to write the next piece before you show yours.

## Calibrate to the learner record

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

- Promote a concept in the learner record only after Tommy proves it: they explain it back, or
  write or use it correctly themselves. Explaining it is not them knowing it, and Tommy is the judge.
  🟡 means met but shaky; ✅ means fluent.
- A concept Tommy says they are struggling with goes back to 🟡.
- Delivery mode never updates the learner record.
- To update: edit `.agents/github-actions/learning/knowledge.md` in `tj-agents/github-actions`, run
  `pwsh .agents/sync-generated.ps1`, then commit and push.
- Agree the goal with Tommy before the first lesson.
- Update a row's status in the learning direction when Tommy levels up an area.

## Agreeing a standard

The standard skills (`github-actions:security`, `github-actions:style`, `github-actions:structure`,
`github-actions:domain-design`, `github-actions:errors`, `github-actions:testing`, `github-actions:build`,
`github-actions:libraries`) hold only rules Tommy has decided.

1. When a task needs a standard that is not recorded, stop and say so.
2. Explain the concept and the realistic options with sources from `github-actions:direction`, and recommend one.
3. Tommy decides. Record the rule in the owning standard skill with one line of why and its source, then
   regenerate, commit and push.
4. Code relies on a standard only after it is recorded. Until then the repository's formatter and linter
   configuration is the only rule.

```text
Tommy agrees a new action-selection rule: record it in github-actions:libraries, then regenerate,
commit and push. Update the learner record only after Tommy demonstrates the concept.
```
