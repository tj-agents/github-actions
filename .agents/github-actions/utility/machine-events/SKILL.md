---
name: machine-events
description: Ship the shared GitHub publisher for Tommy's global machine event channel. Use when connecting a repository's main-branch changes or generated marketplace publication to background machine updates.
kind: utility
domain: github-actions
profile: core
applicability: tj-agents, Concertable and tomjseery repositories
requires: python
provenance: house
---

# Machine events

Core's machine setup owns the topic and background subscription. This package owns the publisher action
at `.github/actions/machine-events` and the uniform caller. There is no admin credential in Actions;
`MACHINE_EVENTS_TOPIC` is the only channel configuration. Hints contain a repository and change categories,
never file contents. Every subscriber re-reads GitHub before acting.

On Windows use `python`; on Linux use `python3`. Render or install the caller with the immutable publisher
commit to use:

```text
python -B scripts/caller.py --revision <40-character-sha> --project <repository>
```

The caller runs on every push to main. A job that pushes generated plugins with `GITHUB_TOKEN` must also
call the same action after its push with `published: 'true'`, because that push does not trigger another
workflow. Set the repository's `MACHINE_EVENTS_TOPIC` Actions variable to the channel configured by core
setup. Keep the action SHA pinned and update it with Dependabot.

The ntfy topic is public to anyone who knows it; its obscurity provides noise reduction, never authority.
The free hosted service has quotas and a finite replay cache. Core reconciles after an offline gap. A
malformed or forged hint can only request a bounded re-read of a repository in the allowed accounts.
