# K3s Platform Baseline

K3s 集群平台文档索引。完整约定见根目录 [`AGENTS.md`](../AGENTS.md)。

## 当前拓扑

| 角色 | 节点 | Tailscale IP | 说明 |
|------|------|-------------|------|
| **Server** (control-plane) | tencent | 100.99.48.76 | 当前唯一 control-plane |
| Agent | gtr | 100.121.0.67 | 主要工作负载与持久化节点 |
| Agent | aliyun | 100.100.99.70 | 旧 control-plane，现已降级为 agent |
| Agent | remote_proxy | 100.66.156.40 | 海外节点；K8s Node 名固定为 `remote-proxy` |

- API server URL: `https://100.99.48.76:6443`
- Pod CIDR: `10.60.0.0/16`
- Service CIDR: `10.61.0.0/16`
- Flannel: `vxlan`，`flannel-iface: tailscale0`
- K3s disabled built-ins: `traefik`、`servicelb`

## 管理边界

| 组件 | 管理方式 |
|------|---------|
| K3s server / agent、Tailscale、内核前置、Edge 基线 | Ansible |
| Argo CD | Ansible 引导安装，之后由集群自管理 |
| Sealed Secrets | ArgoCD Helm chart；私钥从 vault 恢复 |
| Tailscale Operator | ArgoCD Application |
| 集群内业务与平台资源 | ArgoCD GitOps |

原则：**能交给 ArgoCD 的 K8s 资源，尽量不要继续由 Ansible 直接维护。**

## 常用命令

```bash
cd edge/ansible

# K3s
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-server.yml
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-agent.yml
ansible-playbook -i inventory-edge.ini verify-gtr-k3s-server.yml
ansible-playbook -i inventory-edge.ini verify-gtr-k3s-agent.yml

# Platform bootstrap
ansible-playbook -i inventory-edge.ini deploy-platform-argocd.yml
ansible-playbook -i inventory-edge.ini bootstrap-platform-sealed-secrets-key.yml
ansible-playbook -i inventory-edge.ini deploy-platform-tailscale-operator.yml

# Cluster verification
ssh ci@129.211.12.63 "sudo k3s kubectl get nodes -o wide"
ssh ci@129.211.12.63 "sudo k3s kubectl -n argocd get applications"
ssh ci@129.211.12.63 "sudo k3s kubectl -n monitoring get pods"
```

ArgoCD UI: `https://argocd-argocd-server.tail414c32.ts.net`

## 关键路径

| 路径 | 说明 |
|------|------|
| `../edge/ansible/roles/k3s-prereq/` | K3s 前置内核、sysctl、依赖包 |
| `../edge/ansible/roles/k3s-server/` | server 安装与配置 |
| `../edge/ansible/roles/k3s-agent/` | agent 安装与配置 |
| `../edge/ansible/roles/argocd/` | ArgoCD bootstrap |
| `../platform/` | ArgoCD GitOps source |
| `../.github/workflows/deploy-infra.yml` | CI/CD 入口 |

## 备注

- `remote_proxy` 是 **Ansible inventory alias**；Kubernetes Node 对象名必须使用 `remote-proxy`。
- `aliyun` 已不再承担 control-plane 角色；看到旧文档仍写 `aliyun K3s server` 时，应以本文和 `AGENTS.md` 为准。
