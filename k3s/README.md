# K3s Platform Baseline

This directory tracks the K3s cluster platform — the host-level K3s deployment, and the K3s-internal platform components managed by this repository.

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

## Platform Components

| Component | Status | Management |
|-----------|--------|------------|
| **K3s** (server + agents) | ✅ Deployed | Ansible (`edge/ansible/`) |
| **Argo CD** | ✅ Deployed | Ansible bootstrap → self-managed via App-of-Apps |
| **Sealed Secrets** | ✅ Deployed | Ansible bootstrap → Argo CD Application |
| **Tailscale Operator** | ✅ Deployed | Argo CD Application (GitOps) |

Deployment order: `Argo CD → Sealed Secrets → Tailscale Operator → 平台应用`

## Repository Layout

```
nas-deployment-public/
├── edge/ansible/              ← Host-level + K3s platform (Ansible)
│   ├── roles/
│   │   ├── k3s-prereq/        ✅ Installed
│   │   ├── k3s-server/        ✅ Installed
│   │   ├── k3s-agent/         ✅ Installed
│   │   └── argocd/            📋 Planned (Phase 1)
│   ├── deploy-gtr-k3s-server.yml      ✅
│   ├── deploy-gtr-k3s-agent.yml       ✅
│   ├── deploy-platform-argocd.yml      📋 Planned
│   ├── deploy-platform-sealed-secrets.yml 📋 Planned
│   ├── verify-gtr-k3s-server.yml      ✅
│   ├── verify-gtr-k3s-agent.yml       ✅
│   ├── verify-platform-argocd.yml      📋 Planned
│   ├── verify-platform-sealed-secrets.yml 📋 Planned
│   └── verify-platform-tailscale-operator.yml 📋 Planned
│
├── platform/                  ← K3s 内平台组件声明式配置
│   ├── applications/          ← Argo CD Application CRDs (App-of-Apps)
│   │   ├── sealed-secrets.yaml         📋 Planned
│   │   └── tailscale-operator.yaml     📋 Planned
│   └── helm-values/
│       └── tailscale-operator/
│           └── values.yaml             📋 Planned
│
├── k3s/                       ← 本文档
├── docs/issues/               ← 迁移规划文档
│   ├── 001-k3s-platform-bootstrap.md  ✅ Completed
│   ├── 002-argocd-sealed-secrets-tailscale-operator.md  ✅ Completed
│   ├── 003-corp-finance-monitor-helm-migration.md
│   └── 004-corp-finance-monitor-data-migration.md
└── .github/workflows/
    └── deploy-infra.yml       ← CI: deploy-platform-operators job ✅ Added
```

## Deployment

### K3s 集群层（已完成）

```bash
cd edge/ansible

# 1. Deploy K3s server on aliyun (control-plane)
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-server.yml
ansible-playbook -i inventory-edge.ini verify-gtr-k3s-server.yml

# 2. Deploy K3s agents on GTR + tencent (after server is ready)
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-agent.yml
ansible-playbook -i inventory-edge.ini verify-gtr-k3s-agent.yml
```

### 平台组件层（已完成）

```bash
# 3. Deploy platform operators（one-shot）
ansible-playbook -i inventory-edge.ini deploy-platform-argocd.yml
ansible-playbook -i inventory-edge.ini verify-platform-argocd.yml

ansible-playbook -i inventory-edge.ini deploy-platform-sealed-secrets.yml
ansible-playbook -i inventory-edge.ini verify-platform-sealed-secrets.yml

# 4. Verify Tailscale Operator (synced via Argo CD)
ansible-playbook -i inventory-edge.ini verify-platform-tailscale-operator.yml
```

## CI/CD

The CI workflow (`deploy-infra.yml`) includes dedicated jobs:
- `deploy-k3s-server`: runs in parallel with `deploy-edge`, depends on `deploy-gtr`
- `deploy-k3s-agent`: depends on both `deploy-k3s-server` and `deploy-edge`
- `deploy-platform-operators`: depends on `deploy-k3s-agent` (✅ Added)

## Idempotency

Both server and agent roles check runtime health before deciding whether to install:
- **Healthy** (systemctl active + API reachable): skip install, only render config + ensure started
- **Not healthy / missing**: perform full install

Argo CD 安装角色使用类似逻辑：检查 argocd namespace 和 argocd-server deployment 状态。

Sealed Secrets 安装后会在 `/tmp/` 保留私钥备份，需手动 sops 加密后存入 vault repo。

Tailscale Operator 通过 Argo CD Application 管理，首次同步需要集群中存在 `tailscale-operator-oauth` SealedSecret。

## Install Source (`k3s_mirror`)

All nodes default to `k3s_mirror: "cn"` (`group_vars/all/public.yml`), which uses the Rancher CN mirror for faster binary downloads inside China. See detailed node-level override table below.

| Node | `k3s_mirror` | `github_download_proxy` |
|------|------------|---------------------|
| aliyun | `cn` | `gtr:7890` (unused by k3s) |
| gtr | `cn` | `127.0.0.1:7890` (unused by k3s) |
| tencent | `cn` | `gtr:7890` (unused by k3s) |
| remote_proxy | `""` | `""` (direct) |

## Boundaries

- `nas-deployment` owns: host baseline, K3s, Argo CD bootstrap, platform operators, shared platform services
- Application repositories own: their own Helm charts and Kubernetes resources
- `platform/applications/` in this repo holds only platform-level Argo CD Application CRDs
  - Business applications register their own Applications in their own repos
- PRs must link the matching migration issue and planning document

