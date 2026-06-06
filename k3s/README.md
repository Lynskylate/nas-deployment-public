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

## Cluster Topology

| Role | Node | Tailscale IP |
|------|------|-------------|
| **Server** (control-plane) | aliyun | 100.102.140.59 |
| Agent | gtr | 100.121.0.67 |
| Agent | tencent | 100.99.48.76 |

- API server URL: `https://100.102.140.59:6443`
- Cluster CIDR: `10.60.0.0/16`, Service CIDR: `10.61.0.0/16`
- Flannel backend: `tailscale0` (host Tailscale mesh)
- Built-ins disabled: `traefik`, `servicelb` (replaced by Tailscale Operator in next phase)

## Deployment

Server and agents are deployed as separate Ansible playbooks and CI jobs:

```bash
cd edge/ansible

# 1. Deploy K3s server on aliyun (control-plane)
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-server.yml
ansible-playbook -i inventory-edge.ini verify-gtr-k3s-server.yml

# 2. Deploy K3s agents on GTR + tencent (after server is ready)
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-agent.yml
ansible-playbook -i inventory-edge.ini verify-gtr-k3s-agent.yml
```

The CI workflow (`deploy-infra.yml`) runs server and agents in separate jobs:
- `deploy-k3s-server`: runs in parallel with `deploy-edge`, depends on `deploy-gtr`
- `deploy-k3s-agent`: depends on both `deploy-k3s-server` and `deploy-edge`

### Idempotency

Both server and agent roles check runtime health before deciding whether to install:
- **Healthy** (systemctl active + API reachable): skip install, only render config + ensure started
- **Not healthy / missing**: perform full install

## CI/CD

`nas-deployment-public/.github/workflows/deploy-infra.yml` includes dedicated K3s server and agent stages.

The cluster token is never stored in plaintext — it is decrypted from `nas-deployment-vault` via sops at deploy time.

Manual trigger target:

- `gtr_k3s_platform` — deploys server + agents (triggers `deploy-gtr`, `deploy-edge`, `deploy-k3s-server`, `deploy-k3s-agent`)

## Boundaries

- `nas-deployment` owns host baseline, K3s, Argo bootstrap, platform operators, and shared platform services.
- Application repositories own their own Helm charts and Kubernetes resources.
- PRs must link the matching migration issue and planning document.
