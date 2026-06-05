# [Migration] Move corp-finance-monitor Deployment Ownership Into The App Repo

## Summary

Migrate `corp-finance-monitor` from the legacy `gtr-release-config` deployment model to an app-owned Helm chart reconciled by Argo CD.

## Problem

Today the application deployment truth is split across:

- the app repo for source code and images
- `gtr-release-config` for runtime topology and rollout

The target model requires:

- Helm chart and Kubernetes resources owned by the app repo
- Argo CD directly tracking the app repo
- `nas-deployment` holding only the Argo `Application` registration and platform-owned secrets

## Scope

- Add Helm chart structure in the app repo
- Add `values-prod.yaml`
- Model frontend/backend Services and workloads
- Reference existing secrets/config instead of embedding values
- Register the app in Argo CD from `nas-deployment`

## Out Of Scope

- Historical Podman rollback flow
- K3s cluster bootstrap
- Sealed Secrets controller installation

## Acceptance Criteria

- The app repo contains a production Helm deployment definition
- Argo CD syncs the app directly from the app repo
- Runtime secrets are referenced via pre-created secret names
- The legacy `gtr-release-config` stack is no longer needed for this app

## PR Linking

- Suggested PR title: `feat: migrate corp-finance-monitor to helm + argo`
- GitHub issue: `#5`
- PR body should include: `Closes #5`
- Planning doc path: `docs/issues/003-corp-finance-monitor-helm-migration.md`
