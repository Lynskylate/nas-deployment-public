# K3s Platform Baseline

K3s 集群平台文档索引。完整部署指南见 [`AGENTS.md`](../AGENTS.md)。

## Cluster Topology

| Role | Node | Tailscale IP |
|------|------|-------------|
| **Server** (control-plane) | aliyun | 100.100.99.70 |
| Agent | gtr | 100.121.0.67 |
| Agent | tencent | 100.99.48.76 |

- API server URL: `https://100.100.99.70:6443`
- Pod CIDR: `10.60.0.0/16`, Service CIDR: `10.61.0.0/16`
- Flannel: `vxlan`, `flannel-iface: tailscale0`
- Built-ins disabled: `cloud-controller-manager`, `traefik`, `servicelb`
- Container image pull proxy: Mihomo on GTR

## Platform Components

| Component | Status | Management |
|-----------|--------|------------|
| **K3s** (server + agents) | ✅ | Ansible (`edge/ansible/`) |
| **Argo CD** | ✅ | Ansible bootstrap → self-managed via App-of-Apps |
| **Sealed Secrets** | ✅ | Ansible bootstrap → ArgoCD Application |
| **Tailscale Operator** | ✅ | ArgoCD Application (GitOps) |

## Deployment

```bash
cd edge/ansible

# K3s cluster
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-server.yml
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-agent.yml

# Platform operators
ansible-playbook -i inventory-edge.ini deploy-platform-argocd.yml
ansible-playbook -i inventory-edge.ini deploy-platform-sealed-secrets.yml
ansible-playbook -i inventory-edge.ini deploy-platform-tailscale-operator.yml
```

ArgoCD UI: `https://argocd-argocd-server.tail414c32.ts.net`

## Files

| Path | Purpose |
|------|---------|
| `../edge/ansible/roles/k3s-prereq/` | sysctl, kernel modules, preinstall |
| `../edge/ansible/roles/k3s-server/` | K3s server install + config |
| `../edge/ansible/roles/k3s-agent/` | K3s agent install + config |
| `../edge/ansible/roles/argocd/` | ArgoCD bootstrap (App-of-Apps) |
| `../platform/` | K3s platform manifests (ArgoCD GitOps source) |
| `../.github/workflows/deploy-infra.yml` | CI pipeline |

## Boundaries

- `nas-deployment` owns host baseline, K3s, Argo bootstrap, platform operators, and shared platform services.
- Application repositories own their own Helm charts and Kubernetes resources.
- PRs must link the matching migration issue and planning document.
