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
| Agent | remote_proxy | 100.66.156.40 |

- API server URL: `https://100.102.140.59:6443`
- Cluster CIDR: `10.60.0.0/16`, Service CIDR: `10.61.0.0/16`
- Flannel backend: `wireguard-native` (kernel WireGuard, no tailscale0 dependency)
- Built-ins disabled: `cloud-controller-manager`, `traefik`, `servicelb`
- Node labels: `gtr.io/region` (`cn`/`us`), `gtr.io/visibility` (`public`/`internal`)
- Container image pull proxy: GTR mihomo (`gtr.tail414c32.ts.net:7890`), GTR uses localhost

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

### Install Source (`k3s_mirror`)

All nodes default to `k3s_mirror: "cn"` (`group_vars/all/public.yml`), which uses the Rancher CN mirror for faster binary downloads inside China:

| Mirror | Install script | Binary source |
|--------|---------------|---------------|
| `cn` | `https://rancher-mirror.rancher.cn/k3s/k3s-install.sh` | `rancher-mirror.rancher.cn/k3s/<version>/k3s-amd64` |
| `""` (empty) | `https://get.k3s.io` | `github.com/k3s-io/k3s/releases` |

When `k3s_mirror: "cn"`:
- Install script is downloaded from the Rancher mirror
- `INSTALL_K3S_MIRROR=cn` is set, directing the script to download the binary from the CN mirror
- Proxy settings (`http_proxy`/`https_proxy`) are **not** passed to the install step, since the mirror is directly reachable

When `k3s_mirror: ""` (overseas nodes like remote_proxy):
- Install script comes from `get.k3s.io`
- Binary downloads from GitHub releases
- Proxy is used if `github_download_proxy` is set for the host

| Node | `k3s_mirror` | `github_download_proxy` |
|------|------------|---------------------|
| aliyun | `cn` | `gtr:7890` (unused by k3s) |
| gtr | `cn` | `127.0.0.1:7890` (unused by k3s) |
| tencent | `cn` | `gtr:7890` (unused by k3s) |
| remote_proxy | `""` | `""` (direct) |

## CI/CD

`nas-deployment-public/.github/workflows/deploy-infra.yml` includes dedicated K3s server and agent stages.

The cluster token is never stored in plaintext — it is decrypted from `nas-deployment-vault` via sops at deploy time.

Manual trigger target:

- `gtr_k3s_platform` — deploys server + agents (triggers `deploy-gtr`, `deploy-edge`, `deploy-k3s-server`, `deploy-k3s-agent`)

## Boundaries

- `nas-deployment` owns host baseline, K3s, Argo bootstrap, platform operators, and shared platform services.
- Application repositories own their own Helm charts and Kubernetes resources.
- PRs must link the matching migration issue and planning document.
