# github-actions

Tommy's GitHub Actions workflow conventions for CI and CD.

Published as plugin `github-actions` from this repository's `github-actions-agents` marketplace.

## Skills

- Knowledge: `github-actions:direction`, `github-actions:knowledge`, `github-actions:learning`.
- Contracts, empty until a decision is recorded: `github-actions:build`, `github-actions:domain-design`, `github-actions:errors`, `github-actions:libraries`, `github-actions:structure`, `github-actions:style`, `github-actions:testing`.
- Utilities: `github-actions:scaffold`.

## Authoring and verification

```powershell
pwsh .agents/sync-generated.ps1
pwsh .agents/sync-generated.ps1 -Check
```

The layout, the vendored generator and CI come from [kit](https://github.com/tj-agents/kit).
