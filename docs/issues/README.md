# Migration Issues

These documents are written as GitHub issue descriptions for the K3s migration.

## How To Use

1. Open a GitHub issue based on the matching document in this directory.
2. Keep the issue title aligned with the document title.
3. Link every migration PR back to the issue.

## PR Linking Convention

Every migration PR should include:

- `Closes #<issue-number>` or `Refs #<issue-number>`
- `Planning doc: docs/issues/<file>.md`

## Current Migration Queue

- `001-k3s-platform-bootstrap.md` -> GitHub issue `#3`
- `002-argocd-sealed-secrets-tailscale-operator.md` -> GitHub issue `#4`
- `003-corp-finance-monitor-helm-migration.md` -> GitHub issue `#5`
- `004-corp-finance-monitor-data-migration.md` -> GitHub issue `#6`
- `005-private-secrets-repo-bootstrap.md` -> GitHub issue `#8`
