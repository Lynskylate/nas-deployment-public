# K3s Migration Baseline

This directory tracks the platform migration from the legacy Podman release flow to:

- K3s
- Argo CD
- Sealed Secrets
- Tailscale Operator

## Issue Docs

- [001 Bootstrap K3s Platform](../docs/issues/001-k3s-platform-bootstrap.md)
- [002 Install Argo CD + Sealed Secrets + Tailscale Operator](../docs/issues/002-argocd-sealed-secrets-tailscale-operator.md)
- [003 Migrate corp-finance-monitor Helm ownership](../docs/issues/003-corp-finance-monitor-helm-migration.md)
- [004 Migrate corp-finance-monitor persistent data](../docs/issues/004-corp-finance-monitor-data-migration.md)

## First Deployment Slice

The first migration slice handled in this repository is cluster bootstrap:

```bash
cd edge/ansible
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-platform.yml
ansible-playbook -i inventory-edge.ini verify-gtr-k3s-platform.yml
```

## CI/CD

`nas-deployment-public/.github/workflows/deploy-infra.yml` now includes a dedicated K3s bootstrap stage.

The workflow no longer reads `K3S_CLUSTER_TOKEN` from GitHub Actions secrets or repo-managed plaintext vars.
Instead it decrypts `ansible/edge/group_vars/all/secret.sops.yml` from `nas-deployment-vault` at deploy time and renders `edge/ansible/group_vars/all/secret.runtime.yml` before running Ansible. The same bootstrap flow now also renders service-specific overlays for `mihomo/`, `shadowsocks-shadowtls/`, and Grafana alert secrets.

Manual trigger target:

- `gtr_k3s_platform`

## Boundaries

- `nas-deployment` owns host baseline, K3s, Argo bootstrap, platform operators, and shared platform services.
- Application repositories own their own Helm charts and Kubernetes resources.
- PRs must link the matching migration issue and planning document.
